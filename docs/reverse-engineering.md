# Reverse-engineering notes

Status tags: `VERIFIED` (read from the bytes), `INFERRED`, `UNVERIFIED`,
`DISPROVEN`.

Method note that governs everything below: **IDA headless** with `-pmipsl -c` and
`idc.set_default_sreg_value(segment_ea, "mips16", 1)`. Without the virtual
register IDA prints MIPS32 mnemonics over MIPS16e bytes, which is silently wrong.
Tooling: `tools/ida/m30_ida.sh`, `tools/ida/m30_mips16e.py`.

## The three rules that prevent false positives

Each of these cost a full investigation. Check them before believing any address.

1. **Syscall stubs are not traps — this rule replaces an earlier wrong one.**
   Overlay regions end — and sometimes begin — with runs of
   `li $v1,MODULE ; break`, which are **system-call stubs**: `MODULE` selects a
   system module and the last argument carries the function ID. An earlier pass
   in this project read them as trap/error addresses and concluded two routines
   were dead code. **Withdrawn.** Affected: `0xbfc16a25`, `0xBFC16BB5`.
   `VERIFIED` for the stub bytes; the *meaning* of each stub is per-module and
   must be checked against that module's resident mapping.
2. **Never disassemble an overlay bank linearly.** A cluster of `cmpi $rx, imm`
   immediates at `music.ap +0x1a965` looked like a numeric menu-id dispatcher; the
   immediates are ASCII from a **genre-name table** (`Blues`, `Classic`, `Rock`,
   `Country`, `Dance`, `House`, `Jazz`). `DISPROVEN`.
3. **Same guest address ≠ same function.** `0xbfc16400` holds a `save` prologue
   in browser.ap and a trap table in music.ap and playlist.ap. `VERIFIED`.

## Verified structures

### M3U.LIB / MUSIC.LIB

Envelope, `VERIFIED` against the card:

```
+0x000  4   magic "M3U\0" (MUSIC.LIB: "MUSIC")
+0x008  2   record count        (the high u16 at +0x0A is a fixed 1)
+0x010  8   the one section name, "ALLFILE\0" (MUSIC.LIB: "ALLSONG")
+0x200  .   256-byte records, two per 512-byte sector
  +0x00  64  title, BOM + UTF-16LE + terminator  (30 usable characters)
  +0xa3   1  tag-ok flag
  +0xa4   4  extension as packed text ("M3U\0")
  +0xa8   1  always 1
  +0xa9  16  file location
```

The title cap of 30 characters means `Bring Me The Horizon, Bad Omens` is stored
as `…Bad Omen`, so a stored title is a **label, never a filename**. `VERIFIED`.

### The library filename table

`VERIFIED`, in the `0x7805b200` bank at guest `0x7805b498`, 12-byte stride:

| index | address | contents |
|---|---|---|
| 0 | `0x7805b498` | `MUSIC.LIB\0\0\0` |
| 1 | `0x7805b4a4` | `M3U.LIB\0\0\0\0\0` |

`0x7805b370` computes `0x7805b498 + index*12`: `lhu` index `0x7805b3f2`,
`sll`/`sll` to ×12 `0x7805b3f6`–`3fa`, `lw` base `0x7805b3fc`, `addu` `0x7805b3fe`.
Selecting a library is therefore an **index**, not a pointer to a filename — so a
scan for "a pointer to M3U.LIB" can never succeed. An earlier pass drew the wrong
conclusion from exactly that scan.

### The location field's *layout* (not its meaning)

`VERIFIED` from the card's data, not from disassembly. All ten records share
their first twelve bytes — `0x07000012`, `0x00000540`, `0x00135eac` — and differ
only in the last four:

```text
800  1056  1280  1408  1504  1632  1760  1888  2016  2208
```

all distinct, monotonic in record order, all multiples of 32. So bytes 0–11 are
the constant directory and bytes 12–15 the per-record value. What bytes 4–11
mean is `UNVERIFIED`.

### The syscall convention (rehabilitates the location arithmetic's context)

`VERIFIED` that the routines at `0x7805b264` and `0x7805b2dc` call a **real
syscall**, not a trap: they load a stub address from their pool and `jalrc` to
it, after setting the function ID (`0xB`, `0xD`) as the last argument and
placing a fifth argument at `0x10($sp)`. Under playlist.ap's resident mapping the
stub they load is the module-`0x06` (text conversion) one, so the operation is a
text-conversion service, not a filesystem call. Under music.ap's mapping the
same address is module `0x11` (filesystem), which is a different service — the
caller's module decides.

