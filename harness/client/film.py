#!/usr/bin/env python3
"""Film a recorded test run with the real Minecraft client, after the run.

The run itself only records packets (hidden recorder, harness/bots/recorder.js), so no
client renders while the server is measured. Here the recording is played back into a
real 26.1.2 client by harness/bots/replay_server.js; the client flies a keyframed camera
path and ffmpeg records its screen. Then the metrics overlay is burned in.

Usage:
  python3 harness/client/film.py RUN_DIR --camera cam0 --path harness/cameras/film-center.json \
      [--from-ms 20000] [--name center]
Writes videos/packet-replay_<run>-<name>.mp4 (raw) and ...-overlay.mp4 in the project.
The prefix marks footage recreated from a real run's recorded packets.
The camera must stay inside the area the recorder received (its view distance).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MC = ROOT / ".local" / "minecraft"
JAVA = ROOT / ".local" / "jdk-25" / "bin" / "java"
NODE = ROOT / ".local" / "node" / "bin" / "node"
VIDEOS = ROOT / "videos"
DISPLAY = ":77"
WIDTH, HEIGHT = 1280, 720
REPLAY_PORT = 25600
OPTIONS = {
    "renderDistance": 12, "simulationDistance": 8, "maxFps": 60, "enableVsync": "false",
    "pauseOnLostFocus": "false", "onboardAccessibility": "false", "tutorialStep": "none",
    "skipMultiplayerWarning": "true", "joinedFirstServer": "true", "narrator": 0,
    "soundCategory_master": 0.0, "fov": 0.0, "guiScale": 2, "fullscreen": "false",
}


def offline_uuid(name):
    h = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def launch_command(name, game_dir, server):
    launch = json.loads((MC / "launch.json").read_text())
    subs = {
        "${auth_player_name}": name, "${version_name}": launch["version"],
        "${game_directory}": str(game_dir), "${assets_root}": launch["assetsDir"],
        "${assets_index_name}": launch["assetIndex"], "${auth_uuid}": offline_uuid(name).replace("-", ""),
        "${auth_access_token}": "0", "${clientid}": "0", "${auth_xuid}": "0", "${user_type}": "legacy",
        "${version_type}": "release", "${natives_directory}": str(game_dir / "natives"),
        "${launcher_name}": "project5k", "${launcher_version}": "1",
        "${classpath}": ":".join(launch["classpath"]),
    }

    def expand(args):
        out = []
        for a in args:
            if isinstance(a, str):
                for k, v in subs.items():
                    a = a.replace(k, v)
                out.append(a)
        return out
    return [str(JAVA), "-Xmx3G", *(expand(launch["jvmArgs"]) or ["-cp", subs["${classpath}"]]),
            launch["mainClass"], *expand(launch["gameArgs"]),
            "--width", str(WIDTH), "--height", str(HEIGHT), "--quickPlayMultiplayer", server]


def read_event(proc, wanted, timeout):
    end = time.time() + timeout
    while time.time() < end:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"replay server exited before {wanted}")
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == wanted:
            return event
    raise TimeoutError(f"no {wanted} from replay server")


def film(run, camera, path_file, from_ms, name):
    mcpr = run / "recordings" / f"{camera}.mcpr"
    work = run / f"film-{name}"
    shutil.rmtree(work, ignore_errors=True)
    game_dir = work / "client"
    game_dir.mkdir(parents=True)
    (game_dir / "options.txt").write_text("".join(f"{k}:{v}\n" for k, v in OPTIONS.items()))
    VIDEOS.mkdir(exist_ok=True)
    raw_video = VIDEOS / f"packet-replay_{run.name}-{name}.mp4"
    env = {**os.environ, "DISPLAY": DISPLAY}
    procs = []
    try:
        replay = subprocess.Popen([str(NODE), "replay_server.js", str(mcpr), str(Path(path_file).resolve()),
                                   str(REPLAY_PORT), str(from_ms)], cwd=ROOT / "harness" / "bots",
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=(work / "replay.log").open("w"),
                                  text=True)
        procs.append(replay)
        read_event(replay, "LISTENING", 60)
        procs.append(subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(2)
        client = subprocess.Popen(launch_command("camera", game_dir, f"127.0.0.1:{REPLAY_PORT}"), cwd=game_dir,
                                  env=env, stdout=(work / "client.log").open("w"), stderr=subprocess.STDOUT)
        procs.append(client)
        ready = read_event(replay, "READY", 300)
        subprocess.run(["xdotool", "key", "F1"], env=env, check=False)   # hide the HUD
        time.sleep(1)
        ffmpeg = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "x11grab", "-framerate", "30",
                                   "-video_size", f"{WIDTH}x{HEIGHT}", "-i", f"{DISPLAY}.0", "-c:v", "libx264",
                                   "-preset", "veryfast", "-pix_fmt", "yuv420p", str(raw_video)], stdin=subprocess.PIPE)
        procs.append(ffmpeg)
        replay.stdin.write("GO\n")
        replay.stdin.flush()
        read_event(replay, "DONE", 3600)
        ffmpeg.communicate(b"q", timeout=60)
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill()
        shutil.rmtree(game_dir / "natives", ignore_errors=True)
    replay_start = ready["play_start_ms"] + ready["from_ms"]
    overlay_video = VIDEOS / f"packet-replay_{run.name}-{name}-overlay.mp4"
    subprocess.run([sys.executable, "-I", str(ROOT / "harness" / "video" / "overlay.py"), "--run", str(run),
                    "--camera", camera, "--video", str(raw_video), "--replay-start-ms", str(replay_start),
                    "--path", str(Path(path_file).resolve()), "--out", str(overlay_video)], check=True)
    overlay_video.with_suffix(".ass").unlink(missing_ok=True)
    print(json.dumps({"raw": str(raw_video), "overlay": str(overlay_video), "replay_start_ms": replay_start}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--camera", default="cam0")
    ap.add_argument("--path", required=True)
    ap.add_argument("--from-ms", type=int, default=0, help="recording time at which filming starts")
    ap.add_argument("--name", default="film")
    a = ap.parse_args()
    film(Path(a.run).resolve(), a.camera, a.path, a.from_ms, a.name)


if __name__ == "__main__":
    main()
