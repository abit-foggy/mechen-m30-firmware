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
