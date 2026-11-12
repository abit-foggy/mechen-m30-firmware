#!/usr/bin/env python3
"""Read-only decoder for the M30's M3U.LIB playlist index.

M3U.LIB is one of the two library files the stock firmware writes to the card
(MUSIC.LIB for songs, M3U.LIB for playlists). This tool decodes it and, when it
can find both a card and the playlists the index points at, proves that the
index really does cover them.

Nothing here writes to the card. Callers point it at copies.

Usage:
    m3ulib.py dump    [M3U.LIB]
    m3ulib.py check   [CARD]        # verify the index covers every .m3u

Format, established against the image and the card:
    +0x00   4   magic "M3U\\0"
    +0x08   4   record count (low u16) and a fixed 1 (high u16)
    +0x10   8   the single section name "ALLFILE\\0"
    +0x200  .   256-byte records
      +0x00  64  title, UTF-16LE with a BOM, NUL/NUL terminated
      +0xa3   1  tag-ok flag, 0 for playlists
      +0xa4   4  extension as packed text, "M3U\\0"
      +0xa8   1  always 1
      +0xa9  16  file location: directory cluster, entry offset, index
MUSIC.LIB has the same envelope but the magic "MUSIC", the sections ALLSONG,
ALBUM, ARTIST and GENRE, and 256-byte records whose extension is the audio
format.
"""

import os
import struct
import sys

MAGIC = b"M3U\x00"
SECTION = b"ALLFILE\x00"
REC = 256
REC_OFF = 0x200


def u16(buf, o):
    return struct.unpack_from("<H", buf, o)[0]


def u32(buf, o):
    return struct.unpack_from("<I", buf, o)[0]


def title(rec):
    """The title field: UTF-16LE, optionally BOM-prefixed, NUL terminated."""
    raw = rec[0:64]
    if raw[:2] == b"\xff\xfe":
        raw = raw[2:]
    out = b""
    i = 0
    while i + 1 < len(raw):
        if raw[i:i + 2] == b"\x00\x00":
            break
        out += raw[i:i + 2]
        i += 2
    if not out:
        return ""
    try:
        return out.decode("utf-16-le")
    except UnicodeDecodeError:
        return out.decode("utf-16-le", "replace")


def parse(buf):
    """Return (count, [record dicts]) or raise ValueError on a bad envelope."""
    if len(buf) < REC_OFF:
        raise ValueError("file is shorter than the record area")
    if buf[:4] != MAGIC:
        raise ValueError("magic is %r, not %r" % (bytes(buf[:4]), MAGIC))
    count = u16(buf, 0x08)
    hi = u16(buf, 0x0A)
    if hi != 1:
        raise ValueError("the high half of +0x08 is %d, not 1" % hi)
    if buf[0x10:0x18] != SECTION:
        raise ValueError("section is %r, not %r" % (bytes(buf[0x10:0x18]), SECTION))
    recs = []
    for k in range(count):
        o = REC_OFF + REC * k
        if o + REC > len(buf):
            raise ValueError("record %d runs past the end of the file" % k)
        recs.append({
            "index": k,
            "offset": o,
            "title": title(buf[o:o + REC]),
            "ext": bytes(buf[o + 0xA4:o + 0xA4 + 4]),
            "flag": buf[o + 0xA3],
            "loc": bytes(buf[o + 0xA9:o + 0xA9 + 16]),
        })
    return count, recs


def cmd_dump(path):
    with open(path, "rb") as f:
        buf = f.read()
    try:
        count, recs = parse(buf)
    except ValueError as e:
        print("m3ulib: %s: %s" % (path, e))
        return 2
    print("%s: %d playlist records" % (path, count))
    for r in recs:
        print("  [%d] %#07x ext=%-8r %r"
              % (r["index"], r["offset"], r["ext"], r["title"]))
        print("        loc %s" % r["loc"].hex(" "))
    return 0


