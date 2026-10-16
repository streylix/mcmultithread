#!/usr/bin/env python3
"""Serial, rotated player-count scaling matrix and raw-data re-analysis."""
import argparse
import csv
import json
import math
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate
import run as harness

ROOT = harness.ROOT
SIZES = (50, 100, 250, 500)
EXTRA_METRICS = ('lagging_tick_share', 'network.bytes_s', 'network.mb_s',
                 'network.bytes_player_tick', 'drift_pct')
PHASES = ('Entity Tick', 'Entity Tracker Tick', 'Chunk Source Tick', 'Tile Entity Tick',
          'Block Tick', 'Fluid Tick', 'Player Packet Processing', 'Connection Tick')


def generator_health(directory, meta, sustained=10):
    lo, hi = meta.get('measure_start_wall_ms'), meta.get('measure_end_wall_ms')
    if lo is None or hi is None:
        return {}, ['missing generator measurement window']
    result, reasons = {}, []
    for shard in meta.get('shards', []):
        path = directory / (shard['actions'] + '.health.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        rows = sorted((r for r in rows if lo <= r['t'] <= hi), key=lambda r: r['t'])
        if (not rows or rows[0]['t'] - lo > 2500 or hi - rows[-1]['t'] > 2500
                or any(b['t'] - a['t'] > 3000 or b['t'] <= a['t'] for a, b in zip(rows, rows[1:]))):
            reasons.append(f"missing generator health coverage: shard {shard['index']}")
        start, previous, longest = None, None, 0
        for row in rows:
            if not math.isfinite(row['p99_ms']) or row['p99_ms'] < 0:
                reasons.append(f"malformed generator health: shard {shard['index']}")
            if row['p99_ms'] > 100:
                if start is None or (previous is not None and row['t'] - previous > 2500):
                    start = row['t']
                longest = max(longest, (row['t'] - start) / 1000)
            else:
                start = None
            previous = row['t']
        result[str(shard['index'])] = {'samples': len(rows),
            'p50_ms': calibrate.distribution([r['p50_ms'] for r in rows]),
            'p99_ms': calibrate.distribution([r['p99_ms'] for r in rows]),
            'fraction_p99_over_100ms': sum(r['p99_ms'] > 100 for r in rows) / len(rows) if rows else None,
            'longest_p99_over_100ms_s': longest}
        if longest >= sustained:
            reasons.append(f"generator-limited: shard {shard['index']} event-loop p99 >100 ms for {longest:.1f} s")
    if meta.get('bots') and not meta.get('shards'):
        reasons.append('missing generator shard metadata')
    return result, reasons


def network_metrics(directory, meta, tps=20):
    snapshots = [json.loads((directory / f'network-{edge}.json').read_text()) for edge in ('start', 'end')]
    first, last = (s['connections'] for s in snapshots)
    reasons = []
    expected = meta['bots_joined'] + len(meta['cameras'])
    if set(first) != set(last) or len(first) != expected:
        reasons.append('network connection set changed or count differs from joined clients')
    # Prefer bytes_sent consistently for every socket; bytes_acked is the fallback.
    key = 'bytes_sent' if all('bytes_sent' in c for s in (first, last) for c in s.values()) else 'bytes_acked'
    delta = sum(last[k][key] - first[k][key] for k in first.keys() & last.keys())
    if delta < 0:
        reasons.append('network counters reversed')
    seconds = (snapshots[1]['wall_ms'] - snapshots[0]['wall_ms']) / 1000
    rate = delta / seconds
    return {'bytes_s': rate, 'mb_s': rate / 1e6,
            'bytes_player_tick': rate / meta['bots'] / tps, 'normalization_tps': tps, 'counter': key,
            'seconds': seconds, 'bytes': delta, 'connections': len(first)}, reasons


def phase_profile(directory):
    totals = {'Full Tick': 0, **{p: 0 for p in PHASES}}
    files = sorted((directory / 'profiler').glob('*/region-*.txt'))
    for path in files:
        for line in path.read_text().splitlines():
            match = re.search(r'([^│├└─]+?)\s+[\d,.]+% total,.*?, ([\d,.]+)ms raw sum$', line)
            if match:
                name = match[1].strip()
                if name in totals:
                    totals[name] += float(match[2].replace(',', ''))
    full = totals.pop('Full Tick')
    return {'files': len(files), 'full_tick_ms': full,
            'phase_ms': totals, 'share_pct': {p: 100 * v / full if full else None for p, v in totals.items()}}


def quadratic_fit(points):
    """OLS on independent repetition values, scaled for numerical conditioning."""
    if len(set(x for x, _ in points)) < 3:
        return None
    rows = [[1, x / 500, (x / 500) ** 2] for x, _ in points]
    matrix = [[sum(row[i] * row[j] for row in rows) for j in range(3)] +
              [sum(row[i] * y for row, (_, y) in zip(rows, points))] for i in range(3)]
    for i in range(3):
        pivot = max(range(i, 3), key=lambda j: abs(matrix[j][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        divisor = matrix[i][i]
        matrix[i] = [v / divisor for v in matrix[i]]
        for j in range(3):
            if j != i:
                factor = matrix[j][i]
                matrix[j] = [a - factor * b for a, b in zip(matrix[j], matrix[i])]
    a, b, c = (matrix[i][-1] / (500 ** i) for i in range(3))
    residual = sum((y - a - b * x - c * x * x) ** 2 for x, y in points)
    mean = statistics.fmean(y for _, y in points)
    total = sum((y - mean) ** 2 for _, y in points)
    return {'a': a, 'b': b, 'c': c, 'r2': 1 - residual / total if total else None,
            'rmse': math.sqrt(residual / len(points)), 'n': len(points),
            'min_players': min(x for x, _ in points), 'max_players': max(x for x, _ in points)}


def threshold_players(fit, target=50):
    if fit is None:
        return None
    a, b, c = fit['a'] - target, fit['b'], fit['c']
    if abs(c) < 1e-15:
        return -a / b if b > 0 and -a / b > 0 else None
    discriminant = b * b - 4 * c * a
    if discriminant < 0:
        return None
    roots = [(-b + s * math.sqrt(discriminant)) / (2 * c) for s in (-1, 1)]
    roots = [x for x in roots if x > 0 and b + 2 * c * x > 0]
    return min(roots) if roots else None


def read_run(directory, args):
    directory = Path(directory)
    result = calibrate.read_run(directory, args, scaling=True)
    meta = result.get('meta', {})
    if 'summary' not in result:
        for metric in EXTRA_METRICS:
            result['metrics'][metric] = None
        return result
    try:
        result['generator'], reasons = generator_health(directory, meta, args.sustained_seconds)
        result['reasons'].extend(reasons)
        result['network'], reasons = network_metrics(directory, meta, result['summary']['region_tps_mean'])
        result['reasons'].extend(reasons)
        result['profile'] = phase_profile(directory)
        if meta.get('profile_seconds') and not result['profile']['full_tick_ms']:
            result['reasons'].append('requested profiler output missing or empty')
        if any(code != 0 for code in meta.get('swarm_exitcodes', [])):
            result['reasons'].append('nonzero generator shard exit')
        summary = result['summary']
        result['metrics']['lagging_tick_share'] = summary['lagging_tick_share']
        windows = summary['tick_window_medians_ms']
        result['metrics']['drift_pct'] = (100 * (windows['last30'] / windows['first30'] - 1)
                                          if windows['first30'] else None)
        for key in ('bytes_s', 'mb_s', 'bytes_player_tick'):
            result['metrics']['network.' + key] = result['network'][key]
        lo, hi = meta['measure_start_wall_ms'], meta['measure_end_wall_ms']
        with (directory / 'frequency.csv').open() as stream:
            rows = [r for r in csv.DictReader(stream) if lo <= int(r['wall_ms']) <= hi]
        result['frequency_mhz'] = {group: calibrate.distribution([float(r['mhz']) for r in rows
                                    if int(r['cpu']) in harness.cpu_set(meta[group + '_cpus'])])
                                   for group in ('server', 'client')}
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        result['reasons'].append(f'incomplete scaling telemetry: {exc}')
    for metric in EXTRA_METRICS:
        result['metrics'].setdefault(metric, None)
    result['valid'] = not result['reasons']
    return result


def analyze(directories, args, out):
    paths = [Path(p).resolve() for p in directories]
    if len(paths) != len(set(paths)):
        raise ValueError('duplicate run directory')
    runs = [read_run(p, args) for p in paths]
    keys = ('jar_sha256', 'world_sha256', 'warmup_s', 'measure_s', 'seed', 'spread', 'mobs',
            'center_x', 'center_z', 'jvm_args', 'view_distance', 'cameras', 'server_cpus', 'client_cpus', 'shard_size',
            'placement_scheme')
    signatures = {json.dumps({k: r['meta'].get(k) for k in keys}, sort_keys=True) for r in runs if 'meta' in r}
    if len(signatures) > 1:
        for r in runs:
            r['reasons'].append('mixed frozen inputs in scaling batch')
            r['valid'] = False
    sizes = sorted(set(r.get('meta', {}).get('bots', 0) for r in runs))
    metrics = (*calibrate.METRICS, *EXTRA_METRICS)
    scenarios = {}
    for size in sizes:
        selected = [r for r in runs if r.get('meta', {}).get('bots') == size]
        valid = [r for r in selected if r['valid']]
        scenarios[str(size)] = {'total': len(selected), 'valid': len(valid),
            'metrics': {m: calibrate.distribution([r['metrics'][m] for r in valid]) for m in metrics}}
    fits = {m: quadratic_fit([(r['meta']['bots'], r['metrics'][m]) for r in runs
                             if r['valid'] and r['metrics'][m] is not None])
            for m in ('region_tick.median_ms', 'network.bytes_s')}
    result = {'schema': 1, 'runs': runs, 'sizes': scenarios, 'fits': fits,
              'extrapolated_median_50ms_players': threshold_players(fits['region_tick.median_ms'])}
    calibrate.write_json(out / 'scaling.json', result)
    return result


def matrix(args, out):
    jar, world = Path(args.jar).resolve(), Path(args.world).resolve()
    sources = ('harness/run.py', 'harness/calibrate.py', 'harness/scaling.py', 'harness/bots/swarm.js',
               'harness/bots/recorder.js', 'harness/bots/package-lock.json', 'scripts/pressure-monitor.py')
    manifest = {'parameters': vars(args), 'jar_sha256': harness.sha256(jar),
                'world_sha256': harness.sha256(world), 'source_sha256': {p: harness.sha256(ROOT / p) for p in sources},
                'telemetry_sha256': harness.sha256(harness.TELEMETRY_JAR), 'runs': []}
    for name, executable in (('java', harness.JAVA), ('node', harness.NODE)):
        proc = subprocess.run([str(executable), '-version' if name == 'java' else '--version'],
                              capture_output=True, text=True, check=True)
        manifest[name] = proc.stdout + proc.stderr
    manifest['upstream_commit'] = subprocess.check_output(['git', '-C', str(ROOT / 'upstream/folia-26.1-baseline'),
                                                          'rev-parse', 'HEAD'], text=True).strip()
    calibrate.write_json(out / 'manifest.json', manifest)
    directories, fallback_done = [], False
    schedule = [(rep + 1, size) for rep in range(args.repetitions)
                for size in (SIZES[rep % len(SIZES):] + SIZES[:rep % len(SIZES)])]
    index = 0
    while index < len(schedule):
        rep, size = schedule[index]
        index += 1
        calibrate.check_ports()
        label = f'scaling-p{size}-r{rep}'
        entry = {'label': label, 'pre_pressure': calibrate.pressure_snapshot()}
        command = [sys.executable, '-I', '-u', str(ROOT / 'harness/run.py'), 'run',
                   '--jar', str(jar), '--world', str(world), '--label', label,
                   '--bots', str(size), '--mobs', '100', '--spread', '80', '--center-x', '16', '--center-z', '16',
                   '--warmup', str(args.warmup), '--duration', str(args.duration),
                   '--server-cpus', args.server_cpus, '--client-cpus', args.client_cpus,
                   '--shard-size', str(args.shard_size),
                   '--profile-seconds', '60' if rep == 1 and args.duration >= 120 else '0']
        entry['command'] = command
        manifest['runs'].append(entry)
        calibrate.write_json(out / 'manifest.json', manifest)
        before = set((ROOT / '.local/runs').glob(f'*-{label}'))
        print(f'Starting {label} ({index}/{len(schedule)})', flush=True)
        with (out / f'{label}.log').open('w') as log:
            proc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        entry['returncode'] = proc.returncode
        new = set((ROOT / '.local/runs').glob(f'*-{label}')) - before
        if len(new) != 1:
            raise RuntimeError('run failed to create exactly one directory')
        directory = new.pop()
        entry['run_dir'] = str(directory)
        calibrate.write_json(directory / 'calibration-entry.json', entry)
        calibrate.write_json(out / 'manifest.json', manifest)
        directories.append(directory)
        result = analyze(directories, args, out)
        latest = result['runs'][-1]
        print(f"Finished {label}: {'valid' if latest['valid'] else '; '.join(latest['reasons'])}", flush=True)
        if latest.get('meta', {}).get('host_abort'):
            print('ABORTING MATRIX: host PSI affected; no further workload.', flush=True)
            break
        if (out / 'STOP').exists():
            print('Stopping between runs: local STOP file exists.', flush=True)
            break
        if size == 500 and any('generator-limited' in r for r in latest['reasons']) and not fallback_done:
            schedule.insert(index, (1, 375))
            fallback_done = True
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--jar', default=str(ROOT / 'upstream/folia-26.1-baseline/folia-server/build/libs/folia-paperclip-26.1.2.local-SNAPSHOT.jar'))
    run.add_argument('--world', default=str(ROOT / '.local/worlds/city-1000.tar.gz'))
    run.add_argument('--repetitions', type=calibrate.positive_int, default=3)
    run.add_argument('--warmup', type=calibrate.positive_int, default=180)
    run.add_argument('--duration', type=calibrate.positive_int, default=300)
    run.add_argument('--server-cpus', default='0-2,6-8')
    run.add_argument('--client-cpus', default='3-5,9-11')
    run.add_argument('--shard-size', type=int, choices=range(1, 51), default=10)
    analysis = sub.add_parser('analyze')
    analysis.add_argument('run_dirs', nargs='+')
    for parser in (run, analysis):
        parser.add_argument('--out', help='new directory under .local/scaling')
        parser.add_argument('--cpu-psi', type=calibrate.positive_float, default=20)
        parser.add_argument('--memory-psi', type=calibrate.positive_float, default=5)
        parser.add_argument('--sustained-seconds', type=calibrate.positive_float, default=10)
    args = ap.parse_args()
    out = Path(args.out).resolve() if args.out else ROOT / '.local/scaling' / time.strftime('%Y%m%d-%H%M%S')
    if not out.is_relative_to(ROOT / '.local/scaling'):
        raise ValueError('output must be under .local/scaling')
    out.mkdir(parents=True, exist_ok=False)
    print(f'scaling folder: {out}', flush=True)
    result = matrix(args, out) if args.command == 'run' else analyze(args.run_dirs, args, out)
    for size, data in result['sizes'].items():
        print(size, data['valid'], '/', data['total'], json.dumps(data['metrics']), flush=True)
    print('fits:', json.dumps(result['fits']), flush=True)


if __name__ == '__main__':
    main()
