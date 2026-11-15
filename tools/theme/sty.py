"""Read, list, dump and repaint the M30 .sty theme resources.

usage:
  sty.py list  FILE.sty                 list every resource in a .sty image
  sty.py dump  FILE.sty OUTDIR          write every bitmap to OUTDIR/<stem>_<i>.ppm
  sty.py apply FILE.sty THEMEDIR OUT.sty
                                        repaint the bitmaps found in THEMEDIR

The .sty container, all fields little-endian, firmware images unpacked from FWIMAGE.FW:
  0x00 "RU3" + 0x19 magic       0x04 u32 slot count (bitmaps + strings: never the entry count)
  0x08 u32 content length       0x0c "V100"
  0x10 u32 table 1 offset       0x14 u16 n1   0x16 u16 sentinel
  0x20 u32 table 2 offset       0x24 u16 n2   0x26 u16 sentinel
  0x30 u32 offset of the trailing <ResDescriptor> XML
Table 1 holds the n1 bitmaps, table 2 the n2 language/string groups; both are 16-byte
entries of {u32 offset, u32 length, u16 type, u16 a, u32 b}:
  type 2: raw 16bpp RGB565 bitmap, a = width, b = height, length == width*height*2
  type 1: string group, a = number of u32 pairs in its sub-table, b = entry index
The screen is 320x240 RGB565 with no alpha (docs/theme-gallery.html).

A repaint rewrites only the pixel bytes of type 2 entries, so the file length, the
content length at 0x08, every table entry and the XML block stay byte-identical.  That
keeps the image the same size as its FWIMAGE.FW slot, which tools/repack_fw.py requires,
and avoids touching anything the loader walks.  Images are exchanged as binary PPM
(P6, 8 bits per channel), which needs no imaging library.
"""
import os
import struct
import sys

MAGIC = b'RU3\x19'
VERSION = b'V100'
ENTRY = 16


def parse(d):
    """Every (type, offset, length, a, b) entry of a .sty image, table 1 then table 2."""
    if d[:4] != MAGIC:
        raise SystemExit('not a RU3 .sty file')
    if d[0x0c:0x10] != VERSION:
        raise SystemExit('unexpected .sty version %r' % d[0x0c:0x10])
    out = []
    for at in (0x10, 0x20):
        off, n = struct.unpack_from('<I', d, at)[0], struct.unpack_from('<H', d, at + 4)[0]
        for i in range(n):
            o = off + i * ENTRY
            if o + ENTRY > len(d):
                raise SystemExit('sty: table at %#x entry %d runs past the end' % (off, i))
            eoff, elen = struct.unpack_from('<II', d, o)
            etype, a = struct.unpack_from('<HH', d, o + 8)
            b = struct.unpack_from('<I', d, o + 12)[0]
            if etype not in (1, 2):
                raise SystemExit('sty: unknown resource type %d at %#x' % (etype, o))
            if eoff + elen > len(d):
                raise SystemExit('sty: resource at %#x len %d runs past the end' % (eoff, elen))
            out.append((etype, eoff, elen, a, b))
    return out


def bitmaps(d):
    """(index, offset, length, width, height) of every type 2 bitmap, in table order."""
    return [(i, e[1], e[2], e[3], e[4]) for i, e in enumerate(parse(d)) if e[0] == 2]


def down(v8, bits):
    """8 bits per channel -> bits, rounding to nearest."""
    return (v8 * ((1 << bits) - 1) + 127) // 255


def up(v, bits):
    """bits -> 8 bits per channel, rounding to nearest.  up(down(v8, b), b) == v8."""
    return (v * 255 + (1 << (bits - 1)) - 1) // ((1 << bits) - 1)


def to_rgb565(px):
    """RGB565 words from 8-bit r,g,b triples (the order PPM P6 stores)."""
    out = []
    for i in range(0, len(px), 3):
        r, g, b = px[i], px[i + 1], px[i + 2]
        out.append((down(r, 5) << 11) | (down(g, 6) << 5) | down(b, 5))
    return out


def to_rgb888(words):
    """r,g,b triples from RGB565 words."""
    out = bytearray()
    for v in words:
        out.append(up((v >> 11) & 31, 5))
        out.append(up((v >> 5) & 63, 6))
        out.append(up(v & 31, 5))
    return bytes(out)