What remains `UNVERIFIED` is what those two routines *do* with the result, and
whether they are on the live M3U path.

### The withdrawn location arithmetic

`DISPROVEN as an explanation`. `0x7805b264` and `0x7805b2dc` compute
`sector = arg0 + (arg1 >> 5)`, `slot = (arg1 & 0x1F) << 4`, then `sector << 9`.
512 is a sector size, not necessarily a cluster size; 16 is not exFAT's 32-byte
directory entry; and all ten selectors are multiples of 32, so `(arg1 & 0x1F)` is
zero for every record and the routines never exercise their own low-bit path.
`tools/fw/m3ufs.c` keeps the transcription because it is the only firm evidence,
labelled in its header as instructions from routines whose relevance is
unproven.

### ID3 TAG parsing

`VERIFIED`. Bank `0x713d2500`, function at `0x713d2600`: reads `0x80` bytes then
compares `T`,`A`,`G` at `0x713d261a`, `0x713d2626`, `0x713d2632` — an ID3 `TAG`
header check. Same bank also holds the genre-name table that produced false
positive #2.

### music.mcg menu tree

`VERIFIED`, 139 nodes. Top-level ids a dispatcher would key on:

| node | id | name |
|---|---|---|
| NODE1 | 0 | 所有音乐 — All Music (root) |
| NODE6 | 1 | 主菜单 — Main Menu |
| NODE15 | 2 | 正在播放(乐库) — Now Playing (music library) |
| NODE17 | 3 | 上传歌曲音乐(乐库) |
| NODE19 | 4 | 正在播放(播放机) |
| NODE21 | 5 | 上传歌曲音乐(播放机) |
| NODE65 | 21 | 音乐(列表选择1) |
| NODE169 | 41 | 随机播放 — Shuffle play |
| NODE182 | 45 | **所有音乐(列表选择1) — All Songs (list select 1)** |
| NODE184 | 46 | 正在播放 |
| NODE188 | 48 | 我的最爱 — My Favourites |
| NODE192/194/197/200/203 | 49–53 | m3u列表选择1..5 |

So All Songs is **id 45** in the list-select-1 context. Whether id 45 is a
runtime identifier in code (rather than only a resource-tree index) is
`UNVERIFIED`.

### Shared extension arrays

Three separate arrays, none containing `M3U`:

| module | file offset | slots | notes |
|---|---|---|---|
| fat_32n.drv | `0x780` → guest `0xbfc17180` | 31 | 28 extensions then `**`, `*f`, three spaces |
| exfatn.drv | `0x7f8` → guest `0xbfc171f8` | 31 | byte-identical array; drivers are mutually exclusive |
| browser.ap | `0xc188` → guest `0x71352b88` | 31 | adds `WMV`, `AMV`; closes with `**`, `*f`, `*d` |
| music.ap | `0x4ae4` → guest `0x7135eae4` | 9 | audio only |

Pinned by `tools/m3u/exttest.py` (52 assertions). `VERIFIED`.

### The enumeration filter

`VERIFIED` for *browser.ap's* copy: walker at guest `0xbfc168a0`, 16-byte nodes
(`sll $a2,$v0,4` at `0xbfc168b2`), `node+1` a type that must be 1,
`node+5` a **category byte** compared against the active filter, where `0xFF`
means "any" (`cmpi $v1,0xFF` at `0xbfc168ce`), `node+12` a callback called with
`jalrc`. Globals `0x9fc15574` (count), `0x9fc15584` (node array base, a RAM
pointer), `0x9fc1a1c8`, `0x9fc15588` (active filter).

`UNVERIFIED`: whether this walker is the folder-browser's enumeration filter, and
what builds the node array.

## Verified call chain — music.ap entry

`VERIFIED` end to end: header pointer, bank-table entry, prologue bytes and pool
targets all agree.

### The ISA-bit convention

Function pointers in overlay banks carry the **MIPS16e ISA bit in bit 0**; the
routine starts at `pointer & ~1`. This resolves the off-by-one that made the
syscall stubs look like mid-instruction addresses:

