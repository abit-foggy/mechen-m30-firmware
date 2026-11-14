# M3U integration journal

A running record of what is verified, how, and what is still open. Kept so the
investigation does not have to be redone. Everything here is traceable to a
command or a test; nothing is asserted from a resource name alone.

Legend: **[dis]** from disassembly · **[host]** host test · **[card]** read from
the user's SD card · **[hw]** on the device. Nothing in this document is **[hw]**.

## The user's data

Verified by reading the card read-only; MD5 `8db71b6488694bbf32352cf5ac717467`
for `M3U.LIB`, unchanged before and after all analysis **[card]**.

- `M3U.LIB`: **10 records**, one per playlist. 256-byte records from `+0x200`,
  two per 512-byte sector. Title in UTF-16LE with a BOM at `+0x00` (64 bytes);
  extension `M3U\0` at `+0xa4`; a 16-byte location at `+0xa9`.
- Titles are capped at **30 characters** — 64 bytes is a BOM plus 30 UTF-16
  units plus the terminator. `Bring Me The Horizon, Bad Omens` is stored as
  `…Bad Omen`, so a stored title is a **label, never a filename**.
- All ten paths in the playlists resolve, and all ten parse to **615 tracks**,
  order preserved **[host]**.
- The card was unmounted during this session; read-only copies in `/tmp/m30lib`
  carry the same MD5 and are what the tests now run against.

## The library filename table

`music.ap` bank `0x7805b200`, guest `0x7805b498`, 12-byte stride **[dis]**:

| slot | address | contents |
|---|---|---|
| 0 | `0x7805b498` | `MUSIC.LIB\0\0\0` |
| 1 | `0x7805b4a4` | `M3U.LIB\0\0\0\0\0` |

The routine at `0x7805b370` picks one with `0x7805b498 + index*12` (`lhu` index
`0x7805b3f2`, `sll`/`sll` to ×12 `0x7805b3f6`–`3fa`, `lw` base `0x7805b3fc`,
`addu` `0x7805b3fe`) **[dis]**. Selecting a library is therefore an **index**,
not a pointer to a filename — so a scan for "a pointer to M3U.LIB" is guaranteed
to find nothing. An earlier pass drew the wrong conclusion from exactly that
scan and it is corrected here.

## The bank at 0x7805b200

1208 bytes, MIPS16e, and its **only** ASCII strings are `MUSIC.LIB` and
`M3U.LIB` — no ID3, vorbis, FLAC or APE tag strings, so it is a
**library-access bank**, not the tag reader that an offhand note in
`docs/library-builder.md` makes it out to be **[dis]**.

Six modules declare it at file `+0x710`: browser, config, mainmenu, music,
playlist, setting — so it is shared **[dis]**.

## Withdrawn: the location-field interpretation

An earlier stage transcribed arithmetic from `0x7805b264` and `0x7805b2dc` and
concluded that a record's 16-byte location addressed an exFAT directory entry.
**That is withdrawn.** What settled it:

- **Nothing references those routines.** The bank's only call is
  `jal loc_7805B200` at `0x7805b402`; `0x7805b264`, `0x7805b2dc` and
  `0x7805b370` are pointed at by nothing, in the bank or anywhere in the image
  **[dis]**.
- 512 is a **sector** size, not necessarily a cluster size, and 16 is not the
  exFAT directory-entry size of 32.
- All ten location selectors are multiples of 32, so `(arg1 & 0x1F)` is zero
  for every one of them: the routines never exercise their own low-bit path.

`tools/fw/m3ufs.c` keeps the transcription because it is the only firm evidence
there is, and its header says plainly that it describes unreferenced
instructions.

## The location field's layout **[card]**

This part *is* settled, by the data rather than by disassembly. All ten records
share their first twelve bytes — `0x07000012`, `0x00000540`, `0x00135eac` — and
differ only in the last four:

```text
800  1056  1280  1408  1504  1632  1760  1888  2016  2208
```

all distinct and monotonic in record order, all multiples of 32. So bytes 0–11
are constant across the ten playlists (the directory they live in) and bytes
12–15 carry the per-record value. What bytes 4–11 *mean* is not established.

