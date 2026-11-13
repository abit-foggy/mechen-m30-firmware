# M30 firmware architecture

Findings are marked `VERIFIED` (from the bytes), `INFERRED` (reasoned, not
confirmed) or `DISPROVEN`.

## Container layout

`MECHEN_M30.HEX` → AFI container → `FWIMAGE.FW` → components.

- **AFI directory**: 32-byte entries from `0x20`: `{name8, ext3, pad1, u32 load,
  u32 file-offset, u32 size}`. `VERIFIED`.
- **FWIMAGE.FW directory**: at `0x200`, 32-byte entries,
  `doff = rd32(o+16) << 9`. `VERIFIED`.
- **YQHX module headers** (magic at `+4`): triplets at `+0x08` (resident),
  `+0x14` (res2, empty in every module seen), `+0x2c` (data). `VERIFIED`.

## Modules

`build/work/stock/fw/` holds the unpacked components. The ones that matter here:
`.ap` applications (browser, config, mainmenu, music, playlist, setting,
mengine), `.drv` device drivers (card, udisk, usound, fat_32n, exfatn, …),
`kernel.drv` and `ker_*.bin`, and the `.sty`/`.mcg`/`.fnt` resources.

## Overlay structure — the load addresses are shared slots, not per-module homes

`VERIFIED`. Three modules declare the **same** resident load address with
**different** content:

| module | file offset | size | load | first 16 bytes |
|---|---|---|---|---|
| browser.ap | `0x0c00` | `0x0634` | `0xbfc16400` | `d4 64 04 01 …` — `save` (code) |
| music.ap | `0x0c00` | `0x07bc` | `0xbfc16400` | `10 6b 05 e8 06 6b 05 e8` — **trap table**, then `save` |
| playlist.ap | `0x1400` | `0x07bc` | `0xbfc16400` | `0c 6b 05 e8 09 6b 05 e8` — **trap table** |

So `0xbfc16400` is an **overlay window**, and the YQHX field called "resident
load" names the window, not a permanent home. Consequences that cost this
project real time:

- **Two banks at the same guest address are different code.** An address is only
  meaningful together with the module that supplies it.
- Banks are also shared across modules. `0x713d2500` is declared by browser.ap
  (`0xcb00..0xd300`, `0x800`), mainmenu.ap (`0xd200..0xd900`, `0x700`) and
  music.ap (`0x1a600..0x1add8`, `0x7d8`) — `VERIFIED` — and `0x7805b200` by six
  modules at `+0x710`.
- **No code references a bank base by address.** The only pointers to a bank
  base are its own bank-table entry. `VERIFIED` for `0x713d2500` and
  `0x7805b200`. This is expected for overlays: the loader places them, and
  callers reach them from inside the same bank or through an entry established
  at load. It also means **absence of a static reference is not evidence of dead
  code** — an earlier conclusion in this project said otherwise and was wrong.

## Bank tables

Group 3 at table offset `0x100`, group 4 at `0xA00`, 12-byte triples
`{file offset, load address, size}`. `VERIFIED`. Reading group 4 off by four
bytes yields plausible but wrong banks; the true start is `0xA00`.

## Syscall stub tables

`VERIFIED`, and a correction to an earlier claim in this project.

Overlay regions end — and sometimes begin — with runs of MIPS16e
`li $v1, MODULE ; break`. **These are not trap or error addresses. They are
system-call stubs.** The `MODULE` byte selects a system module and the *last
argument* (`$a3`) carries the function ID; the `break` traps into the kernel
dispatcher. Modules documented upstream: `0x0f` kernel (function `0x1c` the
millisecond clock, `0x35` the RNG), `0x11` filesystem, `0x06` text conversion.

`VERIFIED` per-module, and they differ at the same address:

| module | resident range | stubs at `0xbfc16bb0` / `0xbfc16bb4` |
|---|---|---|
| music.ap | `0xbfc16400..0xbfc16bbc` | `0x0f` / `0x11` (filesystem) |
| playlist.ap | `0xbfc16400..0xbfc16bbc` | `0x0f` / `0x06` (text conversion) |

So a stub address is only meaningful with its module attached — the same point as
the overlay windows above. `0xBFC16BB5` and `0xbfc16a25` were both read as error
addresses; that reading is withdrawn.

## Subsystems

- **Music library**: `MUSIC.LIB` (songs) and `M3U.LIB` (playlists), selected by
  index into a 12-byte filename table at `0x7805b498` in the `0x7805b200` bank.
  See [firmware-api.md](firmware-api.md).
- **Tag reading**: bank `0x713d2500` holds ID3 `TAG` parsing (compares `T`,`A`,`G`
  at `0x713d261a`–`0x713d2632`) and a genre-name table.
- **Theming**: `.sty` files, `RU3\x19` magic, type 2 = raw RGB565. Unrelated to
  M3U; see `theme-switching.md`.
- **QEMU**: the `m30` machine model in the sibling `qemu` checkout. Boot blocked
  at an unmapped `0xBFC01800`–`0xBFC08000` code hole.

## References

- [reverse-engineering.md](reverse-engineering.md) — addresses, call graphs,
  false positives.
- [firmware-api.md](firmware-api.md) — ABIs, what is established and what is not.
- [m3u-integration.md](m3u-integration.md) — the M3U feature and its blockers.
