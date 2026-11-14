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

### `0x9FC15436` — a byte state slot, and a withdrawn lead

`VERIFIED` by decoding the actual instruction, and this **withdraws the lead
recommended in an earlier handoff**, which rested on a search artefact.

The write in `0x400552A0`:

```text
0x400552a8  12 b3   lw $v1, dword_400552F0   ; $v1 = the VALUE 0x9FC15436
0x400552ac  40 c3   sb $v0, 0($v1)          ; ONE BYTE stored at that address
```

The pool word at `0x400552F0` holds the address; the instruction stores a single
byte through it. So `0x9FC15436` is a **byte state slot, not a pointer** — and it
could not be a 32-bit pointer anyway, since `0x9FC15436` is only halfword-aligned
(`0x436 mod 4 == 2`). What `0x400552A0` writes is its `u8` argument.

**The "eight readers" do not exist.** Searching the image for the four bytes
`36 54 c1 9f` finds the address *literal* wherever it is embedded in a pool, so
all eight matches are pool words, not loads or stores:

| file offset | guest | bank | what it is |
|---|---|---|---|
| `0x1754` | `0x40054f54` | `0x40054c00` | pool word |
| `0x1a88` | `0x40055288` | `0x40054c00` | pool word (decodes as `slti/lw` because the bytes *are* the literal) |
| `0x1af0` | `0x400552f0` | `0x40054c00` | pool word |
| `0x2050` | `0x40095050` | `0x40094c00` | pool word |
| `0x2624` | `0x400d4e24` | `0x400d4c00` | pool word |
| `0x32f0` | `0x401152f0` | `0x40114c00` | pool word |
| `0x3fa0` | `0x40194fa0` | `0x40194c00` | pool word |
| `0x5710` | `0x40254f10` | `0x40254c00` | pool word |

`0x40055288` is the clearest demonstration: IDA decodes it as
`slti $a0,0x36` because the bytes there *are* `36 54`. Chasing it as a function
would have been the fourth false positive.

**The method error, recorded so it is not repeated:** a byte search for an
address finds the address constant, never its uses. To find readers one must
resolve `lw`/`sb`/`lbu` instructions whose *operand* names the pool word — i.e.
control-flow analysis, not a literal scan. This is the same class of mistake as
the genre-table false positive.

`0x9FC15436` sits `0x22` bytes past music.ap's declared data segment
(`0x9fc15400..0x9fc15414`), so it is undeclared application scratch. It is
written as a byte by `0x400552A0`; its readers are **not established**.

## VERIFIED browser.ap call chain

The first multi-bank chain in this project, and the first *reusable* firmware
interface. Every edge below comes from an actual instruction; the disassembly is
anchored at the header entry, never linear from a bank base.

```text
browser.ap header +0x40 = 0x40014C31
  → browser.ap:0x40014C30                      entry bank 0x40014c00, size 0xcc
      initialise: syscall(module 0x10, fn 0x10)      [pool 0x40014CC0]
                  kernel (module 0x0f, fn 0x33)       [pool 0x40014CC8]
      build struct on frame:  {fn=0x40014C00, $a0, 4($a1), lhu 2($a1)}
      kernel(module 0x0f, fn 0x4A)  with $a0 = &struct   ← CALLBACK REGISTRATION
      on failure: syscall(0x10, 0x11) then kernel(0x0f, 0x34)   [cleanup]

  → browser.ap:0x40014C00                       the registered callback
      $v0 = 0x40055174(arg, 0)                  [pool 0x40014C28 = 0x40055175]
      syscall(module 0x10, fn 0x0E)  with (i8)$v0   [pool 0x40014C2C]

  → browser.ap:0x40055174                       bank 0x40054c00, +0x574
      *[0x9fc154dc] = arg                       [pool 0x40055208]  state byte
      jal 0x40054C40 ; jal 0x40054DD0 → u16 result
      loop while *[0x9fc154d4] != 0:            [pool 0x4005520C]  flag byte
        flag == 1 → indirect  [0x40055210] = 0xBFC16579 → 0xBFC16578
        flag == 2 → jal 0x4009508C               CROSS-BANK, bank 0x40094c00
        else     → *[0x9fc154d4] = 0
        jal 0x40055110 with $a0 = the frame      [own struct passed on]
      exit: jal 0x40054F14(result)
            kernel(0x0f, …) with (0x9fc15408, 0x00070000, 0xA8, 0x13)

  → browser.ap:0xBFC16578                       resident, +0x178
      state = *[0x9fc154dc]
      state == 1        → skip to 0xBFC16622
      state == 9 or 10  → 0xBFC165E6
      else: flag = 1 ; jal 0xBFC164B4
            if it returns 0 → *[frame+0x20] = 0x8D04 (a NEGATIVE error code)
            else → [0x19]=1, [0x18]=1

  → browser.ap:0xBFC164B4                       resident, +0xb4
      0x7805b400(':')                            [pool 0xBFC16560 = 0x7805b401]
      0x7805b400('/', *0xbfc166fc)               [pool 0xBFC16564]  resident buffer
      fallback: 0x780db200(...)                  [pool 0xBFC16568 = 0x780db201]
      0x780db200('/', *0xbfc1670c)               [pool 0xBFC1656C]
```

### What this establishes

- **The application registers a callback with the kernel.** The entry builds a
  four-field structure — first field a MIPS16e function pointer, then a pointer,
  a loaded word and a loaded halfword — and passes its address to kernel function
  `0x4A` (module `0x0f`). The kernel invokes `0x40014C00` later. This is the
  pattern the M3U integration can reuse, and it is the first reusable interface
  found. `VERIFIED`.
- **The registered function is an event loop**, not a one-shot handler: it waits
  on a flag byte at `0x9fc154d4`, dispatches on 1 and 2, and passes its own frame
  as a struct to `0x40055110`. `VERIFIED`.
- **`0xBFC16578` is a state dispatcher** over a state byte at `0x9fc154dc`, with
  1, 9, 10 special-cased and everything else falling through to `0xBFC164B4`.
  `VERIFIED`.
- **`0xBFC164B4` is a path builder**, not a file opener: it hands the characters
  `':'` and `'/'` to a service in bank `0x7805b200` with resident buffer pointers.
  `VERIFIED`.
- `0x7805b200` in browser.ap is a **path/text service** — a third distinct meaning
  for that bank address across modules. One more confirmation that a guest address
  means nothing without its module. `VERIFIED`.
- **Shared status codes.** `0x8014` (expected success) and `0x8D04` (a negative
  error, `-0x72FC` as i16) appear in *two* separate functions — `0xBFC16578`'s
  failure path and `0x4009508C`'s — and `0x8014` is one of the same `0x80xx`
  family the music.ap dispatcher compares. This is the firmware's status-code
  range. `VERIFIED`.
- **`0x40C14C00` is a shared service reached from the browser.** It takes a
  16-bit code and a five-byte descriptor `{1, 3, 0, 0, 0}`, and it is the entry
  point of its own bank — so several modules can call it. `VERIFIED` for the call
  edge and the argument shape.

### The limit of this chain, demonstrated not assumed

The chain is verified down to the call `0x400950b0`, and **no further**. `0x40C14C00`
is one function spanning `0x40c14c00..0x40c14e7c` (the bank's only `jrc $ra`, at
`+0x27c`; everything after `0x40c14e80` is data, including the string `AHEH` at
`+0x280`). Inside it, the instruction IDA decodes as
`lw $v0, dword_40C14E80 ; jalrc $v0` would call `0x48454841` — the ASCII at
`+0x280`.

So either IDA is mis-resolving that operand, or the call is genuinely bogus, and
**a single linear disassembly of the body cannot tell the two apart.** That is the
same failure mode as the genre table, caught here before it produced a false edge.
The body needs re-derivation from a second anchor before any of it is cited.

`UNVERIFIED`: everything below `0x400950b0`, including the meaning of code
`0x6002`, descriptor `{1,3,0,0,0}`, and the two status codes.

### What is still unknown

- What kernel function `0x4A` does with the struct beyond invoking the callback.
- Which of `flag == 1` vs `flag == 2` is a file selection rather than a directory
  change — `flag == 2` calls across banks into `0x40094c00`, `flag == 1` reaches
  the path builder.
- Whether the path built by `0xBFC164B4` ever reaches an open, or only prepares it.
- The playback entry point: not reached from anything established here.

### Neither recovered path leads to a stock UI or playback operation

`0x400552A0` → `0x40614FC0` is a compute-a-status-then-dispatch pair, and the
status slot it writes is only reachable by an unestablished reader. **Neither
gives an interface our M3U code can call.**

## VERIFIED mengine.ap: the engine dispatch table and `get_location`

The strongest result of the engine investigation, and the first genuine dispatch
table found. Every pointer below resolves to a valid bank and carries the
MIPS16e ISA bit.