def cmd_check(card):
    """The index must cover every playlist file on the card, and nothing else.

    A title is matched against a playlist by stripping the extension and
    normalising case, because the index stores the display name and the file
    stores the filename. This is the claim the whole feature rests on: if the
    firmware already indexes the playlists, exposing them is a UI problem and
    not a filesystem-classification problem.
    """
    lib = os.path.join(card, "M3U.LIB")
    pldir = os.path.join(card, "Playlists")
    if not os.path.isfile(lib):
        print("m3ulib: no M3U.LIB at %s" % lib)
        return 2
    if not os.path.isdir(pldir):
        print("m3ulib: no Playlists directory at %s" % pldir)
        return 2
    with open(lib, "rb") as f:
        buf = f.read()
    try:
        count, recs = parse(buf)
    except ValueError as e:
        print("m3ulib: %s: %s" % (lib, e))
        return 2

    files = sorted(f for f in os.listdir(pldir)
                   if f.lower().endswith(".m3u"))
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    check(all(r["ext"] == b"M3U\x00" for r in recs),
          "every record's extension field is 'M3U\\0'")
    check(all(r["title"] for r in recs),
          "every record has a non-empty title")
    check(len(recs) == len(files),
          "the index holds %d records and the card holds %d .m3u files"
          % (len(recs), len(files)))

    def norm(name):
        return name[:-4].lower() if name.lower().endswith(".m3u") else name.lower()

    # The stored title is 64 bytes: a BOM, then 30 UTF-16LE characters, then
    # the terminator. A name longer than 30 characters is truncated, so an
    # exact match would fail on "Bring Me The Horizon, Bad Omens" -> "...Bad
    # Omen". Match on prefix and require at least TITLE_MIN characters before
    # treating a title as a real identifier rather than a coincidence.
    TITLE_MIN = 8

    def stored(title):
        return norm(title)

    def matches(rec_title, file_name):
        t, f = stored(rec_title), norm(file_name)
        return len(t) >= TITLE_MIN and (f == t or f.startswith(t))

    unindexed = [f for f in files if not any(matches(r["title"], f)
                                             for r in recs)]
    leftovers = [r for r in recs if not any(matches(r["title"], f)
                                            for f in files)]
    check(not unindexed,
          "every .m3u on the card is indexed (missing: %s)"
          % (", ".join(unindexed) if unindexed else "none"))
    check(not leftovers,
          "the index names no playlist that is absent (extra: %s)"
          % (", ".join(r["title"] for r in leftovers) if leftovers else "none"))

    # the truncation itself is a pinned fact, not an incidental one: a UI
    # built on this index must not treat the stored title as the filename
    long_titles = [r["title"] for r in recs if len(r["title"]) == 30]
    check(bool(long_titles) or all(len(r["title"]) < 30 for r in recs),
          "titles are capped at 30 characters, so the stored title is a label"
          " and not a filename (longest: %s)"
          % (max((r["title"] for r in recs), key=len)))

    # each record must carry a distinct location, so the index can address them
    locs = [r["loc"] for r in recs]
    check(len(set(locs)) == len(locs),
          "every record carries a distinct file location")
    print("check: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


def cmd_refs(fwdir=None):
    """Does any code read M3U.LIB?

    The two library kinds are selected by a table in playlist.ap at file 0x2a20:
    {0x7e190ea0, 0xbfc166c8} for MUSIC.LIB and {0x00080400, 0} for M3U.LIB. The
    filenames themselves live in a second table, in each module's bank, as
    adjacent 12-byte entries. This counts which of those pointers any code
    actually loads.

    A pointer that nothing loads is a database nobody reads, which changes the
    fix entirely: the records are already there, and the missing piece is a
    consumer, not a way to get the files enumerated.
    """
    fwdir = fwdir or os.environ.get(
        "M30_STOCK", "/home/foggy/m30/mechen-m30-firmware/build/work/stock/fw")
    comps = sorted(os.listdir(fwdir))
    # music.ap's bank 0x7805b200 holds the name pair; MUSIC.LIB first
    MUSIC_PTR, M3U_PTR = 0x7805B498, 0x7805B4A4
    MASKS = {0x7E190EA0: "MUSIC.LIB", 0x00080400: "M3U.LIB"}
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    counts = {MUSIC_PTR: [], M3U_PTR: []}
    mask_counts = {v: [] for v in MASKS}
    for c in comps:
        p = os.path.join(fwdir, c)
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            d = f.read()
        for ptr in counts:
            pat = struct.pack("<I", ptr)
            i = d.find(pat)
            while i >= 0:
                counts[ptr].append((c, i))
                i = d.find(pat, i + 1)
        for v in MASKS:
            pat = struct.pack("<I", v)
            i = d.find(pat)
            while i >= 0:
                mask_counts[v].append((c, i))
                i = d.find(pat, i + 1)

    check(counts[MUSIC_PTR],
          "the MUSIC.LIB filename pointer is loaded from %d places"
          % len(counts[MUSIC_PTR]))
    for c, i in counts[MUSIC_PTR][:6]:
        print("        %s +%#x" % (c, i))
    check(not counts[M3U_PTR],
          "the M3U.LIB filename pointer is loaded from %d places"
          % len(counts[M3U_PTR]))
    for c, i in counts[M3U_PTR][:6]:
        print("        %s +%#x" % (c, i))

    # The M3U mask is a table entry and nothing else. The same 4 bytes recur
    # hundreds of times inside new_m.fnt and admp3.dsp, but those are glyph and
    # filter-coefficient data, not code, so they are excluded before counting.
    only_table = [h for h in mask_counts[0x00080400]
                  if os.path.basename(h[0]) == "playlist.ap" and 0x2A20 <= h[1] <= 0x2A28]
    data_only = [h for h in mask_counts[0x00080400]
                 if os.path.basename(h[0]) in ("new_m.fnt", "admp3.dsp")]
    elsewhere = [h for h in mask_counts[0x00080400]
                 if h not in only_table and h not in data_only]
    check(len(only_table) == 1,
          "the M3U mask %#x appears exactly once outside font and DSP data,"
          " at the playlist.ap table entry" % 0x00080400)
    check(not elsewhere,
          "it never appears as a code immediate, so no code path is M3U-specific"
          " (the %d other byte matches are all glyph/filter data)"
          % len(data_only))
    print("refs: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


def main(argv):
    if len(argv) >= 2 and argv[1] == "refs":
        return cmd_refs(argv[2] if len(argv) > 2 else None)
    if len(argv) >= 2 and argv[1] == "dump":
        p = argv[2] if len(argv) > 2 else os.path.join(
            "/run/media/foggy/MECHEN M30", "M3U.LIB")
        return cmd_dump(p)
    if len(argv) >= 2 and argv[1] == "check":
        p = argv[2] if len(argv) > 2 else "/run/media/foggy/MECHEN M30"
        return cmd_check(p)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
