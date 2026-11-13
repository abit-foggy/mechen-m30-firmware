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

## MIPS16e addressing and the syscall convention

`VERIFIED` — this is the entry that unlocks the rest.

**Function pointers carry the MIPS16e ISA bit in bit 0.** The routine starts at
`pointer & ~1`. Every pool pointer in an overlay bank follows it:

| pool pointer | routine | what it is |
|---|---|---|
| `0x40014C31` | `0x40014C30` | **music.ap's declared entry point** (header `+0x40`) |
| `0xBFC16BB1` | `0xBFC16BB0` | `li $v1,0x0f ; break` — kernel syscall stub |
| `0xBFC16401` | `0xBFC16400` | `li $v1,0x10 ; break` — module `0x10` stub |
| `0x400552A1` | `0x400552A0` | routine in bank `0x40054c00`, the mask-table bank |

**A syscall is reached by `jalrc` through a pool pointer, not by `jal` to the
stub.** The caller sets `$a3` to the function ID; the stub sets `$v1` to the
module and `break` traps into the dispatcher; the result comes back in `$v0`.

- Four register arguments `$a0`–`$a3`, plus a fifth at `0x10($sp)` where seen.
- `$a3` = function ID. `$v1` = module, set by the stub.
- Result in `$v0`.
- Callers frequently load a context pointer and a destination buffer from RAM
  globals first.

Modules identified: `0x0f` kernel (`0x1c` millisecond clock, `0x35` RNG),
`0x10`, `0x11` filesystem, `0x06` text conversion. **A stub's meaning is
per-module** — `0xBFC16BB0` is module `0x0f` in playlist.ap's mapping and the
same address is module `0x11` in music.ap's.

`UNVERIFIED`: the semantics of specific function IDs beyond the three above.

## MIPS16e notes that matter for calling anything

- `save 0xNN, $ra,$s0-$s1` is `0x64xx`; `restore` is its inverse; `jr $ra` is
  `0xE820`; `break` is `05 e8`.
- `li $rd, imm8` puts the immediate in the **first** byte (`0b 6a` = `li $v0,11`).
  Getting this wrong silently corrupts every immediate-based scan.
- `save`/`restore` are `0x64xx`-style extended pairs; `jr $ra` is `0xE820`;
  `break` is `05 e8` and is the second halfword of a syscall stub, not an error.

## Filesystem adapter — `tools/fw/m30fs.c` — the first callable interface

`VERIFIED` ABI, host-tested logic, **not yet executed on the target**.

```c
/* tools/fw/m30fs.h — opens a file BY PATH through the stock kernel. */
void m30fs_set_stub(u32 stub, u32 ctx);   /* per-module: see below */
int  m30fs_init(struct m30fs_file *f, u32 ctx, const char *path);
long m30fs_read(struct m30fs_file *f, void *buf, u32 n);
u32  m30fs_tell(const struct m30fs_file *f);
void m30fs_close(struct m30fs_file *f);
```

Derived from `playlist.ap:0x40194c78`, the stock library-file creator
`docs/library-builder.md` documents and the expanded-library build exercises, so
the ABI is known-working by construction:

| op | meaning | call shape |
|---|---|---|
| `8` | chdir | `(ctx, ':', 0, 0, 8)` — to the root drive |
| `5` | **open** | `(ctx, name, 0, 0, 5)` — `name` is NUL-terminated; handle in `$v0`, `0` = failure |
| `9` | size | `(ctx, &size, handle, 0, 9)` |
| `0xD` | read | `(ctx, buf, n, handle, 0xD)` |
| `7` | close | `(ctx, handle, 0, 0, 7)` |

The function id is the **last** argument, a fifth word at `0x10($sp)` — which the
adapter gets from a five-argument function pointer rather than hand-written asm,
so the compiler emits the o32 sequence. Verified at object level: the compiled
`fscall` stores the id at `16(sp)` and `jalrc`s the stub, matching the stock
sequence instruction for instruction.

**`name` is a plain pathname.** The stock code passes a name from its own table,
but nothing in the call ties it to that table, so `"Playlists\foo.m3u"` opens
that file. That is why the unresolved `get_location` contract is no longer on the
critical path.