```text
mengine.ap bank 0x7a052d00 (file 0x5600, size 0x638, code to +0x3a8)

  [0] +0x3a8  0x7a0530a8 = 0x7b06856d → 0x7b06856c   bank 0x7b068000  get_location
  [1] +0x3ac  0x7a0530ac = 0x7b228119 → 0x7b228118   bank 0x7b228000  state reader
  [2] +0x3b0  0x7a0530b0 = 0x7b1283ad → 0x7b1283ac   bank 0x7b128000
  [3] +0x3b4  0x7a0530b4 = 0x7b0685f5 → 0x7b0685f4   bank 0x7b068000  ← driver base
  [4] +0x3b8  0x7a0530b8 = 0x7b2281b9 → 0x7b2281b8   bank 0x7b228000
  [5] +0x3bc  0x7a0530bc = 0x7b128245 → 0x7b128244   bank 0x7b128000
  [6] +0x3c0  0x7a0530c0 = 0x7b0e81f9 → 0x7b0e81f8   bank 0x7b0e8000
  [7] +0x3c4  0x7a0530c4 = 0x7b1e81e1 → 0x7b1e81e0   bank 0x7b1e8000
```

**Eight** entries, not five — the earlier count stopped where the dump stopped.
All eight resolve to a valid bank, so the table's bounds are `0x7a0530a8` to
`0x7a0530c8`, and the driver's base `0x7A0530B4` is **entry 3**, i.e. the driver
uses the subset from entry 3 onward. That resolves the address discrepancy
without either address being wrong: one is the table start, the other is where
the driver's indexed subset begins. `VERIFIED`.

`VERIFIED` by bank-table resolution of all eight targets. Entries 0 and 3 are in
bank 0x7b068000; 1 and 4 share 0x7b228000; 2 and 5 share 0x7b128000; 6 and 7 are
in 0x7b0e8000 and 0x7b1e8000. The pattern is three bank-pairs, which suggests the
table is grouped by subsystem rather than being a flat list.

**Effective index range:** the driver indexes from entry 3, so driver indices
0–4 are valid (five handlers). Indices 5 and up would read past `0x7a0530c8` into
the zero tail of the bank and call address 0 — so **the driver has exactly five
reachable handlers**, which is worth knowing before treating any index as safe.

### `mengine.ap:0x7b06856c` — the record-to-file operation

`VERIFIED` by anchored disassembly. It is the function the upstream docs call
`get_location`, and it is the **record → file resolution** this project has been
looking for:

```text
0x7b06856c  save 0x28, $ra,$s1
0x7b068570  [0x10($s1)] = $a0          ; arg0 = a record/struct pointer
0x7b068574  [0x14($s1)] = $a1          ; arg1 = a byte
0x7b068576  struct->4 = *[0x9fc15f28]  ; [pool 0x7B0685D8]
0x7b06857e  $a0 = *[0x9fc15f34]       ; [pool 0x7B0685DC]
0x7b068586  sw 3, 0x10($sp)           ; 5th arg = 3
0x7b068596  jalrc [0x7B0685E0]        ; = 0xBFC11CCD → FILESYSTEM syscall,
                                       ;   module 0x11, stub at 0xbfc11ccc
                                       ;   verified 'li $v1,0x11 ; break'
            ; (*[0x9fc15f34], struct+0x10, struct+8, 0, 3)
0x7b06859e  if (zeb(result) == 0) → return 0        ; failure
0x7b0685a8  struct->0    = [0x9fc15f38][3]          ; [pool 0x7B0685E4]  byte
0x7b0685b6  struct->1    = *[0x9fc15f22]            ; [pool 0x7B0685E8]  byte
0x7b0685be  struct->0x5C = *[0x9fc15f26]            ; [pool 0x7B0685EC]  u16
0x7b0685c8  struct->0x5E = *[0x9fc15f24]            ; [pool 0x7B0685F0]  u16
0x7b0685cc  return 1
```

So: it takes a record pointer, asks the **filesystem** to resolve it (module
`0x11`, function `3`), and on success fills the struct with the file's location
— including the **u16 pair at `+0x5C`/`+0x5E`**, which is the same field shape
as the 16-byte location in the `M3U.LIB`/`MUSIC.LIB` records at `+0xa9`.

The globals it reads form one contiguous block:

| global | read as | fills |
|---|---|---|
| `0x9fc15f28` | word | `struct+4` |
| `0x9fc15f34` | word | argument to the fs syscall |
| `0x9fc15f38` | byte `[3]` | `struct+0` |
| `0x9fc15f22` | byte | `struct+1` |
| `0x9fc15f26` | u16 | `struct+0x5C` |
| `0x9fc15f24` | u16 | `struct+0x5E` |

`0x9fc15f22..0x9fc15f38` is therefore the engine's "current file" state block.

### What this gives the M3U feature

A **reusable, verified interface**: `get_location(struct, byte)` returns 1 and
fills the struct's location fields on success. That is exactly the operation the
`m3udb` adapter needs — it already produces a record, and this is the step from
record to a filesystem-resolvable file.

`UNVERIFIED`, and the reason no adapter is written yet:
- the **filesystem call's argument order** — in particular which of
  `*[0x9fc15f34]`, `struct+0x10` and `struct+8` is the input record and which is
  the output buffer;
- what function `3` of module `0x11` does;
- whether the struct `get_location` fills is the same one the caller passes, so
  the ownership of the buffer;
- whether entries 1, 2 and 4 of the table are the playback entry points.

## CROSS-VALIDATED: the engine's file-descriptor struct and state block

`VERIFIED`, and validated by **two independent functions in two different banks**
that read the same globals and fill the same struct fields. This is the only
struct layout in this project supported by more than one witness.

`mengine.ap:0x7b228118` (bank `0x7b228000`, dispatch-table entry 1) is the pure
state-reader sibling of `0x7b06856c`: same prologue shape, **no filesystem
call**, and it fills the same fields from the same globals.

The two share five globals — `0x9fc15f38`, `0x9fc15f22`, `0x9fc15f26`,
`0x9fc15f24`, `0x9fc15f28` — and write the same four struct offsets. Because they
agree, neither can be a mis-decode of the other.

```text
mengine engine file/record descriptor:

  +0x00  byte   ←  [0x9fc15f38]+3
  +0x01  byte   ←  *[0x9fc15f22]
  +0x02  u16    ←  *[0x9fc15f60]     (0x7b228118 only)
  +0x04  word   ←  *[0x9fc15f28]     (get_location only)
  +0x5C  u16    ←  *[0x9fc15f26]
  +0x5E  u16    ←  *[0x9fc15f24]
  +0x60  u16    ←  *[0x9fc15f74]     (0x7b228118 only)
  +?     u16    ←  *[0x9fc15f76]     (0x7b228118 only)
```

The globals form one contiguous **engine state block**, `0x9fc15f22..0x9fc15f78`:

| global | read as | role |
|---|---|---|
| `0x9fc15f22` | byte | descriptor `+1` |
| `0x9fc15f24` | u16 | descriptor `+0x5E` |
| `0x9fc15f26` | u16 | descriptor `+0x5C` |
| `0x9fc15f28` | word | descriptor `+4`, and an argument |
| `0x9fc15f34` | word | argument to the filesystem call |
| `0x9fc15f38` | byte `[3]` | descriptor `+0` |
| `0x9fc15f60` | u16 | descriptor `+2` |
| `0x9fc15f74` | u16 | descriptor `+0x60` |
| `0x9fc15f76` | u16 | descriptor tail |

So the pair `0x9fc15f24`/`0x9fc15f26` feeding `+0x5E`/`+0x5C` is the same
field shape as the 16-byte location in the `M3U.LIB` records at `+0xa9` — two
u16s, adjacent.

### Why this matters for the M3U adapter

The `m3udb` adapter already produces a record. The missing step was "turn this
record into a filesystem object", and the engine has exactly that operation
(`get_location`), plus a cached-state reader that shows the result layout. Both
are in a **dispatch table**, so they are called through a stable indirection
rather than a hard-coded address.

### What is still unverified, and why no adapter was written

- The **filesystem call's argument order** in `get_location`: which of
  `*[0x9fc15f34]`, `struct+0x10`, `struct+8` is the input record and which is
  the output buffer. Getting this backwards would corrupt the record in place.
- Module `0x11` function `3`'s semantics.
- Whether the descriptor the caller passes is the one filled (ownership).
- Entries 2 and 4 of the table — untraced, so possibly the playback entry
  points, but unproven.

None of these can be settled from a single anchored disassembly, so writing an
adapter now would mean guessing an ABI — which is what this project's earlier
false positives all amounted to. The adapter is written when the argument order
is established from a caller-side view.

## VERIFIED: the runtime dispatch driver

