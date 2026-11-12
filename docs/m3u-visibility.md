# `.m3u` visibility in the folder browser

This answers one question: what stops a user selecting a `.m3u` file from the
browser, and what would a fix have to look like. Every claim below is
re-derived from the unpacked image by `tools/m3u/exttest.py` rather than
recorded as an offset, so repacking cannot silently invalidate it.

## The firmware already has an M3U subsystem

The missing feature was not a playlist engine. The stock 2025-06-26 image
ships one, in three places:

| Where | What |
|---|---|
| `playlist.ap` | the `M3U` literal at `+0x16c8`, and `M3U.LIB` as a library type with its own builder (`FUN_40154ecc`) alongside `FUN_40055194` for `MUSIC.LIB` |
| `music.sty` | the `s_m3ulist_option1..5` scene strings, a dedicated M3U list view |
| `music.mcg` | five menu nodes named `m3u列表选择N` (`list select 1..5`), ids 49–53 |

So the parser, the list screen and the menu all exist. The gap is upstream of
them: how a file gets into the list the user sees.

## The browser filters by a bit mask, not by string comparison

`playlist.ap`'s mask table at file `0x2a20` holds one mask per library type:

| Offset | Value | Meaning |
|---|---|---|
| `0x2a20` | `0x7e190ea0` | `MUSIC.LIB`: 14 bits set |
| `0x2a24` | `0xbfc166c8` | a resident address between the two masks; not a MIPS16e pointer (its low bit is clear), function undetermined |
| `0x2a28` | `0x00080400` | `M3U.LIB`: 2 bits set |

Each bit selects one slot of the file system driver's extension array. The
folder views additionally OR in the literal `0x00400000`.

## The array is a fixed 4-byte slot array, not a string list

`fat_32n.drv` file `0x780` (guest `0xbfc17180`) and `exfatn.drv` file `0x7f8`
(guest `0xbfc171f8`); both drivers load their resident bank at `0xbfc16c00` and
are mutually exclusive, so there is one array whichever is resident. It is a
run of whole 4-byte slots holding NUL-padded uppercase text:

```
slot  ext    slot  ext     slot  ext    slot  ext
   0  MP3      8  JPG      16  ISO      24  BMK
   1  WMA      9  JPEG     17  AAX      25  AIF
   2  WAV     10  DSF      18  AA       26  APK
   3  AAC     11  DFF      19  MP1      27  PCM
   4  FLAC    12  LRC      20  MP2      28  **
   5  APE     13  ASF      21  M4A      29  *f
   6  AVI     14  OGG      22  POS      30  (three spaces)
   7  TXT     15  TTA      23  ACT      31  <zero slot, terminator>
```

`FLAC` and `JPEG` fill a whole slot with no room for a terminator, which is
why NUL-splitting the region yields the nonsense pairs `FLACAPE` and
`JPEGDSF` — the stride is what matters, and `tools/m3u_audit.py` already warns
about exactly this.

Slots 28–30 are the wildcards. They are matched as whole words, not as prefix
patterns, so `**` is a category of its own rather than "anything".

## There is no `M3U` slot

Neither driver contains the string `M3U` anywhere, and there is no slot for it,
so **no mask value can select one**. That is the whole blocker: the library
type exists, the list view exists, and the enumeration cannot return the files.

## Neither shipped release ever added one

Comparing stock against community V1.101.11:

- the arrays in both drivers are byte-identical;
- the mask table in `playlist.ap` is byte-identical;
- `M3U` appears in neither driver.

`M30-FW-007`, the only playlist change the community release made, is the
CRLF/LF line-ending fix isolated in `docs/firmware-m3u-fw007.md` — a fix to the
existing parser, not a change to what the browser enumerates.

## What a fix must therefore do, and the open risk

Adding a slot is the only route, and it must be **additive**: append after the
wildcards, because inserting anywhere else shifts every later index and the
masks are index-based. The zero run after the terminator has room — 504 bytes
(126 slots) in `fat_32n.drv`, 384 bytes (96 slots) in `exfatn.drv` — but it
does **not** run to the end of the bank:

> the last 8 bytes of both resident banks hold `10 6b 05 e8 0f 6b 05 e8`, a
> small MIPS16e stub pair that is already in use. Its function is undetermined,
> so an append that assumed "zeros to the end of the segment" would land on it.

The unresolved question is the one the wildcards create: slots 28–30 come
*before* an appended slot 31, and they are matched as whole words. Whether a
walker reaching `**` classifies every unmatched file — including an M3U one —
before it ever consults an appended slot is not answerable from the image
alone. Until it is, the safe position is the one taken here: the layout is
pinned by a test, the writer that makes playlists exists, and no byte of the
extension array is modified.

## Delivered alongside this

- `tools/m3u/m3uw.c` / `m3uw.h` — a bounded M3U writer, the reader's mirror
  image, with `tools/m3u/test_m3uw.py` (27 host tests, write-file-read-back
  round trips for both line endings). The stock engine reads playlists and
  nothing produced them; this closes that half.
- `tools/m3u/exttest.py` — the assertions above, so a later session cannot
  drift from the slot layout, the mask values, or the stub in the tail.
