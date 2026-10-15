#!/usr/bin/env python3
"""Project 5K run orchestrator.

  prepare-world  pregenerate a built world with Chunky on the server jar, then archive it
                 with its SHA-256 (fixtures are restored from the archive for every run)
  run            one measured run: restore world, start server with TickTelemetry, place
                 camera recorders, start the bot swarm, measure, collect everything

Raw output stays in .local/runs/<timestamp>-<label>/ (ignored). summary.json in that
folder holds only aggregate, synthetic data.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness" / "world"))
from rcon import Rcon  # noqa: E402

JAVA = ROOT / ".local" / "jdk-25" / "bin" / "java"
NODE = ROOT / ".local" / "node" / "bin" / "node"
BOTS = ROOT / "harness" / "bots"
TELEMETRY_JAR = ROOT / "harness" / "telemetry" / "build" / "TickTelemetry.jar"
CHUNKY_JAR = ROOT / ".local" / "plugins" / "Chunky-Bukkit-1.5.3.jar"
PORT, RCON_PORT = 25599, 25598
JVM_ARGS = ["-Xms6G", "-Xmx6G", "-XX:+UseG1GC", "-XX:+AlwaysPreTouch"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def wait_for_log(path, text, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and text in path.read_text(errors="replace"):
            return
        time.sleep(0.5)
    raise TimeoutError(f"'{text}' not seen in {path}")


class Server:
    """A Folia server in its own directory, controlled over RCON."""

    def __init__(self, directory, jar, world_src, plugins, view_distance=10):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jar, self.dir / "server.jar")
        if world_src.is_dir():
            shutil.copytree(world_src, self.dir / "world")
        else:
            with tarfile.open(world_src) as tar:
                tar.extractall(self.dir, filter="data")
        (self.dir / "plugins").mkdir(exist_ok=True)
        for p in plugins:
            shutil.copy2(p, self.dir / "plugins" / p.name)
        self.password = secrets.token_hex(16)
        (self.dir / "eula.txt").write_text("eula=true\n")
        props = {
            "online-mode": "false", "server-ip": "127.0.0.1", "server-port": PORT,
            "enable-rcon": "true", "rcon.port": RCON_PORT, "rcon.password": self.password,
            "spawn-protection": 0, "max-players": 6000, "view-distance": view_distance,
            "simulation-distance": 10, "pause-when-empty-seconds": 0, "sync-chunk-writes": "false",
        }
        (self.dir / "server.properties").write_text("".join(f"{k}={v}\n" for k, v in props.items()))
        self.log = self.dir / "server.log"
        self.proc = None
        self.rcon = None

    def start(self, timeout=600):
        self.proc = subprocess.Popen([str(JAVA), *JVM_ARGS, "-jar", "server.jar", "--nogui"], cwd=self.dir,
                                     stdout=self.log.open("w"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        wait_for_log(self.log, "Done (", timeout)
        wait_for_log(self.log, "RCON running", 60)
        self.rcon = Rcon("127.0.0.1", RCON_PORT, self.password)

    def cmd(self, command):
        return self.rcon.command(command)

    def stop(self, timeout=300):
        if self.proc is None:
            return
        try:
            self.cmd("stop")
            self.rcon.close()
        except Exception:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# --- prepare-world --------------------------------------------------------------------

def prepare_world(args):
    out = Path(args.out).resolve()
    work = out.parent / (out.name + ".work")
    if work.exists():
        shutil.rmtree(work)
    srv = Server(work, Path(args.jar), Path(args.world), [CHUNKY_JAR])
    srv.start()
    try:
        for c in ["chunky world world", "chunky shape square", "chunky center 0 0",
                  f"chunky radius {args.radius}", "chunky start"]:
            print(c, "->", srv.cmd(c))
        wait_for_log(srv.log, "Task finished for world", args.timeout)
        srv.cmd("save-all flush")
    finally:
        srv.stop()
    with tarfile.open(out, "w:gz") as tar:
        tar.add(work / "world", arcname="world")
    digest = sha256(out)
    manifest = {"archive": out.name, "sha256": digest, "pregenerated_radius": args.radius,
                "server_jar_sha256": sha256(args.jar), "built_world": str(Path(args.world).name)}
    layout = Path(args.world).parent / "layout.json"
    if layout.exists():
        manifest["layout_sha256"] = sha256(layout)
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=1))
    shutil.rmtree(work)
    print(json.dumps(manifest, indent=1))


# --- run ------------------------------------------------------------------------------

def start_node(script, args_, log):
    return subprocess.Popen([str(NODE), script, *map(str, args_)], cwd=BOTS,
                            stdout=log.open("w"), stderr=subprocess.STDOUT)


def run(args):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rundir = ROOT / ".local" / "runs" / f"{stamp}-{args.label}"
    rundir.mkdir(parents=True)
    cameras = json.loads(Path(args.cameras).read_text()) if args.cameras else []
    meta = {"label": args.label, "jar": Path(args.jar).name, "jar_sha256": sha256(args.jar),
            "world": Path(args.world).name, "world_sha256": sha256(args.world),
            "bots": args.bots, "seed": args.seed, "warmup_s": args.warmup, "measure_s": args.duration,
            "mobs": args.mobs, "cameras": cameras, "jvm_args": JVM_ARGS, "view_distance": args.view_distance}
    host = subprocess.Popen([sys.executable, "-I", str(ROOT / "scripts" / "pressure-monitor.py"), "--interval", "1"],
                            stdout=(rundir / "host.csv").open("w"), stderr=subprocess.DEVNULL)
    srv = Server(rundir / "server", Path(args.jar), Path(args.world), [TELEMETRY_JAR], args.view_distance)
    recorders, swarm = [], None
    rng = random.Random(args.seed)
    try:
        srv.start()
        meta["server_ready_wall_ms"] = int(time.time() * 1000)
        for i, cam in enumerate(cameras):
            name = f"cam{i}"
            rec = start_node("recorder.js", ["127.0.0.1", PORT, name, rundir / "recordings" / name], rundir / f"{name}.log")
            recorders.append((name, rec))
            wait_for_log(rundir / f"{name}.log", '"event":"spawn"', 120)
            srv.cmd(f"gamemode spectator {name}")
            srv.cmd(f"tp {name} {cam['x']} {cam['y']} {cam['z']} {cam.get('yaw', 0)} {cam.get('pitch', 30)}")
        for _ in range(args.mobs):
            x, z = rng.randint(-450, 450), rng.randint(-450, 450)
            srv.cmd(f"summon {rng.choice(['cow', 'pig', 'sheep', 'chicken'])} {x} 1 {z}")
        swarm = start_node("swarm.js", ["127.0.0.1", PORT, args.bots, args.seed, rundir / "actions.jsonl", "b", 450],
                           rundir / "swarm.log")
        joined, deadline = set(), time.time() + 60 + args.bots * 0.5
        while len(joined) < args.bots and time.time() < deadline:
            time.sleep(1)
            if (rundir / "actions.jsonl").exists():
                for line in (rundir / "actions.jsonl").read_text().splitlines():
                    e = json.loads(line)
                    if e["action"] == "spawn" and e["bot"] not in joined:
                        joined.add(e["bot"])
                        srv.cmd(f"gamemode creative {e['bot']}")
                        srv.cmd(f"give {e['bot']} oak_planks 640")
                        srv.cmd(f"tp {e['bot']} {rng.randint(-450, 450)} 1 {rng.randint(-450, 450)}")
        meta["bots_joined"] = len(joined)
        meta["warmup_start_wall_ms"] = int(time.time() * 1000)
        time.sleep(args.warmup)
        meta["measure_start_wall_ms"] = int(time.time() * 1000)
        time.sleep(args.duration)
        meta["measure_end_wall_ms"] = int(time.time() * 1000)
    finally:
        if swarm:
            swarm.send_signal(signal.SIGTERM)
            swarm.wait(timeout=60)
        for _, rec in recorders:
            rec.send_signal(signal.SIGINT)
            rec.wait(timeout=60)
        srv.stop()
        host.terminate()
    for name, _ in recorders:
        src = rundir / "recordings" / name
        with zipfile.ZipFile(rundir / "recordings" / f"{name}.mcpr", "w", zipfile.ZIP_DEFLATED) as z:
            for f in ("recording.tmcpr", "metaData.json"):
                z.write(src / f, f)
    tel = srv.dir / "plugins" / "TickTelemetry"
    for f in ("ticks.csv", "regions.csv"):
        if (tel / f).exists():
            shutil.copy2(tel / f, rundir / f)
    (rundir / "meta.json").write_text(json.dumps(meta, indent=1))
    summary = summarize(rundir, meta)
    (rundir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"run folder: {rundir}")


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def summarize(rundir, meta):
    """Aggregate tick timings and bot actions inside the measurement window."""
    regions = list(csv.DictReader((rundir / "regions.csv").open())) if (rundir / "regions.csv").exists() else []
    # Map nanoTime to wall clock from the per-second anchors.
    anchors = sorted({(int(r["nano"]), int(r["wall_ms"])) for r in regions})
    def wall(ns):
        if not anchors:
            return None
        n0, w0 = min(anchors, key=lambda a: abs(a[0] - ns))
        return w0 + (ns - n0) / 1e6
    lo, hi = meta.get("measure_start_wall_ms"), meta.get("measure_end_wall_ms")
    ticks_ms, global_ms, per_region = [], [], {}
    if (rundir / "ticks.csv").exists():
        for t in csv.DictReader((rundir / "ticks.csv").open()):
            w = wall(int(t["tick_start_ns"]))
            if w is None or lo is None or not (lo <= w <= hi):
                continue
            ms = (int(t["tick_end_ns"]) - int(t["tick_start_ns"])) / 1e6
            (global_ms if t["region"] == "-1" else ticks_ms).append(ms)
            per_region.setdefault(t["region"], 0)
            per_region[t["region"]] += 1
    seconds = (hi - lo) / 1000 if lo and hi else None
    region_ticks = [n for r, n in per_region.items() if r != "-1"]
    actions = {}
    if (rundir / "actions.jsonl").exists():
        for line in (rundir / "actions.jsonl").read_text().splitlines():
            e = json.loads(line)
            if lo is None or not (lo <= e["t"] <= hi) or e["phase"] == "attempt":
                continue
            a = actions.setdefault(e["action"], {"done": 0, "fail": 0, "ms": []})
            a[e["phase"]] = a.get(e["phase"], 0) + 1
            if "ms" in e:
                a["ms"].append(e["ms"])
    for a in actions.values():
        ms = a.pop("ms")
        a["p50_ms"], a["p99_ms"] = pct(ms, 50), pct(ms, 99)
    def stats(v):
        return {"n": len(v), "median_ms": pct(v, 50), "p95_ms": pct(v, 95), "p99_ms": pct(v, 99),
                "max_ms": max(v) if v else None, "mean_ms": statistics.fmean(v) if v else None}
    return {
        "label": meta["label"], "bots_joined": meta.get("bots_joined"), "measure_s": seconds,
        "region_tick": stats(ticks_ms), "global_tick": stats(global_ms),
        "regions_seen": len(region_ticks),
        "region_tps_mean": statistics.fmean(n / seconds for n in region_ticks) if region_ticks and seconds else None,
        "global_tps": per_region.get("-1", 0) / seconds if seconds else None,
        "actions": actions,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-world")
    p.add_argument("--jar", required=True)
    p.add_argument("--world", required=True, help="built world directory")
    p.add_argument("--out", required=True, help="archive path (.tar.gz)")
    p.add_argument("--radius", type=int, default=640)
    p.add_argument("--timeout", type=int, default=3600)
    r = sub.add_parser("run")
    r.add_argument("--jar", required=True)
    r.add_argument("--world", required=True, help="world archive (.tar.gz)")
    r.add_argument("--label", default="run")
    r.add_argument("--bots", type=int, default=50)
    r.add_argument("--mobs", type=int, default=100)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--warmup", type=int, default=60)
    r.add_argument("--duration", type=int, default=120)
    r.add_argument("--view-distance", type=int, default=10)
    r.add_argument("--cameras", help="JSON list of {x,y,z,yaw,pitch}")
    a = ap.parse_args()
    prepare_world(a) if a.command == "prepare-world" else run(a)


if __name__ == "__main__":
    main()
