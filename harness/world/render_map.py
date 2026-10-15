#!/usr/bin/env python3
"""Render a top-down map of a saved world straight from its region files.

For each column it draws the highest non-air block, shaded by height. This reads
what was actually saved, not the generator's plan.

Usage: python3 harness/world/render_map.py WORLD_DIR OUT.png [HALF]   (default HALF=500)
"""
import io
import struct
import sys
import zlib
from pathlib import Path

from PIL import Image

COLORS = {
    "gray_concrete": (70, 72, 78), "moss_block": (89, 110, 45), "grass_block": (110, 150, 70),
    "stone_bricks": (122, 121, 122), "bricks": (150, 95, 80), "white_concrete": (207, 213, 214),
    "light_gray_concrete": (125, 125, 115), "sandstone": (216, 203, 155),
    "polished_andesite": (132, 135, 134), "deepslate_bricks": (70, 70, 72),
    "terracotta": (152, 94, 67), "oak_planks": (162, 130, 78), "glass": (175, 213, 219),
    "redstone_lamp": (230, 160, 60), "observer": (98, 98, 98), "hopper": (60, 60, 60),
    "poppy": (200, 30, 30), "dandelion": (240, 220, 40), "azure_bluet": (230, 230, 240),
    "dirt": (134, 96, 67), "stone": (125, 125, 125), "bedrock": (40, 40, 40),
}
AIR = {"air", "cave_air", "void_air"}


# --- minimal NBT reader --------------------------------------------------------------

def read_nbt(buf):
    tag = buf.read(1)[0]
    _name(buf)
    return _payload(buf, tag)


def _name(buf):
    (n,) = struct.unpack(">H", buf.read(2))
    return buf.read(n).decode("utf-8", "replace")


def _payload(buf, tag):
    if tag == 1:
        return struct.unpack(">b", buf.read(1))[0]
    if tag == 2:
        return struct.unpack(">h", buf.read(2))[0]
    if tag == 3:
        return struct.unpack(">i", buf.read(4))[0]
    if tag == 4:
        return struct.unpack(">q", buf.read(8))[0]
    if tag == 5:
        return struct.unpack(">f", buf.read(4))[0]
    if tag == 6:
        return struct.unpack(">d", buf.read(8))[0]
    if tag == 7:
        (n,) = struct.unpack(">i", buf.read(4))
        return buf.read(n)
    if tag == 8:
        return _name(buf)
    if tag == 9:
        sub = buf.read(1)[0]
        (n,) = struct.unpack(">i", buf.read(4))
        return [_payload(buf, sub) for _ in range(n)]
    if tag == 10:
        out = {}
        while True:
            t = buf.read(1)[0]
            if t == 0:
                return out
            key = _name(buf)  # the name precedes the payload; read it first
            out[key] = _payload(buf, t)
    if tag == 11:
        (n,) = struct.unpack(">i", buf.read(4))
        return list(struct.unpack(f">{n}i", buf.read(4 * n)))
    if tag == 12:
        (n,) = struct.unpack(">i", buf.read(4))
        return list(struct.unpack(f">{n}q", buf.read(8 * n)))
    raise ValueError(f"bad NBT tag {tag}")


# --- region / chunk decoding ---------------------------------------------------------

def chunks(region_path):
    data = region_path.read_bytes()
    for i in range(1024):
        (loc,) = struct.unpack(">I", data[i * 4:i * 4 + 4])
        offset, count = loc >> 8, loc & 0xFF
        if not count:
            continue
        start = offset * 4096
        (length,) = struct.unpack(">I", data[start:start + 4])
        kind = data[start + 4]
        raw = data[start + 5:start + 4 + length]
        if kind == 2:
            raw = zlib.decompress(raw)
        elif kind != 3:
            continue
        yield read_nbt(io.BytesIO(raw))


def section_blocks(section):
    """Return (palette names, 4096 palette indices) for one 16^3 section, or None."""
    states = section.get("block_states")
    if not states:
        return None
    palette = [p["Name"].split(":", 1)[1] for p in states["palette"]]
    if len(palette) == 1:
        return palette, None
    bits = max(4, (len(palette) - 1).bit_length())
    per_long = 64 // bits
    mask = (1 << bits) - 1
    idx = []
    for value in states["data"]:
        value &= (1 << 64) - 1
        for k in range(per_long):
            idx.append((value >> (k * bits)) & mask)
    return palette, idx[:4096]


def render(world, out, half):
    size = 2 * half
    img = Image.new("RGB", (size, size), (20, 20, 25))
    px = img.load()
    region_dir = world / "dimensions" / "minecraft" / "overworld" / "region"  # 26.x layout
    if not region_dir.is_dir():
        region_dir = world / "region"
    for region in sorted(region_dir.glob("r.*.mca")):
        for chunk in chunks(region):
            cx, cz = chunk["xPos"], chunk["zPos"]
            if not (-half <= cx * 16 < half and -half <= cz * 16 < half):
                continue
            top = {}
            for sec in sorted(chunk.get("sections", []), key=lambda s: -s["Y"]):
                decoded = section_blocks(sec)
                if decoded is None:
                    continue
                palette, idx = decoded
                for lz in range(16):
                    for lx in range(16):
                        if (lx, lz) in top:
                            continue
                        for ly in range(15, -1, -1):
                            name = palette[0] if idx is None else palette[idx[(ly * 16 + lz) * 16 + lx]]
                            if name not in AIR:
                                top[(lx, lz)] = (name, sec["Y"] * 16 + ly)
                                break
                if len(top) == 256:
                    break
            for (lx, lz), (name, y) in top.items():
                x, z = cx * 16 + lx + half, cz * 16 + lz + half
                if 0 <= x < size and 0 <= z < size:
                    r, g, b = COLORS.get(name, (255, 0, 255))
                    shade = min(1.4, 0.75 + max(0, y) / 60)
                    px[x, z] = (min(255, int(r * shade)), min(255, int(g * shade)), min(255, int(b * shade)))
    img.save(out)


if __name__ == "__main__":
    render(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 500)
