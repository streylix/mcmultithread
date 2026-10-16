"""Scaling acceptance and fits, using synthetic observations only."""
import json
import argparse
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import scaling
import run as harness
import calibrate


class ScalingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_quadratic_recovery_and_threshold(self):
        fit = scaling.quadratic_fit([(p, 2 + .01 * p + .0001 * p * p)
                                     for p in (50, 100, 250, 500) for _ in range(3)])
        self.assertAlmostEqual(fit['a'], 2)
        self.assertAlmostEqual(fit['b'], .01)
        self.assertAlmostEqual(fit['c'], .0001)
        self.assertAlmostEqual(fit['r2'], 1)
        threshold = scaling.threshold_players(fit)
        self.assertAlmostEqual(fit['a'] + fit['b'] * threshold + fit['c'] * threshold ** 2, 50)
        self.assertIsNone(scaling.quadratic_fit([(50, 1), (100, 2)]))
        self.assertIsNone(scaling.threshold_players({'a': 1, 'b': 0, 'c': -1}))

    def health(self, values):
        path = self.root / 'actions-00.jsonl.health.jsonl'
        path.write_text(''.join(json.dumps({'t': t * 1000, 'p50_ms': 10, 'p99_ms': value}) + '\n'
                                for t, value in values))
        meta = {'bots': 50, 'measure_start_wall_ms': 100000, 'measure_end_wall_ms': 120000,
                'shards': [{'index': 0, 'actions': 'actions-00.jsonl'}]}
        return scaling.generator_health(self.root, meta)

    def test_health_sustained_spike_equality_and_gaps(self):
        _, reasons = self.health([(t, 101 if t <= 110 else 10) for t in range(100, 121)])
        self.assertTrue(any('generator-limited' in r for r in reasons))
        _, reasons = self.health([(t, 101 if t == 105 else 100) for t in range(100, 121)])
        self.assertEqual(reasons, [])
        stats, reasons = self.health([(t, 101) for t in range(100, 121) if not 107 <= t <= 113])
        self.assertTrue(any('coverage' in r for r in reasons))
        self.assertLess(stats['0']['longest_p99_over_100ms_s'], 10)

    def test_network_deltas_and_changed_connections(self):
        for edge, value, t in (('start', 1000, 100000), ('end', 21000, 110000)):
            (self.root / f'network-{edge}.json').write_text(json.dumps({
                'wall_ms': t, 'connections': {'socket': {'bytes_sent': value, 'bytes_acked': value - 10}}}))
        metrics, reasons = scaling.network_metrics(self.root, {'bots_joined': 0, 'bots': 10, 'cameras': [{}]})
        self.assertEqual(reasons, [])
        self.assertEqual(metrics['bytes_s'], 2000)
        self.assertEqual(metrics['bytes_player_tick'], 10)
        metrics, _ = scaling.network_metrics(self.root, {'bots_joined': 0, 'bots': 10, 'cameras': [{}]}, tps=10)
        self.assertEqual(metrics['bytes_player_tick'], 20)
        _, reasons = scaling.network_metrics(self.root, {'bots_joined': 10, 'bots': 10, 'cameras': [{}]})
        self.assertTrue(reasons)

    def test_ss_parser_and_action_file_selection(self):
        raw = '0 0 127.0.0.1:25599 127.0.0.1:40000\n\t cubic bytes_sent:12000 bytes_acked:11900\n'
        with patch.object(harness.subprocess, 'run') as process:
            process.return_value.stdout = raw
            snapshot = harness.network_snapshot(self.root / 'network.json')
        self.assertEqual(list(snapshot['connections'].values()), [{'bytes_sent': 12000, 'bytes_acked': 11900}])
        for name in ('actions-00.jsonl', 'actions-01.jsonl', 'actions-00.jsonl.health.jsonl', 'actions.jsonl'):
            (self.root / name).touch()
        self.assertEqual([p.name for p in harness.action_files(self.root)], ['actions-00.jsonl', 'actions-01.jsonl'])

    def test_tick_drift_lagging_and_shard_actions_without_double_counting(self):
        (self.root / 'regions.csv').write_text('wall_ms,nano,region\n100000,1000000000,1\n')
        ticks = [(2000000000, 2), (61000000000, 50), (291000000000, 51)]
        (self.root / 'ticks.csv').write_text('region,tick_start_ns,tick_end_ns\n' + ''.join(
            f'1,{start},{start + ms * 1000000}\n' for start, ms in ticks))
        event = json.dumps({'t': 110000, 'action': 'walk', 'phase': 'done', 'ms': 10}) + '\n'
        (self.root / 'actions-00.jsonl').write_text(event)
        (self.root / 'actions.jsonl').write_text(event)
        (self.root / 'actions-00.jsonl.health.jsonl').write_text('{"p99_ms": 20}\n')
        summary = harness.summarize(self.root, {'label': 'test', 'measure_start_wall_ms': 100000,
                                               'measure_end_wall_ms': 400000})
        self.assertAlmostEqual(summary['lagging_tick_share'], 1 / 3)
        self.assertEqual(summary['tick_window_medians_ms']['first30'], 2)
        self.assertEqual(summary['tick_window_medians_ms']['last30'], 51)
        self.assertEqual(summary['actions']['walk']['done'], 1)

    def test_aborted_ramp_retains_actual_joins_and_no_invented_measurement(self):
        (self.root / 'meta.json').write_text(json.dumps({'label': 'abort', 'bots': 100,
            'mobs': 100, 'runner_error': 'host PSI abort'}))
        (self.root / 'actions-00.jsonl').write_text(''.join(
            json.dumps({'action': 'spawn', 'bot': f'b{i}'}) + '\n' for i in range(98)) + '{"action":')
        args = argparse.Namespace(cpu_psi=20, memory_psi=5, sustained_seconds=10)
        result = scaling.read_run(self.root, args)
        self.assertFalse(result['valid'])
        self.assertEqual(result['bots_joined_observed'], 98)
        self.assertTrue(any('host PSI abort' in r for r in result['reasons']))
        self.assertFalse(any('generator-limited' in r for r in result['reasons']))
        self.assertIsNone(result['metrics']['network.bytes_s'])

    def test_analysis_retains_invalid_runs_and_excludes_them_from_fits(self):
        observations = []
        for size, valid in ((50, True), (100, True), (250, True), (500, False)):
            value = 2 + .01 * size + .0001 * size * size if valid else 999999
            observations.append({'meta': {'bots': size}, 'valid': valid,
                'reasons': [] if valid else ['generator-limited'],
                'metrics': {m: value for m in (*calibrate.METRICS, *scaling.EXTRA_METRICS)}})
        args = argparse.Namespace(cpu_psi=20, memory_psi=5, sustained_seconds=10)
        with patch.object(scaling, 'read_run', side_effect=observations):
            result = scaling.analyze([self.root / str(i) for i in range(4)], args, self.root)
        self.assertEqual(len(result['runs']), 4)
        self.assertEqual(result['sizes']['500']['valid'], 0)
        fit = result['fits']['region_tick.median_ms']
        self.assertEqual(fit['n'], 3)
        self.assertAlmostEqual(fit['c'], .0001)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            scaling.analyze([self.root, self.root], args, self.root)

    def test_profile_full_tick_denominator_and_nested_phases(self):
        directory = self.root / 'profiler' / '123'
        directory.mkdir(parents=True)
        (directory / 'region-1.txt').write_text(
            '  ├─Full Tick 80.000% total, 80.000% parent, self 10% total, self 10% children, avg 1 sum 20, 1,000.000ms raw sum\n'
            '  │ ├─Chunk Source Tick 40.000% total, 50.000% parent, self 10% total, self 10% children, avg 1 sum 20, 500.000ms raw sum\n'
            '  │ │ └─Entity Tracker Tick 20.000% total, 50.000% parent, self 10% total, self 10% children, avg 1 sum 20, 250.000ms raw sum\n')
        profile = scaling.phase_profile(self.root)
        self.assertEqual(profile['share_pct']['Chunk Source Tick'], 50)
        self.assertEqual(profile['share_pct']['Entity Tracker Tick'], 25)


if __name__ == '__main__':
    unittest.main()
