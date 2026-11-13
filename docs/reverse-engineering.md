# Reverse-engineering notes

Status tags: `VERIFIED` (read from the bytes), `INFERRED`, `UNVERIFIED`,
`DISPROVEN`.

Method note that governs everything below: **IDA headless** with `-pmipsl -c` and
`idc.set_default_sreg_value(segment_ea, "mips16", 1)`. Without the virtual
register IDA prints MIPS32 mnemonics over MIPS16e bytes, which is silently wrong.
Tooling: `tools/ida/m30_ida.sh`, `tools/ida/m30_mips16e.py`.

## The three rules that prevent false positives

Each of these cost a full investigation. Check them before believing any address.

1. **Trap tables.** Overlay regions end — and sometimes begin — with runs of
   `li $v1,N ; break`; `05 e8` is the `break` halfword. A pointer into such a run
   is an **error path, not a call target**. Affected: `0xbfc16a25`,
   `0xBFC16BB5`. `VERIFIED`.
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

## Call graphs

**None established.** No verified edge exists yet from the Music application
entry through All Songs to playback. This is the open task; see
[m3u-integration.md](m3u-integration.md#handoff).

## Traps to avoid, summarised

- NUL-splitting an extension array yields `FLACAPE`/`JPEGDSF`; the stride is what
  matters.
- `M3U.LIB` is a media library, not a playlist database, despite the name.
- The extension masks are not bit selectors of the arrays; see
  [m3u-integration.md](m3u-integration.md).
- `atjboottool` output directories need a trailing separator.
