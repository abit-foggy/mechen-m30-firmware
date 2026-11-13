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

## Completed and verified

**Host side, complete.** `tools/m3u/m3ulib.py` decodes `M3U.LIB` (10 records,
one per playlist, UTF-16LE titles, extension `M3U\0`);
`tools/m3u/m3udb.c` turns a record index into ordered tracks — verified against
read-only copies of the real card: **10 records → 615 tracks**, order and
duplicates preserved, deterministic. `tools/m3u/m3u.c` is the reader; 18 tests.
All cross-compile to MIPS16e warning-free.

**Firmware side, first real chain.** `music.ap`'s declared entry point is
`0x40014C30` (header `+0x40` = `0x40014C31`; the `+1` is the MIPS16e ISA bit).
It is initialisation: acquire with a module-`0x10` service, abort on failure,
register a structure with the kernel (module `0x0f`, function `0x33`). One call
path from it reaches `0x400552A0` → `0x40614FC0`, both decoded — see
[reverse-engineering.md](reverse-engineering.md).

## Latest verified findings

1. `M3U.LIB` already indexes all ten playlists. The database is not the problem.
2. A library is chosen by **index** into a 12-byte table at `0x7805b498`
   (`MUSIC.LIB` slot 0, `M3U.LIB` slot 1); `0x7805b370` computes
   `base + index*12`.
3. The location field's *layout* is known from the card — twelve constant bytes
   then a per-record u32 — its *meaning* is not.
4. `li v1,MODULE ; break` are **syscall stubs**; pool pointers carry the MIPS16e
   ISA bit in bit 0, so `0xBFC16BB1` is the kernel stub at `0xBFC16BB0`.
5. Overlay loading is **demand-driven** — a call into an unloaded bank raises an
   exception and the kernel loads and retries — so "no static references" is
   expected and proves nothing about reachability.
6. `0x40614FC0` dispatches **six service result codes**, not menu ids. No
   `0x802D` for All Songs, none of `0x8031`–`0x8035` for the `m3u` slots.
7. Bank contents differ per module at the same guest address; the documented
   mask table is playlist.ap-only and absent from music.ap's copy.

## Exact blockers

1. **The All Songs handler is not found.** The one chain recovered so far is
   status dispatch, not menu dispatch.
2. Consequently no record → file resolution, no playback entry point, no display
   surface.

## Next recommended step

**Stop following the `0x9FC15436` / `0x400552A0` / `0x40614FC0` path** — it is
compute-a-status-then-dispatch, its status slot has no established reader, and
the "eight references" that motivated it were a search artefact (a byte scan for
the address literal finds the literal in pools, not its uses).

Go to the folder browser instead, as the task brief allows. `browser.ap` is where
a user actually picks a file, so the selection callback there is the real
selection path, and it is reached from `browser.ap`'s own entry point (header
`+0x40`, same convention as music.ap's `0x40014C31` → `0x40014C30`). One command
gives it: parse `browser.ap`'s header `+0x40`, clear the ISA bit, disassemble
from that prologue, and follow.

Whatever that reaches, verify each edge by resolving instructions, not by
searching for address literals — the two errors above both came from the latter.

## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`fw007test` — all pass. `test_m3udb`'s card path-resolution check reports an
explicit **NOTE/SKIPPED** (not a pass) because the SD card is unmounted.

## Latest commits

`73d6c37` decode entry + `0x400552A0` + withdraw the mask over-claim ·
`5e624e0` verified chain + ISA-bit · `ff20624` API reference ·
`0c0c1ec` syscall-stub correction · `f49a234` dev log.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing pushed.
