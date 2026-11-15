#!/usr/bin/env python3
"""Rename the Settings > Information "modify time" row label to "build:id".

usage: patch_label.py SETTING.sty OUT.sty

The Information screen body lives in setting.sty as one UTF-16LE format string
per language group - pair 107 of group 19 (file 0x23642, Simplified) and of
group 20 (file 0x249f6, Traditional):

    "型号:[%s]\r\n软件版本:[%s]\r\n修改时间:[%s]\0"      (修改时间 = "modify time")

The third %s is fed by sub_40115074's third row pointer, which patch_version.py
already redirects to the build identifier - so the row reads
"修改时间:[6d5b8457]".  This patch rewrites the label in every copy to

    "...build:id:[%s]\0"

Each new string is 8 bytes longer, and the groups have no slack, so the content
tail from the end of each old string on is shifted right inside the fixed-size
file:

  - every resource table entry at/after an insert point moves +8 per insert
    point before it, and each affected group's length grows accordingly (file
    size and slot count are unchanged, so repack_fw.py still accepts the image);
  - every string sub-table pair (in every group) at/after an insert point moves
    the same way; each target pair gets the new length;
  - the XML ResDescriptor offset at 0x30 and the content length at 0x08 grow by
    the total delta (the XML holds names only, no offsets).

The last bytes of the file beyond the old content length are dropped.  Every
stock byte the patch depends on is asserted first (magic, tables, the target
strings), and the result is re-read: all other strings must decode
byte-identically, and only the header words, the table entries and the shifted
content region may differ.
"""
import struct
import sys

MAGIC = b'RU3\x19'
VERSION = b'V100'
ENTRY = 16
# exact code units: 型号： uses a fullwidth colon (U+FF1A), the other two rows an
# ASCII ':' - the stock string mixes both
STOCK_INFO = struct.pack('<30H',
    0x578B, 0x53F7, 0xFF1A, 0x5B, 0x25, 0x73, 0x5D, 0x0D, 0x0A,             # 型号：[%s]\r\n
    0x8F6F, 0x4EF6, 0x7248, 0x672C, 0x3A, 0x5B, 0x25, 0x73, 0x5D, 0x0D, 0x0A,  # 软件版本:[%s]\r\n
    0x4FEE, 0x6539, 0x65F6, 0x95F4, 0x3A, 0x5B, 0x25, 0x73, 0x5D, 0x00)      # 修改时间:[%s]\0
OLD_LABEL = struct.pack('<5H', 0x4FEE, 0x6539, 0x65F6, 0x95F4, 0x3A)      # 修改时间:
NEW_LABEL = 'build:id:'.encode('utf-16-le')
DELTA = len(NEW_LABEL) - len(OLD_LABEL)


def parse_entries(d):
    """[(table_at, entry_off, type, a, b, eoff, elen)] for both tables."""
    assert d[:4] == MAGIC and d[0x0c:0x10] == VERSION, 'not a RU3 V100 .sty'
    out = []
    for at in (0x10, 0x20):
        toff, n = struct.unpack_from('<I', d, at)[0], struct.unpack_from('<H', d, at + 4)[0]
        for i in range(n):
            o = toff + i * ENTRY
            eoff, elen = struct.unpack_from('<II', d, o)
            etype, a = struct.unpack_from('<HH', d, o + 8)
            b = struct.unpack_from('<I', d, o + 12)[0]
            out.append((at, o, etype, a, b, eoff, elen))
    return out


