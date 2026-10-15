#!/usr/bin/env python3
"""Burn per-tick server metrics into a ReplayMod render of a run's recording.

Each server tick of the region nearest the camera becomes one subtitle event (top-left)
lasting until the next tick, showing that tick's measured values, so the video steps
through server orchestration tick by tick.

Time alignment: replay time 0 is the recorder's start (metaData.json `date`, wall ms).
ReplayMod renders from a chosen replay timestamp at 1x speed, so a video frame at time
t shows wall time  date + replay_start_ms + t.  Telemetry nanoTime is mapped to wall time
through the per-second anchors in regions.csv.

Usage:
  python3 harness/video/overlay.py --run RUN_DIR --camera cam0 --video render.mp4 \
      --replay-start-ms 12000 --out overlay.mp4
  (--ass-only writes just the .ass subtitle file)
"""
import argparse
import bisect
import csv
import json
import subprocess
import zipfile
from pathlib import Path


def load_anchors(regions_csv):
    anchors = sorted({(int(r["nano"]), int(r["wall_ms"])) for r in regions_csv})
    nanos = [a[0] for a in anchors]

    def wall(ns):
        i = min(max(bisect.bisect_left(nanos, ns), 0), len(anchors) - 1)
        n0, w0 = anchors[i]
        return w0 + (ns - n0) / 1e6
    return wall


def ass_time(ms):
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms // 10:02d}"


def build_ass(run, camera, replay_start_ms, video_ms, width, height):
    meta = json.loads((run / "meta.json").read_text())
    cam_index = int(camera.removeprefix("cam"))
    cam = meta["cameras"][cam_index]
    with zipfile.ZipFile(run / "recordings" / f"{camera}.mcpr") as z:
        rec_date = json.loads(z.read("metaData.json"))["date"]
    regions = list(csv.DictReader((run / "regions.csv").open()))
    wall = load_anchors(regions)

    # Per-second region snapshots: pick the region whose centre is nearest the camera.
    by_second = {}
    for r in regions:
        if r["region"] == "-1":
            continue
        by_second.setdefault(int(r["wall_ms"]), []).append(r)
    seconds = sorted(by_second)
    cam_cx, cam_cz = cam["x"] // 16, cam["z"] // 16

    def snapshot(w):
        i = max(0, bisect.bisect_right(seconds, w) - 1)
        rows = by_second[seconds[i]] if seconds else []
        if not rows:
            return None, rows
        near = min(rows, key=lambda r: (int(r["center_chunk_x"] or 0) - cam_cx) ** 2 + (int(r["center_chunk_z"] or 0) - cam_cz) ** 2)
        return near, rows

    ticks = {}
    for t in csv.DictReader((run / "ticks.csv").open()):
        ticks.setdefault(t["region"], []).append(t)
    for v in ticks.values():
        v.sort(key=lambda t: int(t["tick_start_ns"]))

    t0_wall = rec_date + replay_start_ms
    t1_wall = t0_wall + video_ms
    events = []
    w = t0_wall
    while w < t1_wall:
        near, rows = snapshot(w)
        region = near["region"] if near else None
        series = ticks.get(region, [])
        starts = [wall(int(t["tick_start_ns"])) for t in series]
        i = bisect.bisect_right(starts, w) - 1
        if i < 0:
            w += 50
            continue
        t = series[i]
        next_w = starts[i + 1] if i + 1 < len(starts) else w + 50
        window = [s for s in series[max(0, i - 19):i + 1]]
        mspt = [(int(s["tick_end_ns"]) - int(s["tick_start_ns"])) / 1e6 for s in window]
        dur = mspt[-1]
        cpu = int(t["cpu_ns"]) / 1e6 if int(t["cpu_ns"]) >= 0 else float("nan")
        lag = (int(t["tick_start_ns"]) - int(t["scheduled_start_ns"])) / 1e6
        one_sec = sum(1 for s in starts[:i + 1] if s > starts[i] - 1000)
        lines = [
            f"replay {ass_time(w - rec_date)}   {meta['label']}",
            f"region {region}  tick #{i}",
            f"tick time {dur:6.2f} ms   cpu {cpu:6.2f} ms",
            f"start lag {lag:6.2f} ms   tps {one_sec:2d}",
            f"mspt 1s avg {sum(mspt) / len(mspt):6.2f}  max {max(mspt):6.2f}",
            f"regions {len(rows)}   players {near['players']}   entities {near['entities']}",
            f"chunks {near['chunks']}",
        ]
        colour = "&H0000FF00&" if dur < 40 else ("&H0000FFFF&" if dur < 50 else "&H000000FF&")
        text = "\\N".join(lines)
        events.append(f"Dialogue: 0,{ass_time(w - t0_wall)},{ass_time(min(next_w, t1_wall) - t0_wall)},HUD,,0,0,0,,"
                      f"{{\\an7\\c{colour}}}{text}")
        w = max(next_w, w + 1)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HUD,DejaVu Sans Mono,{max(14, height // 40)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,2,0,7,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n", len(events)


def probe(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    s = info["streams"][0]
    return s["width"], s["height"], float(info["format"]["duration"]) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--camera", default="cam0")
    ap.add_argument("--video", required=True)
    ap.add_argument("--replay-start-ms", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ass-only", action="store_true")
    a = ap.parse_args()
    width, height, duration = probe(a.video)
    ass, n = build_ass(Path(a.run), a.camera, a.replay_start_ms, duration, width, height)
    ass_path = Path(a.out).with_suffix(".ass")
    ass_path.write_text(ass)
    print(f"{n} tick events -> {ass_path}")
    if not a.ass_only:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a.video, "-vf", f"ass={ass_path}",
                        "-c:a", "copy", a.out], check=True)
        print(a.out)


if __name__ == "__main__":
    main()
