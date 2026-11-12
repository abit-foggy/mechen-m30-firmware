# M30-FW-007: the dispatch pointer redirection

Tools used: IDA Pro 9.4 headless, `mipsl` processor, with the MIPS16e virtual
register enabled via `idc.set_default_sreg_value(ea, "mips16", 1)` (IDA uses a
virtual register named `mips16` for the MIPS32/MIPS16/microMIPS encoding
choice; it is settable per segment and is at register index 67 of the MIPS
processor's register list).

## 1. The patch

`browser.ap`, stock vs community V1.101.11:

| image | bytes at `+0x46CC` | u32 |
|---|---|---|
| stock | `E1 26 41 71` | `0x714126E1` |
| community | `59 26 4D 71` | `0x714D2659` |

Two halfwords differ, both halves of one 32-bit word. It is **not** an
instruction change: it is one entry of a pointer table.

## 2. Where the pointer lives

The patched bytes are inside the overlay bank whose table entry is at
`browser.ap` file `0x724` (file offset `0x4300`, load address `0x780DB200`,
size `0x800`). So `+0x46CC` is guest `0x780DB5CC`, i.e. bank `+0x3CC`.

**Correction to an earlier mapping:** a previous report put this at guest
`0x40154ECC` by associating the file offset with the wrong bank
(file `0x4400`). The bank table shows the correct owner is the one at `0x4300` /
`0x780DB200`, so the guest address is `0x780DB5CC`.

## 3. The dispatch structure

The bank holds a set of four 4-entry pointer tables, 16 bytes apart, all entries
odd (MIPS16e), terminated by zeroes:

```
0x780DB5A0: 0x713d2a31  0x71312815  0x71452821  0x713927b1
0x780DB5B0: 0x71312951  0x71412889  0x713928f5  0x71352501
0x780DB5C0: 0x714529a9  0x713d28ad  0x71352821  0x714126e1 <- patched
0x780DB5D0: 0x71392659  0x713125dd  0x714525ad  0x713925f5
0x780DB5E0: 0x00000000 ...  (terminator, referenced by 25+ sites)
```

The consumer pattern, repeated throughout the bank, is:

```asm
lw   $a2, <address of a flag byte>      ; e.g. 0x9FC15734
lbu  $v0, 0($a2)                        ; load the selector
sll  $a3, $v0, 2                        ; index * 4
addu $a2, $a3, $v1                      ; v1 = table base (0x780DB5xx)
lw   $v0, 0($a2)                        ; fetch the handler pointer
jalrc/jalr $v0                          ; call it
```

Several such stubs exist in this one bank (at `0x780DB200`, `0x780DB24C`,
`0x780DB2DC`, `0x780DB310`, `0x780DB344`, `0x780DB440`, ...), each with its own
flag address and table base. The tables at `0x780DB5A0`/`0x780DB5B0`/`0x780DB5D0`
are separate dispatch grids for other selector bytes.

So the pointer is indexed by a **runtime byte** (e.g. at `0x9FC15734`), and
whether entry `0x780DB5CC` ever executes depends on that byte's value, which
static analysis cannot determine.

## 4. The two routines

Both are MIPS16e and both start with a stack-frame prologue.

### Stock routine at `0x714126E0`

```asm
0x714126e0  save  0x30, $ra,$s0-$s1
0x714126e2  move  $s1, $a0
0x714126e4  lw    $a0, dword_7141285C
0x714126e6  li    $v1, 0
0x714126e8  move  $s0, $a1
0x714126ea  lw    $v0, dword_71412860
0x714126ec  li    $a1, 1
0x714126ee  neg   $a1, $a1              ; a1 = -1
0x714126f0  sh    $a1, 0($a0)           ; store -1 to a variable
0x714126f2  sw    $v1, 0x14($sp)        ; save 0
0x714126f4  jalr  $v0                   ; indirect call
0x714126f6  move  $a0, $v1
0x714126f8  lw    $v1, 0x14($sp)
0x714126fa  beqz  $v0, 0x7141275e       ; check result
0x714126fc  lbu   $a0, 1($s1)
0x714126fe  lhu   $v1, 2($s1)
0x71412700  lw    $v0, dword_71412868
0x71412702  lw    $s1, dword_71412864
0x71412704  sw    $v1, 0x18($sp)
0x71412706  lhu   $v1, 0($s1)
...
```

It takes two pointer arguments (`$a0` → `$s1`, `$a1` → `$s0`), stores `-1`
through a pointer loaded from an internal variable table, makes an indirect
call, then reads bytes at `+1` and `+2` of its first argument and walks two
further pointers. The shape is a **parser/validator over a packed record**: it
reads a length/type pair from the caller's buffer and walks a linked structure.

### Community routine at `0x714D2658`

```asm
0x714d2658  save  0x50, $ra,$s0-$s1
0x714d265a  move  $s0, $sp
0x714d265c  sw    $a1, 0x24($s0)
0x714d265e  sw    $a0, 0x40($s0)
0x714d2660  li    $v0, 0x9FC1
0x714d2664  sll   $v0, 16                ; v0 = 0x9FC10000
0x714d2668  li    $v1, 0xFFFF
0x714d266c  sw    $v1, 0x3C($s0)
0x714d266e  sh    $v1, 0x5754($v0)       ; 0x9FC15754 = 0xFFFF
0x714d2672  li    $s1, 0
0x714d2674  jal   0x7811B3DC             ; direct call
0x714d2678  move  $a0, $s1               ; a0 = 0
0x714d267a  nop
0x714d267c  beqz  $v0, unk_714d26b4      ; check result
0x714d267e  li    $v0, 0x9FC1
0x714d2682  sll   $v0, 16
0x714d2686  lhu   $v1, 0x57FC($v0)       ; read 0x9FC157FC
0x714d268a  li    $v0, 0x9FC1
0x714d268e  sll   $v0, 16
0x714d2692  lhu   $v0, 0x57FE($v0)       ; read 0x9FC157FE
0x714d2696  addu  $a0, $v0, $v1         ; sum them
0x714d2698  lw    $a2, 0x3C($s0)
0x714d269a  and   $a0, $a2
0x714d269c  li    $a1, 0
0x714d269e  sw    $a1, 0x38($s0)
0x714d26a0  lw    $a1, 0x40($s0)
0x714d26a2  lhu   $a3, 2($a1)
...
```

Differences from stock, all additions before the shared tail:

| | stock | community |
|---|---|---|
| frame size | `0x30` | `0x50` |
| saves `$a0`/`$a1` to locals | no | yes (`0x40`, `0x24`) |
| writes `0xFFFF` to `0x9FC15754` | no | yes |
| calls `0x7811B3DC` with `$a0 = 0` | no | yes, and tests the return |
| reads `0x9FC157FC` and `0x9FC157FE`, sums them | no | yes |

Those `0x9FC15xxx` words are the same shared-state area the dispatch selectors
read (`0x9FC15734`, `0x9FC15735`, `0x9FC15748`, ...), and the dispatch consumer
reads its selector from `0x9FC15734` too. So the community routine writes into
the same state the other stubs read.

## 5. What the redirection changes

Verified: the patch swaps which routine the selector-driven dispatcher calls.
Both routines take equivalent arguments, and the community routine adds extra
state writes and a call before the shared body. Static analysis cannot show
whether those extra writes are only cosmetic or change behavior, because the
selector value and the callee at `0x7811B3DC` are runtime values.

**What is not established:** that either routine parses playlists. There is no
string handling, no line-ending comparison (no `0x0A`/`0x0D` constant), and no
path construction in either listing. That the community firmware documents M3U
fixes does not make this region the M3U parser.

## 6. The other changed module

`playlist.ap` also changes (14 ranges, 137 bytes). Those are separate and are
the better candidate for playlist parsing, since `playlist.ap` carries
`M3U.LIB` and `playlist.sty`.
