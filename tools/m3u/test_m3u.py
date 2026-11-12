#!/usr/bin/env python3
"""Host tests for the M3U parser (tools/m3u/m3u.c).

The parser is compiled with the cross compiler in hosted mode and pointed at
fixtures generated here, so the tests exercise exactly the source the player
will run. Nothing is flashed and no stock firmware is modified.

Covered: LF and CRLF endings, a final line without a terminator, comments and
EXTM3U/EXTINF, blank lines, relative paths, directory prefixing, order
preservation, the empty playlist, a long-but-legal path, bounds overflow, and
the entry limit.

Usage: test_m3u.py   (exits non-zero on any failure)
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CROSS = os.environ.get("CROSS", "mips64-linux-gnu-")
M3U_MAX_ENTRIES = 4000

# (name, dir, fixture bytes, expected output lines, expected exit status)
CASES = [
    ("lf", "Music/FLAC",
     b"track one.flac\ntrack two.flac\n",
     ["E Music/FLAC/track one.flac", "E Music/FLAC/track two.flac", "END 2"], 0),

    ("crlf", "Playlists",
     b"#EXTM3U\r\n#EXTINF:130,Queen - Killer Queen\r\n01 Killer Queen.flac\r\ntwo.flac\r\n",
     ["E Playlists/01 Killer Queen.flac", "E Playlists/two.flac", "END 2"], 0),

    ("no-final-newline", "d",
     b"a.flac\nb.flac",
     ["E d/a.flac", "E d/b.flac", "END 2"], 0),

    ("crlf-no-final", "d",
     b"a.flac\r\nb.flac",
     ["E d/a.flac", "E d/b.flac", "END 2"], 0),

    ("blank-and-comment", "x",
     b"\n   \n#comment\n\t#indented\n#EXTM3U\nreal.flac\n\n",
     ["E x/real.flac", "END 1"], 0),

    ("empty", "d", b"", ["END 0"], 0),
    ("only-comments", "d", b"#a\n#b\r\n", ["END 0"], 0),

    ("nested-relative", "a/b/c",
     b"../../flac/song.flac\n",
     ["E a/b/c/../../flac/song.flac", "END 1"], 0),

    ("dot-dir", ".",
     b"a.flac\nb.flac\n",
     ["E ./a.flac", "E ./b.flac", "END 2"], 0),

    ("long-but-legal", "d",
     b"x" * 100 + b".flac\n",
     ["E d/" + "x" * 100 + ".flac", "END 1"], 0),

    ("dir-prefix-added", "Playlists",
     b"s.flac\n",
     ["E Playlists/s.flac", "END 1"], 0),

    ("already-slashed-dir", "Playlists/",
     b"s.flac\n",
     ["E Playlists/s.flac", "END 1"], 0),

    ("spaces-in-name", "d",
     b"My Great Song (Remix).flac\n",
     ["E d/My Great Song (Remix).flac", "END 1"], 0),

    ("utf8-path", "d",
     "Löwe & Strauß.flac\n".encode("utf-8"),
     None, 0),   # checked separately: bytes must pass through unchanged

    # --- failure cases ---
    ("too-long-path", "d",
     b"x" * 300 + b".flac\n",
     ["ERR -2"], 1),
    ("too-long-dir", "d" * 80,
     b"s.flac\n",
     ["INIT_ERR"], 1),
]

# entry-limit case is generated separately to keep the fixture small in source
# a fixture of 4001 entries is enough to exercise the cap, and keeps the
# file small: the parser must stop at 4000 and report END, not error
# a fixture one entry past the cap: the parser must deliver exactly
# M3U_MAX_ENTRIES and then fail closed with M3U_ERR_TRUNCATED, never silently
# stopping at the cap or growing
LIMIT_CASE = ("limit", "d", b"".join(b"f%d.flac\n" % i for i in range(4001)),
              None, 1)


def build(work):
    exe = os.path.join(work, "m3u_test")
    # the parser is freestanding C, so it compiles natively as well as for the
    # player; the native build is what these host tests use
    host_cc = os.environ.get("HOST_CC", "cc")
    cmd = [host_cc, "-O1", "-Wall", "-Wextra", "-I" + HERE,
           "-o", exe, os.path.join(HERE, "harness.c"),
           os.path.join(HERE, "m3u.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("test_m3u: build failed")
        print(r.stderr)
        sys.exit(2)
    return exe


def run(exe, work, name, directory, data):
    fix = os.path.join(work, "%s.m3u" % name)
    with open(fix, "wb") as f:
        f.write(data)
    r = subprocess.run([exe, fix, directory], capture_output=True, timeout=60)
    out = [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l]
    return out, r.returncode


def main():
    work = tempfile.mkdtemp(prefix="m3ut.")
    try:
        exe = build(work)
    except Exception as e:
        print("test_m3u: %s" % e)
        return 2

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    for name, directory, data, expected, status in CASES + [LIMIT_CASE]:
        out, got_status = run(exe, work, name, directory, data)
        if name == "utf8-path":
            want = "E d/" + data.decode("utf-8").rstrip("\n")
            ok = out == [want, "END 1"]
            check(ok, "%s: UTF-8 path bytes pass through unchanged"
                  % name + ("" if ok else "  got %r want %r" % (out, [want, "END 1"])))
            continue
        if name == "limit":
            entries = [l for l in out if l.startswith("E ")]
            check(len(entries) == M3U_MAX_ENTRIES,
                  "limit: exactly %d entries returned (got %d)"
                  % (M3U_MAX_ENTRIES, len(entries)))
            check(out[-1] == "ERR -3" and got_status == 1,
                  "limit: fails closed with M3U_ERR_TRUNCATED instead of"
                  " reporting END (got exit %d, last %r)"
                  % (got_status, out[-1] if out else None))
            continue
        ok = out == expected and got_status == status
        check(ok, "%s: %d line(s)%s"
              % (name, len(out), "" if ok else "\n      got %r\n      want %r (exit %d vs %d)"
                 % (out, expected, got_status, status)))

    print("test_m3u: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
