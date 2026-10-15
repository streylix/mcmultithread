#!/usr/bin/env python3
"""Build the deterministic `city-1000` fixture world.

The layout comes only from SEED, so the same script always produces the same city.
Construction uses the vanilla server jar of the pinned version (Folia restricts
world-editing commands); Folia loads the saved world unchanged.

Usage: python3 harness/world/build_city.py VANILLA_JAR OUT_DIR
Writes OUT_DIR/world plus OUT_DIR/layout.json (what was placed where).
"""
import json
import os
import random
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rcon import Rcon  # noqa: E402

SEED = 5000
HALF = 500            # city spans x,z in [-HALF, HALF)
BLOCK = 64            # street grid pitch
ROAD = 8              # road width
GROUND = -1           # top solid layer; players stand at y=0
RCON_PORT = 25598
FLAT = {
    "layers": [
        {"block": "minecraft:bedrock", "height": 1},
        {"block": "minecraft:stone", "height": 59},
        {"block": "minecraft:dirt", "height": 3},
        {"block": "minecraft:grass_block", "height": 1},
    ],
    "biome": "minecraft:plains",
    "structure_overrides": [],
}
WALLS = ["stone_bricks", "bricks", "white_concrete", "light_gray_concrete", "sandstone",
         "polished_andesite", "deepslate_bricks", "terracotta"]