def main(argv):
    src, out = argv
    d = open(src, 'rb').read()
    content_len = struct.unpack_from('<I', d, 8)[0]
    xml_off = struct.unpack_from('<I', d, 0x30)[0]
    assert content_len <= len(d), 'content length past end of file'

    # locate every string holding the label, as (group_eoff, pair, poff, plen)
    targets = []
    for at, o, etype, a, b, eoff, elen in parse_entries(d):
        if etype != 1:
            continue
        for p in range(a):
            poff, plen = struct.unpack_from('<II', d, eoff + 8 * p)
            assert eoff <= poff and poff + plen <= eoff + elen, \
                'pair %d of group %#x points outside its blob' % (p, eoff)
            s = d[poff:poff + plen]
            if s.find(OLD_LABEL) >= 0:
                targets.append((eoff, p, poff, plen, s))
    assert targets, 'no string with the 修改时间 label found'
    targets.sort(key=lambda t: t[2])
    for eoff, p, poff, plen, s in targets:
        assert s.replace(OLD_LABEL, NEW_LABEL).find(OLD_LABEL) < 0
    ins_points = [poff + plen for _, _, poff, plen, _ in targets]   # end of each old string
    total = DELTA * len(targets)
    assert content_len + total <= len(d), 'grown content would exceed the fixed file size'

    def shift(o):
        """file offset o in the stock image -> offset in the patched image."""
        return o + DELTA * sum(1 for ins in ins_points if ins <= o)

    # rebuild the content: old string -> new string at each target, the tail
    # between/after them copied verbatim (shifts right by the cumulative delta)
    b = bytearray(d[:targets[0][2]])          # up to the first target string
    for k, ((eoff, p, poff, plen, s), ins) in enumerate(zip(targets, ins_points)):
        b += s.replace(OLD_LABEL, NEW_LABEL)  # the grown string
        nxt = targets[k + 1][2] if k + 1 < len(targets) else content_len
        b += d[ins:nxt]                       # verbatim tail up to the next target
    # the last `total` bytes of the file lie beyond the old content length and are dropped
    b += d[content_len:len(d) - total]
    assert len(b) == len(d), 'rebuilt file size changed: %#x vs %#x' % (len(b), len(d))

    # resource table entries: move those at/after an insert point; grow affected groups
    for at, o, etype, a, b2, eoff, elen in parse_entries(d):
        if eoff >= ins_points[0]:
            struct.pack_into('<I', b, o, shift(eoff))
        grew = DELTA * sum(1 for t in targets if t[0] == eoff)
        if grew:
            struct.pack_into('<I', b, o + 4, elen + grew)
    # string sub-table pairs: move those at/after an insert point; retarget lengths
    for at, o, etype, a, b2, eoff, elen in parse_entries(d):
        if etype != 1:
            continue
        base = shift(eoff)
        for p in range(a):
            poff, plen = struct.unpack_from('<II', d, eoff + 8 * p)
            nlen = plen + DELTA if any(t[0] == eoff and t[1] == p for t in targets) else plen
            struct.pack_into('<II', b, base + 8 * p, shift(poff), nlen)
    # header fields
    struct.pack_into('<I', b, 8, content_len + total)
    if xml_off >= ins_points[0]:
        struct.pack_into('<I', b, 0x30, shift(xml_off))

    # ---- read-back verification ----
    r = bytes(b)
    assert len(r) == len(d), 'file size changed'
    assert struct.unpack_from('<I', r, 8)[0] == content_len + total
    # every string decodes identically except the targets
    def all_strings(img):
        out = []
        for at, o, etype, a, b2, eoff, elen in parse_entries(img):
            if etype != 1:
                continue
            for p in range(a):
                poff, plen = struct.unpack_from('<II', img, eoff + 8 * p)
                out.append((eoff, p, img[poff:poff + plen]))
        return out
    ss, ps = all_strings(d), all_strings(r)
    assert len(ss) == len(ps), 'string count changed'
    n_changed = 0
    for (g1, p1, s1), (g2, p2, s2) in zip(ss, ps):
        assert shift(g1) == g2 and p1 == p2, 'string order changed at %#x/%d' % (g1, p1)
        if s1 != s2:
            assert s1.replace(OLD_LABEL, NEW_LABEL) == s2, 'unexpected string change at %#x/%d' % (g1, p1)
            n_changed += 1
    assert n_changed == len(targets), 'changed %d strings, expected %d' % (n_changed, len(targets))
    # resource blobs identical modulo the shift (affected groups grow by DELTA each)
    for at, o, etype, a, b2, eoff, elen in parse_entries(r):
        old_eoff = eoff
        for ins in ins_points:
            if ins <= old_eoff:
                old_eoff -= DELTA
        old_elen = elen - DELTA * sum(1 for t in targets if t[0] == old_eoff)
        if old_eoff != eoff or old_elen != elen:
            continue                      # moved and/or grown group: strings checked above
        assert r[eoff:eoff + elen] == d[eoff:eoff + elen], 'resource at %#x corrupted' % eoff
    # bytes before the first insert point: only header fields and table entries
    allowed = set(range(8, 12)) | set(range(0x30, 0x34))
    for at, o, etype, a, b2, eoff, elen in parse_entries(d):
        allowed.update(range(o, o + ENTRY))
        if etype == 1:
            allowed.update(range(eoff, eoff + 8 * a))   # group sub-tables (pair offsets)
    for _, _, poff, plen, _ in targets:
        allowed.update(range(poff, poff + plen))        # the target strings themselves
    diff = [i for i in range(ins_points[0]) if d[i] != r[i]]
    assert set(diff) <= allowed, 'bytes changed outside header/tables before the first insert point: %r' % [
        hex(i) for i in diff if i not in allowed][:12]

    open(out, 'wb').write(r)
    for eoff, p, poff, plen, s in targets:
        print('setting.sty: group %#x pair %d label 修改时间 -> build:id (string %#x -> %#x bytes)' % (
            eoff, p, plen, plen + DELTA))
    print('   content length %#x -> %#x, file size unchanged %#x, %d strings changed' % (
        content_len, content_len + total, len(d), n_changed))
    print('   new row text: %r' % targets[0][4].replace(OLD_LABEL, NEW_LABEL).decode('utf-16-le'))
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:3]))