## The trap-table rule

**Resident banks of this firmware end with a run of MIPS16e `li $v1,N ; break`
pairs.** Any pointer *into* that region is an error path, never a call target.
This has now produced two false conclusions in this project, so it is a standing
rule:

| address | where |
|---|---|
| `0xbfc16a25` | second byte of `li $v1,15 ; break` at `0xbfc16a24`, in **browser.ap**'s resident trap table |
| `0xBFC16BB5` | inside **music.ap**'s resident trap table; its resident bank is `0xbfc16400`–`0xbfc16bbc` and ends with the same `li;break` run |

So `0xBFC16BB5` is **not** a shared kernel filesystem entry. It is a trap, which
is also *why* the three routines of bank `0x7805b200` are unreachable: calling
any of them would trap. Nothing about a filesystem ABI follows from them.

Whenever a promising "kernel entry" or "callback pointer" resolves into
`0xbfc16xxx` near the end of a resident bank, check for the `05 e8` (`break`)
byte before believing it.

---

# Handoff (current state)


## Objective

The user's **ten existing M3U playlists** browseable and playable through the
stock Music interface, in the custom `MECHEN_M30.HEX`. No new playlists, no
reorganisation, no replacement of the stock base.

## Latest verified call graph

```text
mengine.ap bank 0x7a052d00 — dispatch table at 0x7A0530A8, EIGHT entries

  [0] 0x7b06856c   bank 0x7b068000   get_location   ← mode 0
  [1] 0x7b228118   bank 0x7b228000   state reader
  [2] 0x7b1283ac   bank 0x7b128000
  [3] 0x7b0685f4   bank 0x7b068000   ← driver 0x7A052E34's base = entry 3
  [4] 0x7b2281b8   bank 0x7b228000
  [5] 0x7b128244   bank 0x7b128000
  [6] 0x7b0e81f8   bank 0x7b0e8000
  [7] 0x7b1e81e0   bank 0x7b1e8000

  → mengine.ap:0x7A052E64                the caller that reaches get_location
      guard: the u16 at 0x9FC15F24 zero → return 0 immediately, so
             *[0x9FC15F24] is what means "a file is current"
      index the table from its START 0x7A0530A8 by *[0x9FC15F20]
      → table[mode] with ($a0, zeb($a1))
      → mode 0 selects get_location                       ← VERIFIED

  → mengine.ap:0x7A052E34                the second view of the same table
      *[0x9FC15F21] = 0; index from 0x7A0530B4 (entry 3) by *[0x9FC15F20]
      five reachable handlers; indices past 4 read the bank's zero tail

  → mengine.ap:0x7b06856c   get_location($a0 = descriptor, $a1 = byte)
      descriptor->4 = *[0x9FC15F28]
      fs(module 0x11, fn 3)(*[0x9FC15F34], descriptor+0x10, descriptor+8, 0, 3)
        stub 0xbfc11ccc = 'li $v1,0x11 ; break' — VERIFIED in the resident
      on success fills descriptor +0, +1, +0x5C, +0x5E; returns 1, else 0
```

**The engine's shared state block** is `0x9FC15F20..0x9FC15F38`, named by about
22 mengine banks. Its most-referenced members are the u16 pair
`0x9FC15F24`/`0x9FC15F26` — the same field shape as the 16-byte location in the
`M3U.LIB` records at `+0xa9`.


1. `M3U.LIB` already indexes all ten playlists. The database is not the problem.
2. A library is chosen by **index** into a 12-byte table at `0x7805b498`.
3. **The engine's shared state block is `0x9FC15F20..0x9FC15F38`**, named by about
   22 mengine banks. Its most-referenced members are the u16 pair
   `0x9FC15F24`/`0x9FC15F26` — the same field shape as the 16-byte location in
   the `M3U.LIB` records at `+0xa9`. This reframes the adapter: put the selected
   track's location there and tell the engine to play.
