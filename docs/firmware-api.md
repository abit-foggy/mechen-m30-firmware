# Firmware APIs and ABIs

Only what the evidence supports. Anything not marked `VERIFIED` must not be
called from production code. Nothing here has been exercised on hardware — every
entry is `host` (host tests) or `dis` (disassembly) at best.

## Nothing is verified enough to call yet

The honest summary: **no firmware ABI is established well enough to invoke from a
patch.** The sections below record what is known, what is not, and what each
missing piece would take.

## Library database access

`VERIFIED` (disassembly + card data):

- Filename table, `0x7805b498`, 12-byte stride, index 0 = `MUSIC.LIB`,
  index 1 = `M3U.LIB`.
- `0x7805b370` selects by index: `0x7805b498 + index*12`.
- Record envelope and the location-field *layout* — see
  [reverse-engineering.md](reverse-engineering.md).

`UNVERIFIED`, and these are the gaps:

| Question | State |
|---|---|
| Does index 1 actually select `M3U.LIB` at runtime? | never executed |
| Who calls `0x7805b370`? | no live caller chain |
| What reads a record from a selected library? | not traced |
| What opens the file a record's location names? | **the core blocker** |

## Bank `0x7805b200` — a real syscall, not a trap

`VERIFIED`, and a correction to an earlier entry here that said the opposite.

The routines `0x7805b264`, `0x7805b2dc` and `0x7805b370` `jalrc` through a pool
pointer to an address that an earlier pass read as a trap. It is a **syscall
stub**: `li $v1,MODULE ; break`, where the last argument is the function ID.

**Calling convention at these sites** (`VERIFIED` as a transcription):

- `$a0`–`$a3` register arguments, plus a fifth at `0x10($sp)`
- `$a3` carries the function ID; `$v1` the module, set by the stub itself
- result in `$v0`
- the caller sets up a context pointer and a destination buffer from RAM
  globals before calling

`UNVERIFIED`: the semantics of the services these particular routines request,
and whether they are on a live path.

## The enumeration filter (browser.ap's copy)

`VERIFIED` from disassembly, `UNVERIFIED` as the folder browser's filter:

- Walker at guest `0xbfc168a0`.
- Node layout, 16 bytes: `+1` type (must be 1), `+5` category byte (`0xFF` = any),
  `+2` u16, `+8` data pointer, `+12` callback.
- Test at `0xbfc168ca`–`0xbfc168d0`: a node passes when `node[+5]` equals the
  active filter, or when it is `0xFF`.
- Globals: `0x9fc15574` file count, `0x9fc15584` node-array base (a RAM pointer,
  so the array is built at runtime), `0x9fc1a1c8`, `0x9fc15588` active filter.
- Kernel-style call sites in the same bank use a context from `0x9fc15980` and a
  scratch buffer at `0x7805b4b0`.

Because the node array is runtime-built and its builder is untraced, **no patch
here is derivable from the image alone**.

## Calling convention observed at the kernel-style entry points

`VERIFIED` as a transcription of instructions; `UNVERIFIED` as a working ABI:

- Four register arguments `$a0`–`$a3`, plus a fifth on the stack at `0x10($sp)`.
- Operation codes seen as immediates: `0xB` (seek), `0xD` (read `0x200` bytes).
- Return value in `$v0`.
**Do not build a call on this table without executing it** — the convention is
transcribed, never run, and the module a stub addresses depends on which
application's resident mapping is loaded.

## Filesystem

Nothing established. Specifically unknown: how a pathname is opened, how a
directory is enumerated, what a file handle looks like, and how a handle is
closed. The `M3U.LIB` location field's semantics are unknown, so no
record → file resolution can be written.

## Playback

**Nothing established.** Unknown whether playback accepts a record index, a
pathname, a handle, a queue descriptor, or something else; and how Next/Previous
walk the queue. This is the next investigation, not a gap to fill by assumption.

## The portable M3U modules (host-verified, not firmware-verified)

These are ours, not firmware APIs. `tools/m3u/m3u.c` is a bounded streaming
reader (576 B MIPS16e) taking a `long (*read)(void*, char*, unsigned long)`
callback; `tools/m3u/m3udb.c` (496 B) turns a record index into ordered tracks
via a sector reader and an open-by-location callback. Both compile warning-free
for MIPS16e and are covered by host tests, but **neither has run on the device**,
and `m3udb`'s open callback is the seam a verified firmware ABI would fill.

## MIPS16e notes that matter for calling anything

- `save 0xNN, $ra,$s0-$s1` is `0x64xx`; `restore` is its inverse; `jr $ra` is
  `0xE820`; `break` is `05 e8`.
- `li $rd, imm8` puts the immediate in the **first** byte (`0b 6a` = `li $v0,11`).
  Getting this wrong silently corrupts every immediate-based scan.
- Function pointers into `0xbfc16xxx` should be checked against the trap-table
  pattern before use.