| pool pointer | routine | identity |
|---|---|---|
| `0xBFC16BB1` | `0xBFC16BB0` | `li $v1,0x0f ; break` — **kernel** syscall stub |
| `0xBFC16401` | `0xBFC16400` | `li $v1,0x10 ; break` — module `0x10` stub |
| `0x400552A1` | `0x400552A0` | a routine in bank `0x40054c00` |
| `0x40014C31` | `0x40014C30` | **music.ap's entry point** |

It also matches the upstream-documented addresses exactly: `0xBFC16BB1` is the
module `0x0f` stub and `0xBFC1640D` the module `0x11` filesystem stub, both in
playlist.ap's resident mapping.

### The edges

```
music.ap header +0x40 = 0x40014C31
   → 0x40014C30              entry. save 0x30, $ra,$s0-$s1; $a0 → 0x20($s1);
                             $a1 → 0x24($s1). Takes two arguments.
   → [pool 0x40014CC0 = 0xBFC16401]  syscall, module 0x10, function 0x10
   → [pool 0x40014CC8 = 0xBFC16BB1]  syscall, module 0x0f kernel, function 0x33
   → [pool 0x40014CC4 = 0x40014C01]  the sibling at 0x40014C00

0x40014C00                  sibling. save 0x20; $a0 saved; then
   → [pool 0x40014C28 = 0x400552A1]  0x400552A0, bank 0x40054c00,
                                      file 0x1400..0x1c00, size 0x800
   → [pool 0x40014C2C = 0xBFC16401]  syscall, module 0x10, function 0x0e
```

**Correction to an earlier version of this section, which over-claimed here.**
Bank `0x40054c00` is *a* bank both modules declare, but the contents differ and
the documented mask table does not transfer:

| module | bank file range | `0x400552A0` | mask `0x7e190ea0` |
|---|---|---|---|
| music.ap | `0x1400..0x1c00` | real code (`save 0x20` prologue) | **ABSENT** |
| playlist.ap | `0x2400..0x2c00` | **all zeros** | at bank `+0x620` |

So the mask table is a **playlist.ap** structure and music.ap's copy of the same
guest address carries no masks at all. The entry path does *not* reach it, and
the earlier sentence saying it did is withdrawn. `VERIFIED` by scanning both
banks for the mask literals.

### `music.ap:0x400552A0` — decoded, `VERIFIED`

Signature `u16 f(u8 arg)`; `$a1` is saved to the frame and unused in the body
shown. Anchored disassembly from the `save 0x20` prologue at bank `+0x6a0`:

```text
0x400552a0  save 0x20, $ra,$s1            ; frame
0x400552a4  sw  $a0, 0x10($s1)            ; arg
0x400552a8  lw  $v1, [0x9FC15436]         ; RAM global -> pointer
0x400552ac  sb  $a0, 0($v1)               ; *global = arg
0x400552ae  jal 0x40054D88                ; A
0x400552b4  cmpi $v0, 1 / bteqz           ; if (A() == 1) ...
0x400552bc  ...zeb(arg)
0x400552c2  jal 0x40054FF4                ; B(arg)  -> u16 result
0x400552cc  li $v0,0x7FFA ; neg           ; else result = 0x8006
0x400552d4  move $a0, result
0x400552d8  jal 0x40614FC0                ; C(result) -- CROSS-BANK, bank 0x40614c00
0x400552de  jal 0x40054F80                ; D
0x400552e4  return result                 ; u16
```

So it *stores its argument into the RAM global at `0x9FC15436`*, then gates on
an in-bank call, computes a 16-bit code (`0x8006` on the failure path), hands it
to a routine in a **different bank** (`0x40614c00`), calls one more in-bank
routine, and returns the code. The shape is an event or command handler that
dispatches a numeric result onward.

**`0x400552d8` is the first cross-bank `jal` verified on a live path** — a direct
`jal` into bank `0x40614c00`, which under demand-driven loading is exactly the
mechanism that raises the load exception. No pointer, no indirect table: a
literal branch target.

`UNVERIFIED`: what `0x40054D88`, `0x40054FF4`, `0x40054F80` and `0x40614FC0` do.

### `music.ap:0x40614FC0` — a result-code dispatcher, not a menu dispatcher

`VERIFIED` by anchored disassembly from the `save 0xD0` at `0x40614fc0` (a
4-byte EXTEND+`save`, which is why it reads as `10 f0 | da 64`):