def read_ppm(path):
    """(width, height, bytes of r,g,b triples) from a binary P6 PPM."""
    d = open(path, 'rb').read()
    if d[:2] != b'P6':
        raise SystemExit('%s: not a binary PPM (P6)' % path)
    fields, p = [], 2
    while len(fields) < 3:
        while p < len(d) and d[p:p + 1].isspace():
            p += 1
        if d[p:p + 1] == b'#':
            while p < len(d) and d[p:p + 1] != b'\n':
                p += 1
            continue
        q = p
        while q < len(d) and not d[q:q + 1].isspace():
            q += 1
        fields.append(int(d[p:q]))
        p = q
    p += 1
    w, h, maxv = fields
    if maxv != 255:
        raise SystemExit('%s: maxval %d, expected 255' % (path, maxv))
    if p + w * h * 3 != len(d):
        raise SystemExit('%s: %d bytes of pixel data, expected %d' % (path, len(d) - p, w * h * 3))
    return w, h, d[p:]


def write_ppm(path, w, h, rgb):
    open(path, 'wb').write(b'P6\n%d %d\n255\n' % (w, h) + rgb)


def cmd_list(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    d = open(argv[0], 'rb').read()
    print('%s: %d bytes, content length %d, %d slots, %d bitmaps'
          % (argv[0], len(d), struct.unpack_from('<I', d, 8)[0],
             struct.unpack_from('<I', d, 4)[0], len(bitmaps(d))))
    print('  %3s %-6s %9s %9s  %s' % ('idx', 'type', 'offset', 'length', 'resource'))
    for i, (t, off, ln, a, b) in enumerate(parse(d)):
        if t == 2:
            if ln != a * b * 2:
                raise SystemExit('sty: bitmap %d len %d != %dx%dx2' % (i, ln, a, b))
            what = 'bitmap %dx%d' % (a, b)
        else:
            what = 'string group, %d entries, index %d' % (a, b)
        print('  %3d %-6s %9d %9d  %s' % (i, t, off, ln, what))


def cmd_dump(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    d = open(argv[0], 'rb').read()
    stem = os.path.splitext(os.path.basename(argv[0]))[0]
    os.makedirs(argv[1], exist_ok=True)
    n = 0
    for i, off, ln, w, h in bitmaps(d):
        write_ppm(os.path.join(argv[1], '%s_%d.ppm' % (stem, i)), w, h,
                  to_rgb888(struct.unpack('<%dH' % (ln // 2), d[off:off + ln])))
        n += 1
    print('dumped %d bitmaps from %s to %s' % (n, argv[0], argv[1]))


def cmd_apply(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    src, themedir, out = argv
    orig = open(src, 'rb').read()
    d = bytearray(orig)
    stem = os.path.splitext(os.path.basename(src))[0]
    bms = bitmaps(d)
    done, total = [], 0
    for i, off, ln, w, h in bms:
        path = os.path.join(themedir, '%s_%d.ppm' % (stem, i))
        if not os.path.exists(path):
            continue
        pw, ph, px = read_ppm(path)
        if (pw, ph) != (w, h):
            raise SystemExit('%s: %dx%d does not fit slot %d of %d bytes (%dx%d)'
                             % (path, pw, ph, i, ln, w, h))
        words = to_rgb565(px)
        if len(words) * 2 != ln:
            # repack_fw.py cannot resize a slot, so a short or long image is fatal
            raise SystemExit('%s: %d pixels fill %d bytes but the slot holds %d'
                             % (path, len(words), len(words) * 2, ln))
        d[off:off + ln] = struct.pack('<%dH' % len(words), *words)
        done.append(i)
        total += ln
    if not done:
        # a theme may target only some of the .sty files: that is not an error
        print('%s: nothing to repaint' % stem)
        return
    open(out, 'wb').write(d)
    ids = ','.join(str(i) for i in done)
    print('repainted %d of %d bitmaps in %s, %d bytes%s -> %s'
          % (len(done), len(bms), stem, total, ' (%s)' % ids if len(done) <= 8 else '', out))


COMMANDS = {'list': cmd_list, 'dump': cmd_dump, 'apply': cmd_apply}

if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](sys.argv[2:])
