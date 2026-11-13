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

# Handoff (current state)

## Objective

The user's **ten existing M3U playlists** browseable and playable through the
stock Music interface, in the custom `MECHEN_M30.HEX`. No new playlists, no
reorganisation, no replacement of the stock base.

## Latest verified findings

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

1. **The resolver ABI**: which of `*[0x9FC15F34]`, `record+0x10` and `record+8`
   is the input record and which is the output buffer. This is the only thing
   between the host chain and a firmware adapter.
2. **A writer of the state block** — no writer traced, so an adapter must not
   poke `0x9FC15F24`/`0x9FC15F26` directly.
3. The playback entry point; entries 2 and 4 of the table untraced.
4. Display: no list widget traced.

## Next actionable steps

1. **Find a caller of `get_location`.** Its pointer appears exactly once, in the
   table at `0x7a0530a8` — and that entry is *before* the driver's base, so the
   driver does not use it. Something else indexes from `0x7a0530a8`; finding that
   consumer gives the caller-side view that settles argument roles.
2. **Entries 2 and 4** (`0x7b1283ac`, `0x7b2281b8`) for playback.
3. Then the adapter.

## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`eb6cb25` shared state block · `5a3da6c` dispatch-table bounds ·
`fc401e6` engine regression test · `062408b` runtime dispatch driver ·
`5ed836d` cross-validated descriptor layout · `d87876c` engine dispatch table +
`get_location` · `a19bddc` browser chain bounded · `4f4a3b9` browser chain.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.
