"""Calibration acceptance checks with synthetic telemetry; no server required."""
import argparse
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibrate


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = argparse.Namespace(cpu_psi=20, memory_psi=5, sustained_seconds=10)

    def host(self, cpu=None, memory=None, skip=()):
        path = self.root / "host.csv"
        rows = ["time,cpu,memory,io,temp_c,breach"]
        for t in range(100, 121):
            if t not in skip:
                rows.append(f"{t},{cpu(t) if cpu else 0},{memory(t) if memory else 0},0,60,")
        path.write_text("\n".join(rows) + "\n")
        return path

    def test_sustained_pressure_and_spike(self):
        path = self.host(cpu=lambda t: 21 if t <= 110 else 0, memory=lambda t: 6 if t == 115 else 0)
        host, reasons = calibrate.pressure_window(path, 100000, 120000, 20, 5, 10)
        self.assertEqual(host["cpu"]["longest_above_limit_s"], 10)
        self.assertEqual(len(reasons), 1)
        self.assertIn("cpu PSI", reasons[0])

    def test_threshold_equality_and_outside_window(self):
        path = self.host(cpu=lambda t: 99 if t < 105 else 20, memory=lambda t: 5)
        _, reasons = calibrate.pressure_window(path, 105000, 120000, 20, 5, 10)
        self.assertEqual(reasons, [])

    def test_memory_pressure_and_missing_coverage(self):
        path = self.host(memory=lambda t: 6)
        _, reasons = calibrate.pressure_window(path, 100000, 120000, 20, 5, 10)
        self.assertIn("memory PSI", reasons[0])
        path = self.host(cpu=lambda t: 30, skip=range(108, 113))
        host, reasons = calibrate.pressure_window(path, 100000, 120000, 20, 5, 10)
        self.assertLess(host["cpu"]["longest_above_limit_s"], 10)
        self.assertEqual(len(reasons), 1)
        self.assertIn("coverage", reasons[0])

    def fixture(self, name, offset=0):
        directory = self.root / name
        directory.mkdir()
        meta = {"label": name, "bots": 50, "mobs": 100, "bots_joined": 50,
                "measure_start_wall_ms": 100000, "measure_end_wall_ms": 120000, "measure_s": 20}
        (directory / "meta.json").write_text(json.dumps(meta))
        (directory / "summary.json").write_text("{}")  # Analyzer must read raw telemetry.
        (directory / "host.csv").write_text(self.host().read_text())
        (directory / "regions.csv").write_text("wall_ms,nano,region\n100000,1000000000,1\n")
        rows = ["region,tick_start_ns,tick_end_ns"]
        for region, start, duration in ((1, 900000000, 900), (1, 2000000000, 2 + offset),
                                        (1, 3000000000, 4 + offset), (-1, 2000000000, 1),
                                        (1, 22000000000, 900)):
            rows.append(f"{region},{start},{start + int(duration * 1e6)}")
        (directory / "ticks.csv").write_text("\n".join(rows) + "\n")
        events = [{"t": t, "action": "walk", "phase": phase, "ms": ms} for t, phase, ms in
                  ((99000, "done", 9000), (105000, "attempt", 0), (106000, "done", 20),
                   (107000, "fail", 40), (121000, "fail", 9000))]
        (directory / "actions.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        return directory

    def test_raw_windows_aggregation_and_invalid_retention(self):
        first, second = self.fixture("first"), self.fixture("second", 2)
        meta_path = second / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["bots_joined"] = 49
        meta_path.write_text(json.dumps(meta))
        result = calibrate.analyze([first, second], self.args, self.root)
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["scenarios"]["crowd50"]["valid"], 1)
        self.assertIn("incomplete bot joins", result["runs"][1]["reasons"][0])
        metrics = result["runs"][0]["metrics"]
        self.assertEqual(metrics["region_tick.max_ms"], 4)
        self.assertEqual(metrics["region_tps_mean"], .1)
        self.assertEqual(metrics["actions.walk.fail_rate"], .5)
        self.assertEqual(metrics["actions.walk.p50_ms"], 20)
        self.assertIsNone(metrics["actions.chat.p50_ms"])
        self.assertEqual(result["scenarios"]["crowd50"]["metrics"]["region_tick.max_ms"]["n"], 1)

    def test_statistics_zero_missing_and_sample_stdev(self):
        stats = calibrate.distribution([1, 3, None])
        self.assertEqual(stats["mean"], 2)
        self.assertAlmostEqual(stats["stdev"], math.sqrt(2))
        self.assertAlmostEqual(stats["cv"], math.sqrt(2) / 2)
        self.assertIsNone(calibrate.distribution([0, 0])["cv"])
        self.assertIsNone(calibrate.distribution([1])["stdev"])
        self.assertIsNone(calibrate.distribution([])["mean"])

    def test_duplicate_and_mixed_inputs(self):
        first, second = self.fixture("first"), self.fixture("second")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            calibrate.analyze([first, first], self.args, self.root)
        meta_path = second / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["seed"] = 2
        meta_path.write_text(json.dumps(meta))
        result = calibrate.analyze([first, second], self.args, self.root)
        self.assertTrue(all(not r["valid"] for r in result["runs"]))
        self.assertTrue(all("mixed frozen inputs" in r["reasons"][-1] for r in result["runs"]))


if __name__ == "__main__":
    unittest.main()
