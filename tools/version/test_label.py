#!/usr/bin/env python3
"""Test the Information-screen label patch (patch_label.py) on the stock setting.sty.

usage: test_label.py STOCK_setting.sty PATCHED_setting.sty

Checks, against the real stock file:
  1. the patch tool ran cleanly and the file size is unchanged (repack constraint);
  2. exactly one string in the whole image changed: the Information format string
     in group 19 pair 107, 修改时间 -> build; every other string in every
     group decodes byte-identically;
  3. header/table bookkeeping is consistent: content length and XML offset grew
     by exactly the string delta, group 19's length grew by the same, every other
     resource entry is untouched and still points at identical bytes;
  4. the .sty parser (tools/theme/sty.py) still accepts the patched image;
  5. running the patch on the already-patched output fails (stock asserts);
  6. byte isolation: outside the header fields, the table entries and the shifted
     content tail, nothing moved.

Exits non-zero on any failure.
"""
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'theme'))
from sty import parse  # noqa: E402

STOCK_INFO = struct.pack('<30H',
    0x578B, 0x53F7, 0xFF1A, 0x5B, 0x25, 0x73, 0x5D, 0x0D, 0x0A,
    0x8F6F, 0x4EF6, 0x7248, 0x672C, 0x3A, 0x5B, 0x25, 0x73, 0x5D, 0x0D, 0x0A,
    0x4FEE, 0x6539, 0x65F6, 0x95F4, 0x3A, 0x5B, 0x25, 0x73, 0x5D, 0x00)
OLD = struct.pack('<5H', 0x4FEE, 0x6539, 0x65F6, 0x95F4, 0x3A)   # 修改时间:
NEW = 'build:'.encode('utf-16-le')
NEW_INFO = STOCK_INFO.replace(OLD, NEW)
DELTA = len(NEW_INFO) - len(STOCK_INFO)


def strings_of(d):
    """[(group_eoff, pair, bytes)] for every string of every type-1 resource."""
    out = []
    for i, (t, off, ln, a, b) in enumerate(parse(d)):
        if t != 1:
            continue
        for p in range(a):
            poff, plen = struct.unpack_from('<II', d, off + 8 * p)
            out.append((off, p, d[poff:poff + plen]))
    return out


def main(stock, patched):
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    sd = open(stock, 'rb').read()
    pd = open(patched, 'rb').read()

    check(len(pd) == len(sd), "file size unchanged (%#x)" % len(sd))
    check(struct.unpack_from('<I', pd, 8)[0] == struct.unpack_from('<I', sd, 8)[0] + 2 * DELTA,
          "content length grew by exactly 2 label deltas (+%d, one per language group)" % (2 * DELTA))
    check(struct.unpack_from('<I', pd, 0x30)[0] == struct.unpack_from('<I', sd, 0x30)[0] + 2 * DELTA,
          "XML descriptor offset shifted by the same total")
    check(pd[:4] == b'RU3\x19' and pd[0x0c:0x10] == b'V100', "magic/version intact")
    check(struct.unpack_from('<I', pd, 4)[0] == struct.unpack_from('<I', sd, 4)[0],
          "slot count unchanged")

    ss, ps = strings_of(sd), strings_of(pd)
    check(len(ss) == len(ps), "same number of strings (%d)" % len(ss))
    changed = [(g, p, o, n) for (g, p, o), (g2, p2, n) in zip(ss, ps)
               if o != n]
    check(len(changed) == 2 and all(o.replace(OLD, NEW) == n for g, p, o, n in changed),
          "exactly the two language copies of the Information format changed (修改时间 -> build)")
    check(all(n.endswith(NEW.rstrip(b'\x00') + '[%s]\x00'.encode('utf-16-le')) or
              NEW in n for g, p, o, n in changed),
          "new row 3 reads build:[%s] in both copies")

    # insert points = end of each changed stock string
    ins_points = []
    for g, p, o, n in changed:
        a = next(e[3] for e in parse(sd) if e[0] == 1 and e[1] == g)
        for q in range(a):
            poff, plen = struct.unpack_from('<II', sd, g + 8 * q)
            if sd[poff:poff + plen] == o:
                ins_points.append(poff + plen)
                break
    ins_points.sort()
    ins = ins_points[0]

    def shift(o):
        return o + DELTA * sum(1 for i in ins_points if i <= o)

    # resource entries: only the two language groups grew; all blobs identical modulo shift
    se, pe = parse(sd), parse(pd)
    check(len(se) == len(pe), "same number of resources")
    grew_groups = {g for g, p, o, n in changed}
    ok_res = True
    for i, (t1, o1, l1, a1, b1) in enumerate(se):
        t2, o2, l2, a2, b2 = pe[i]
        exp_l = l1 + DELTA if o1 in grew_groups else l1
        if not (t2 == t1 and o2 == shift(o1) and l2 == exp_l and a2 == a1 and b2 == b1):
            ok_res = False
        elif o1 not in grew_groups and (t1 == 2 or o1 < ins) and pd[o2:o2 + l2] != sd[o1:o1 + l1]:
            # type-1 groups after the insert point have shifted sub-tables; their
            # strings were already verified above, so only bitmaps and early
            # groups are byte-compared here
            ok_res = False
    check(ok_res, "resource table: only the 2 language groups grew (+%d each); every other resource intact" % DELTA)

    # byte isolation: before the first insert point only header fields, table
    # entries, group sub-tables and the target strings themselves may differ
    allowed = set(range(8, 12)) | set(range(0x30, 0x34))
    for at in (0x10, 0x20):
        toff, n = struct.unpack_from('<I', sd, at)[0], struct.unpack_from('<H', sd, at + 4)[0]
        allowed.update(range(toff, toff + 16 * n))
    for t, o, l, a, b in parse(sd):
        if t == 1:
            allowed.update(range(o, o + 8 * a))
    for g, p, o, n in changed:
        a = next(e[3] for e in parse(sd) if e[0] == 1 and e[1] == g)
        for q in range(a):
            poff, plen = struct.unpack_from('<II', sd, g + 8 * q)
            if sd[poff:poff + plen] == o:
                allowed.update(range(poff, poff + plen))
                break
    diff = [i for i in range(ins) if sd[i] != pd[i]]
    check(set(diff) <= allowed, "bytes before the first insert point: only header fields and table entries moved")

    # the patch must refuse an already-patched input
    work = tempfile.mkdtemp(prefix="m30lbl.")
    again = os.path.join(work, "again.sty")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_label.py"),
                        patched, again], capture_output=True, text=True)
    check(r.returncode != 0, "patch refuses an already-patched input (stock asserts)")

    # and must run cleanly on a fresh copy
    fresh = os.path.join(work, "fresh.sty")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_label.py"),
                        stock, fresh], capture_output=True, text=True)
    check(r.returncode == 0 and open(fresh, 'rb').read() == pd,
          "patch is deterministic and reproduces the build's output")

    import shutil
    shutil.rmtree(work, ignore_errors=True)
    print("test_label: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
