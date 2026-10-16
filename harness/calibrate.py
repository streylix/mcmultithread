#!/usr/bin/env python3
"""Interleaved Folia noise calibration; raw results stay under .local/calibration.

  run [--repetitions 5 --warmup 60 --duration 120]
  analyze RUN_DIR...    re-read telemetry, including invalid runs
"""
import argparse
import csv
import datetime
import json
import math
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
import run as harness  # noqa: E402

SCENARIOS = {"idle": (0, 0), "crowd50": (50, 100)}
ACTIONS = ("walk", "place", "break", "attack", "chat")
BASE_METRICS = ("region_tick.median_ms", "region_tick.p95_ms", "region_tick.p99_ms",
                "region_tick.max_ms", "global_tick.median_ms", "region_tps_mean")
METRICS = (*BASE_METRICS, *(f"actions.{a}.{m}" for a in ACTIONS for m in ("p50_ms", "fail_rate")))


def write_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=1, allow_nan=False) + "\n")
    tmp.replace(path)


def output_dir(path=None):
    out = Path(path) if path else ROOT / ".local" / "calibration" / time.strftime("%Y%m%d-%H%M%S")
    out = out.resolve()
    if not out.is_relative_to(ROOT / ".local" / "calibration"):
        raise ValueError("output must be under .local/calibration")
    out.mkdir(parents=True, exist_ok=False)
    return out


def pressure_snapshot():
    result = {"wall_ms": int(time.time() * 1000)}
    for resource in ("cpu", "memory", "io"):
        result[resource] = {}
        for line in Path(f"/proc/pressure/{resource}").read_text().splitlines():
            kind, *fields = line.split()
            result[resource][kind] = {k: float(v) for k, v in (s.split("=") for s in fields)}
    return result


