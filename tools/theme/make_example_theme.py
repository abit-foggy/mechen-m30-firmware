"""Write a small example M30 theme that recolours the flat backgrounds and bars.

usage: make_example_theme.py OUTDIR

A theme is a folder of <sty>_<bitmap-index>.ppm images, indexed the way `sty.py list`
prints them.  Every image has to match its slot's dimensions exactly, because a repaint
lands in a fixed FWIMAGE.FW slot that tools/repack_fw.py cannot resize.  Only the flat,
single-colour bitmaps are touched here: the two 320x240 backdrops, the list top bar, the
selection and scroll bars, the main-menu top bar and the playlist separator.  Run
`sty.py dump` on a .sty file first if you would rather edit the real art instead.
"""
import os
import sys

BG = (24, 88, 62)        # backdrop and list background, a deep green
BAR = (200, 176, 44)     # bars, an amber accent

# (file, bitmap index, width, height) of the flat slots this example recolours
SLOTS = [
    ('config', 0, 320, 240),      # boot and settings backdrop
    ('common', 26, 320, 240),     # list background
    ('common', 80, 310, 29),      # list top bar
    ('common', 130, 310, 29),     # selection bar
    ('common', 131, 310, 29),     # scroll track
    ('common', 132, 310, 29),     # volume track
    ('mainmenu', 1, 320, 29),     # main menu top bar
    ('playlist', 1, 320, 3),      # playlist separator rule
]


def ppm(path, w, h, col):
    """Write a binary P6 PPM of w x h pixels, all of the colour col."""
    open(path, 'wb').write(b'P6\n%d %d\n255\n' % (w, h) + bytes(col) * (w * h))


def main(outdir):
    if not outdir:
        sys.exit(__doc__)
    os.makedirs(outdir, exist_ok=True)
    for name, i, w, h in SLOTS:
        ppm(os.path.join(outdir, '%s_%d.ppm' % (name, i)), w, h, BG if h != 29 or i == 1 else BAR)
    print('wrote %d flat bitmaps to %s' % (len(SLOTS), outdir))


if __name__ == '__main__':
    main(sys.argv[1])