`mengine.ap:0x7A052E34` (bank `0x7a052d00`, `+0xe34`). This is the code that
*uses* the dispatch table, so it settles both the table's real base and how a
handler is chosen at runtime. `VERIFIED` by anchored disassembly.

```text
0x7a052e34  save 0x18, $ra
0x7a052e36  $v0 = [0x9fc15f21]          ; a byte
0x7a052e3c  *$v0 = 0                    ; clear it
0x7a052e3e  $t8 = $a0                   ; save the argument
0x7a052e40  beqz $a0 → return            ; nothing to do
0x7a052e42  $a2 = [0x9fc15f20]          ; AN INDEX, read from RAM
0x7a052e44  $v1 = [0x7a0530b4]          ; the table base
0x7a052e46  $v0 = lbu 0($a2)
0x7a052e48  sll $a3, $v0, 2             ; index * 4
0x7a052e4a  addu $a2, $a3, $v1          ; &table[index]
0x7a052e4c  lw  $v0, 0($a2)             ; the handler pointer
0x7a052e4e  jalrc $v0                   ; call it, with ($a0, zeb($a1))
0x7a052e50  $t8 = $v0
0x7a052e52  return $t8
```

Two consequences that correct the table note above:

- **The table's real base is `0x7A0530B4`, not `0x7a0530a8`.** The driver reads
  that address as its base, so the pointer at `0x7a0530a8` (`0x7b06856d`,
  `get_location`) is the entry *before* the driver's base and belongs to a
  preceding group.
- **Handlers are selected by a RAM byte at `0x9FC15F20`**, not by a compile-time
  index. `0x7a052e36`–`0x7a052e3c` also clears a byte at `0x9FC15F21` on every
  call, so the engine keeps a small state block and a mode byte side by side.

So the engine's handler indirection is: a mode byte in RAM selects which
function in a bank-resident table runs, and the selected function is called with
the caller's own arguments passed straight through. That is a genuinely reusable
pattern and the first *dynamic* dispatch established in this project.

`UNVERIFIED`: which mode values select which entries — that needs the writer of
`0x9fc15f20`, which was not traced this session.

## The bank entry: a mode dispatcher, decode SUSPECT

`mengine.ap:0x7A052D00` is the first function of bank `0x7a052d00`, and it reads
the mode byte at `0x9FC15F20`:

```text
0x7a052d00  save 0x18, $ra
0x7a052d02  lw  $v0, [0x9fc15f20]        ; the mode byte's address
0x7a052d04  lw  $a1, [0x9fc15f21]        ; a neighbouring state byte
0x7a052d06  lbu $a3, 0($v0)              ; mode
0x7a052d08  lw  $v1, [0x7a0530d8]        ; claimed to be a second table base
0x7a052d0c  sb  $a2, 0($a1)              ; *[0x9FC15F21] = 0
0x7a052d0e  sll  $a2, $a3, 2             ; mode * 4
0x7a052d10  addu $a1, $a2, $v1
0x7a052d12  lw  $v0, 0($a1)
0x7a052d14  jalrc $v0
```

**The decode is suspect and is not used.** Following it through, the word at
`0x7A0530D8` is `0x9FC15F20` — a RAM address, not an instruction — so for mode 0
the `jalrc` would jump into RAM. Either the operand resolution is wrong or the
call is nonsense, and a single linear pass cannot tell which. This is the fourth
time a decode has produced a non-instruction target, and the rule that has
emerged each time is the same: **a decode whose terminal target is not an
instruction is not yet a decode.**

What survives is the shape — the bank entry reads the mode byte, clears the byte
next to it, and dispatches — and the observation that `0x9FC15F20`'s address
appears in **ten separate pools** within this one bank (`+0x24, +0x4c, +0x84,
+0xc0, +0x160, +0x19c, +0x1cc, +0x1fc, +0x22c, +0x2d8`), so roughly ten functions
here are gated on that byte.

`UNVERIFIED`: the mode values and their handlers; the writer of `0x9FC15F20`;
the second table's real base.

## VERIFIED: the engine's shared current-file state block

`0x9FC15F20..0x9FC15F38` is referenced by **about 22 engine banks**, all of them.
This is not an incidental cluster — it is the engine's cross-bank shared state.

| global | pool refs across mengine.ap | role |
|---|---|---|
| `0x9FC15F20` | 166 | the mode byte |
| `0x9FC15F21` | 333 | a byte cleared on dispatch |
| `0x9FC15F22` | 320 | descriptor `+1` |
| `0x9FC15F24` | **821** | descriptor `+0x5E` — the most-referenced member |
| `0x9FC15F26` | **876** | descriptor `+0x5C` — the most-referenced member |
| `0x9FC15F28` | 416 | descriptor `+4`, and an fs-call argument |
| `0x9FC15F34` | **765** | the fs-call context |
| `0x9FC15F38` | 425 | descriptor `+0` (byte `[3]`) |

Banks naming the whole block include `0x60010d00`, `0x60050d00`, `0x60090d00`,
`0x600d0d00`, `0x60110d00`, `0x60150d00`, `0x60190d00`, `0x601d0d00`,
`0x60210d00`, `0x7a012d00`, `0x7a052d00`, `0x7a092d00`, `0x7a0d2d00`,
`0x7b028000`, `0x7b068000`, `0x7b0a8000`, `0x7b0e8000`, `0x7b128000`,
`0x7b168000`, `0x7b1a8000`, `0x7b1e8000`, `0x7b228000`.

The three most-referenced members are `0x9FC15F26`, `0x9FC15F24` and
`0x9FC15F34` — and the first two are exactly the **u16 pair** that `get_location`
and the state reader both write into a descriptor's `+0x5C`/`+0x5E`, which is the
same shape as the 16-byte location field in the `M3U.LIB`/`MUSIC.LIB` records at
`+0xa9`.

**So the engine's notion of "the current file" is a shared RAM block, and its
most-used component is that location pair.** That is the single most useful fact
this project has produced for the M3U feature: a playlist adapter's job is to put
the selected track's location into `0x9FC15F24`/`0x9FC15F26` and tell the engine
to play, rather than to reimplement any file handling.

**Caveat, stated plainly:** these are counts of *pool words naming the address*,
not of instructions. They establish that the block is shared — which is a
structural fact — but not what any individual instruction does with it. The
same literal-scan discipline applies here as everywhere else.

## `get_location`'s ABI — what is inferred, and from what

`INFERRED`, with the evidence:

- The state reader `0x7b228118` has **no filesystem call** and copies the same
  five globals into the same descriptor offsets that `get_location` writes.
- If the globals were outputs of `get_location`'s fs call, the state reader would
  be reading a *result*; if they are the cached current file, both functions are
  snapshots.
- The far more likely reading, given the block is engine-global and
  heavily-referenced: **the globals are the engine's current-file state**, and
  both functions copy from it into a per-call descriptor.

So `get_location($a0 = descriptor, $a1 = byte)` most likely:
1. asks the filesystem (module `0x11`, fn `3`) to make the current context ready
   — `*[0x9FC15F34]` is that context, `record+0x10` the input side;
2. copies the resulting state from the globals into the descriptor.

`UNVERIFIED` and the reason there is no wrapper: **which of `*[0x9FC15F34]`,
`record+0x10` and `record+8` is input and which is output is not established**,
and getting it backwards would write through a caller-supplied pointer. No
caller of `get_location` was found this session — its pointer appears exactly
once, in the table — so the caller-side view that would settle it is still
missing.

## VERIFIED: the get_location caller and the mode-0 mapping

`mengine.ap:0x7A052E64` (bank `0x7a052d00`, `+0x164`) is the caller that reaches
`get_location`, and it settles two things at once.

```text
0x7a052e64  save 0x18, $ra
0x7a052e66  lw  $v1, [0x9fc15f24]        ; the location global's ADDRESS
0x7a052e68  lw  $a2, [0x9fc15f21]         ; the flag byte's ADDRESS
0x7a052e6a  lhu $v0, 0($v1)              ; $v0 = the u16 AT 0x9FC15F24
0x7a052e6e  zeb $a1                       ; $a1 = arg1, zero-extended
0x7a052e70  sb  $a3(0), 0($a2)           ; *[0x9FC15F21] = 0
0x7a052e72  beqz $v0  → return 0          ; no location → nothing to do
0x7a052e74  beqz $a0  → return 0          ; no argument  → nothing to do
0x7a052e76  lw  $a2, [0x9fc15f20]        ; the MODE byte's ADDRESS
0x7a052e78  lw  $v1, [0x7a0530a8]        ; THE TABLE START
0x7a052e7a  lbu $v0, 0($a2)              ; mode
0x7a052e7c  sll $a3, $v0, 2              ; mode * 4
0x7a052e7e  addu $a2, $a3, $v1           ; &table[mode]
0x7a052e80  lw  $v0, 0($a2)              ; table[mode]
0x7a052e82  jalrc $v0                    ; call it with ($a0, zeb($a1))
0x7a052e84  restore; jrc $ra
```

