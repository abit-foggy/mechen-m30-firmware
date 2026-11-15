#!/usr/bin/env python3
"""Rename the Settings > Information "Modify time" row label to "Build ID:".

usage: patch_label.py SETTING.sty OUT.sty

The Information screen body lives in setting.sty as one UTF-16LE format string
per language (pair 107 of each of the 28 string groups).  Most groups - all the
European ones, including the English group the player UI uses - label the third
row with the English text "Modify time:"; the CJK groups use their own 5-char
labels, which are too short for "Build ID:" and are left stock.

    "Model:[%s]\r\nSoftware version:[%s]\r\nModify time:[%s]\0"

The third %s is fed by sub_40115074's third row pointer, which patch_version.py
already redirects to the build identifier - so the row reads
"Modify time:[6d5b8457]".  This patch rewrites the label in place to

    "Build ID:   [%s]"          (padded with spaces to the original length)

The replacement is EXACTLY as long as the original label (12 UTF-16 units), so
this is a pure in-place byte swap: no shifting, the file size, the content
length at 0x08, the XML offset at 0x30, every table entry and every other
string stay byte-identical, and repack_fw.py's fixed-slot constraint holds
trivially.  (Group 27 uses "Modify time " with a space instead of the colon -
both spellings are handled.)

Every stock byte the patch depends on is asserted first, and the result is
re-read: only the matched label spans may differ from the input.
"""
import struct
import sys

MAGIC = b'RU3\x19'
VERSION = b'V100'
ENTRY = 16
OLD_LABELS = ['Modify time:', 'Modify time ']                 # 12 chars each
NEW_LABEL = 'Build ID:'.ljust(12)                             # same 12 chars


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
    olds = [s.encode('utf-16-le') for s in OLD_LABELS]
    new = NEW_LABEL.encode('utf-16-le')
    assert len(new) == len(olds[0]), 'replacement must keep the label length'

    # locate every string holding a Modify-time label, as (group_eoff, pair, poff, plen, which)
    targets = []
    for at, o, etype, a, b, eoff, elen in parse_entries(d):
        if etype != 1:
            continue
        for p in range(a):
            poff, plen = struct.unpack_from('<II', d, eoff + 8 * p)
            assert eoff <= poff and poff + plen <= eoff + elen, \
                'pair %d of group %#x points outside its blob' % (p, eoff)
            s = d[poff:poff + plen]
            for k, old in enumerate(olds):
                if s.find(old) >= 0:
                    targets.append((eoff, p, poff, plen, k))
    assert targets, 'no string with a Modify-time label found'
    assert not any(NEW_LABEL.encode('utf-16-le') in d[poff:poff + plen]
                   for _, _, poff, plen, _ in targets), 'already patched'

    b = bytearray(d)
    for eoff, p, poff, plen, k in targets:
        s = bytes(b[poff:poff + plen])
        i = s.find(olds[k])
        b[poff + i:poff + i + len(new)] = new

    # ---- read-back verification ----
    r = bytes(b)
    assert len(r) == len(d), 'file size changed'
    assert struct.unpack_from('<I', r, 8)[0] == struct.unpack_from('<I', d, 8)[0]
    assert r[:8] == d[:8] and r[0x30:0x34] == d[0x30:0x34], 'header fields moved'
    allowed = set()
    for eoff, p, poff, plen, k in targets:
        i = d[poff:poff + plen].find(olds[k])
        allowed.update(range(poff + i, poff + i + len(new)))
    diff = [i for i in range(len(d)) if d[i] != r[i]]
    assert set(diff) <= allowed, 'bytes changed outside the label spans: %r' % [
        hex(i) for i in diff if i not in allowed][:8]
    # every patched string decodes with the new label and intact format
    for eoff, p, poff, plen, k in targets:
        s = r[poff:poff + plen].decode('utf-16-le')
        assert NEW_LABEL in s and OLD_LABELS[k] not in s, 'label swap failed at %#x/%d' % (eoff, p)
        assert s.count('[%s]') == d[poff:poff + plen].decode('utf-16-le').count('[%s]')

    open(out, 'wb').write(r)
    print('setting.sty: %d language copies relabeled "Modify time" -> "%s" (in place, size unchanged %#x)'
          % (len(targets), NEW_LABEL.rstrip(), len(d)))
    print('   new row text: %r' % r[targets[0][2]:targets[0][2] + targets[0][3]].decode('utf-16-le'))
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:3]))
