#!/usr/bin/env python3
"""Test the Information-screen label patch (patch_label.py) on the stock setting.sty.

usage: test_label.py STOCK_setting.sty PATCHED_setting.sty

Checks, against the real stock file:
  1. the patch tool ran cleanly and the file size, content length, XML offset,
     magic and slot count are all unchanged (pure in-place swap);
  2. every string containing a "Modify time" label (all language groups that use
     the English label - the player UI is English) changed to the space-padded
     "Build ID:" label, and NOTHING else changed anywhere in the file;
  3. each patched string keeps its three [%s] rows and decodes cleanly;
  4. the .sty parser (tools/theme/sty.py) still accepts the patched image;
  5. running the patch on the already-patched output fails (stock asserts);
  6. byte isolation: only the matched label spans differ from stock.

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

OLDS = ['Modify time:', 'Modify time ']
NEW = 'Build ID:'.ljust(12)
OLD_B = [s.encode('utf-16-le') for s in OLDS]
NEW_B = NEW.encode('utf-16-le')


def strings_of(d):
    """[(group_eoff, pair, offset, bytes)] for every string of every type-1 resource."""
    out = []
    for i, (t, off, ln, a, b) in enumerate(parse(d)):
        if t != 1:
            continue
        for p in range(a):
            poff, plen = struct.unpack_from('<II', d, off + 8 * p)
            out.append((off, p, poff, d[poff:poff + plen]))
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
    check(struct.unpack_from('<I', pd, 8)[0] == struct.unpack_from('<I', sd, 8)[0],
          "content length unchanged")
    check(struct.unpack_from('<I', pd, 0x30)[0] == struct.unpack_from('<I', sd, 0x30)[0],
          "XML offset unchanged")
    check(pd[:4] == b'RU3\x19' and pd[0x0c:0x10] == b'V100', "magic/version intact")
    check(struct.unpack_from('<I', pd, 4)[0] == struct.unpack_from('<I', sd, 4)[0],
          "slot count unchanged")

    ss = strings_of(sd)
    n_targets = sum(1 for g, p, o, s in ss if any(ob in s for ob in OLD_B))
    check(n_targets >= 20, "found the Modify-time labels in the stock file (%d language copies)" % n_targets)

    ps = strings_of(pd)
    check(len(ss) == len(ps), "same number of strings (%d)" % len(ss))
    changed = [(g, p, o, s, n) for (g, p, o, s), (g2, p2, o2, n) in zip(ss, ps) if s != n]
    check(len(changed) == n_targets, "exactly the %d Modify-time labels changed" % n_targets)
    ok_labels = all(
        any(s.replace(ob, NEW_B) == n for ob in OLD_B) for g, p, o, s, n in changed)
    check(ok_labels, 'every change is Modify time: -> space-padded "Build ID:"')
    check(all(n.decode('utf-16-le').count('[%s]') == s.decode('utf-16-le').count('[%s]')
              for g, p, o, s, n in changed),
          "each patched string keeps its [%s] rows")
    check(any('Software version' in n.decode('utf-16-le') for g, p, o, s, n in changed),
          "the English group (player UI) is among them: %r" %
          next(n.decode('utf-16-le') for g, p, o, s, n in changed if 'Software version' in n.decode('utf-16-le')))

    # byte isolation: only the label spans differ
    allowed = set()
    for g, p, o, s, n in changed:
        for ob in OLD_B:
            i = s.find(ob)
            if i >= 0:
                allowed.update(range(o + i, o + i + len(NEW_B)))
    diff = [i for i in range(len(sd)) if sd[i] != pd[i]]
    check(set(diff) <= allowed, "only the label spans differ from stock (%d bytes)" % len(diff))

    # the patch must refuse an already-patched input
    work = tempfile.mkdtemp(prefix="m30lbl.")
    again = os.path.join(work, "again.sty")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_label.py"),
                        patched, again], capture_output=True, text=True)
    check(r.returncode != 0, "patch refuses an already-patched input (stock asserts)")

    # and must run cleanly on a fresh copy, deterministically
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
