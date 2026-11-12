#!/usr/bin/env python3
"""Host tests for the M3U writer (tools/m3u/m3uw.c) and its round trip.

The writer is compiled with the native compiler alongside the reader, so the
round trip is writer -> file -> reader with the same source the player will
run. Every claim below is checked against bytes on disk, not against an
expectation recorded by hand.

Covered: LF and CRLF output, the optional #EXTM3U header, size prediction,
UTF-8 pass-through, order preservation, the entry cap, every rejection class,
and the lossless round trip through the reader for both line endings.

Usage: test_m3uw.py   (exits non-zero on any failure)
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOST_CC = os.environ.get("HOST_CC", "cc")


def build(work):
    exe = os.path.join(work, "m3u_test")
    cmd = [HOST_CC, "-O1", "-Wall", "-Wextra", "-I" + HERE,
           "-o", exe, os.path.join(HERE, "harness.c"),
           os.path.join(HERE, "m3u.c"),
           os.path.join(HERE, "m3uw.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("test_m3uw: build failed")
        print(r.stderr)
        sys.exit(2)
    return exe


def run(exe, *args):
    r = subprocess.run([exe] + list(args), capture_output=True, timeout=60)
    out = [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l]
    return out, r.returncode


def main():
    work = tempfile.mkdtemp(prefix="m3uw.")
    try:
        exe = build(work)
    except Exception as e:
        print("test_m3uw: %s" % e)
        return 2

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    def write(name, paths, eol="lf", header=0):
        pf = os.path.join(work, name + ".paths")
        of = os.path.join(work, name + ".m3u")
        with open(pf, "w", encoding="utf-8") as f:
            f.write("\n".join(paths) + "\n")
        out, code = run(exe, "--write", pf, of, eol, str(header))
        if code:
            return None, out
        with open(of, "rb") as f:
            return f.read(), out

    # --- byte-exact output ---
    data, _ = write("basic", ["a.flac", "b.flac"], "lf", 0)
    check(data == b"a.flac\nb.flac\n",
          "lf without header: bare entries, LF terminators%s"
          % ("" if data == b"a.flac\nb.flac\n" else "  got %r" % data))

    data, _ = write("crlf", ["a.flac", "b.flac"], "crlf", 0)
    check(data == b"a.flac\r\nb.flac\r\n",
          "crlf without header: CRLF terminators%s"
          % ("" if data == b"a.flac\r\nb.flac\r\n" else "  got %r" % data))

    data, _ = write("hdr", ["a.flac"], "lf", 1)
    check(data == b"#EXTM3U\na.flac\n",
          "header is written once, before the first entry%s"
          % ("" if data == b"#EXTM3U\na.flac\n" else "  got %r" % data))

    data, _ = write("empty", [], "lf", 0)
    check(data == b"", "an empty playlist is a zero-byte file%s"
          % ("" if data == b"" else "  got %r" % data))

    data, _ = write("emptyhdr", [], "lf", 1)
    check(data == b"#EXTM3U\n",
          "an empty playlist with a header is the header only%s"
          % ("" if data == b"#EXTM3U\n" else "  got %r" % data))

    # --- paths the reader trims or prefixes must round trip ---
    utf8 = "Löwe & Straße.flac"
    data, _ = write("utf8", [utf8], "lf", 0)
    want = utf8.encode("utf-8") + b"\n"
    check(data == want, "UTF-8 paths are written byte for byte%s"
          % ("" if data == want else "  got %r want %r" % (data, want)))

    data, _ = write("dots", ["../../flac/song.flac"], "lf", 0)
    check(data == b"../../flac/song.flac\n",
          "relative paths with .. are written verbatim%s"
          % ("" if data == b"../../flac/song.flac\n" else "  got %r" % data))

    data, _ = write("inner-space", ["My Great Song (Remix).flac"], "lf", 0)
    check(data == b"My Great Song (Remix).flac\n",
          "blanks inside a path are kept%s"
          % ("" if data == b"My Great Song (Remix).flac\n" else "  got %r" % data))

    # --- size prediction ---
    _, out = write("sized", ["a.flac", "bb.flac"], "crlf", 1)
    # "#EXTM3U\r\n" = 9, "a.flac\r\n" = 8, "bb.flac\r\n" = 9
    check(out == ["WROTE 2 26"],
          "m3uw_size predicts the exact byte count (got %r)" % out)

    # --- rejections: nothing may be written when a path is refused ---
    def reject(name, paths, expect):
        pf = os.path.join(work, name + ".paths")
        of = os.path.join(work, name + ".m3u")
        with open(pf, "w", encoding="utf-8") as f:
            f.write("\n".join(paths) + "\n")
        out, code = run(exe, "--write", pf, of, "lf", "0")
        ok = out and out[0].startswith("ADD_ERR %d" % expect)
        check(ok, "%s: refused with status %d (got %r)"
              % (name, expect, out))

    def reject_one(name, raw, expect):
        pf = os.path.join(work, name + ".one")
        of = os.path.join(work, name + ".m3u")
        with open(pf, "wb") as f:
            f.write(raw)
        out, code = run(exe, "--add-one", pf, of, "lf", "0")
        ok = out and out[0].startswith("ADD_ERR %d" % expect)
        check(ok, "%s: refused with status %d (got %r)"
              % (name, expect, out))

    reject("comment", ["# looks like a comment"], -4)
    reject("absolute", ["/music/a.flac"], -4)
    reject("too-long", ["x" * 200], -2)
    # a leading blank and an empty path cannot survive the reader's own
    # normalisation, so the writer refuses them rather than writing a
    # playlist that points at a file which was never named in it
    reject("leading-blank", ["  spaced.flac"], -4)
    reject_one("leading-tab", b"\tsong.flac\n", -4)
    reject_one("empty-path", b"\n", -4)
    reject_one("bare-empty", b"", -4)

    # a refusal must not leave a partial playlist behind
    pf = os.path.join(work, "partial.paths")
    of = os.path.join(work, "partial.m3u")
    with open(pf, "w") as f:
        f.write("good.flac\n/absolute.flac\n")
    out, code = run(exe, "--write", pf, of, "lf", "0")
    size = os.path.getsize(of) if os.path.exists(of) else -1
    check(code == 1 and size == 0,
          "a refused entry leaves nothing on disk (exit %d, size %d)"
          % (code, size))

    # --- the entry cap ---
    pf = os.path.join(work, "cap.paths")
    of = os.path.join(work, "cap.m3u")
    with open(pf, "w") as f:
        f.write("".join("f%d.flac\n" % i for i in range(4001)))
    out, code = run(exe, "--write", pf, of, "lf", "0")
    check(code == 1 and out and out[0].startswith("ADD_ERR -3"),
          "4001 entries are refused at the cap with M3UW_ERR_FULL (got %r)" % out)

    # --- round trips ---
    cases = [
        ("rt-lf", ["track one.flac", "track two.flac"], "lf", 0),
        ("rt-crlf", ["track one.flac", "track two.flac"], "crlf", 0),
        ("rt-hdr", ["a.flac"], "lf", 1),
        ("rt-utf8", ["Löwe & Straße.flac", "Bjørn.flac"], "crlf", 1),
        ("rt-inner-space", ["My Great Song (Remix).flac", "plain.flac"], "lf", 0),
        ("rt-many", ["song %04d.flac" % i for i in range(500)], "crlf", 1),
        ("rt-dots", ["../up.flac", "./here.flac", "sub/deep.flac"], "lf", 0),
        ("rt-longish", [("d" * 90) + ".flac"], "lf", 1),
    ]
    for name, paths, eol, header in cases:
        pf = os.path.join(work, name + ".paths")
        of = os.path.join(work, name + ".m3u")
        with open(pf, "w", encoding="utf-8") as f:
            f.write("\n".join(paths) + "\n")
        out, code = run(exe, "--roundtrip", pf, of, eol, str(header), "Music/FLAC")
        ok = code == 0 and out and out[-1] == "RTOK %d" % len(paths)
        check(ok, "%s: %d entries survive the round trip (got %r)"
              % (name, len(paths), out[-1] if out else None))

    print("test_m3uw: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
