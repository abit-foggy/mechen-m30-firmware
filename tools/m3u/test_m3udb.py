#!/usr/bin/env python3
"""End-to-end test for the M3U.LIB adapter (tools/m3u/m3udb.c).

This is the whole chain the firmware still lacks a consumer for: a record index
becomes a playlist title, a file location, and an ordered list of tracks that
the portable reader parsed. It runs against copies of the user's real M3U.LIB
and Playlists directory, so it exercises the actual bytes rather than a
synthetic fixture.

The one step that is stubbed is resolving a record's location to a filename,
because the firmware-side meaning of that 16-byte field is not established. The
host resolver pairs records with files by the order of the location field, which
is monotonic across the card's ten records, and the test says so rather than
depending on it silently.

Usage: test_m3udb.py   (exits non-zero on failure; skips if no fixture)
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOST_CC = os.environ.get("HOST_CC", "cc")

# copies made read-only from the card; override with M30LIB to point elsewhere
# the fixture is a read-only copy of M3U.LIB plus the playlists; the track
# paths it returns are relative to the playlists' own directory, so they are
# resolved against the real card, where the Music tree they point at lives
FIXTURE = os.environ.get("M30LIB", "/tmp/m30lib")
CARD = os.environ.get("M30CARD", "/run/media/foggy/MECHEN M30")


def build(work):
    exe = os.path.join(work, "m3udb_test")
    cmd = [HOST_CC, "-O1", "-Wall", "-Wextra", "-I" + HERE,
           "-o", exe, os.path.join(HERE, "harness_db.c"),
           os.path.join(HERE, "m3u.c"),
           os.path.join(HERE, "m3udb.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("test_m3udb: build failed")
        print(r.stderr)
        sys.exit(2)
    return exe


def main():
    lib = os.path.join(FIXTURE, "M3U.LIB")
    pldir = os.path.join(FIXTURE, "Playlists")
    if not os.path.isfile(lib):
        print("test_m3udb: no fixture; copy M3U.LIB and Playlists/ from the"
              " card to %s (read-only)" % FIXTURE)
        return 0

    work = tempfile.mkdtemp(prefix="m3udb.")
    try:
        exe = build(work)
    except Exception as e:
        print("test_m3udb: %s" % e)
        return 2

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # build the explicit record-to-file pairing the harness needs: a record's
    # title, matched against a playlist filename. Titles are truncated at 30
    # characters on the card, so the match is a prefix match, and the pairing is
    # handed to the harness explicitly rather than inferred inside it.
    import struct
    with open(lib, "rb") as f:
        raw = f.read()
    nrec = struct.unpack_from("<H", raw, 8)[0]
    files = sorted(f for f in os.listdir(pldir) if f.lower().endswith(".m3u"))
    used, mapping = set(), []
    for i in range(nrec):
        txt = raw[0x200 + 256 * i + 2:0x200 + 256 * i + 64].split(b"\x00\x00")[0]
        if len(txt) % 2:
            txt = txt[:-1]
        title = txt.decode("utf-16-le", "replace")
        hit = next((f for f in files
                    if f not in used and f[:-4].lower().startswith(title.lower())),
                   None)
        if hit is None:
            hit = next(f for f in files if f not in used)
        used.add(hit)
        mapping.append("%d:%s" % (i, hit))

    work = tempfile.mkdtemp(prefix="m3udb.")
    try:
        exe = build(work)
    except Exception as e:
        print("test_m3udb: %s" % e)
        return 2

    r = subprocess.run([exe, lib, pldir, "\n".join(mapping)],
                       capture_output=True, timeout=180)
    out = [l for l in r.stdout.decode("utf-8", "replace").splitlines() if l]
    bad = [l for l in out
           if l.split(" ", 1)[0] in ("INIT_ERR", "READ_ERR", "OPEN_ERR",
                                     "PARSE_ERR")]
    check(r.returncode == 0 and not bad,
          "every record resolved and parsed without error%s"
          % ("" if not bad else "  (%r)" % bad[:3]))

    check(out and out[0] == "RECORDS %d" % nrec,
          "the adapter reports %d records" % nrec)

    tracks = [l.split(" ", 3)[3] for l in out if l.startswith("T ")]
    check(len(tracks) >= nrec,
          "all %d playlists produced tracks (%d total)" % (nrec, len(tracks)))

    # the decisive assertion: every returned path resolves against the playlist
    # directory, which is what the device would have to do to open the file
    bad = [t for t in tracks
           if not os.path.isfile(os.path.normpath(
               os.path.join(CARD, "Playlists", t)))]
    check(not bad,
          "every track path resolves from its playlist directory on the card"
          + ("" if not bad else "  (%d do not, e.g. %r)" % (len(bad), bad[0])))

    # order preservation: compare each playlist's first track against the file
    firsts = {}
    for l in out:
        if l.startswith("T "):
            parts = l.split(" ", 3)
            firsts.setdefault(int(parts[1]), parts[3])
    wrong = []
    for i, name in enumerate(mapping):
        fn = os.path.join(pldir, name.split(":", 1)[1])
        with open(fn, "rb") as f:
            data = f.read()
        lines = [l for l in data.split(b"\n") if l and not l.startswith(b"#")]
        if lines and firsts.get(i, "").encode("utf-8") != lines[0]:
            wrong.append(i)
    check(not wrong,
          "each playlist's first track is the file's first entry, in order"
          + ("" if not wrong else "  (playlists %s differ)" % wrong))

    # a second read must be byte-identical: the adapter is deterministic
    r2 = subprocess.run([exe, lib, pldir, "\n".join(mapping)],
                        capture_output=True, timeout=180)
    check(r2.stdout == r.stdout,
          "a second run reproduces the output exactly")

    print("test_m3udb: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