```text
0x40614fc0  save 0xD0
0x40614fc6  $v0 = $a0                  ; a 16-bit code in
0x40614fc8  sh $v0, 0xC0($s1)
0x40614fd0  sw $v0, 0xB0($s1)
0x40614fd4  li $v0,0x8010 ; xor ; compare   → 0x40615048
0x40614fe2  li $v0,0x8010 ; slt             → 0x4061500C
0x40614fee  li $v0,0x8006 ; xor             → 0x40615078
0x40614ffc  li $v0,0x800F ; xor             → 0x40615060
0x40615026  li $v0,0x8015 ; xor             → 0x4061513A
0x4061500c  li $v0,0x861C ; xor             → 0x406150A8
0x4061500a  b 0x40615124                   ; default
```

The complete set of dispatch constants in the bank is
**`0x8000, 0x8006, 0x800F, 0x8010, 0x8015, 0x861C`** — six codes, nothing else.

**This disconfirms a hypothesis of mine that it was the menu dispatcher.** None
of the menu ids appear: no `0x802D` for All Songs (id 45), no `0x8031`–`0x8035`
for the five `m3u` slots, no `0x8030` for My Favourites. `0x8015` happens to
equal `0x8000 + 21` and id 21 is 音乐(列表选择1), but that is arithmetic
coincidence, not evidence — `0x8015` is one of six codes in a result dispatch.

The strong reading is that these are **service result codes**, not menu ids:
`0x861C` is `0x8600 + 0x1C`, and the upstream README documents kernel function
`0x1C` as the millisecond clock, so `0x8600|fn` is the kernel-service family and
`0x8000|code` another service family. `0x400552A0` returns `0x8006` on its
failure path, and `0x8006` is one of the six, which fits: the pair is
"compute a status, then dispatch on it".

So the verified two-function chain is:

```text
music.ap 0x40014C00 ──jal──► 0x400552A0     bank 0x40054c00, +0x6a0
                              │ u16 code (0x8006 on the failure path)
                              ├──jal──► 0x40614FC0   bank 0x40614c00, +0x3c0
                              │            dispatches 0x8000/0x8006/0x800F/
                              │            0x8010/0x8015/0x861C
                              └──jal──► 0x40054F80
```

**The All Songs handler is still not found.** This pair is status dispatch, and
the menu path remains open.

### Entry `0x40014C30` — decoded, `VERIFIED`

Initialisation, not an event loop:

```text
0x40014c34  sw $a0, 0x20($s1)             ; two arguments saved
0x40014c36  sw $a1, 0x24($s1)
0x40014c38  li $a3,0x10 ; jalrc [0xBFC16401]   ; syscall module 0x10, fn 0x10
0x40014c44  sb $v0, 0x10($s1)
0x40014c46  ...compare with -1
0x40014c52  return -1 if it failed        ; init aborts
0x40014c5a  [0($s1)] = [pool 0x40014CC4]  ; the sibling 0x40014C00
0x40014c5e  [4($s1)] = $a0                ; build a struct from the arguments
0x40014c64  [8($s1)] = 4($a1) (lw)
0x40014c6c  sh [0xC($s1)], 2($a1) (lhu)
0x40014c6e  li $a3,0x33 ; jalrc [0xBFC16BB1]   ; kernel syscall module 0x0f, fn 0x33
```

So: acquire a resource with a module-`0x10` service, abort on failure, then
register a structure with the kernel (module `0x0f`, function `0x33`).

### The bank table has five groups

`VERIFIED`. Groups at `0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700, 0x800,
0x900, 0xA00, 0xB00, 0xC00, 0xD00, 0xE00, 0xF00, 0x1000` — the README says
blocks of 64 entries per group, with the length word at `0x2c` understating it.
Earlier scans in this project covered only `0x100` and `0xA00`, which missed
`music.ap`'s entry bank at table offset `0x100` region and the mask bank at
`0x10c`.

## Call graphs (older section) No verified edge exists yet from the Music application
entry through All Songs to playback. This is the open task; see
[m3u-integration.md](m3u-integration.md#handoff).

## Traps to avoid, summarised

- NUL-splitting an extension array yields `FLACAPE`/`JPEGDSF`; the stride is what
  matters.
- `M3U.LIB` is a media library, not a playlist database, despite the name.
- The extension masks are not bit selectors of the arrays; see
  [m3u-integration.md](m3u-integration.md).
- `atjboottool` output directories need a trailing separator.
