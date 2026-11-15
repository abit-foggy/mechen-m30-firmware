#!/usr/bin/env python3
"""Build-channel version metadata for the M30 CFW.

usage: version.py [--channel dev|nightly|release] [--config STR] [--json] [--out FILE]

The base version lives in the VERSION file at the repo root — the single
source of truth for every channel, the firmware patch, and the release
workflows.

Channels:
  dev      (default) version "<base>-dev", identifier = 8-hex-digit build ID
           derived deterministically from the firmware-relevant source files
           (VERSION, build.sh, tools/, patches/) and the build configuration.
           Identical inputs give an identical ID; any source change (committed
           or not) changes it. No timestamps, no randomness. Generated build
           output (build/) is not part of the inputs.
  nightly  version "<base>-nightly", identifier = short commit SHA of HEAD.
           Requires a clean git working tree (tracked and untracked files);
           dirty trees are rejected so a published nightly always matches its
           commit.
  release  version "<base>-release", identifier = the tag "v<base>". Requires
           a clean tree and that HEAD is exactly tagged "v<base>"; mismatches
           are rejected.

Output: shell-eval-able lines by default (CHANNEL=, VERSION=, IDENT=, ...),
--json for a single JSON object, --out FILE additionally writes the JSON
metadata file consumed by the GitHub release automation.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # repo root
VERSION_FILE = os.path.join(ROOT, "VERSION")

# firmware-relevant source state: everything the build reads to produce the HEX
SRC_TOP = ["VERSION", "build.sh"]
SRC_DIRS = ["tools", "patches"]
SKIP = ("__pycache__",)
BUILD_ID_TAG = "m30-cfw-build-id-v1"


class VersionError(Exception):
    pass


def base_version():
    try:
        v = open(VERSION_FILE).read().strip()
    except OSError as e:
        raise VersionError("cannot read %s: %s" % (VERSION_FILE, e))
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise VersionError("VERSION must be MAJOR.MINOR.PATCH, got %r" % v)
    return v


def git(*args):
    return subprocess.run(["git", "-C", ROOT] + list(args),
                          capture_output=True, text=True)


def dirty_reason():
    """None if the working tree is clean, else a human-readable reason."""
    r = git("status", "--porcelain")
    if r.returncode != 0:
        return "not a git repository (%s)" % r.stderr.strip()
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if lines:
        return "dirty working tree: %s" % "; ".join(lines[:5])
    return None


def source_fingerprint():
    """sha256 over the firmware-relevant source files (content, not git state)."""
    h = hashlib.sha256()
    h.update((BUILD_ID_TAG + "\n").encode())
    paths = []
    for name in SRC_TOP:
        p = os.path.join(ROOT, name)
        if os.path.isfile(p):
            paths.append(p)
    for d in SRC_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP]
            for fn in filenames:
                if fn.endswith(".pyc"):
                    continue
                paths.append(os.path.join(dirpath, fn))
    for p in sorted(paths):
        rel = os.path.relpath(p, ROOT)
        h.update(rel.encode() + b"\0")
        h.update(hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest()


def dev_metadata(config):
    ident = hashlib.sha256(
        (BUILD_ID_TAG + "\n" + source_fingerprint() + "\nconfig=" + config + "\n")
        .encode()).hexdigest()[:8]
    return {"channel": "dev", "version": base_version() + "-dev",
            "identifier": ident, "commit": None, "dirty": dirty_reason() is not None}


def nightly_metadata(config):
    reason = dirty_reason()
    if reason:
        raise VersionError("nightly builds require a clean working tree: " + reason)
    r = git("rev-parse", "--short=7", "HEAD")
    if r.returncode:
        raise VersionError("cannot resolve HEAD: " + r.stderr.strip())
    commit = r.stdout.strip()
    return {"channel": "nightly", "version": base_version() + "-nightly",
            "identifier": commit, "commit": git("rev-parse", "HEAD").stdout.strip(),
            "dirty": False}


def release_metadata(config):
    reason = dirty_reason()
    if reason:
        raise VersionError("release builds require a clean working tree: " + reason)
    base = base_version()
    tag = "v" + base
    r = git("describe", "--exact-match", "--tags", "HEAD")
    if r.returncode or r.stdout.strip() != tag:
        got = r.stdout.strip() if r.returncode == 0 else "no tag on HEAD"
        raise VersionError(
            "release channel expects HEAD to be tagged %s (VERSION=%s), got %r"
            % (tag, base, got))
    return {"channel": "release", "version": base + "-release",
            "identifier": tag, "commit": git("rev-parse", "HEAD").stdout.strip(),
            "dirty": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=os.environ.get("BUILD_CHANNEL", "dev"),
                    choices=["dev", "nightly", "release"])
    ap.add_argument("--config", default=os.environ.get("BUILD_CONFIG", ""),
                    help="build configuration string folded into the dev build ID")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    try:
        if args.channel == "dev":
            md = dev_metadata(args.config)
        elif args.channel == "nightly":
            md = nightly_metadata(args.config)
        else:
            md = release_metadata(args.config)
    except VersionError as e:
        print("version: %s" % e, file=sys.stderr)
        return 2

    md["base"] = base_version()
    md["config"] = args.config
    if args.json:
        print(json.dumps(md, indent=2, sort_keys=True))
    else:
        print("CHANNEL=%r" % md["channel"])
        print("VERSION=%r" % md["version"])
        print("IDENT=%r" % md["identifier"])
        print("BASE=%r" % md["base"])
        print("COMMIT=%r" % md["commit"])
        print("DIRTY=%d" % int(md["dirty"]))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(md, f, indent=2, sort_keys=True)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