Two results:

- **Mode 0 selects `get_location`.** This function indexes the table from its
  start `0x7A0530A8`, so `mode == 0` picks `table[0]` = `0x7b06856c`. `VERIFIED`.
- **`*[0x9FC15F24]` is the guard.** If that u16 is zero the handler never runs, so
  a nonzero value at `0x9FC15F24` is what means "a file is current". That is the
  same field `get_location` writes into descriptor `+0x5E`. `VERIFIED`.

It also explains the two dispatchers: `0x7A052E64` uses the table **start**
(`0x7A0530A8`, modes 0–7) while `0x7A052E34` uses the **subset** from entry 3
(`0x7A0530B4`). They are two different views of one table, not a discrepancy.

`UNVERIFIED`: which mode values callers actually set, and therefore which of
`table[1]`–`table[7]` a given caller reaches. Only mode 0's target is established.

## VERIFIED: the mask writer, and the engine's interface pool

`mengine.ap:0x60050F40`-region, in bank `0x60050d00` (file `0x1000..0x1800`). This
is the function that finally settles whether the extension masks are used, and
they are.

Its pool, at guest `0x60051010`:

```text
0x60051010  0x7e190ea0   the documented MUSIC.LIB extension mask
0x60051014  0x9fc15d90   RAM
0x60051018  0x7a012d01 → 0x7a012d00   an engine bank entry
0x6005101C  0x9fc15c80   RAM
0x60051020  0x7a052e35 → 0x7a052e34   dispatcher A
0x60051024  0xbfc11ccd → 0xbfc11ccc   filesystem module 0x11 stub
0x60051028  0xbfc11cc1 → 0xbfc11cc0   a second module 0x11 stub
```

The data flow:

```text
0x60050f4a  $v0 = 0x7e190ea0
0x60050f4c  frame+4 = $v0
0x60050f52  *[0x9FC15D90] = $v0        ← THE MASK IS PUBLISHED TO RAM

0x60050f58  jalrc 0x7a012d00           ; (frame, 0)
0x60050f60  *[0x9FC15C80] = result     ; a status is published too

0x60050f78  jalrc 0x7a052e34           ; dispatcher A (frame+0x10, frame+0x14)
0x60050f7c  frame+0x15 = result
0x60050f7e  if (frame+0x15 == 1):
0x60050f9a    jalrc 0xbfc11ccc         ; fs(module 0x11, FUNCTION 2)
                                            (*[0x9FC15C80], frame+8, 0, 0, 2)
0x60050fae    jalrc 0xbfc11cc0         ; (frame+8, frame+0x14, 3, 5)
```

Three results, each `VERIFIED`:

1. **The extension mask `0x7e190ea0` is live.** It is written into the RAM global
   `0x9FC15D90` by a function that then drives the dispatcher. The mask is not
   dead data, which completes the picture begun in `docs/library-builder.md`.
2. **Filesystem module `0x11` has at least two functions in use here** — `2` via
   the `0xbfc11ccc` stub and an unnumbered call via `0xbfc11cc0` with
   `(frame+8, frame+0x14, 3, 5)`. Note this is **function 2, not 3**; `get_location`
   uses function 3, so the module's functions are distinct operations.
3. **A second engine bank entry** (`0x7a012d00`) is called before the dispatcher,
   so bank `0x7a012d00` is on the live path too — it was already known to name the
   state block.

`UNVERIFIED`: what `0x7a012d00` does; what the mask does once published to
`0x9FC15D90`; who reads `0x9FC15C80`; the roles of the `(frame+8, frame+0x14, 3, 5)`
arguments.

The relevant discipline applies to this pool exactly as elsewhere: it was found by
resolving pool words to *instructions that load them*, not by scanning for the mask
value. Scanning for `0x7e190ea0` alone would have found the mask literal in many
places (it appears in fifteen pools across the image) without revealing this writer.

## VERIFIED: the record preparer `mengine.ap:0x7A012D00`

Bank `0x7a012d00` (file `0x5000`, size `0x5b8`). This is the function the
interface at `0x60050f40` calls *before* the dispatcher, so it is the stage that
reads a record and primes the engine.

```text
0x7a012d00  save 0x30, $ra,$s0-$s1
0x7a012d04  frame+0x20 = $a0             ; arg0 = a record pointer
0x7a012d08  frame+0x24 = $a1             ; arg1 = a byte
0x7a012d0c  *[0x9FC15F21] = 0            ; clear the flag
0x7a012d12  *[0x9FC15F34] = -1           ; invalidate the fs context
0x7a012d1c  if (arg0 == 0) → frame+8 = -1, return      ; null guard
0x7a012d26  $a0 = 0x9FC15F38            ; a RAM address, passed BY VALUE
0x7a012d2c  $a1 = arg0                   ; the record
0x7a012d2e  $a2 = 8                      ; LENGTH 8
0x7a012d32  jalrc 0xbfc11cc0             ; fs stub #2 (0x9FC15F38, arg0, 8, 0)
0x7a012d36  ... mask byte 1 of a struct with 0xF, write it back
0x7a012d44  $v1 = arg0[1]
0x7a012d48  $v0 = 0xF0
0x7a012d4a  and
0x7a012d4e  if (arg0[1] & 0xF0)  → *[0x9FC15F23] = 1
0x7a012d56  else                  → *[0x9FC15F23] = 0
0x7a012d5c  $v0 = arg0[3]
0x7a012d60  sltiu $v0, 8
0x7a012d62  if (arg0[3] < 8) → the validation path at 0x7A012DC2
```

Its pool, at guest `0x7A012ED0`:

| address | value | what |
|---|---|---|
| `0x7A012ED0` | `0x9FC15F21` | cleared |
| `0x7A012ED4` | `0x9FC15F34` | set to `-1` |
| `0x7A012ED8` | `0x9FC15F38` | passed as a pointer to the fs stub |
| `0x7A012EDC` | `0xBFC11CC1` | **filesystem module `0x11`, a SECOND stub** |
| `0x7A012EE0` | `0x9FC15F23` | set from `arg0[1] & 0xF0` |
| `0x7A012EE4`/`EE8` | `0x7A0130B4`, `0x7A013084` | in-bank data |

Four results, each `VERIFIED`:

1. **Filesystem module `0x11` has at least two distinct stubs in live use.**
   `0xbfc11ccc` takes function `3` (used by `get_location`); `0xbfc11cc0` is
   called here with a **length of 8** and no function-id argument. So the two are
   different services, and the module's functions are not interchangeable.
2. **The engine's record preparation validates the record's own bytes** — `arg0[1]
   & 0xF0` becomes a boolean at `0x9FC15F23`, and `arg0[3] < 8` gates a path.
   Those are record fields, not descriptor fields.
3. **`0x9FC15F34` is invalidated (`-1`) before every use.** It is the fs context
   `get_location` passes as its first argument, so the context is per-operation
   rather than a persistent handle.
4. **This function is not the mode writer.** It touches `0x9FC15F21`,
   `0x9FC15F34`, `0x9FC15F23` and `0x9FC15F38` but **not** `0x9FC15F20`.

`UNVERIFIED`: what `0xbfc11cc0` does with `(0x9FC15F38, record, 8, 0)`; what
record layout has bytes 1 and 3 in those roles — the `M3U.LIB` record has its
title at `+0`, so if `arg0` points at a *library* record then byte 1 is inside
the title, which would mean the preparer takes a different structure; who writes
`0x9FC15F20`.

The `8` is the most useful single fact: it is a byte count, and eight bytes is
exactly the size of the two u16s plus a word — or of a packed extension plus
fields — so the call is probably reading an eight-byte group out of the record
into `0x9FC15F38`.

## VERIFIED: the engine's driver-name table

Immediately after the record preparer's pool, in bank `0x7a012d00` at guest
`0x7A013084`, is a table of **driver names** at 12-byte stride:

| guest | string |
|---|---|
| `0x7A013084` | `nand.drv` |
| `0x7A013090` | `card.drv` |
| `0x7A01309B` | `cards.drv` |
| `0x7A0130A8` | `uhost.drv` |
| `0x7A0130B4` | *(empty — the slot after the last)* |

`VERIFIED` by decoding the bytes in place; these are real NUL-terminated names,
not fragments of a longer blob.

The record preparer's pool names two of these slots directly:
`0x7A012EE8 = 0x7A013084` (the first, `nand.drv`) and
`0x7A012EE4 = 0x7A0130B4` (one past the last). That pairing — a first element and
one-past-the-last — is the shape of a **search loop**, so the preparer almost
certainly walks this table to decide which driver a record belongs to.

