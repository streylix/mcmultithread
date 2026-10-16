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
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time
import threading
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


def wait_for_log(path, text, timeout, guard=None):
    end = time.time() + timeout
    while time.time() < end:
        if guard:
            guard()
        if path.exists() and text in path.read_text(errors="replace"):
            return
        time.sleep(0.5)
    raise TimeoutError(f"'{text}' not seen in {path}")


class Server:
    """A Folia server in its own directory, controlled over RCON."""

    def __init__(self, directory, jar, world_src, plugins, view_distance=10, cpus=None):
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
        self.cpus = cpus

    def start(self, timeout=600, guard=None):
        self.proc = subprocess.Popen(affinity(self.cpus) + [str(JAVA), *JVM_ARGS, "-jar", "server.jar", "--nogui"], cwd=self.dir,
                                     stdout=self.log.open("w"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        wait_for_log(self.log, "Done (", timeout, guard)
        wait_for_log(self.log, "RCON running", 60, guard)
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
            self.proc.wait()


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

def affinity(cpus):
    return ["taskset", "-c", cpus] if cpus else []


def cpu_set(value):
    result = set()
    for part in value.split(","):
        ends = list(map(int, part.split("-")))
        if len(ends) > 2 or ends[0] < 0 or ends[-1] < ends[0]:
            raise ValueError("invalid CPU list")
        result.update(range(ends[0], ends[-1] + 1))
    return result


def network_snapshot(path):
    """Server-side TCP payload counters, keyed by connection (raw data stays local)."""
    proc = subprocess.run(["ss", "-tinH", "state", "established", f"( sport = :{PORT} )"],
                          capture_output=True, text=True, check=True)
    connections, key = {}, None
    for line in proc.stdout.splitlines():
        if not line[:1].isspace():
            fields = line.split()
            key = " ".join(fields[2:4])
        elif key:
            counters = {k: int(v) for k, v in re.findall(r"(bytes_sent|bytes_acked):(\d+)", line)}
            if counters:
                connections[key] = counters
    snapshot = {"wall_ms": int(time.time() * 1000), "connections": connections}
    path.write_text(json.dumps(snapshot, indent=1))
    return snapshot


class HostWatch:
    """Cheap frequency samples and continuous PSI warnings, including warmup/setup.

    Sustained pressure is recorded (meta.json `host_warnings`), not fatal: the owner
    accepts slower background services during tests. Analysis still marks runs whose
    measurement window was under pressure as invalid for comparison."""

    def __init__(self, directory):
        self.finished = threading.Event()
        self.warnings = []
        self.warned = set()
        self.directory = directory
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()

    def watch(self):
        starts = {}
        with (self.directory / "frequency.csv").open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(("wall_ms", "cpu", "mhz"))
            while not self.finished.is_set():
                now = time.time()
                for resource, limit in (("cpu", 20), ("memory", 5), ("io", 30)):
                    line = Path(f"/proc/pressure/{resource}").read_text().splitlines()[0]
                    value = float(line.split()[1].split("=")[1])
                    if value > limit:
                        starts.setdefault(resource, now)
                        if now - starts[resource] >= 10 and resource not in self.warned:
                            self.warned.add(resource)
                            self.warnings.append({"wall_ms": int(now * 1000), "resource": resource, "value": value,
                                                  "warning": f"host PSI: {resource} some avg10 > {limit}% for >=10 s"})
                            print(f"WARNING: {self.warnings[-1]['warning']} (now {value}%)", flush=True)
                    else:
                        starts.pop(resource, None)
                        self.warned.discard(resource)
                cpu = None
                for line in Path("/proc/cpuinfo").read_text().splitlines():
                    if line.startswith("processor"):
                        cpu = int(line.split(":")[1])
                    elif line.startswith("cpu MHz"):
                        writer.writerow((int(now * 1000), cpu, float(line.split(":")[1])))
                stream.flush()
                self.finished.wait(1)

    def check(self):
        if not self.thread.is_alive():
            raise RuntimeError("host watch stopped unexpectedly")

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            time.sleep(min(0.5, max(0, end - time.monotonic())))
        self.check()

    def stop(self):
        self.finished.set()
        self.thread.join(timeout=5)


def start_node(script, args_, log, env=None, cpus=None):
    return subprocess.Popen(affinity(cpus) + [str(NODE), script, *map(str, args_)], cwd=BOTS, env={**os.environ, **(env or {})},
                            stdout=log.open("w"), stderr=subprocess.STDOUT)


def action_files(directory):
    return sorted(p for p in directory.glob("actions-*.jsonl") if not p.name.endswith(".health.jsonl"))


def joined_bots(directory):
    """Recover observed joins even when a run aborts in the connection ramp."""
    joined = set()
    paths = action_files(directory) or [directory / "actions.jsonl"]
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # Preserve failure metadata even after a truncated writer.
            if event.get("action") == "spawn":
                joined.add(event["bot"])
    return joined


def run(args):
    if cpu_set(args.server_cpus) & cpu_set(args.client_cpus):
        raise ValueError("server and client CPU sets overlap")
    if not (cpu_set(args.server_cpus) | cpu_set(args.client_cpus)) <= os.sched_getaffinity(0):
        raise ValueError("requested CPUs are unavailable")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rundir = ROOT / ".local" / "runs" / f"{stamp}-{args.label}"
    rundir.mkdir(parents=True)
    # Every run records at least one camera, so any run can be filmed later. A/B pairs
    # must use identical cameras: each recorder is one extra connected client.
    cameras = (json.loads(Path(args.cameras).read_text()) if args.cameras
               else [{"x": args.center_x, "y": 60, "z": args.center_z, "yaw": 0, "pitch": 90}])
    if not cameras:
        sys.exit("at least one camera is required")
    meta = {"label": args.label, "jar": Path(args.jar).name, "jar_sha256": sha256(args.jar),
            "world": Path(args.world).name, "world_sha256": sha256(args.world),
            "bots": args.bots, "seed": args.seed, "warmup_s": args.warmup, "measure_s": args.duration,
            "mobs": args.mobs, "spread": args.spread, "cameras": cameras, "center_x": args.center_x, "center_z": args.center_z, "jvm_args": JVM_ARGS, "view_distance": args.view_distance,
            "server_cpus": args.server_cpus, "client_cpus": args.client_cpus,
            "shard_size": args.shard_size, "profile_seconds": args.profile_seconds,
            "placement_scheme": "global-index-precomputed"}
    host = subprocess.Popen([sys.executable, "-I", str(ROOT / "scripts" / "pressure-monitor.py"), "--interval", "1"],
                            stdout=(rundir / "host.csv").open("w"), stderr=subprocess.DEVNULL)
    watch = HostWatch(rundir)
    srv = Server(rundir / "server", Path(args.jar), Path(args.world), [TELEMETRY_JAR], args.view_distance, args.server_cpus)
    recorders, swarms = [], []
    rng = random.Random(args.seed)
    error = None
    try:
        srv.start(guard=watch.check)
        meta["server_ready_wall_ms"] = int(time.time() * 1000)
        for i, cam in enumerate(cameras):
            name = f"cam{i}"
            rec = start_node("recorder.js", ["127.0.0.1", PORT, name, rundir / "recordings" / name], rundir / f"{name}.log",
                             {"MC_VERSION": args.mc_version}, args.client_cpus)
            recorders.append((name, rec))
            wait_for_log(rundir / f"{name}.log", '"event":"spawn"', 120, watch.check)
            srv.cmd(f"gamemode spectator {name}")
            srv.cmd(f"tp {name} {cam['x']} {cam['y']} {cam['z']} {cam.get('yaw', 0)} {cam.get('pitch', 30)}")
        for _ in range(args.mobs):
            watch.check()
            x = args.center_x + rng.randint(-args.spread, args.spread)
            z = args.center_z + rng.randint(-args.spread, args.spread)
            srv.cmd(f"summon {rng.choice(['cow', 'pig', 'sheep', 'chicken'])} {x} 1 {z}")
        (rundir / "actions.jsonl").touch()
        shard_count = (args.bots + args.shard_size - 1) // args.shard_size
        meta["shards"] = []
        placements = {}
        for shard, offset in enumerate(range(0, args.bots, args.shard_size)):
            count = min(args.shard_size, args.bots - offset)
            path = rundir / f"actions-{shard:02}.jsonl"
            path.touch()
            meta["shards"].append({"index": shard, "offset": offset, "count": count,
                                    "prefix": f"s{shard}b", "actions": path.name})
            for i in range(count):
                placements[f"s{shard}b{i}"] = (args.center_x + rng.randint(-args.spread, args.spread),
                                              args.center_z + rng.randint(-args.spread, args.spread))
            # Round-robin shards: aggregate connection ramp remains one bot / 250 ms.
            swarms.append(start_node("swarm.js", ["127.0.0.1", PORT, count, args.seed, path,
                          f"s{shard}b", args.spread, 0, args.center_x, args.center_z,
                          offset, 250 * shard_count, 250 * shard], rundir / f"swarm-{shard:02}.log",
                          cpus=args.client_cpus))
        joined, deadline = set(), time.time() + 60 + args.bots * 0.5
        while len(joined) < args.bots and time.time() < deadline:
            watch.wait(1)
            for path in action_files(rundir):
                for line in path.read_text().splitlines():
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # The writer may be in the middle of its last line.
                    if e["action"] == "spawn" and e["bot"] not in joined:
                        joined.add(e["bot"])
                        srv.cmd(f"gamemode creative {e['bot']}")
                        srv.cmd(f"give {e['bot']} oak_planks 640")
                        bx, bz = placements[e['bot']]
                        srv.cmd(f"tp {e['bot']} {bx} 1 {bz}")
        meta["bots_joined"] = len(joined)
        meta["warmup_start_wall_ms"] = int(time.time() * 1000)
        (rundir / "meta.json").write_text(json.dumps(meta, indent=1))
        watch.wait(args.warmup)
        network_snapshot(rundir / "network-start.json")
        meta["measure_start_wall_ms"] = int(time.time() * 1000)
        (rundir / "meta.json").write_text(json.dumps(meta, indent=1))
        if args.profile_seconds:
            watch.wait(min(60, max(0, args.duration - args.profile_seconds)))
            meta["profile_start_wall_ms"] = int(time.time() * 1000)
            meta["profile_response"] = srv.cmd(f"profiler world {args.center_x} {args.center_z} {args.profile_seconds} 100")
        watch.wait(max(0, args.duration - (time.time() * 1000 - meta["measure_start_wall_ms"]) / 1000))
        meta["measure_end_wall_ms"] = int(time.time() * 1000)
        network_snapshot(rundir / "network-end.json")
    except Exception as exc:
        error = exc
        meta["runner_error"] = str(exc)
    finally:
        for swarm in swarms:
            if swarm.poll() is None:
                swarm.send_signal(signal.SIGTERM)
        for swarm in swarms:
            try:
                swarm.wait(timeout=60)
            except subprocess.TimeoutExpired:
                swarm.kill()
                swarm.wait()
        meta["swarm_exitcodes"] = [swarm.returncode for swarm in swarms]
        for _, rec in recorders:
            if rec.poll() is None:
                rec.send_signal(signal.SIGINT)
            try:
                rec.wait(timeout=60)
            except subprocess.TimeoutExpired:
                rec.kill()
                rec.wait()
        srv.stop()
        host.terminate()
        host.wait(timeout=10)
        watch.stop()
        meta["host_warnings"] = watch.warnings
        meta["bots_joined"] = len(joined_bots(rundir))
        (rundir / "meta.json").write_text(json.dumps(meta, indent=1))
    with (rundir / "actions.jsonl").open("w") as merged:
        for path in action_files(rundir):
            with path.open() as stream:
                shutil.copyfileobj(stream, merged)
    for name, _ in recorders:
        src = rundir / "recordings" / name
        with zipfile.ZipFile(rundir / "recordings" / f"{name}.mcpr", "w", zipfile.ZIP_DEFLATED) as z:
            for f in ("recording.tmcpr", "metaData.json"):
                if (src / f).exists():
                    z.write(src / f, f)
    if (srv.dir / "profiler").exists():
        shutil.copytree(srv.dir / "profiler", rundir / "profiler")
    tel = srv.dir / "plugins" / "TickTelemetry"
    for f in ("ticks.csv", "regions.csv"):
        if (tel / f).exists():
            shutil.copy2(tel / f, rundir / f)
    (rundir / "meta.json").write_text(json.dumps(meta, indent=1))
    summary = summarize(rundir, meta)
    (rundir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"run folder: {rundir}")
    if error:
        raise error


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def summarize(rundir, meta):
    """Aggregate tick timings and bot actions inside the measurement window."""
    regions = []
    if (rundir / "regions.csv").exists():
        with (rundir / "regions.csv").open() as stream:
            regions = list(csv.DictReader(stream))
    # Map nanoTime to wall clock from the per-second anchors.
    anchors = sorted({(int(r["nano"]), int(r["wall_ms"])) for r in regions})
    def wall(ns):
        if not anchors:
            return None
        n0, w0 = min(anchors, key=lambda a: abs(a[0] - ns))
        return w0 + (ns - n0) / 1e6
    lo, hi = meta.get("measure_start_wall_ms"), meta.get("measure_end_wall_ms")
    ticks_ms, global_ms, per_region = [], [], {}
    windows = {"first30": [], "last30": [], **{f"minute{i}": [] for i in range(5)}}
    if (rundir / "ticks.csv").exists():
        with (rundir / "ticks.csv").open() as stream:
            for t in csv.DictReader(stream):
                w = wall(int(t["tick_start_ns"]))
                if w is None or lo is None or not (lo <= w <= hi):
                    continue
                ms = (int(t["tick_end_ns"]) - int(t["tick_start_ns"])) / 1e6
                (global_ms if t["region"] == "-1" else ticks_ms).append(ms)
                if t["region"] != "-1":
                    if w < lo + 30000:
                        windows["first30"].append(ms)
                    if w >= hi - 30000:
                        windows["last30"].append(ms)
                    minute = f"minute{int((w - lo) // 60000)}"
                    if minute in windows:
                        windows[minute].append(ms)
                per_region.setdefault(t["region"], 0)
                per_region[t["region"]] += 1
    seconds = (hi - lo) / 1000 if lo and hi else None
    region_ticks = [n for r, n in per_region.items() if r != "-1"]
    actions = {}
    action_paths = action_files(rundir) or [rundir / "actions.jsonl"]
    for path in action_paths:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
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
        "lagging_tick_share": sum(v > 50 for v in ticks_ms) / len(ticks_ms) if ticks_ms else None,
        "tick_window_medians_ms": {k: pct(v, 50) for k, v in windows.items()},
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
    r.add_argument("--cameras", help="JSON list of {x,y,z,yaw,pitch}; default: one above the centre")
    r.add_argument("--mc-version", default="26.1.2", help="written into recording metadata")
    r.add_argument("--spread", type=int, default=450, help="bots/mobs placed within +-spread of the centre")
    r.add_argument("--center-x", type=int, default=0)
    r.add_argument("--center-z", type=int, default=0)
    r.add_argument("--server-cpus", default="0-5")
    r.add_argument("--client-cpus", default="6-11")
    r.add_argument("--shard-size", type=int, choices=range(1, 51), default=50)
    r.add_argument("--profile-seconds", type=int, default=0)
    a = ap.parse_args()
    prepare_world(a) if a.command == "prepare-world" else run(a)


if __name__ == "__main__":
    main()
