# Development log

Chronological. Newest last. Every correction is kept; nothing is silently erased.

## M3U visibility investigation (sessions 1–2)

- Established the three extension arrays and that none has an `M3U` slot.
  `VERIFIED`. Pinned by `tools/m3u/exttest.py`.
- `docs/m3u-visibility.md` records the browser-array finding and 63 free slots.
- **Correction:** an early pass concluded the browser selects extension slots
  with a 32-bit bitmask. It does not — the walker filters on a per-node category
  byte. Corrected in `0cba810`.

## Portable M3U reader and writer

- `tools/m3u/m3u.c` — bounded streaming reader, 576 B MIPS16e, 18 host tests.
  Commit `d61b702`.
- `tools/m3u/m3uw.c` — bounded writer, 808 B, 26 tests incl. write→read round
  trips. Commit `6bfaf78`. Not needed for the feature (the user's playlists
  already exist) but kept and tested.
- Writer design bug found by its own tests: leading blanks do not survive the
  reader's trim, so the writer refuses them rather than writing a playlist that
  names a file it never named.

## M3U.LIB decode — the database is already built

- `tools/m3u/m3ulib.py` decodes `M3U.LIB`: 10 records, one per playlist, each
  with a UTF-16LE title, extension `M3U\0`, and a location. Decoding against the
  card reproduces all ten filenames. Commit `5c95be4`.
- Title cap of 30 characters discovered here — `Bad Omens` is stored as
  `Bad Omen`. A stored title is a label, never a filename.

## The library-selection mechanism — and a self-correction

- An early pass reported "no code references the `M3U.LIB` pointer, therefore no
  reader". **Wrong.** `M3U.LIB` is selected by *index* into a 12-byte table at
  `0x7805b498`; a pointer scan was guaranteed to fail. Corrected in `8cd46fa`.
- Session 3 restated this as `docs/m3u-integration.md`.

## Host-side database → playlist adapter

- `tools/m3u/m3udb.c` — record index → ordered playlist, 496 B MIPS16e.
  Verified end to end against copies of the real card: 10 records, **615
  tracks**, order preserved, deterministic. Commit `86cddc7`.
- Harness bug found by the test: `m3udb_first` returns the first entry and the
  loop discarded it, losing each playlist's first track. Fixed, and the
  regression test covers it.

## Session 4 — Stage A, and two withdrawn claims

- `tools/fw/m3ufs.c` transcribed arithmetic from `0x7805b264`/`0x7805b2dc` and
  claimed a record's location addresses an exFAT directory entry.
- `7ed88ef` **withdraws** that: the routines are pointed at by nothing, 512 is a
  sector size not necessarily a cluster size, 16 is not exFAT's 32-byte entry,
  and all ten selectors are multiples of 32 so the routines never exercise their
  own low-bit path.
- `8ba774d` records that `0xBFC16BB5` — taken for a shared kernel filesystem
  entry — is a **trap-table address**. That is also why the routines are
  unreachable: invoking them would trap. Second trap-table false positive.

## Session 5 — menu tree, and a third false positive

- `music.mcg` decoded: 139 nodes; All Songs is **id 45** in the list-select-1
  context, `m3u` slots are ids 49–53. Commit `42f067d`.
- A cluster of `cmpi` immediates at `music.ap +0x1a965` looked like a numeric
  menu-id dispatcher. The immediates are ASCII from a **genre-name table** —
  linear disassembly of an overlay bank decodes string data as instructions.
  Third false positive, same root cause as the others: a pattern found without
  establishing how the code is reached.
- `52b658a` establishes the shared-bank overlay structure: bank `0x713d2500` is
  declared by browser, mainmenu and music with different content at one address,
  and no code references a bank base — which is normal for overlays, so
  "no static references" is *not* evidence of dead code.

## Where it stands

Host side complete and tested. Firmware side: no module patched, no `M3U.LIB`
consumer found, no playback ABI, no `.HEX`. The blocker is that no live call
chain has been established into any overlay bank, and without one no ABI can be
verified. See `m3u-integration.md` for the handoff.

## Session 6 — the syscall-stub correction (withdraws two earlier claims)

Read the upstream research the task pointed at, and it overturns two of this
project's conclusions.

- **`li v1,MODULE ; break` is a system-call stub, not a trap or error address.**
  The README says so outright: stubs sit at the end of resident code, the `MODULE`
  byte selects a system module, and the *last argument* is the function ID.
  Modules documented: `0x0f` kernel (`0x1c` millisecond clock, `0x35` RNG),
  `0x11` filesystem, `0x06` text conversion.
- **Overlay loading is demand-driven.** A call into an unloaded bank raises an
  exception, the kernel loads it and retries. So "no static references" is
  *expected* for a bank, and proves nothing about reachability — which retracts
  the dead-code wording added in `52b658a`.
- Verified per-module, and they differ at the same address:
  `music.ap` has `0x0f`/`0x11` at `0xbfc16bb0`/`0xbfc16bb4`; `playlist.ap` has
  `0x0f`/`0x06` at the same addresses. `VERIFIED` from the resident bytes.
- Consequence: the routines at `0x7805b264` and `0x7805b2dc` **do call a real
  service** — they set a function ID (`0xB`, `0xD`) as the last argument and
  `jalrc` through the stub. Under playlist.ap's mapping that is module `0x06`
  (text conversion). The "dead code / trap" reading is withdrawn.
- Also learned from the README: the bank table has **five** groups (`0x100` to
  `0x1000`), 12-byte entries in blocks of 64, not the two this project had been
  scanning; the music-engine group is `0x7b` at `0x700` and the shared-library
  group `0x71` at `0xa00`.

Net: two claims withdrawn, one rehabilitated, and a bank-table scan range
corrected. `docs/architecture.md`, `reverse-engineering.md` and `firmware-api.md`
now carry the corrected model with the old wording marked as withdrawn rather
than deleted.
