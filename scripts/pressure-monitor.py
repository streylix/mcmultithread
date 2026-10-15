#!/usr/bin/env python3
"""Watch host pressure (PSI) and temperature; stop a workload when thresholds trip.

Usage: python3 scripts/pressure-monitor.py [--unit NAME | --pid PID] [--interval S]
Without a target it only logs. Logs CSV to stdout: time, cpu/mem/io some avg10, temp.
Thresholds are provisional until baseline calibration (docs/BENCHMARK_PROTOCOL.md).
"""
import argparse, glob, os, signal, subprocess, sys, time

LIMITS = {"cpu": 60.0, "memory": 10.0, "io": 30.0}  # PSI some avg10, percent
TEMP_LIMIT_C = 90.0
TRIP_SAMPLES = 3  # consecutive breaches before stopping


def psi(resource):
    with open(f"/proc/pressure/{resource}") as f:
        for line in f:
            if line.startswith("some"):
                return float(line.split()[1].split("=")[1])
    return 0.0


def max_temp_c():
    temps = []
    for path in glob.glob("/sys/class/hwmon/hwmon*/temp*_input"):
        try:
            with open(path) as f:
                temps.append(int(f.read()) / 1000)
        except OSError:
            pass
    return max(temps) if temps else float("nan")


def stop(args):
    if args.unit:
        subprocess.run(["systemctl", "--user", "stop", args.unit], check=False)
    elif args.pid:
        os.kill(args.pid, signal.SIGTERM)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    breaches = 0
    print("time,cpu,memory,io,temp_c,breach", flush=True)
    while True:
        vals = {r: psi(r) for r in LIMITS}
        temp = max_temp_c()
        over = [r for r, v in vals.items() if v > LIMITS[r]]
        if temp > TEMP_LIMIT_C:
            over.append("temp")
        breaches = breaches + 1 if over else 0
        print(f"{time.time():.0f},{vals['cpu']},{vals['memory']},{vals['io']},{temp:.1f},{'|'.join(over)}", flush=True)
        if breaches >= TRIP_SAMPLES and (args.unit or args.pid):
            print(f"ABORT: sustained {','.join(over)}; stopping workload", file=sys.stderr, flush=True)
            stop(args)
            return 3
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
