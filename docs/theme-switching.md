# Theme switching: repainting the M30 UI bitmaps

`tools/theme/` reads, lists and repaints the `.sty` theme resources inside the firmware's
`FWIMAGE.FW`.  `build.sh --theme DIR` applies a theme to a build.  This explains the
format, what a repaint may and may not change, and how to edit real art.

## What a theme is

A theme is a directory of binary PPM images (`P6`, 8 bits per channel, no alpha), one per
bitmap you want to change, named

```
<sty-stem>_<bitmap-index>.ppm
```

where `<sty-stem>` is the `.sty` file name without its extension and `<bitmap-index>` is
the index `sty.py list` prints.  PPM is used because it needs no imaging library: any tool
that writes PPM works, and GIMP, ImageMagick and `pnmtopng` all convert to and from it.

## The `.sty` container

All fields little-endian, firmware images unpacked from `FWIMAGE.FW`:

```
0x00  "RU3" + 0x19 magic
0x04  u32  slot count        bitmaps + string groups: never the entry count
0x08  u32  content length
0x0c  "V100"
0x10  u32  table 1 offset   0x14 u16 n1   0x16 u16 sentinel
0x20  u32  table 2 offset   0x24 u16 n2   0x26 u16 sentinel
0x30  u32  offset of the trailing <ResDescriptor> XML
```

Both tables hold 16-byte entries of `{u32 offset, u32 length, u16 type, u16 a, u32 b}`:

| type | meaning | `a` | `b` | length |
|---|---|---|---|---|
| 2 | raw 16bpp RGB565 bitmap | width | height | `width * height * 2`, always |
| 1 | language/string group | entry count of its sub-table | entry index | varies |

Table 1 holds the bitmaps, table 2 the string groups.  `browser.sty` and `setting.sty`
have `n1 == 0` — no bitmaps, only string groups — so they cannot be repainted.

Two traps worth knowing before writing a parser:

- The u32 at `0x04` is **not** the entry count.  It equals
  `n1 + the number of distinct string names in the XML block`, which is why it reads 13
  for `browser.sty` (13 strings, no bitmaps) and 221 for `setting.sty`.
- The offsets at the head of table 2 do not continue table 1's data run, so walking entries
  while "each offset equals the previous entry's end" stops early.  Read `n1` at `0x14` and
  `n2` at `0x24` instead.

## The screen

320x240 RGB565, no alpha channel.  285 bitmaps across the ten `.sty` files that have them.
Every UI surface is an uncompressed raw bitmap, so a repaint is a plain byte copy.

Where the art lives (from `docs/theme-gallery.html`, confirmed by `sty.py list`):

| file | notable slots |
|---|---|
| `config.sty` | bitmap 0, 320x240 boot/settings backdrop; six 145x180 frames |
| `common.sty` | bitmap 26 and 122, 320x240 list backgrounds; 80 and 130-136, 310x29 bars (top bar, selection, scroll track, volume track); status-bar icons; digits; 320x240 volume popup |
| `mainmenu.sty` | bitmaps 0 and 2-7, 320x211 and 320x150 frames; bitmap 1, 320x29 top bar; an unused orange 320x176 frame |
| `music.sty` | 150x150 art placeholder, transport buttons, 231x6 progress track and fill, info icons |
| `playlist.sty` | 320x53 and 320x3 bars, 160x24 and 50x24 glyphs |
| `udisk.sty`, `upgrade.sty`, `usound.sty` | 28x24, 16x16 and 30x30 icons and media art |

## What a repaint changes, and what it must not

A repaint rewrites **only the pixel bytes of the `type == 2` entries you name**:

- every table entry, the magic, the slot count at `0x04`, the content length at `0x08` and
  the XML block stay byte-identical;
- the file length is unchanged, so the image still fits the `FWIMAGE.FW` slot that
  `tools/repack_fw.py` requires — `repack_fw.py` rejects a resize with
  `resizing not supported`, so a repaint can never silently produce a corrupt image;
- nothing the `.sty` loader walks is touched, so there is no way to desynchronise the
  table from the data.

Consequences: a repaint recolours art.  It cannot move art, add art, change a bitmap's
size, or reskin the type 1 string groups.

## Usage

```sh
# what is in a .sty file
python3 -I tools/theme/sty.py list build/work/stock/fw/common.sty

# write every bitmap to PPM, to edit the real art
python3 -I tools/theme/sty.py dump build/work/stock/fw/common.sty /tmp/common-art

# apply a theme dir to a build
ATJBOOTTOOL=../rockbox/utils/atj2137/atjboottool/atjboottool \
  ./build.sh --theme ../themes/example ../firmware/MECHEN_M30.HEX
```

`build.sh` walks every `.sty` in the unpacked stock firmware, repaints the bitmaps your
theme names, and adds only the files that actually changed to the `PATCHED` list — so
`build.sh`'s existing verify step (re-unpack, re-check every checksum, and assert that
exactly the listed files differ from stock) covers a theme exactly as it covers a code
patch.  A theme that touches nothing still builds the unmodified firmware.

A small worked example lives in `tools/theme/make_example_theme.py`:

```sh
python3 -I tools/theme/make_example_theme.py /tmp/my-theme
```

It writes eight flat single-colour bitmaps — the two 320x240 backdrops, the list top bar,
the selection and scroll bars, the main-menu top bar and the playlist rule — in the accent
colours at the top of that file.  Change them, or `sty.py dump` real art and edit that
instead.

## Round-trip guarantee

`sty.py dump` followed by `sty.py apply` of the dump directory reproduces every `.sty`
byte for byte, for all 285 bitmaps in all ten files that carry them.  This was run against
the stock firmware; it is what pins the RGB565 to 8-bit-per-channel PPM conversion, which
round-trips losslessly by rounding to nearest rather than truncating.

Loading a theme whose image dimensions do not match its slot is an error that stops the
build before anything is written, as is a malformed PPM or a file that is not a `.sty`.

## Limitations

- Text drawn by the firmware is white, so a *light* theme needs the text colour changed in
  code as well as the bitmaps repainted (`docs/theme-gallery.html`).
- Labels the main menu bakes into its 320x211 frames cannot be changed by a repaint; they
  are part of the bitmap.
- Adding whole new `.sty` files — for instance to actually ship the `cm_green.sty`,
  `cm_gray.sty`, `cm_pink.sty`, `cm_red.sty`, `setgreen.sty`, `set_gray.sty`, `set_pink.sty`
  and `set_red.sty` that the apps already name but that were never shipped — needs
  `tools/repack_fw.py` to grow the `FWIMAGE.FW` payload.  The payload is fully packed (the
  last directory entry ends exactly at the `FWIMAGE.FW` size), so that is a repacker change,
  not a theme change, and is out of scope here.
- A repaint cannot be verified against real hardware from this workspace; the checks that
  pass are the firmware's own per-file checksums, re-computed on unpack, plus the existing
  QEMU suite.  Nothing here flashes a player.
