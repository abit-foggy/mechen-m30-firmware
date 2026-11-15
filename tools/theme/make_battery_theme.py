"""Write a battery-icon theme for the M30, replacing common.sty bitmaps 14 and 15.

usage: make_battery_theme.py [OUTDIR]

The battery is two 51x21 RGB565 bitmaps in common.sty, which the status bar picks
between by charge level:

  common_14  normal level   teal outline 0xf79e, green bar 0x07e0 from x=11 to x=40
  common_15  low power      teal outline 0xf79e, red bar 0xf800 from x=37 to x=40

Both bars are anchored at their right end and grow left as the battery charges; the
status-bar background is the dark grey 0x18c3 that fills the rest of both bitmaps.
RGB565 has no alpha, so replacement art has to carry that background itself or it
shows as a visible box, which is why this generator paints BG everywhere first.
"""
import os
import sys

W, H = 51, 21
BG = 0x18c3          # status-bar background
OUTLINE = 0xf79e     # stock teal outline and terminal
GOOD = 0x07e0        # green level bar
LOW = 0xf800         # red low-power bar

NUB_X0, NUB_X1 = 4, 10          # the positive terminal, left of the body
BODY_X0, BODY_X1 = 11, 45       # body outline
BODY_Y0, BODY_Y1 = 0, 20
BAR_X0, BAR_X1 = 13, 43         # where the level bar is drawn
BAR_Y0, BAR_Y1 = 5, 15
SEGS = 4                        # segmented level bar


def expand(v, shift, bits):
    """One RGB565 channel to 8 bits."""
    return ((v >> shift) & ((1 << bits) - 1)) * 255 // ((1 << bits) - 1)


def battery(fill, filled):
    """A battery: rectangular outline, left terminal, and `filled` of SEGS right-anchored segments."""
    g = [[BG] * W for _ in range(H)]
    for y in range(BAR_Y0, BAR_Y1):                      # the terminal, left of the body
        for x in range(NUB_X0, NUB_X1):
            g[y][x] = OUTLINE
    for x in range(BODY_X0, BODY_X1 + 1):                # top and bottom edges
        g[BODY_Y0][x] = OUTLINE
        g[BODY_Y1][x] = OUTLINE
    for y in range(BODY_Y0, BODY_Y1 + 1):                # left and right edges
        g[y][BODY_X0] = OUTLINE
        g[y][BODY_X1] = OUTLINE
    for x, y in ((BODY_X0, BODY_Y0), (BODY_X1, BODY_Y0),   # knock the corners off
                 (BODY_X0, BODY_Y1), (BODY_X1, BODY_Y1)):
        g[y][x] = BG
    seg = (BAR_X1 - BAR_X0 + 1) // SEGS - 1              # segments, anchored right
    for s in range(filled):
        x0 = BAR_X1 - (s + 1) * (seg + 1) + 1
        for y in range(BAR_Y0, BAR_Y1):
            for x in range(x0, x0 + seg):
                g[y][x] = fill
    return g


def write_ppm(path, g):
    out = bytearray(b'P6\n%d %d\n255\n' % (W, H))
    for y in range(H):
        for x in range(W):
            v = g[y][x]
            out += bytes((expand(v, 11, 5), expand(v, 5, 6), expand(v, 0, 5)))
    open(path, 'wb').write(out)


if __name__ == '__main__':
    outdir = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(outdir, exist_ok=True)
    write_ppm(os.path.join(outdir, 'common_14.ppm'), battery(GOOD, SEGS))   # full battery
    write_ppm(os.path.join(outdir, 'common_15.ppm'), battery(LOW, 1))       # low power
    print('wrote common_14.ppm and common_15.ppm (51x21) to %s' % outdir)