The four names match the firmware's storage backends exactly: `nand.drv` (NAND
flash), `card.drv` (SD), `cards.drv`, `uhost.drv` (USB host). The engine chooses
among them by driver name, so **the engine addresses a file as driver + path, not
as a bare pathname**.

### Why this matters for the M3U adapter

The adapter's job is not "open a path" but "open a path *on a given driver*".
That changes the interface: the engine needs both a driver identifier and the
file's path. It also explains `0x9FC15F24`/`0x9FC15F26` — two u16s is exactly the
shape of a *cluster and offset* pair, which is how a location is expressed once
the driver is chosen.

`UNVERIFIED`: which field of a record names the driver (a byte index into this
table, or a string?), and whether `0x7A0130B4` being empty means the table is
four long or that a fifth slot is reserved.

### Combined with the earlier findings, the resolver is now mostly shaped

Putting the session's results together, the operation the adapter needs is:

```text
record (with a driver name index and a location)
  → mengine.ap:0x7A012D00   validate the record's bytes 1 and 3
                            clear *[0x9FC15F21], invalidate *[0x9FC15F34]
                            call fs module 0x11 stub 0xbfc11cc0
                              with (0x9FC15F38, record, 8, 0)
  → mengine.ap:0x7b06856c   get_location(descriptor, byte)
                            fs module 0x11 stub 0xbfc11ccc, function 3
                            fills descriptor +0, +1, +4, +0x5C, +0x5E
  → playback
```

Both fs calls are present, both stubs verified, the descriptor layout is
cross-validated, and the driver table is decoded. What is *still* missing is the
ordering of `get_location`'s three pointer arguments, which comes from the caller
of `0x7A052E64`.

## VERIFIED: the call edge into `0x7A052E64`, and a state-block magic

**Stage A's acceptance criterion.** All three candidate sites are pool words in
three different banks, and the one in bank `0x60050d00` is *used*:

```text
0x60050fee  lw  $v0, [0x60051030]        ; = 0x7A052E65 → 0x7A052E64
0x60050ff0  jalrc $v0
```

with, immediately before:

```text
0x60050fe6  lw  $v0, 0x10($s1)
0x60050fe8  lbu $v1, 0x14($s1)
0x60050fea  move $a0, $v0
0x60050fec  move $a1, $v1
```

So the caller is `mengine.ap:0x60050fee` and it passes **frame+0x10 as arg0 (a
descriptor pointer) and frame+0x14 as arg1 (a byte)**. `VERIFIED` by instruction
evidence, not by address literal.

The other two sites — bank `0x600d0d00` and bank `0x60190d00` — are pool words in
the same shape and are `UNVERIFIED` as call edges (they may be unused copies).

### The same bank also initialises the state block with a magic

```text
0x60050d24  lw  $v0, [dword_60050EAC]     ; a RAM pointer
0x60050d26  lhu $v0, 0($v0)
0x60050d28  cmpi $v0, 0x55B9             ← the magic
...
0x60050d4c  li  $v0, 0x55B9
0x60050d4c  sh  $v0, 0($v1)              ← it is WRITTEN on the miss path
```

So `0x55B9` is a **signature stored into and compared against a RAM global** — a
state-validity check, in the same function that publishes the extension mask.

**Correction to the first draft of this note, which implied the magic was part of
the engine state block. It is not.** Resolving `dword_60050EAC` gives
`0x9FC15DD4`, which is *outside* `0x9FC15F20..0x9FC15F38`. So the magic belongs
to a **separate RAM region**, and the two should not be conflated.

### Where the descriptor comes from

`frame+0x10` is **never written** anywhere in bank `0x60050d00`'s code, so it is
an *input* to this function, not something it builds. That matters: the
descriptor passed to `0x7A052E64` — and hence to `get_location` — is supplied by
this function's own caller. Chasing its origin means going one more frame up.

