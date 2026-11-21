#!/usr/bin/env python3
"""Copy the latest built firmware to a MECHEN M30 connected in USB storage mode."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HEX = "MECHEN_M30.HEX"
BUILD = Path(__file__).resolve().parent / "build"


def latest():
    candidates = [p for pattern in (HEX, "*/" + HEX) for p in BUILD.glob(pattern) if p.is_file()]
    if not candidates:
        raise ValueError(f"No firmware found under {BUILD}.")
    return max(candidates, key=lambda p: (p.stat().st_mtime_ns, str(p)))


def player():
    output = subprocess.check_output(
        ["lsblk", "--json", "--list", "-o", "PATH,LABEL,MAJ:MIN,MOUNTPOINTS,RO"], text=True
    )
    matches = [d for d in json.loads(output)["blockdevices"] if d["label"] == "MECHEN M30"]
    if not matches:
        raise ValueError("Connect the M30 in USB storage mode and run this command again.")
    if len(matches) > 1:
        raise ValueError("Multiple volumes are labeled MECHEN M30. Connect only the target player.")
    dev = matches[0]
    if dev["ro"]:
        raise ValueError(f'{dev["path"]} is read-only.')
    return dev


def copy_verified(data, folder):
    dest = folder / HEX
    if dest.is_file() and dest.read_bytes() == data:
        return "Already up to date"
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".m30-", delete=False) as out:
        tmp = Path(out.name)
    try:
        with tmp.open("wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if tmp.read_bytes() != data:
            raise OSError("Firmware read-back verification failed.")
        tmp.replace(dest)
        return "Copied and verified"
    finally:
        tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", nargs="?", type=Path, help="specific HEX or build directory")
    parser.add_argument("--dry-run", action="store_true", help="show the build and player without mounting or copying")
    args = parser.parse_args()
    src = args.firmware or latest()
    if src.is_dir():
        src = src / HEX
    data = src.read_bytes()
    if not data:
        raise ValueError(f"{src} is empty.")
    print(f"Firmware: {src}\nSHA-256: {hashlib.sha256(data).hexdigest()}", flush=True)
    dev = player()
    paths = list(filter(None, dev["mountpoints"] or []))
    print(f'Player: {dev["path"]} ({paths[0] if paths else "unmounted"})', flush=True)
    if args.dry_run:
        return
    if not paths:
        subprocess.run(["udisksctl", "mount", "-b", dev["path"]], check=True)
        mounted = player()
        if mounted["path"] != dev["path"] or mounted["maj:min"] != dev["maj:min"]:
            raise ValueError("The connected player changed during mounting.")
        paths = list(filter(None, mounted["mountpoints"] or []))
    if not paths:
        raise ValueError("The player has no visible mount point.")
    # Pin the mounted directory so an unplug cannot redirect a copy onto the host.
    fd = os.open(paths[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        major, minor = map(int, dev["maj:min"].split(":"))
        if os.fstat(fd).st_dev != os.makedev(major, minor):
            raise ValueError("The mount point no longer belongs to the player.")
        result = copy_verified(data, Path(f"/proc/self/fd/{fd}"))
        os.fsync(fd)
    finally:
        os.close(fd)
    print(f"{result}: {Path(paths[0]) / HEX}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"Upload failed: {error}")
