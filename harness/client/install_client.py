#!/usr/bin/env python3
"""Download a vanilla Minecraft Java client (jar, libraries, natives, assets) from
Mojang's launcher metadata into a local directory, verifying every file's SHA-1.

Usage: python3 harness/client/install_client.py VERSION OUT_DIR
Writes OUT_DIR/launch.json (classpath, main class, args) for run_camera.py.
"""
import concurrent.futures
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def download(url, dest, sha1):
    dest = Path(dest)
    if dest.exists() and hashlib.sha1(dest.read_bytes()).hexdigest() == sha1:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    if hashlib.sha1(data).hexdigest() != sha1:
        raise ValueError(f"SHA-1 mismatch for {url}")
    dest.write_bytes(data)


def allowed(rules):
    if not rules:
        return True
    ok = False
    for rule in rules:
        os_name = rule.get("os", {}).get("name")
        if rule.get("features"):
            continue
        if os_name in (None, "linux"):
            ok = rule["action"] == "allow"
    return ok


def main():
    version, out = sys.argv[1], Path(sys.argv[2]).resolve()
    entry = next(v for v in fetch_json(MANIFEST)["versions"] if v["id"] == version)
    meta = fetch_json(entry["url"])
    (out / "versions").mkdir(parents=True, exist_ok=True)
    (out / "versions" / f"{version}.json").write_text(json.dumps(meta))
    jobs = []
    client = meta["downloads"]["client"]
    client_jar = out / "versions" / f"{version}.jar"
    jobs.append((client["url"], client_jar, client["sha1"]))
    classpath = []
    for lib in meta["libraries"]:
        if not allowed(lib.get("rules")):
            continue
        art = lib.get("downloads", {}).get("artifact")
        if art:
            path = out / "libraries" / art["path"]
            jobs.append((art["url"], path, art["sha1"]))
            classpath.append(str(path))
    classpath.append(str(client_jar))
    index_info = meta["assetIndex"]
    index_path = out / "assets" / "indexes" / f"{index_info['id']}.json"
    download(index_info["url"], index_path, index_info["sha1"])
    for obj in json.loads(index_path.read_text())["objects"].values():
        h = obj["hash"]
        jobs.append((f"https://resources.download.minecraft.net/{h[:2]}/{h}", out / "assets" / "objects" / h[:2] / h, h))
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        futures = [pool.submit(download, *j) for j in jobs]
        for i, f in enumerate(concurrent.futures.as_completed(futures)):
            f.result()
            if i % 500 == 0:
                print(f"{i}/{len(jobs)} files", flush=True)
    launch = {
        "version": version, "mainClass": meta["mainClass"], "classpath": classpath,
        "assetIndex": index_info["id"], "assetsDir": str(out / "assets"),
        "gameArgs": meta.get("arguments", {}).get("game", []),
        "jvmArgs": meta.get("arguments", {}).get("jvm", []),
        "javaMajor": meta.get("javaVersion", {}).get("majorVersion"),
    }
    (out / "launch.json").write_text(json.dumps(launch, indent=1))
    print(f"installed {version}: {len(jobs)} files, java {launch['javaMajor']}")


if __name__ == "__main__":
    main()