Stub addresses are **per-module** — `0xBFC1640D` in playlist.ap's resident
mapping, `0xBFC11CCC` in mengine.ap's — while the function ids are the kernel's.
Hence `m30fs_set_stub`, and hence the note in `m30fs.h` that the context is read
from RAM rather than hard-coded.

`UNVERIFIED`: whether op `0xD`'s argument order is exactly `(buf, n)` — the
adapter mirrors the stock append-write helper's `(buf, len)` for op `0xE`, which
is an inference from symmetry, not from a decoded read site. If reads come back
wrong on hardware, that is the first thing to check.

## Engine current-file state block — `0x9FC15F20..0x9FC15F38`

The engine's cross-bank shared state, named by approximately 22 mengine.ap banks.
This is the interface an M3U adapter targets.

```c
/* Verified layout from two independent readers; see reverse-engineering.md.
 * Addresses are guest RAM in the engine's data window. */
#define M30_MODE_BYTE      0x9FC15F20   /* selects the dispatch handler */
#define M30_MODE_FLAG      0x9FC15F21   /* cleared on every dispatch */
#define M30_STATE_B        0x9FC15F22   /* descriptor +1 */
#define M30_LOC_LO         0x9FC15F24   /* descriptor +0x5E — most referenced */
#define M30_LOC_HI         0x9FC15F26   /* descriptor +0x5C — most referenced */
#define M30_DESC4          0x9FC15F28   /* descriptor +4 */
#define M30_FS_CTX         0x9FC15F34   /* the filesystem context */
#define M30_DESC0          0x9FC15F38   /* descriptor +0, read as byte[3] */
```

`VERIFIED`: the eight addresses, their data types (from the `lbu`/`lhu`/`lw`
widths used), and which descriptor field each one fills — established by
`0x7b06856c` and `0x7b228118` independently.

`VERIFIED`: the block is shared — roughly 22 banks name it, and the pair
`0x9FC15F24`/`0x9FC15F26` is the engine's most-referenced state.

`UNVERIFIED`: what a *write* to any of these does — no writer was traced. So
this document does **not** authorise an adapter to poke the block; doing so
without knowing the writer's side would race the engine.

### The shape a safe adapter takes

Given what is verified, the adapter's structure is determined even though its
engine call is not:

1. `m3udb_read` a record → the playlist's location and title.
2. Open the `.m3u` file — **not yet possible**, because the resolver ABI
   (`get_location`'s fs argument order) is unestablished.
3. `m3u_next` its entries in order.
4. Present the selection.

Step 2 is the whole gap, and it is one question, not a project: which of
`*[0x9FC15F34]`, `record+0x10` and `record+8` is the input record and which is
the output buffer.

### `get_location` — the intended call, with the unknown marked

```c
/* INFERRED, NOT VERIFIED. Do not call this. */
int m30_get_location(void *descriptor, unsigned char b);
/*   0x7b06856c. Fills descriptor +0, +1, +4, +0x5C, +0x5E on success,
 *   returns 1; 0 on failure. Internally calls filesystem module 0x11
 *   function 3 as:
 *     fs11_3(*[0x9FC15F34], descriptor + 0x10, descriptor + 8, 0, 3)
 *   and the input/output roles of those three pointers are UNKNOWN. */
```

`VERIFIED` about it: the module-`0x11` stub at `0xbfc11ccc`; function id `3`; the
five descriptor fields filled; the globals read. `UNVERIFIED`: argument roles,
buffer ownership, whether the descriptor is modified in place, and what function
`3` does.

### Module `0x11` (filesystem) — what is established

| function id | seen at | note |
|---|---|---|
| `0x0E` | browser.ap `0x40014C00` | called with a byte from `0x40055174` |
| `0x10` | browser.ap entry, music.ap entry | acquire-a-resource pattern |
| `0x11` | browser.ap entry cleanup | release |
| `0x33`, `0x34`, `0x4A` | module `0x0F` (kernel) | registration and lifecycle |

`VERIFIED` as call sites and function ids. `UNVERIFIED`: the semantics — no
module-`0x11` function's meaning is known, so no adapter may rely on one.