def layout(seed):
    """Return the ordered list of commands and a description of the city."""
    rng = random.Random(seed)
    cmds, desc = [], {"seed": seed, "buildings": [], "parks": [], "redstone": [], "hoppers": []}
    lo, hi = -HALF, HALF - 1
    # Roads: grid lines every BLOCK blocks, ROAD wide, in both directions.
    for g in range(lo, HALF, BLOCK):
        cmds.append(f"fill {g} {GROUND} {lo} {g + ROAD - 1} {GROUND} {hi} gray_concrete")
        cmds.append(f"fill {lo} {GROUND} {g} {hi} {GROUND} {g + ROAD - 1} gray_concrete")
    cells = [(x, z) for x in range(lo, HALF, BLOCK) for z in range(lo, HALF, BLOCK)]
    redstone_cell = cells[len(cells) // 2]          # middle column, north edge
    hopper_cell = cells[len(cells) // 2 + 1]
    for cx, cz in cells:
        x0, z0 = cx + ROAD, cz + ROAD                 # interior of the city block
        x1, z1 = min(cx + BLOCK - 1, hi), min(cz + BLOCK - 1, hi)
        if x1 - x0 < 20 or z1 - z0 < 20:
            continue
        if (cx, cz) == redstone_cell:
            for i in range(0, 40, 4):                 # observer clocks driving lamps
                for j in range(0, 40, 4):
                    x, z = x0 + 4 + i, z0 + 4 + j
                    cmds += [f"setblock {x - 1} 0 {z} redstone_lamp",
                             f"setblock {x + 2} 0 {z} redstone_lamp",
                             f"setblock {x} 0 {z} observer[facing=east]",
                             f"setblock {x + 1} 0 {z} observer[facing=west]"]
                    desc["redstone"].append([x, 0, z])
            continue
        if (cx, cz) == hopper_cell:
            for i in range(0, 40, 3):                 # hopper pairs passing items forever
                for j in range(0, 40, 3):
                    x, z = x0 + 4 + i, z0 + 4 + j
                    cmds += [f'setblock {x} 0 {z} hopper[facing=east]{{Items:[{{Slot:0b,id:"minecraft:cobblestone",count:5}}]}}',
                             f"setblock {x + 1} 0 {z} hopper[facing=west]"]
                    desc["hoppers"].append([x, 0, z])
            continue
        if rng.random() < 0.15:                       # park
            cmds.append(f"fill {x0} {GROUND} {z0} {x1} {GROUND} {z1} moss_block")
            for _ in range(12):
                fx, fz = rng.randint(x0, x1), rng.randint(z0, z1)
                cmds.append(f"setblock {fx} 0 {fz} {rng.choice(['poppy', 'dandelion', 'azure_bluet'])}")
            desc["parks"].append([x0, z0, x1, z1])
            continue
        for _ in range(rng.randint(1, 4)):            # buildings with doorways and windows
            w, d, h = rng.randint(10, 22), rng.randint(10, 22), rng.choice([6, 9, 12, 18, 24, 36])
            bx, bz = rng.randint(x0, x1 - w), rng.randint(z0, z1 - d)
            mat = rng.choice(WALLS)
            cmds.append(f"fill {bx} 0 {bz} {bx + w - 1} {h - 1} {bz + d - 1} {mat} hollow")
            for floor in range(4, h - 1, 4):
                cmds.append(f"fill {bx + 1} {floor} {bz + 1} {bx + w - 2} {floor} {bz + d - 2} oak_planks")
            mid = bx + w // 2
            cmds.append(f"fill {mid} 0 {bz} {mid + 1} 2 {bz} air")
            for floor in range(1, h - 2, 4):
                cmds.append(f"fill {bx + 2} {floor + 1} {bz + d - 1} {bx + w - 3} {floor + 1} {bz + d - 1} glass")
            desc["buildings"].append({"min": [bx, 0, bz], "size": [w, h, d], "material": mat})
    return cmds, desc


def wait_for(path, text, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and text in path.read_text(errors="replace"):
            return
        time.sleep(1)
    raise TimeoutError(f"'{text}' not seen in {path}")


def main():
    jar, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if (out / "world").exists():
        sys.exit(f"{out}/world already exists; refusing to overwrite")
    out.mkdir(parents=True, exist_ok=True)
    password = secrets.token_hex(16)
    (out / "eula.txt").write_text("eula=true\n")
    props = {
        "online-mode": "false", "server-ip": "127.0.0.1", "server-port": "25597",
        "enable-rcon": "true", "rcon.port": str(RCON_PORT), "rcon.password": password,
        "level-seed": str(SEED), "level-type": "minecraft\\:flat",
        "generator-settings": json.dumps(FLAT, separators=(",", ":")),
        "generate-structures": "false", "spawn-protection": "0", "max-tick-time": "-1",
        "pause-when-empty-seconds": "0",
    }
    (out / "server.properties").write_text("".join(f"{k}={v}\n" for k, v in props.items()))
    java = os.environ.get("JAVA", "java")
    log = out / "build-server.log"
    proc = subprocess.Popen([java, "-Xms2G", "-Xmx8G", "-jar", str(jar), "--nogui"], cwd=out,
                            stdout=log.open("w"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        wait_for(log, "RCON running", 300)
        rc = Rcon("127.0.0.1", RCON_PORT, password)
        rc.command("setworldspawn 0 0 0")
        # Chunk-aligned 16x16-chunk tiles: forceload accepts at most 256 chunks per command.
        edge = -((HALF + 15) // 16) * 16
        tiles = range(edge, -edge, 256)
        for tx in tiles:
            for tz in tiles:
                reply = rc.command(f"forceload add {tx} {tz} {tx + 255} {tz + 255}")
                if "Marked" not in reply:
                    raise RuntimeError(f"forceload rejected: {reply}")
        for tx in tiles:
            for tz in tiles:
                for _ in range(600):
                    corner = f"{tx + 255} 0 {tz + 255}"
                    if "passed" in rc.command(f"execute if loaded {tx} 0 {tz} if loaded {corner}"):
                        break
                    time.sleep(1)
                else:
                    raise TimeoutError(f"tile {tx},{tz} never loaded")
        cmds, desc = layout(SEED)
        failures = []
        for i, cmd in enumerate(cmds):
            reply = rc.command(cmd)
            if any(s in reply.lower() for s in ("unknown", "incorrect", "error", "not loaded", "too many", "expected")):
                failures.append([cmd, reply])
            if i % 500 == 0:
                print(f"{i}/{len(cmds)} commands", flush=True)
        desc["commands"] = len(cmds)
        desc["failures"] = failures
        rc.command("forceload remove all")
        print(rc.command("save-all flush"))
        rc.command("stop")
        rc.close()
        proc.wait(timeout=300)
        (out / "layout.json").write_text(json.dumps(desc, indent=1))
        print(f"done: {len(cmds)} commands, {len(failures)} failures")
        for f in failures[:10]:
            print("FAIL", f)
    finally:
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    main()
