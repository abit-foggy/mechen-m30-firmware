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

## Latest verified call graph

Two chains, both anchored at module headers, neither linear from a bank base.

```text
browser.ap header +0x40 = 0x40014C31
  → browser.ap:0x40014C30                      entry, bank 0x40014c00, size 0xcc
      syscall(module 0x10, fn 0x10)  [0x40014CC0]
      kernel (module 0x0f, fn 0x33)  [0x40014CC8]
      struct {fn=0x40014C00, $a0, 4($a1), lhu 2($a1)}
      kernel(module 0x0f, fn 0x4A) with $a0 = &struct   ← CALLBACK REGISTRATION
      cleanup: syscall(0x10, 0x11), kernel(0x0f, 0x34)
  → browser.ap:0x40014C00                       the registered callback
      → browser.ap:0x40055174                   bank 0x40054c00, +0x574 EVENT LOOP
          *[0x9fc154dc] = arg   [state byte]
          jal 0x40054C40 ; jal 0x40054DD0 → u16
          loop on *[0x9fc154d4]                 [flag byte]
            flag 1 → 0xBFC16578                 resident, +0x178
                       state = *[0x9fc154dc]; 1/9/10 special, else →
                       0xBFC164B4               resident, +0xb4  PATH BUILDER
                         0x7805b400(':') ; 0x7805b400('/', *0xbfc166fc)
                         0x780db200(...) ; 0x780db200('/', *0xbfc1670c)
            flag 2 → browser.ap:0x4009508C      bank 0x40094c00, +0x48c
                       descriptor {1,3,0,0,0}, code 0x6002
                       → browser.ap:0x40C14C00  bank 0x40c14c00, +0x0
                         ✦ body NOT TRUSTWORTHY — an indirect call resolves to
                           the ASCII at +0x280 ("AHEH"), so one linear pass
                           cannot distinguish a mis-resolved operand from a
                           bogus call. Bounded here deliberately.

mengine.ap bank 0x7a052d00, dispatch table at +0x3a8
  [0] 0x7b06856c   bank 0x7b068000   get_location   ← record→file
  [1] 0x7b228118   bank 0x7b228000   state reader   ← layout cross-check
  [2] 0x7b1283ac   bank 0x7b128000
  [3] 0x7b0685f4   bank 0x7b068000
  [4] 0x7b2281b8   bank 0x7b228000

  → mengine.ap:0x7b06856c   get_location($a0 = record, $a1 = byte)
      record->4 = *[0x9fc15f28]
      fs(module 0x11, fn 3)(*[0x9fc15f34], record+0x10, record+8, 0, 3)
        stub 0xbfc11ccc = 'li $v1,0x11 ; break' — VERIFIED in the resident
      on success fills record+0, +1, +0x5C, +0x5E from the state block
      returns 1; 0 otherwise

  → mengine.ap:0x7A052E34   the driver that USES the table
      *[0x9fc15f21] = 0
      index = *[0x9fc15f20]          ← a RAM byte selects the handler
      call table_base 0x7A0530B4 [index], passing the caller's own arguments
```

Full detail, including every pool offset and the corrections, in
[reverse-engineering.md](reverse-engineering.md).

## Completed implementations

- **Host chain, complete and tested**: `M3U.LIB` → 10 records → 10 playlists →
  **615 ordered tracks**, order and duplicates preserved, deterministic.
  `tools/m3u/m3u.c` (reader, 576 B MIPS16e), `m3udb.c` (adapter, 496 B),
  `m3uw.c` (writer, 808 B — kept, not needed for this feature).
- **Firmware findings pinned by a regression test**: `tools/fw/test_m3uengine.py`
  re-derives the dispatch table, the cross-validated descriptor layout and the
  filesystem stub from the unpacked component.

## Known false leads — do not resume

- `0x9FC15436` byte scans: the eight "readers" were pool words holding the
  address literal, not instructions.
- The genre-name table at `music.ap +0x1a965` misread as a menu dispatcher.
- `0xBFC16BB5` / `0xbfc16a25` read as traps: they are **syscall stubs**.
- The playlist.ap mask table transferred to music.ap: absent there.
- The 16-byte location field's meaning as an exFAT directory entry.
- `0x40C14C00`'s body, which a single linear pass cannot decode.

## Exact remaining blockers

1. **`get_location`'s filesystem argument order.** Which of `*[0x9fc15f34]`,
   `record+0x10` and `record+8` is the input record and which is the output
   buffer. Getting it backwards would corrupt the record in place, so the
   adapter is deliberately unwritten.
2. **Module 0x11 function 3's semantics**, and buffer ownership.
3. **The playback entry point.** Entries 2 and 4 of the table are untraced.
4. **Which mode byte at `0x9FC15F20` selects which handler** — needs its writer.

## Next actionable steps

1. **Settle the argument order from a caller's view.** Find who calls
   `0x7b06856c` through the driver, i.e. who sets `*[0x9fc15f20]` to select it
   and what it puts in `record+0x10` and `record+8`. That is one RAM address to
   trace, not a bank to search — the same discipline that produced every
   verified edge above.
2. **Entries 2 and 4** (`0x7b1283ac`, `0x7b2281b8`) for the playback path.
3. Then the adapter: `m3udb` record → `get_location` → `m3u` reader → list.

## Tests

`test_m3u` 18, `test_m3uw` 26, `exttest` 52, `test_m3fs`, `test_m3udb`,
`test_m3uengine`, `fw007test` — **all pass**. `test_m3udb`'s card
path-resolution check reports **NOTE/SKIPPED**, not a pass, because the SD card
is unmounted.

## Latest commits

`fc401e6` engine regression test · `062408b` runtime dispatch driver ·
`5ed836d` cross-validated descriptor layout · `d87876c` engine dispatch table +
`get_location` · `a19bddc` browser chain bounded · `4f4a3b9` browser chain.

Working tree clean apart from the user's pre-existing theme work (`README.md`,
`build.sh`, `docs/theme-switching.md`, `tools/theme/`), untouched. Nothing
pushed. No `MECHEN_M30.HEX` built.

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