def distribution(values):
    """Sample stdev and relative CV; a zero mean or fewer than two reps has no CV."""
    values = [v for v in values if v is not None]
    mean = statistics.fmean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    return {"n": len(values), "mean": mean, "stdev": stdev,
            "cv": stdev / abs(mean) if stdev is not None and mean else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def pressure_window(path, lo, hi, cpu_limit, memory_limit, sustained):
    """Check PSI some avg10 within measurement; gaps break sustained sequences."""
    reasons = []
    if not path.exists() or lo is None or hi is None or hi <= lo:
        return {}, ["missing host pressure or measurement window"]
    rows = []
    with path.open() as stream:
        for row in csv.DictReader(stream):
            t = float(row["time"])
            if lo / 1000 <= t <= hi / 1000:
                vals = {k: float(row[k]) for k in ("cpu", "memory", "io", "temp_c")}
                if not all(math.isfinite(vals[k]) for k in ("cpu", "memory", "io")):
                    raise ValueError("non-finite PSI sample")
                rows.append({"time": t, **vals})
    rows.sort(key=lambda r: r["time"])
    if not rows:
        return {}, ["no host samples in measurement window"]
    gaps = [b["time"] - a["time"] for a, b in zip(rows, rows[1:])]
    if (rows[0]["time"] - lo / 1000 > 2 or hi / 1000 - rows[-1]["time"] > 2
            or any(g > 3 or g <= 0 for g in gaps)):
        reasons.append("incomplete host pressure coverage (edge >2 s or sample gap >3 s)")
    result = {"samples": len(rows), "max_gap_s": max(gaps, default=0)}
    for resource in ("cpu", "memory", "io", "temp_c"):
        result[resource] = distribution([r[resource] for r in rows if math.isfinite(r[resource])])
    for resource, limit in (("cpu", cpu_limit), ("memory", memory_limit)):
        start, previous, longest = None, None, 0
        for row in rows:
            t = row["time"]
            if row[resource] > limit:
                if start is None or t - previous > 2:
                    start = t
                longest = max(longest, t - start)
            else:
                start = None
            previous = t
        result[resource]["longest_above_limit_s"] = longest
        if longest >= sustained:
            reasons.append(f"{resource} PSI some avg10 > {limit:g}% for {longest:g} s (limit {sustained:g} s)")
    return result, reasons


def scenario_for(meta):
    for scenario, (bots, mobs) in SCENARIOS.items():
        if meta.get("bots") == bots and meta.get("mobs") == mobs:
            return scenario
    return "other"


def read_run(directory, args, scaling=False):
    """Retain failures explicitly; never substitute zero for an absent metric."""
    directory = Path(directory).resolve()
    entry_path = directory / "calibration-entry.json"
    entry = json.loads(entry_path.read_text()) if entry_path.exists() else {}
    result = {"run_dir": str(directory), "label": entry.get("label", directory.name),
              "scenario": entry.get("scenario", "other"), "valid": False, "reasons": [],
              "pre_pressure": entry.get("pre_pressure"), "metrics": {m: None for m in METRICS}}
    reasons = result["reasons"]
    if entry.get("returncode", 0):
        reasons.append(f"run.py exited {entry['returncode']}")
    try:
        meta = json.loads((directory / "meta.json").read_text())
        result.update(meta=meta, label=meta["label"], scenario=scenario_for(meta))
        if result["scenario"] == "other" and not scaling:
            reasons.append("not an idle or crowd50 scenario")
        if scaling:
            joined = meta.get("bots_joined")
            if joined is None:
                joined = len(harness.joined_bots(directory))
            result["bots_joined_observed"] = joined
            if joined < .95 * meta["bots"]:
                reasons.append(f"generator-limited: fewer than 95% joined: {joined} / {meta['bots']}")
        elif meta.get("bots_joined") != meta.get("bots"):
            reasons.append(f"incomplete bot joins: {meta.get('bots_joined')} / {meta.get('bots')}")
        if meta.get("runner_error"):
            reasons.append(meta["runner_error"])
        lo, hi = meta.get("measure_start_wall_ms"), meta.get("measure_end_wall_ms")
        host, pressure_reasons = pressure_window(directory / "host.csv", lo, hi,
                                                 args.cpu_psi, args.memory_psi, args.sustained_seconds)
        result["host"] = host
        reasons.extend(pressure_reasons)
        if lo is None or hi is None or hi <= lo:
            raise ValueError("missing or reversed measurement window")
        if abs((hi - lo) / 1000 - meta["measure_s"]) > 2:
            reasons.append("actual measurement duration differs by more than 2 s")
        for filename in ("ticks.csv", "regions.csv", "actions.jsonl", "summary.json"):
            if not (directory / filename).exists():
                reasons.append(f"missing {filename}")
        summary = harness.summarize(directory, meta)
        result["summary"] = summary
        for kind in ("region_tick", "global_tick"):
            if not summary[kind]["n"]:
                reasons.append(f"no {kind} samples")
        for metric in BASE_METRICS:
            parts = metric.split(".")
            value = summary
            for part in parts:
                value = value[part]
            result["metrics"][metric] = value
        for action in ACTIONS:
            stats = summary["actions"].get(action)
            if stats:
                terminals = stats["done"] + stats["fail"]
                result["metrics"][f"actions.{action}.p50_ms"] = stats["p50_ms"]
                result["metrics"][f"actions.{action}.fail_rate"] = stats["fail"] / terminals if terminals else None
        # Lifecycle events are not gameplay actions and must not disappear in averages.
        for action in ("kicked", "error", "disconnect", "script"):
            if action in summary["actions"]:
                reasons.append(f"bot lifecycle event during measurement: {action}")
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        reasons.append(f"incomplete or malformed run: {type(exc).__name__}: {exc}")
    result["valid"] = not reasons
    return result


def analyze(directories, args, out):
    paths = [Path(p).resolve() for p in directories]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate run directory (would double-count a repetition)")
    runs = [read_run(p, args) for p in paths]
    # Pool repetitions only when their frozen inputs agree. Missing legacy spread
    # metadata is kept explicit rather than guessed from a label.
    keys = ("jar_sha256", "world_sha256", "warmup_s", "measure_s", "seed", "spread",
            "center_x", "center_z", "jvm_args", "view_distance", "cameras")
    signatures = {json.dumps({k: r["meta"].get(k) for k in keys}, sort_keys=True)
                  for r in runs if "meta" in r}
    if len(signatures) > 1:
        for r in runs:
            r["reasons"].append("mixed frozen inputs in analysis batch; analyze matching runs separately")
            r["valid"] = False
    scenarios = {}
    for scenario in SCENARIOS:
        selected = [r for r in runs if r["scenario"] == scenario]
        valid = [r for r in selected if r["valid"]]
        scenarios[scenario] = {"total": len(selected), "valid": len(valid), "invalid": len(selected) - len(valid),
                               "metrics": {m: distribution([r["metrics"][m] for r in valid]) for m in METRICS}}
    result = {"schema": 1, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "pressure_policy": {"cpu_some_avg10_limit_pct": args.cpu_psi,
                                  "memory_some_avg10_limit_pct": args.memory_psi,
                                  "sustained_seconds": args.sustained_seconds},
              "statistics": {"stdev": "sample (ddof=1)", "cv": "stdev / abs(mean); null for zero mean or n < 2",
                             "actions": "terminal events in measurement, p50 includes failures; fail / (done + fail)"},
              "runs": runs, "scenarios": scenarios}
    write_json(out / "calibration.json", result)
    return result


def print_table(result):
    print("\nscenario metric                              n        mean       stdev      CV%         min         max", flush=True)
    def fmt(x):
        return f"{x:.6g}" if x is not None else "n/a"
    for scenario, data in result["scenarios"].items():
        print(f"{scenario}: {data['valid']}/{data['total']} valid", flush=True)
        for metric, stats in data["metrics"].items():
            cv = stats["cv"] * 100 if stats["cv"] is not None else None
            print(f"{scenario:8} {metric:35} {stats['n']:2} {fmt(stats['mean']):>11} {fmt(stats['stdev']):>11} "
                  f"{fmt(cv):>8} {fmt(stats['min']):>11} {fmt(stats['max']):>11}", flush=True)
    for run in result["runs"]:
        if not run["valid"]:
            print(f"INVALID {run['label']}: {'; '.join(run['reasons'])}", flush=True)


def check_ports():
    """Refuse to start another server on either fixed harness port."""
    for port in (harness.PORT, harness.RCON_PORT):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"harness port {port} is already in use; no run started")


