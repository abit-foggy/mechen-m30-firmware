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

## The shared filesystem entry

`0xBFC16BB5`, called by `0x7805b264` and `0x7805b2dc` with op `0xB` to seek and
op `0xD` to read `0x200` bytes into guest `0x7805B4B0`, context from RAM global
`0x9fc15980` **[dis]**. It has on the order of 800 call sites across `music.ap`
and `playlist.ap`; classifying them by opcode is the next step rather than
reviewing them by hand.

## What is built

| File | What it is | Verified by |
|---|---|---|
| `tools/m3u/m3u.c`, `m3u.h` | bounded streaming M3U reader, 576 B MIPS16e | `test_m3u.py`, 18 checks |
| `tools/m3u/m3uw.c`, `m3uw.h` | bounded writer, 808 B, not needed for this feature | `test_m3uw.py`, 26 checks |
| `tools/m3u/m3udb.c`, `m3udb.h` | record index → ordered playlist, 496 B | `test_m3udb.py`, real card |
| `tools/m3u/m3ulib.py` | M3U.LIB decode + reference analysis | `check`, `refs` |
| `tools/fw/m3ufs.c`, `m3ufs.h` | the withdrawn transcription, 176 B | `test_m3ufs.py` |

The complete host-side chain works: `M3U.LIB` → 10 records → 10 playlists →
615 ordered tracks **[host]**. `m3udb` takes a sector reader and an
open-by-location callback, so the filesystem stays the caller's business; the
host test supplies the callback and says so.

## Open

1. **The live record-to-file ABI.** The `0x7805b200` routines are dead code, so
   the working path is elsewhere: how a `MUSIC.LIB` record becomes an open file
   (Stage B1). `MUSIC.LIB` records carry the same 16-byte location layout, so
   whatever consumes those is the ABI we need.
2. **Display.** No list widget or scene has been wired; the `s_m3ulist_*`
   resources and `music.mcg` ids 49–53 are unverified.
3. **Playback dispatch.** Unstarted.
4. **Firmware integration.** No module is patched and no `.HEX` exists.