`0x7a012d00` is called with `$a0 = $s1` (this function's own frame) and reads
`frame[1]` and `frame[3]`, so the record it validates is at the *start* of the
frame while the descriptor is further along it.

## Two distinct RAM regions, not one

Resolving the magic's pointer makes this worth stating separately, because
earlier notes blurred them together.

```text
region A — library/config, ~0x9FC15C80..0x9FC15DD4
  0x9FC15C80  a status word, written by 0x60050f60 and compared to -1
  0x9FC15D90  the published extension mask 0x7e190ea0
  0x9FC15DD4  the 0x55B9 magic, compared and written at 0x60050d28/0x60050d4c

region B — engine current-file state, 0x9FC15F20..0x9FC15F38
  0x9FC15F20  mode byte          0x9FC15F28  descriptor +4
  0x9FC15F21  cleared flag       0x9FC15F34  filesystem context
  0x9FC15F22  descriptor +1      0x9FC15F38  descriptor +0 (byte[3])
  0x9FC15F24  descriptor +0x5E
  0x9FC15F26  descriptor +0x5C
```

`VERIFIED` that both regions exist and are written by the same function
(`0x60050d00`-region). `VERIFIED` that the magic is in region A and not in
region B — which is a correction to an earlier note here.

`UNVERIFIED`: everything in region A's meaning. The mask, the magic and the
status word are all seen being *written* there, but no reader of region A has
been traced, so an adapter must not write to either region.

The distinction matters operationally: an M3U adapter that wanted to set the
current file would target region B, whereas region A looks like configuration
(mask, magic, status) written once by the engine's own setup path.

## VERIFIED: a second caller of `0x7A052E64`, and the argument comparison

`mengine.ap:0x600d1162` (bank `0x600d0d00`, `+0x462`):

```text
0x600d1148  lw  $v0, [0x600D11A4] = 0x9fc15c80   ; region A status
0x600d114a  lw  $v1, 0($v0)
0x600d1154  btnez → skip                          ; if status == -1, do nothing
0x600d1156  lw  $v1, [0x600D119C] = 0x9fc15ce0
0x600d1158  lw  $v0, [0x600D1180] = 0x9fc15c88
0x600d115a  lbu $v0, 0x31($v0)                    ; a byte at struct+0x31
0x600d115e  move $a0, $v1                         ; arg0 = 0x9FC15CE0
0x600d1160  move $a1, $v0                         ; arg1 = that byte
0x600d1162  lw  $v0, [0x600D11A8] = 0x7a052e65
0x600d1164  jalrc $v0                             ; 0x7A052E64(0x9FC15CE0, byte)
```

### The comparison

| caller | arg0 | arg1 | gate |
|---|---|---|---|
| `0x60050fee` | `frame+0x10` — the caller's own descriptor | `frame+0x14` | region-A status `!= -1` |
| `0x600d1162` | **`0x9FC15CE0` — a fixed RAM pointer** | byte at `0x9FC15C88+0x31` | the same gate |

Both agree on the **shape**: a descriptor pointer plus a byte. They differ in
which buffer: the first passes its own, the second passes what looks like the
engine's **persistent descriptor at `0x9FC15CE0`**.

That is the strongest evidence yet for `get_location`'s signature:

```c
/* shape verified from two callers; roles still INFERRED */
int m30_dispatch(void *descriptor, unsigned char mode_or_field);
```

and it also gives the adapter a concrete answer to "which buffer": there is a
**fixed engine descriptor at `0x9FC15CE0`**, in region A's neighbourhood, that
one caller uses directly. If the second fs argument's role can be confirmed, an
adapter could reuse that buffer rather than allocating its own.

`VERIFIED`: both call edges, the argument shapes, and the shared gate.
`UNVERIFIED`: whether `0x9FC15CE0` is the engine's own descriptor or a shared
scratch; what the byte at `0x9FC15C88+0x31` selects; and the fs argument roles.

Notable in the same pool: `0x600d118c = 0xbfc11cc1` (the second fs stub again)
and `0x600d1184 = 0x601910b0` (a function in the *third* bank that also names
this dispatcher), so the three banks form a connected group.

## VERIFIED: the complete path-based file-open ABI

**This is the result the project has been missing.** It comes from decoding the
stock library-file creator `playlist.ap:0x40194c78` — the function
`docs/library-builder.md` already documents as creating `MUSIC.LIB`, and the one
our own expanded-library build exercises. It is known-working by construction.

```text
playlist.ap:0x40194c78   save 0x40, $ra,$s0-$s1
                         arg0 = a library-type index (a byte)

0x40194c8a  $v1 = index * 8
0x40194c8c  $v0 = [0x40194F8C] + index*9     ; per-type struct
0x40194c96  $a3 = 1
0x40194c9a  jalrc [0x40194F90] = 0xBFC16409  ; module 0x10: fill(ptr, 0xFF, 8, 1)

0x40194c9c  $v1 = *[0x9FC15410]              ; THE FILESYSTEM CONTEXT
0x40194ca2  stack arg = 0
0x40194ca6  $a1 = 0x3A ':'                   ; THE ROOT DRIVE
0x40194cac  jalrc [0x40194F98] = 0xBFC1640D  ; module 0x11: cd(ctx, ':', 0, 0, 0)

0x40194cb0  $a0 = 0x9FC15538                 ; the name buffer
0x40194cb8  $v1 = index * 12                 ; THE 12-BYTE STRIDE
0x40194cbe  $v0 = 0x40195244 + index*12      ; THE NAME TABLE
0x40194cc2  $a1 = $v0
0x40194cc4  jal 0x40194C00                   ; build the name into the buffer

0x40194cd2  stack arg = 5                    ; FUNCTION 5 = OPEN
0x40194cd6  $a0 = *[0x9FC15410]              ; the context
0x40194cd8  $a2 = 0
0x40194cda  $a3 = 0
0x40194cde  jalrc [0x40194F98] = 0xBFC1640D  ; fs_open(ctx, name, 0, 0, 5)
0x40194ce0  *[0x9FC1540C] = result           ; THE FILE HANDLE

0x40194cf0  stack arg = 9                    ; FUNCTION 9 = SIZE
0x40194cf6  $a1 = $s1                        ; an output buffer
0x40194cfe  jalrc 0xBFC1640D                 ; fs_size(ctx, &size, handle, 0, 9)
```

Its pool, at guest `0x40194F8C`:

| pool word | value | meaning |
|---|---|---|
| `0x40194F8C` | `0x9fc15838` | per-type struct array |
| `0x40194F90` | `0xBFC16409` | **module `0x10` stub** (string/memory) |
| `0x40194F94` | `0x9fc15410` | **the filesystem context** |
| `0x40194F98` | `0xBFC1640D` | **module `0x11` stub — the filesystem** |
| `0x40194F9C` | `0x9fc15538` | the name buffer |
| `0x40194FA0` | `0x40195244` | **the name table** |
| `0x40194FA4` | `0x9fc1540c` | **the file handle** |

And the name table itself, at `0x40195244`:

```text
[0] "MUSIC.LIB"      [1] "M3U.LIB"      [2]       [3] "ALLSONG"
```

### The ABI, as a source-level interface

```c
/* VERIFIED from playlist.ap:0x40194c78, a function our own build exercises. */
/* fs context: the word at 0x9FC15410, in playlist.ap's resident mapping.      */
/* fs stub:    0xBFC1640D. Function id is the LAST argument (5th/stack slot). */

fs_cd  (ctx, ':', 0, 0, 0);        /* op 8: change to the root drive       */
h = fs_open(ctx, name, 0, 0, 5);   /* op 5: open. name is NUL-terminated.  */
if (h == 0) { /* failure */ }
fs_size(ctx, &size, h, 0, 9);      /* op 9: size of the opened file        */
/* op 0xD read, 0xE write, 7 close — per docs/library-builder.md              */
```

**The decisive fact: `fs_open`'s second argument is a NUL-terminated filename.**
The stock code passes a name from its own table, but nothing in the call ties it
to that table. Supplying `"Playlists\foo.m3u"` opens that file.

**So the opaque function-3 ABI is not needed at all.** The indexed-location path
was one way in; a plain pathname is another, and it is already verified.

### Corrections this forces

- `get_location`'s "function 3" is **not** one of the documented filesystem
  operations (`5/6/7/8/9/0xB/0xD/0xE/0x13/…`). It may not even be a file
  operation. It is no longer on the critical path and should not be chased.
- The claim that module `0x11` has "two stubs in live use" was **wrong**:
  `0xbfc11cc0` in mengine.ap's mapping is **module `0x10`** (string/memory), not
  the filesystem. Only `0xbfc11ccc` is module `0x11`. `DISPROVEN`.
- The stub addresses are **per-module**: `0xBFC1640D` in playlist.ap's resident
  mapping, `0xBFC11CCC` in mengine.ap's. The *function ids* are the kernel's and
  are shared; the stub addresses are not.

## VERIFIED: FUN_71352810 — the per-track search in M3U.LIB

Bank `0x71352500` (music.ap file `0x19e00`, 1740 bytes). This is the function
the builder doc calls "the same search over a user playlist's 8-byte entries."

```text
0x71352810  save 0x30, $ra,$s1
0x71352814  frame+0x20 = $a0            ; the search key (a file location)
0x71352816  frame+0x24 = $a1            ; an output pointer
0x71352818  *frame+0xC = 1
0x7135281c  $a0 = 0
0x71352820  jalrc [dword_713528DC]      ; = 0x7815B4D8, a bank function
0x71352824  lhu $v0, [dword_713528E0]   ; = 0x7815B680, a bank-resident count
0x71352826  frame+6 = count

0x71352828  *(u16*)$a1 = -1              ; initialise the output to "not found"
0x71352830  if (count == 0) → return 0

0x7135283a  frame+0 = 0                 ; current index
0x7135283e  frame+2 = 0                 ; matches found
0x71352842  frame+4 = 0xB15             ; THE STARTING SECTOR
0x71352848  loop: if (frame+0 >= count) → done
0x71352850  if (frame+2 >= 0xFA0) → done  ; 4000 = the per-playlist limit
0x71352858  $v1 = frame+2 * 8            ; 8-BYTE ENTRIES
0x7135285c  $v0 = $v1 & 0x1FF            ; offset within a 512-byte sector
0x71352862  if (offset == 0) → seek to frame+4; frame+4 += 1
0x71352876  $v0 = *(frame+8)             ; the 64-entry buffer
0x71352878  lbu $v0, 0($v0)             ; compare the first byte with the key
```

Its pool at guest `0x713528DC`:

| pool word | value | what |
|---|---|---|
| `0x713528DC` | `0x7815B4D9` | fn `0x7815B4D8` — a bank function (probably seek or read) |
| `0x713528E0` | `0x7815B680` | a bank-resident u16 count |
| `0x713528E4` | `0x7815B5E0` | a bank-resident 64-entry buffer |

The bank addresses `0x7815Bxxx` are in the `0x78` group, which is a different
overlay window from the `0x71` shared banks and the `0x7b` engine banks. The
count and buffer are bank-resident, meaning they are populated by a prior call
and lost when the bank is swapped.

**What this establishes:**

1. **M3U.LIB contains per-track 8-byte entries** beyond the playlist records.
2. **The reader searches them starting at sector `0xB15`.** That sector is
   `0x162A00` bytes into the preallocated `M3U.LIB`.
3. **64 entries per sector** (512 / 8).
4. **The limit is 4000 entries** (`sltiu $v0, 0xFA0`).
5. The search key is an 8-byte file location — the same shape as `+0xa9` in
   MUSIC.LIB records and `+0xa9` in M3U.LIB playlist records.

`UNVERIFIED`: which file handle the search reads through (it uses a bank
function to do the reads); whether the ten playlist records' `+0xa9` location
selects the starting sector per playlist or whether `0xB15` is a global start;
what the eight bytes in each entry contain.

## VERIFIED: FUN_71352810 reads through music.ap's filesystem globals

The bank function at `0x7815B4D8` (bank `0x7815B200`, music.ap file `0x11200`,
size `0x5E0`) is the seek-and-read helper that `FUN_71352810` calls. Its pool
at guest `0x7815B580`:

| pool word | value | what |
|---|---|---|
| `0x7815B580` | `0x9FC1598C` | the current sector cursor |
| `0x7815B584` | `0x9FC1598E` | a flag or secondary pointer |
| `0x7815B588` | `0x9FC15980` | **the filesystem context** |
| `0x7815B58C` | `0x9FC1597C` | **the file handle** |
| `0x7815B590` | `0xBFC16BB5` | **module `0x11` syscall stub** (music.ap's mapping) |
| `0x7815B594` | `0x7815B5E0` | the 64-entry sector buffer |

The function's behaviour:

```text
0x7815b4d8  save 0x30
0x7815b4dc  $s1 = $a0 (the sector argument)
0x7815b4de  $a1 = *(u16*)0x9FC1598C       ; the current cursor
0x7815b4e6  if (cursor == sector) → return 1  ; already there
0x7815b4ea  if (cursor == 0xFFFF) → need seek
0x7815b50c  $a3 = *(0x9FC15980)           ; the fs CONTEXT
0x7815b50e  $v1 = *(0x9FC1597C)           ; the fs HANDLE
0x7815b510  $a2 = 0xB                     ; op = SEEK
0x7815b512  $a0 = *context                ; the context value
0x7815b514  $a1 = sector << 8             ; the byte offset
0x7815b518  $a3 = *handle                 ; the handle value
0x7815b51e  jalr $v0                      ; FS_OP(ctx, offset, ?, handle, 0xB)

0x7815b526  $a1 = 0xD                     ; op = READ
0x7815b528  $a0 = *context
0x7815b52a  $a3 = *handle
0x7815b530  $a1 = 0x7815B5E0              ; the 64-entry buffer
0x7135b532  $a2 = 0x200                   ; 512 bytes
0x7815b536  jalrc $v0                     ; FS_OP(ctx, buf, 512, handle, 0xD)
0x7815b53a  *(u16*)0x9FC1598C = sector    ; update the cursor
```

The syscall stub at `0xBFC16BB4` in **music.ap's** resident is
`li $v1,0x11 ; break` — module `0x11`, the filesystem.

**The fs context at `0x9FC15980` has 83 references in music.ap. The file
handle at `0x9FC1597C` has 14 references.** Both are music.ap data-segment
globals (the segment is at `0x9fc15400`, so they are at offsets `+0x580` and
`+0x57c`).

**This confirms FUN_71352810 reads through music.ap's own filesystem
globals.** The context and handle are the same ones music.ap uses for its
library access. Since the filename table at `0x7805b498` has `MUSIC.LIB` at
index 0 and `M3U.LIB` at index 1, and the library-type selection routine at
`0x7805b370` selects by index, whichever type music.ap last opened is the file
the handle refers to.

`VERIFIED`: the seek+read call shapes, the fs context and handle addresses, the
module-0x11 stub. `INFERRED`: that the handle refers to M3U.LIB (because
music.ap has both filenames in its table and the type is selected by index).

## VERIFIED: the browser's extension filtering is mask-based, not string-based

browser.ap's extension array at bank `0x71352500` bank+`0x688` (guest
`0x71352b88`, file `+0xc188`) holds 31 four-byte extension slots. No code
references the array's guest address directly -- it is reached through the bank
base `0x71352500`, which is referenced only from the bank table.

The builder doc says the folder views in `browser.ap` and `music.ap` use
MUSIC.LIB's mask (`0x7e190ea0`) OR'd with `0x00400000`. The mask bits
correspond to indices in the extension array. Files whose extension index has
a bit set in the mask are shown.

Since `M3U` is not in the extension array, it has no corresponding bit, so
`.m3u` files are not shown regardless of the wildcard slots. The `**` wildcard
does not override the mask — it is a fallback classification for files that
match no named extension, not a bypass of the mask filter.

To make `.m3u` visible in the browser, two things must change:
1. `M3U` must be added to the extension array (63 free slots are available).
2. The corresponding bit must be set in the folder-view mask.

The mask location is not yet decoded: the builder doc mentions `0x00400000`
being OR'd in "separately" but does not identify the instruction or the RAM
address. The extension-index-to-bit mapping is also not decoded ("the bit
order inside the driver isn't decoded" per the builder doc).

`UNVERIFIED`: the exact mask location, the bit-to-index mapping, and whether
adding a slot shifts the existing indices (which would corrupt every other
extension's classification).

## DISPROVEN: the M3U.LIB mask does not select M3U files by extension

The M3U.LIB mask `0x00080400` has bits 10 and 19 set. Mapping those bits
against the driver's extension table (31 slots, bit N = slot N):

- bit 10 → slot 10 = DSF
- bit 19 → slot 19 = MP1

Neither is M3U. Alternative bit orderings (reversed, 1-indexed) produce MP2 and
DFF. **No standard bit ordering maps the M3U.LIB mask to M3U or M3U8.**

This disproves the assumption that the M3U.LIB builder selects .m3u files by
setting extension-mask bits. The mask selects DSF and MP1 — audio formats —
which suggests the M3U.LIB scanner does not use the extension mask to find
.m3u files at all.

The builder doc says the M3U scanner (`FUN_40154ecc`) "has the same shape" as
the MUSIC.LIB scanner and uses a per-type limit table. The MUSIC.LIB scanner
classifies files via `FUN_40094f2c` into tag-reader types (0-8), where type 8
is "anything else." If .m3u files fall into type 8, the M3U scanner may find
them through the fallback path rather than through the extension mask.

`DISPROVEN`: the M3U.LIB mask selects .m3u files by extension.
`UNVERIFIED`: how the M3U.LIB builder actually finds .m3u files on the card.

## VERIFIED: the walker setup stores the mask in RAM past the resident

The walker setup at `0xbfc167d9` (browser.ap resident `+0x3d9`) stores the
extension mask at `0xbfc16ae8`. That address is:
- past browser.ap's resident end (`0xbfc16a34`, size `0x634`)
- inside the uncached RAM alias (`0xbfc00000` = `0x9fc00000` uncached)
- `0x9fc16ae8` = `0x9fc15400 + 0x16e8`, past the data segment (size `0x6f4`)

So the mask is a **RAM variable** in a scratch area beyond the declared data
segment, not a flash constant. The stock image has it as zero. It must be
populated at runtime by the walker setup code.

The walker setup code (from the raw bytes at resident `+0x3d9`) stores the mask
and resets the walker state before returning to the root directory. The mask
value is passed in from the caller (the library-building driver), which passes
`0x7e190ea0` for MUSIC.LIB and `0x00080400` for M3U.LIB.

**The mask is a runtime value, not a compiled constant.** The walker reads it
from RAM when filtering files. Since it is in scratch RAM past the data
segment, its meaning depends on how the walker's filtering code interprets it.

`UNVERIFIED`: how the walker's filtering code maps the mask bits to extensions;
whether the mask is compared against an extension index, a category byte, or
something else entirely.

## VERIFIED: the walker and mask are in playlist.ap's resident, not browser.ap's

The three references to `0xBFC16AE8` (the extension mask) are at file offsets
`+0x17cc`, `+0x1804`, and `+0x1874` in **playlist.ap**. These map to playlist.ap's
second resident segment (file `0x1400`, load `0xBFC16400`, size `0x7BC`), at
guest addresses `0xBFC167CC`, `0xBFC16804`, and `0xBFC16874`.

**browser.ap's resident is shorter** (size `0x634`, ending at `0xBFC16A34`), so
`0xBFC16AE8` is past browser.ap's code. The walker and its mask are
**playlist.ap-specific code**.

### The walker setup (`0xBFC167D8`, resident +0x3D8)

```text
0xbfc167d8  save 0x18, $ra,$s1
0x7bfc167dc  frame+8 = $a0              ; the MASK (0x7E190EA0 or 0x00080400)
0x7bfc167e0  frame+0xC = $a1            ; a byte flag
0x7bfc167e2  *(u32*)0xBFC16AE8 = $a0    ; STORE THE MASK to scratch RAM
0x7bfc167e8  if ($a1 == 1) call 0xBFC16784  ; reset to root
0x7bfc167fc  return 1
```

Pool: `0xBFC167D0 = 0x9FC15410` (fs context), `0xBFC167D4 = 0xBFC1640D`
(module 0x11 fs syscall stub).

### The walker next (`0xBFC16808`, resident +0x408)

```text
0xbfc16808  save 0x30, $ra,$s0-$s1
0x7bfc1680c  frame+0x18 = $a0            ; a callback
0x7bfc1680e  mode = *(u16*)0xBFC16AE2
0x7bfc16812  if (mode == 0) → return -0x82
0x7bfc1681c  else → return -0x80
0x7bfc16822  ... then loads:
               [0xBFC1686C] = 0xBFC16AE4  (an entry counter)
               [0xBFC16870] = 0xBFC16AE0  (a state pointer)
               [0xBFC16874] = 0xBFC16AE8  (THE MASK)
             and calls the fs through 0xBFC1640D (module 0x11)
```

### The walker entry wrapper (`0xBFC1687C`, resident +0x47C)

```text
0xbfc1687c  save 0x28, $ra,$s1
0x7bfc16886  jal 0xBFC16808              ; the walker next, above
```

### Scratch RAM layout

| address | use |
|---|---|
| `0xBFC16AE0` | state pointer |
| `0xBFC16AE2` | mode (u16) |
| `0xBFC16AE4` | entry counter |
| `0xBFC16AE8` | **the extension mask** |

These are in playlist.ap's resident past browser.ap's shorter code — scratch
RAM that only exists when playlist.ap (or another app with a >= 0x7BC resident)
is loaded.

**The mask is stored by the setup and the walker continuation loads it, but
the disassembly was cut off before the actual comparison.** The mask is passed
to the fs operations (module 0x11), suggesting the **filesystem driver** does
the extension classification, not the walker code itself.

`VERIFIED`: the walker setup, the mask store, the walker continuation, and the
scratch RAM layout. `UNVERIFIED`: the actual extension-comparison logic inside
the fs driver; whether the fs driver or the walker makes the admission
decision.

## VERIFIED: the 16-byte node structure and accessor functions

Bank `0x48454600` (browser.ap file `0x14900`, size `0x600`, 1504 bytes live)
contains the node-array accessor functions. The node **stride is confirmed as
16 bytes** by two independent `sll ..., 4` instructions.

### The accessor functions

| bank offset | role | evidence |
|---|---|---|
| `+0x40` | **search**: iterates nodes by advancing `s0 += 0x10`, checks `node+0` against 2 | first pool ref at +0x6c |
| `+0xa0` | **accessor**: computes `node_base + index*16` via `sll $v1, $a0, 4` | second pool ref at +0xbc |
| `+0xe0` | **setter**: computes `node_base + index*16`, writes `1` to `node+0` | third pool ref at +0xf0 |

The pool words:

| address | value | what |
|---|---|---|
| `0x484546EC` | `0x9FC15574` | the node count |
| `0x484546F0` | `0x9FC15584` | the node-array base |

### The node layout, from all witnesses

| offset | size | field | evidence |
|---|---|---|---|
| `+0x00` | 1 | status/flag (written to 1 by the setter; compared against 2 by the search) | `sb $a3(1), 0($a0)` at +0xe8; `cmpi $v0, 2` at +0x50 |
| `+0x01` | 1 | type (compared against 1 by the walker at 0xbfc168b6) | `lbu $a1, 1($s0); cmpi $a1, 1` |
| `+0x05` | 1 | **category byte** (compared against the active filter, 0xFF = any) | `lbu $v1, 5($s0); xor $a1, $v1; cmpi $v1, 0xFF` at 0xbfc168c6-ce |
| `+0x08` | 4 | data pointer (advanced by the walker) | `lw $v1, 8($s0); addu $v0, $v1, $a2` at 0xbfc168de |
| `+0x0C` | 4 | **callback pointer** (called with `jalrc`) | `lw $v0, 0xC($s0); jalrc $v0` at 0xbfc16912-14 |

**Unknown fields**: +2, +3, +4, +6, +7, +9, +10, +11, +13, +14, +15.

### What this establishes

1. **The node stride is 16 bytes** — confirmed by two `sll ..., 4` instructions
   in independent functions.
2. **The node array is dynamically built** — the base pointer at `0x9FC15584`
   is a RAM variable, not a constant.
3. **The setter function writes 1 to node+0**, activating a node.
4. **The search function scans for a node with status 2**, suggesting nodes go
   through a state machine (1 = active, 2 = processed/done).
5. **The category byte at +5 is compared against an active filter**, not
   against a static list of extensions.

`UNVERIFIED`: which function writes to `node+5`; what the category values mean
beyond 0xFF = any; whether the category byte corresponds to a file extension,
a UI state, or a navigation classification; whether the callback at node+12 is
a per-node file handler.

## VERIFIED: the folder-list scroll function and its state struct

Bank `0x48714400` (browser.ap file `0x18900`, size `0x800`, 1663 bytes live).
The scroll-next function at `0x487144A8` (bank `+0xA8`) operates on a **state
struct** passed as `$a1` (the second argument).

```text
0x487144a8  save 0x18, $ra,$s1
0x487144ac  frame+8 = $a0
0x487144ae  frame+0xC = $a1 = state struct
0x487144b0  *(u16*)0x9FC15636 = 1        ; set a REDRAW FLAG

0x487144b6  $v1 = state[+0x0E]           ; the current scroll position
0x487144bc  $v0 = *(u16*)0x9FC15636      ; the flag global
0x487144be  $v1 = position + flag        ; compute the next position
0x487144c0  $v0 = state[+0x0A]           ; the MAXIMUM VISIBLE ROWS
0x487144c4  if (next_pos < max_rows) → scroll normally
0x487144c8  ... (page-forward logic)

0x487144f4  ... (at the boundary):
0x487144f8  $a0 = state[+0x0E]
0x487144fa  $v0 = state[+0x0C]
0x487144fc  $v0 = $a0 ^ $v0              ; compare current position with...
0x487144d4  state[+0x0E] = state[+0x0E] + flag
0x487144dc  state[+0x12] = state[+0x10]
0x487144ea  state[+0x10] = state[+0x10] + flag
0x487144f0  *(u16*)0x9FC15636 = 1        ; set the redraw flag
```

The **state struct** fields, from the scroll function's accesses:

| offset | size | role | evidence |
|---|---|---|---|
| `+0x02` | 1 | total entry count (byte or small u16) | `lbu 2($v0)` |
| `+0x0A` | 2 | **maximum visible rows** | compared against position |
| `+0x0C` | 2 | current page or limit | compared with position |
| `+0x0E` | 2 | **current scroll position** | incremented and compared |
| `+0x10` | 2 | **selected row index** | incremented alongside position |
| `+0x12` | 2 | selected row absolute | copied from +0x10 |
| `+0x15` | 1 | redraw flag (set via the global) | `sb 1, 0x15($v1)` |

The RAM global `0x9FC15636` is a redraw/scroll flag (browser.ap data segment
`+0x236`).

`VERIFIED`: the scroll function's field accesses, the redraw flag, and the
state struct layout. `UNVERIFIED`: which function populates the state struct
with actual directory entries; where the row-text provider reads filenames
from; and what the function at `$a0` (frame+8) does.

## VERIFIED: the scroll functions are dispatched from a different overlay bank

The scroll-next (`0x487144A9`) and scroll-prev (`0x487146CD`) function pointers
are stored in a literal pool at file `+0x12938`/`+0x1293c`, in bank
`0x40D14E00` (browser.ap file `0x12500`, size `0x600`). That bank is
**different** from the folder-list overlay (`0x48714400`).

The pool also contains `0x9FC155A4` (a RAM pointer) at `+0x12934`. The function
ends with `jrc $ra` at `+0x12930`, and the pool follows.

**The architecture has three layers:**

| layer | bank | role |
|---|---|---|
| folder-list overlay | `0x48714400` | scroll-next and scroll-prev: manage the state struct |
| input dispatcher | `0x40D14E00` | loads the scroll-function pointers from its pool and calls them |
| caller | unknown | populates the state struct and passes it to the dispatcher |

The input dispatcher is **not** the list-population function. It routes wheel/key
events to the scroll functions. The list-population function is upstream.

`VERIFIED`: the scroll-function pointers are in bank `0x40D14E00`'s pool, not in
the folder-list bank. The input dispatcher is in a third bank.

## VERIFIED (corrected): the list-state and row-cache layouts from the QEMU harness

`tools/scroll/harness.c` runs the real browser.ap dirlist bank under QEMU with
synthetic data. Its initializations and runtime assertions establish the
authoritative field semantics, correcting the previous report's guesses.

### The list-state struct (32 bytes, `$a1` to the scroll functions)

| offset | size | role | corrected from |
|---|---|---|---|
| `+0x02` | 1 | **page capacity** (visible lines) | was "total entry count" |
| `+0x08` | 2 | **top visible absolute index** | was "max visible rows" |
| `+0x0A` | 2 | **bottom visible absolute index** | was "page limit" |
| `+0x0C` | 2 | **total item count** | was "page/limit" |
| `+0x0E` | 2 | **active absolute index** | was "current scroll position" |
| `+0x10` | 2 | **selected visible line** | was "selected row index" |
| `+0x12` | 2 | additional selection state | was "selected row absolute" |
| `+0x14` | 1 | update flag (cleared after redraw) | was unnamed |
| `+0x15` | 1 | update flag (cleared after redraw) | was "redraw flag" |

The harness's invariant check at each step confirms:
`1 <= top <= active <= bottom <= total` and `line == active - top + 1`.

### The 12-byte row-cache entry (`$a0` to the scroll functions)

The harness initializes `PAGE * 12` bytes (8 entries × 12 bytes):

```c
*(u32 *)(cache + i * 12) = i;                    // +0x00: index
cache[i * 12 + 4] = 16;                          // +0x04: size/type marker
*(u32 *)(cache + i * 12 + 8) = (u32)names[i];    // +0x08: name pointer
```

| offset | size | role |
|---|---|---|
| `+0x00` | 4 | **absolute index** (into the full item list) |
| `+0x04` | 1 | **16** (a fixed marker; possibly the name length or a type code) |
| `+0x08` | 4 | **pointer to the display text** |

### The call convention

```c
p_next((u32)cache, list);   /* scroll forward */
p_prev((u32)cache, list);   /* scroll backward */
```

Function pointers: `0x487144A9` (next, ISA bit set → `0x487144A8`) and
`0x487146CD` (prev → `0x487146CC`). The row cache is `$a0`, the list state is
`$a1`.

### What the scroll functions do NOT do

They **do not populate the row cache**. They only update the list-state fields
(top, bottom, active, line) in response to scroll events. The row cache is
pre-populated by the caller before scrolling.

**The row-cache producer is the function that enumerates directory entries,
classifies them, and builds the 12-byte entries with filenames.** That producer
is the browser's data provider, and it is where `.m3u` files are either
included or excluded.

`VERIFIED`: the list-state field semantics (corrected from the harness), the
row-cache layout, and the call convention. `UNVERIFIED`: who builds the row
cache in the real browser; what the `+4` marker means in production; how the
name pointer at `+8` relates to the displayed text.