def run_matrix(args, out):
    jar, world = Path(args.jar).resolve(), Path(args.world).resolve()
    for path in (jar, world, harness.JAVA, harness.NODE, harness.TELEMETRY_JAR):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_paths = ("harness/run.py", "harness/calibrate.py", "harness/bots/swarm.js",
                    "harness/bots/recorder.js", "harness/bots/package-lock.json", "scripts/pressure-monitor.py")
    manifest = {"parameters": vars(args), "jar_sha256": harness.sha256(jar),
                "world_sha256": harness.sha256(world),
                "source_sha256": {p: harness.sha256(ROOT / p) for p in source_paths},
                "telemetry_sha256": harness.sha256(harness.TELEMETRY_JAR), "runs": []}
    for name, executable in (("java", harness.JAVA), ("node", harness.NODE)):
        version = subprocess.run([str(executable), "-version" if name == "java" else "--version"],
                                 capture_output=True, text=True, check=True)
        manifest[name] = version.stdout + version.stderr
    write_json(out / "manifest.json", manifest)
    directories = []
    for rep in range(1, args.repetitions + 1):
        for scenario, (bots, mobs) in SCENARIOS.items():
            check_ports()
            label = f"calib-{scenario}-r{rep}"
            entry = {"label": label, "scenario": scenario, "pre_pressure": pressure_snapshot()}
            command = [sys.executable, "-I", "-u", str(ROOT / "harness" / "run.py"), "run",
                       "--jar", str(jar), "--world", str(world), "--label", label,
                       "--bots", str(bots), "--mobs", str(mobs), "--spread", "40", "--center-x", "16",
                       "--center-z", "16", "--warmup", str(args.warmup), "--duration", str(args.duration)]
            entry["command"] = command
            manifest["runs"].append(entry)
            write_json(out / "manifest.json", manifest)
            before = set((ROOT / ".local" / "runs").glob(f"*-{label}"))
            print(f"Starting {label}: {bots} bots, {mobs} mobs, warmup {args.warmup}s, measure {args.duration}s", flush=True)
            with (out / f"{label}.log").open("w") as log:
                proc = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            entry["returncode"] = proc.returncode
            new = set((ROOT / ".local" / "runs").glob(f"*-{label}")) - before
            if len(new) != 1:
                # Preserve even attempts that failed before making a run directory.
                directory = out / f"failed-{label}"
                directory.mkdir()
            else:
                directory = new.pop()
            entry["run_dir"] = str(directory)
            write_json(directory / "calibration-entry.json", entry)
            write_json(out / "manifest.json", manifest)
            directories.append(directory)
            result = analyze(directories, args, out)
            latest = result["runs"][-1]
            status = "valid" if latest["valid"] else "INVALID: " + "; ".join(latest["reasons"])
            print(f"Finished {label}: {status}", flush=True)
            # If cleanup failed, check_ports above prevents overlapping the next run.
    return result


def positive_int(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return n


def positive_float(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--jar", default=str(ROOT / "upstream/folia-26.1-baseline/folia-server/build/libs/folia-paperclip-26.1.2.local-SNAPSHOT.jar"))
    run.add_argument("--world", default=str(ROOT / ".local/worlds/city-1000.tar.gz"))
    run.add_argument("--repetitions", type=positive_int, default=5)
    run.add_argument("--warmup", type=positive_int, default=60)
    run.add_argument("--duration", type=positive_int, default=120)
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("run_dirs", nargs="+")
    for parser in (run, analyze_parser):
        parser.add_argument("--out", help="new directory under .local/calibration (default: timestamp)")
        parser.add_argument("--cpu-psi", type=positive_float, default=20)
        parser.add_argument("--memory-psi", type=positive_float, default=5)
        parser.add_argument("--sustained-seconds", type=positive_float, default=10)
    args = ap.parse_args()
    out = output_dir(args.out)
    print(f"calibration folder: {out}", flush=True)
    result = run_matrix(args, out) if args.command == "run" else analyze(args.run_dirs, args, out)
    print_table(result)
    print(f"results: {out / 'calibration.json'}", flush=True)


if __name__ == "__main__":
    main()
