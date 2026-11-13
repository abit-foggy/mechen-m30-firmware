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

## Session 7 — the entry point, found

The upstream research was the unlock. Three things this project had wrong, all
now corrected and committed (`0c0c1ec`, `5e624e0`):

1. `li v1,MODULE ; break` are **syscall stubs**, not trap addresses.
2. Overlay loading is **demand-driven** — a call into an unloaded bank raises an
   exception and the kernel loads and retries — so "no static references" proves
   nothing about reachability.
3. The bank table has **five+ groups to 0x1000**, in blocks of 64, where this
   project scanned two. The missed groups held the entry point.

**First verified runtime call chain.** `music.ap`'s header `+0x40` holds
`0x40014C31`; clearing the MIPS16e ISA bit gives the entry `0x40014C30`, in bank
`0x40014c00` (size `0xcc`), prologue `save 0x30` with two saved arguments. Its
pool gives a kernel syscall (module `0x0f`, fn `0x33`), a module-`0x10` syscall,
and the sibling at `0x40014C00` which calls `0x400552A0` — in bank `0x40054c00`,
**the same bank the library builder documents the extension mask table in** at
`0x40055220`.

The ISA-bit convention is what made the syscall stubs legible and retires the
off-by-one: `0xBFC16BB1` → stub `0xBFC16BB0` = module `0x0f`, matching the
upstream-documented address exactly.

Next: disassemble `0x400552A0` and follow it toward the mask table and the
selection path.

## Session 8 — status dispatch, not menu dispatch

Step 1 paid off immediately and corrected the previous report: bank `0x40054c00`
differs per module. music.ap's copy holds real code at `+0x6a0` and **no masks**;
playlist.ap's holds the documented mask table at `+0x620` and is **zero** at
`+0x6a0`. The earlier claim that the entry path reaches the mask table was an
address-transfer error and is withdrawn (`73d6c37`).

Step 2 decoded both functions. `0x400552A0` is `u16 f(u8 arg)`: stores `arg` to
the RAM global `0x9FC15436`, gates on an in-bank call, returns `0x8006` on the
failure path, and hands the code to `0x40614FC0` in another bank — the first
cross-bank `jal` verified on a live path. `0x40614FC0` is `save 0xD0` and
dispatches on a 16-bit status code.

Step 3 disconfirmed my own hypothesis. The dispatcher compares exactly six
codes — `0x8000`, `0x8006`, `0x800F`, `0x8010`, `0x8015`, `0x861C` — and **not**
one menu id: no `0x802D` for All Songs (id 45), none of `0x8031`–`0x8035` for the
`m3u` slots. `0x861C` is `0x8600 + 0x1C` and the README documents kernel function
`0x1C` as the millisecond clock, so the family is service result codes, and the
pair is "compute a status, dispatch on it". Recorded as a disconfirmation rather
than reshaped into a menu finding (`9c36c35`).

The live lead is narrow and specific: `0x9FC15436` is a **music.ap-private**
global — referenced from eight places in music.ap and from nowhere in
playlist.ap, browser.ap or mainmenu.ap — and it sits just past the declared data
segment (`0x9fc15400..0x9fc15414`), so it is undeclared app scratch. `0x400552A0`
writes its argument there, which makes it the state the menu selection feeds.
Tracing its readers is one address, not a bank.

## Session 9 — the eight-readers lead was an artefact; entry banks are per-module

Validating the previous handoff's recommendation destroyed it. The write at
`0x400552A0` decodes as `lw $v1,[0x400552F0]` then `sb $v0,0($v1)`, so
`0x9FC15436` is a **byte** state slot (and could not be a 32-bit pointer — it is
only halfword-aligned, `0x436 mod 4 == 2`). And all eight "references" to it are
pool words holding the address *literal*, not instructions: `0x40055288` decodes
as `slti $a0,0x36` precisely because the bytes there are `36 54`. A byte search
for an address finds the constant, never its uses — the same method error as the
genre-table false positive, now written down as a rule (`a80cf9d`).

Redirected to browser.ap. Its header `+0x40` also gives `0x40014C30`, and its
first eight bytes match music.ap's — which looks like a shared entry trampoline.
Full-bank md5s say otherwise: all nine `.ap` modules hold **different** banks at
`0x40014c00`, so matching prologues are convention, not sharing. Recorded as a
near-miss with the rule it teaches.

Net for the session: the `0x9FC15436`/`0x40614FC0` path is closed as
status-dispatch with no established reader, and neither recovered function gives
an interface the M3U code can call. No firmware integration, no `.HEX`.

## Session 10 — the browser chain and the engine dispatch table

Sustained block from the documented state. Two independent chains recovered,
both anchored at module headers.

**Browser.ap** (`4f4a3b9`, `a19bddc`). Header `+0x40` gives `0x40014C31`
→ `0x40014C30`, and the entry banks of music.ap and browser.ap are
**byte-identical code differing only in four pool words** — a shared entry
template. The entry **registers a callback with the kernel**: it builds a
four-field struct whose first field is a MIPS16e function pointer and passes its
address to kernel module `0x0f` function `0x4A`, with cleanup at module `0x10`
fn `0x11` and kernel fn `0x34`. The registered function `0x40055174` is an
**event loop** on a flag at `0x9fc154d4`; flag 1 reaches `0xBFC16578` (state
dispatch on `0x9fc154dc`) and falls through to `0xBFC164B4`, a **path builder**
that hands `':'` and `'/'` to a service in bank `0x7805b200`. Flag 2 reaches
`0x4009508C`, which calls `0x40C14C00` with a `{1,3,0,0,0}` descriptor and a
`0x6002` code. **The chain is bounded there deliberately**: `0x40C14C00`'s body
would call `0x48454841`, the ASCII at bank `+0x280`, so one linear pass cannot
distinguish a mis-resolved operand from a bogus call. That is the same failure
mode as the genre table, caught before it produced a false edge.

**mengine.ap** (`d87876c`, `5ed836d`, `062408b`). A genuine **dispatch table** in
bank `0x7a052d00` at `+0x3a8`, five MIPS16e pointers all resolving to valid
banks. `0x7b06856c` — the upstream docs' `get_location` — is the
**record → file operation**: it calls the filesystem module `0x11` (stub
`0xbfc11ccc` verified as `li $v1,0x11 ; break`) with function `3`, and on success
fills the record's `+0`, `+1`, `+4`, `+0x5C`, `+0x5E`. A **second witness** in a
different bank, `0x7b228118`, reads the same five globals and writes the same
four offsets with no filesystem call — so the descriptor layout has multi-witness
support and neither function can be a mis-decode of the other. And
`0x7A052E34` is the **driver that uses the table**: it reads a mode byte from
`0x9fc15f20`, indexes a table whose real base is `0x7A0530B4`, and calls the
handler with the caller's own arguments. That corrected the table base, which an
earlier note had wrong.

**Pinned** by `tools/fw/test_m3uengine.py` (`fc401e6`), which re-derives all of
it from the unpacked component.

**No adapter written**, deliberately: `get_location`'s filesystem argument order
is unresolved, and guessing it would corrupt the record in place. That is the
one thing standing between the host chain and a firmware adapter, and it is one
RAM address to trace rather than a bank to search.
