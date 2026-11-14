#!/usr/bin/env python3
"""Host test for the device-side playlist reader (tools/fw/m30playlist.c).

**Mocked, and it says so.** The kernel syscall is a fake serving bytes from a
real playlist file, so what is verified is the wiring -- adapter callback into
the parser, directory prefixing, entry order, duplicate preservation, cleanup on
every path. It does not establish that the firmware ABI works.

The playlist fixture comes from the card copies when available, otherwise a
synthetic one with duplicate entries and UTF-8 paths is written, so the test
never depends on the card being mounted.

Usage: test_m30playlist.py   (exits non-zero on failure)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.environ.get("HOST_CC", "cc")
FIXTURE = os.environ.get("M30LIB", "/tmp/m30lib/Playlists")


def build(work):
    exe = os.path.join(work, "m30pl_test")
    cmd = [CC, "-m32", "-O1", "-w", "-DM30FS_TEST_HOOK",
           "-I", HERE, "-I", os.path.join(HERE, "..", "m3u"),
           "-o", exe, os.path.join(HERE, "test_m30playlist.c"),
           os.path.join(HERE, "..", "m3u", "m3u.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        cmd[1] = "-DM30FS_TEST_HOOK"
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print("test_m30playlist: build failed\n" + r.stderr)
            sys.exit(2)
        print("NOTE  built 64-bit; treat pointer-dependent results with care")
    return exe


def main():
    work = tempfile.mkdtemp(prefix="m30pl.")

    # pick a fixture: a real playlist from the card copies, else synthetic
    pl = None
    if os.path.isdir(FIXTURE):
        m3us = sorted(f for f in os.listdir(FIXTURE) if f.endswith(".m3u"))
        if m3us:
            pl = m3us[0]
            shutil.copy(os.path.join(FIXTURE, pl), os.path.join(work, pl))
    if pl is None:
        pl = "synthetic.m3u"
        with open(os.path.join(work, pl), "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n"
                    "../Music/A/01 - first.flac\n"
                    "../Music/A/02 - second.flac\n"
                    "../Music/A/01 - first.flac\n"          # duplicate
                    "\n"
                    "#EXTINF:120,Skipped title\n"
                    "../Music/B/03 - third.flac\n")
    path = os.path.join(work, pl)

    exe = build(work)
    run = subprocess.run([exe, path, work], capture_output=True, timeout=60)
    out = [l for l in run.stdout.decode("utf-8", "replace").splitlines() if l]

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    check(run.returncode == 0, "the reader completed without error")
    check(out and out[0] == "OPEN OK", "the playlist opened through m30fs")

    tracks = [l[2:] for l in out if l.startswith("T ")]
    check(len(tracks) == 4, "four entries parsed (got %d)" % len(tracks))
    # entries come back with the playlist's directory prefixed; the relative
    # part is what must match, in order, duplicate included
    # the dir prefix is the work directory, so strip it and compare the
    # playlist-relative remainder, ".." included
    prefix = work + "/"
    rel = [t[len(prefix):] for t in tracks]
    want = ["../Music/A/01 - first.flac",
            "../Music/A/02 - second.flac",
            "../Music/A/01 - first.flac",
            "../Music/B/03 - third.flac"]
    check(rel == want,
          "order preserved with the duplicate in place\n"
          "      got %r" % (rel,))
    check("END 4" in out, "the enumeration ended cleanly with 4 entries")
    check("CLOSE" in out, "close was called")

    # every reference is the dir prefix followed by the playlist's relative
    # entry -- which is what lets ../Music/... resolve from the playlist's own
    # directory
    check(all(t.startswith(work + "/") for t in tracks),
          "entries carry the playlist directory as their prefix")

    # 2. a missing file
    run2 = subprocess.run([exe, os.path.join(work, "nope.m3u"), work],
                          capture_output=True, timeout=60)
    out2 = [l for l in run2.stdout.decode("utf-8", "replace").splitlines() if l]
    check(run2.returncode == 1 and out2 and "OPEN_ERR" in out2[0],
          "a missing playlist reports OPEN_ERR")

    # 3. malformed entries are skipped by the parser, not crashes
    bad_pl = os.path.join(work, "bad.m3u")
    with open(bad_pl, "wb") as f:
        f.write(b"\x00\x01garbage\n\n\n#only comments\nok.flac\n")
    run3 = subprocess.run([exe, bad_pl, work], capture_output=True, timeout=60)
    out3 = [l for l in run3.stdout.decode("utf-8", "replace").splitlines() if l]
    check(run3.returncode == 0 and any(l.startswith("T ") and
          l.endswith("ok.flac") for l in out3),
          "malformed lines are skipped and valid ones still parse")

    # 4. empty playlist
    empty_pl = os.path.join(work, "empty.m3u")
    with open(empty_pl, "w") as f:
        f.write("")
    run4 = subprocess.run([exe, empty_pl, work], capture_output=True, timeout=60)
    out4 = [l for l in run4.stdout.decode("utf-8", "replace").splitlines() if l]
    check(run4.returncode == 0 and "END 0" in out4,
          "an empty playlist ends cleanly with zero entries")

    print("test_m30playlist: %s  (fixture: %s)" % ("OK" if rc == 0 else "FAILED", pl))
    return rc


if __name__ == "__main__":
    sys.exit(main())
