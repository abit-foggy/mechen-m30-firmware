# Theme switching: repainting the M30 UI bitmaps

`tools/theme/` reads, lists and repaints the `.sty` theme resources inside the firmware's
`FWIMAGE.FW`.  `build.sh --theme DIR` applies a theme to a build.  This explains the
format, what a repaint may and may not change, and how to edit real art.

For the experimental SD pack format and Settings picker design, see [SD themes](sd-themes.md).

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
Bitmap slots hold uncompressed pixel data. Layout records, localized strings and app-drawn content also contribute to the final screen.

Where the art lives (from `docs/theme-gallery.html`, confirmed by `sty.py list`):

| file | notable slots |
|---|---|
| `config.sty` | bitmap 0, 320x240 dark backdrop; six 145x180 charging-battery frames |
| `common.sty` | bitmap 26 and 122, 320x240 list backgrounds; 80 and 130-136, 310x29 bars (top bar, selection, scroll track, volume track); status-bar icons; digits; 320x240 volume popup |
| `mainmenu.sty` | red dial frames 0, 15, 19, 21–23; orange alternate 20; EQ graphs 2–9; top bar 1 |
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
- The red main-menu dial frames show icons without item names. The separate item-name draw path still needs tracing. Some other assets do contain lettering, including the power-off and USB graphics.
- Adding whole new `.sty` files — for instance to actually ship the `cm_green.sty`,
  `cm_gray.sty`, `cm_pink.sty`, `cm_red.sty`, `setgreen.sty`, `set_gray.sty`, `set_pink.sty`
  and `set_red.sty` that the apps already name but that were never shipped — needs
  `tools/repack_fw.py` to grow the `FWIMAGE.FW` payload.  The payload is fully packed (the
  last directory entry ends exactly at the `FWIMAGE.FW` size), so that is a repacker change,
  not a theme change, and is out of scope here.
- A repaint cannot be verified against real hardware from this workspace; the checks that
  pass are the firmware's own per-file checksums, re-computed on unpack, plus the existing
  QEMU suite.  Nothing here flashes a player.

## Stock theme atlas

Generate the standalone HTML atlas with Python and Pillow after unpacking the firmware.

```sh
python3 tools/theme/atlas.py build/work/stock/fw build/m30-theme-atlas.html
```

The atlas indexes all 12 stock containers, shows the 285 bitmap slots, lists localized
string keys, and links each bitmap to any frame references in the 68 PictureBox records.
Each section includes the SHA-256 of the input so offsets can be tied to a particular build.

### Layout evidence

In these files the little-endian word at 0x08 points to a second header beginning with
`sty\0`, after the XML. In that header, +8 points to a directory of offset/count
pairs and +12 holds height then width (two u16s). Directory entry 1 indexes
32-byte PictureBox records. At record +2 and +4 are local x and y, at +7 the
frame count and at +8 the u16 bitmap IDs. The first word and byte at +6 are
shown raw. The PD196 reference project's compiled music.sty and music.ui agree
on all 13 picture positions after subtracting the editor origin (80, 10).
The M30 has its own widget order and frame IDs.

For example, stock music.sty record 2 at 0x506d0 places album-art placeholder
slot 0 at (0, 28). Record 4 at 0x50710 places the play, pause, forward and back
images at (15, 197), in slot order 30, 29, 8, 7. Those coordinates describe the
style records. App overrides, clipping and state transitions need runtime validation.

### Now Playing

The stock music scene list at 0x508d8 contains 19 widget references. The
separate list at 0x50924 contains just two text boxes, 0x2006 and 0x2007.
Use scene membership when deciding which records to edit. The stock image
hash appears in the music section of the atlas.

| Widget ID | Stock role and evidence | Local rectangle (x, y, width, height) |
|---|---|---|
| 0x2000 | Album-art region, coincides with PictureBox 2 and matches the PD196 hidden-region convention | 0, 28, 150, 150 |
| 0x2001–0x2004 | Four metadata rows aligned with the track, person, disc and book icons. The icons suggest the first three are title, artist and album. The fourth field's data source is open. | x 190, y 40 / 75 / 111 / 147, each 129 × 20 |
| 0x2005 | Top-row text with EQ backdrop slot 6 | 149, 3, 90, 20 |
| 0x3000 | Track count, digit base 18 and slash slot 36 | 45, 181, 70, 12 |
| 0x4000 / 0x4001 | Left and right timers, digit base 18 and colon slot 5. Elapsed/total binding needs runtime confirmation. | 70 / 235, 202, each 64 × 12 |
| 0x5000 | Playback progress, background and track reference slot 17, filled and unfilled strips 31 and 32 | 70, 220, length 231, track height 6 |
| 0x2006 / 0x2007 | Secondary-scene text; runtime trigger open | 0, 51, 150, 128 / 151, 157, 168, 20 |

Directory entries 2–5 hold 20-byte TextBox, 28-byte numBox, 36-byte timeBox
and 36-byte ProgressBar records respectively. Text bounds occupy four u16
words at +2 through +8 (coordinates signed). Backdrop coordinates are at
+10 and +12. Foreground RGB565 is at +16. All four metadata rows use white
(0xffff), share backdrop slot 10 and carry flags 0x0027. A theme moving a row
should account for its backdrop and the separate icon. Number and timer
bounds start at +0. Progress uses its background origin at +2/+4, length at
+28 and separate strip graphics. Effective fill direction, scrolling and
clipping still require observing the renderer.

### Remaining coverage

| Surface | Evidence to collect next |
|---|---|
| Song title, artist and album text | Trace the metadata values to widget IDs; verify alignment, scrolling and clipping on a long title. |
| Time, track count and progress | Verify the left/right timer values and capture the fill direction at the start, middle and end of playback. |
| Folder lists, settings, dialogs and focus | Trace shared common.sty widget IDs through browser.ap and setting.ap; distinguish shared controls from per-screen overrides. |
| Fonts and light themes | Identify which draw calls select new_m.fnt and which foreground colours come from style fields or code. |
| Home screen, EQ and overlays | Match the selected menu entry, EQ preset, charging level and volume to each observed frame. |
| Theme switching | Trace the settings selection to the resource loader and verify persistence before exposing runtime theme selection. Existing --theme applies art at build time. |