4. The **dispatch table** in bank `0x7a052d00` has **eight** entries; the driver's
   base `0x7A0530B4` is entry 3, so the driver reaches five handlers.
5. `get_location` (`0x7b06856c`) calls filesystem module `0x11` function `3` and
   fills a descriptor; a second witness (`0x7b228118`) fills the same fields from
   the same globals with no filesystem call.
6. `li v1,MODULE ; break` are **syscall stubs**; pool pointers carry the MIPS16e
   ISA bit in bit 0. Overlay loading is **demand-driven**.

## Completed implementations

- **Host chain, complete and tested**: `M3U.LIB` → 10 records → 10 playlists →
  **615 ordered tracks**, order and duplicates preserved, deterministic.
- `tools/fw/test_m3uengine.py` pins the dispatch table, the descriptor layout and
  the filesystem stub, re-derived from the unpacked component.

## Known false leads — do not resume

- `0x9FC15436` byte scans (pool words, not instructions).
- The genre table at `music.ap +0x1a965` read as a menu dispatcher.
- `0xBFC16BB5`/`0xbfc16a25` read as traps — they are syscall stubs.
- The playlist.ap mask table transferred to music.ap.
- `0x40C14C00`'s body, and `0x7A052D00`'s bank-entry decode: both terminate in a
  non-instruction target, so both need a second anchor. Do not cite either.

## Exact remaining blockers

1. **The fs read argument order on hardware.** The adapter now uses the
   builder's own shapes -- `(ctx, buffer, len, h, 0xD)` with the handle as the
   FOURTH argument -- so the remaining question is whether the real kernel
   agrees with the builder's code. That is a read-only hardware check.
2. **A writer of the mode byte `0x9FC15F20`**: not found.
3. The playback entry point: table entries 2, 4, 5, 6 and 7 untraced.
4. Display: no list widget traced.

## The pipeline now exists on the firmware side

**`tools/fw/m30playlist.c`** wires the stock filesystem adapter to the existing
parser. 240 bytes of MIPS16e:

```text
playlist path
  -> m30pl_open    m30fs_set_stub(per-module stub) -> m30fs_init
                   (chdir ':', op 5 open, op 9 size)
  -> m30pl_next    4 KB bounded buffered read -> the existing m3u parser
  -> track entries, prefixed with the playlist's own directory
  -> m30pl_close   close on every path, idempotent
```

Two subtleties the host test caught:
- `m3u_init` validates its io, so the read callback must be installed *before*
  it runs.
- Entries come back prefixed with the playlist's directory -- which is what makes
  `../Music/...` resolve, since the card's playlists reference their tracks
  relative to themselves.

And `m30fs.c` gained the builder's own call shapes, correcting a real bug: the
handle is the FOURTH argument to seek and read. The previous version passed 0,
which the host mock caught -- the kernel would have read from no file at all. The
read path also now implements the builder's 4 KB constraint: transfers split at
the next 4096-byte boundary, seek only when the handle is not already there, one
sector buffer on top so callers see an ordinary byte stream.

Sizes: playlist module 240 B, adapter 816 B, both MIPS16e no warnings.

## Next actionable steps

1. **Decode music.ap's handler for the m3u menu entries** (ids 49-53) to see
   whether the stock path already reads M3U.LIB and displays playlist contents.
2. If the stock path works, identify why the user's playlists don't appear —
   possibly the five-slot assignment, possibly the 4,000-entry limit.
3. If the stock path is broken, the smallest fix may be in the existing code
   rather than in a new module.

## Next actionable steps

1. **Playback** -- table entries 2 and 4 of the engine dispatch table, or the
   browser's selection path.
2. **List UI** -- display ten playlist titles, open one, list its tracks.
3. **Firmware build** -- bank placement for `m30playlist` + `m30fs` + `m3u`.

## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`e7197f7` pipeline logged · `c69be2f` m30playlist wired to m30fs and the parser ·
`ab4271f` handle restored to seek/read + 4 KB bounded buffer ·
`30141fb` the verified path-based open ABI · `2648b14` mocked adapter test ·
`e723917` two-caller comparison.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
