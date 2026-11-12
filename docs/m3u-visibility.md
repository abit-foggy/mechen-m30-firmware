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

## The browser has its own array, and it has room

`browser.ap` carries a second, *different* extension array at file `+0xc188`,
and it is not a copy of the driver's:

| Difference | Driver's array | browser.ap's array |
|---|---|---|
| Entries | 28 | 31 |
| Video | — | adds `WMV`, `AMV` |
| Ordering | `MP3 WMA WAV AAC FLAC APE …` | `MP3 WMA APE FLA OGG AAC AAX M4A AA …` |
| Wildcards | `**`, `*f`, three spaces | `**`, `*f`, `*d` |
| Followed by | 504 bytes of zeros, then an 8-byte in-use MIPS16e stub at the end of the bank | 252 bytes of zeros — **63 free slots**, nothing after them |

`music.ap` carries a third, audio-only array of nine slots (`MP3 WMA APE FLA OGG
AAC AAX M4A AA`).

None of the three contains `M3U`, so none of them can select one. But the
browser's array is in a module our build already patches (`build.sh` rewrites
its read limits), and the 63 free slots that follow it are genuinely free: an
appended slot moves no existing index and collides with nothing.

## There is no `M3U` slot

No array anywhere in the image has an `M3U` slot, and no driver contains the
string `M3U` at all, so **no mask value can select one**. That is the whole
blocker: the library type exists, the list view exists, and the enumeration
cannot return the files.

## Neither shipped release ever added one

Comparing stock against community V1.101.11:

- the arrays in both drivers are byte-identical;
- the mask table in `playlist.ap` is byte-identical;
- `M3U` appears in neither driver.

`M30-FW-007`, the only playlist change the community release made, is the
CRLF/LF line-ending fix isolated in `docs/firmware-m3u-fw007.md` — a fix to the
existing parser, not a change to what the browser enumerates.

## The filter is a category byte, not a bitmask

> **Correction (later in the same investigation).** The location arithmetic
> transcribed in `tools/fw/m3ufs.c` came from routines at `0x7805b264` and
> `0x7805b2dc` that **nothing in the image references**. The bank they live in
> is a shared library bank declared by six modules, its entry is `0x7805b200`,
> and the only call inside it is `jal loc_7805B200`. Treating that arithmetic
> as "how the firmware opens a playlist" was never justified, and
> `tools/fw/m3ufs.h` now says so. See `docs/m3u-integration.md`.

A correction to the section above, from disassembling browser.ap's resident bank
(guest `0xbfc16400`, file `0xc00`–`0x1234`). The enumeration filter is **not**
the 32-bit word at `playlist.ap 0x2a20`. That word is stored into a struct field
at `0xbfc1673a` and never has its bits tested in the function that loads it.

What actually decides enumeration is a walker at guest `0xbfc168a0`:

```
0xbfc168a2  lw   $a0, [0x9fc15574]      ; file count
0xbfc168ac  lw   $s0, [0x9fc15584]      ; node array base (a RAM pointer)
0xbfc168b2  sll  $a2, $v0, 4            ; node stride is 16 bytes
0xbfc168b6  lbu  $a1, 1($s0)            ; node+1 = type, must be 1
0xbfc168c6  lbu  $v1, 5($s0)            ; node+5 = category
0xbfc168c8  lbu  $a1, 0($a2)            ; the active filter
0xbfc168ca  xor  $a1, $v1               ; node passes if equal...
0xbfc168ce  cmpi $v1, 0xFF              ; ...or if category is 0xFF
0xbfc168d0  btnez                       ;   0xFF = matches any filter
0xbfc16912  lw   $v0, 0xC($s0)          ; node+12 = per-node callback
0xbfc16914  jalrc $v0                   ; invoked per passing node
```

So the answers to Phase 3's questions 1–3 are: the mapping is **not** a 32-bit
mask; `0xFF` is the wildcard; and the walker count comes from a RAM global, so
there is no fixed table length in the image. The node array itself is built at
runtime, which is why nothing in the firmware image references the extension
arrays by absolute address.

One decoding trap worth recording: `0xbfc16a25`, which five call sites load as a
pointer, is **not a routine**. It is the second byte of `li $v1,15 ; break` at
`0xbfc16a24`, the sixth entry of an eight-entry trap table at
`0xbfc16a10`–`0xbfc16a30`. Those loads are error paths, and treating
`0xbfc16a25` as a call target is what made the call graph unresolvable.

## What a fix must therefore do, and the open risk

Adding a slot is the only route, and it must be **additive**: append after the
wildcards, because inserting anywhere else shifts every later index and the
masks are index-based. Two constraints on *where* the append is safe:

- in the drivers, the zero run after the terminator does **not** reach the end
  of the bank. Its last 8 bytes hold `10 6b 05 e8 0f 6b 05 e8`, a small
  MIPS16e stub pair that is already in use, whose function is undetermined. An
  append that assumed "zeros to the end of the segment" would land on it. The
  run itself has 504 bytes (126 slots) in `fat_32n.drv` and 384 bytes (96) in
  `exfatn.drv`.
- in `browser.ap` the run is 252 bytes (63 slots) with nothing after it, which
  is the cleanest place to put one.

The unresolved question is the one the wildcards create. The three arrays close
with `**`, `*f` and a third slot — three spaces in the drivers, `*d` in
`browser.ap` — and they are matched as whole words. So they look like the
catch-all categories ("everything", "file", and either "directory" or a
placeholder) that a walker consults when no real extension matched. Whether a
walker consults them *before* an appended slot — which is what an append after
them would require — is not answerable from the image alone. Neither is the
bit-to-slot order of the masks: `MUSIC.LIB`'s 14 set bits do not map onto the
audio slots under either endianness of slot numbering, so the mapping is not
"bit n is slot n" in any obvious direction.

Until either is settled, the position taken here is: the layout is pinned by a
test, the writer that makes playlists exists, and no byte of any extension
array is modified.

## Delivered alongside this

- `tools/m3u/m3uw.c` / `m3uw.h` — a bounded M3U writer, the reader's mirror
  image, with `tools/m3u/test_m3uw.py` (27 host tests, write-file-read-back
  round trips for both line endings). The stock engine reads playlists and
  nothing produced them; this closes that half.
- `tools/m3u/exttest.py` — the assertions above, so a later session cannot
  drift from the slot layout, the mask values, or the stub in the tail.
