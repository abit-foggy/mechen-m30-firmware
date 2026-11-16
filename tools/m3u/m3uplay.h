/* M3U play-on-click: shared state and entry points (Phase D/E).
 *
 * The hook turns clicking a .m3u row in the stock file browser into playing
 * the playlist's tracks with the stock audio engine:
 *
 *   m3uplay_tramp  (m3uplay_tramp.S) replaces the path-B classify call at
 *                  browser.ap 0x40D15194; it recomputes the selected row's
 *                  dir index (list_no - count) and calls m3uplay_click.
 *   m3uplay_click  for an m3u/m3u8 row: fetch the real dir record (to get the
 *                  playlist's name), count its entries, then arm the virtual
 *                  server and re-fetch through the wrapper so *0x9FC1573C
 *                  holds the FIRST TRACK's record. Returns class 0 so the
 *                  stock dispatcher launches the engine exactly as for an
 *                  audio file. Any other row, or any failure, falls back to
 *                  the stock classifier (dialog for m3u only if something
 *                  failed - the shipped class-mask divert stays as backup).
 *   m3uplay_fetch  replaces the fs-stub pool word of the record fetch
 *                  0x780DB460 (browser.ap file 0x4594). The stock wrapper
 *                  still runs: it publishes the returned pointer to
 *                  0x9FC1573C and returns (ptr != 0). With the server armed
 *                  and the index inside the playlist's range, the hook
 *                  parses the playlist and builds a virtual 0x100-byte dir
 *                  record (attr, name pointer, BOM+UTF-16LE relative path)
 *                  in shared RAM; everything else passes through to the
 *                  real fs stub unchanged.
 *
 * Shared state lives in the exfatn.drv resident zero run (guest
 * 0xBFC17274..0xBFC173F8, file 0x874..0x9F8, verified all-zero with no
 * references from any module): it survives app switches, unlike bank memory.
 *
 * Record layout (from the dir-stream decode): +0 attr byte (0 = file),
 * +4 name string pointer (BOM FF FE + UTF-16LE + NUL), records are 0x100
 * bytes. The engine (music.ap 0x40054FAC) registers *0x9FC1573C and
 * *(record+4) with module 0x05 and opens the name - relative names resolve
 * in the browser's current dir, i.e. the playlist's own dir, which is where
 * the m3u's entries are relative to.
 */
#ifndef M3UPLAY_H
#define M3UPLAY_H

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

#define M3UPLAY_MAGIC 0x4D335650u   /* 'M3VP' */

/* name capacity: BOM + UTF-16LE + double NUL, kept inside the zero run */
#define VS_NAME_MAX 0x70

struct vstate {
    u32 magic;                  /* M3UPLAY_MAGIC when armed */
    u32 flag;                   /* 1 = serve virtual records */
    u32 base;                   /* dir index of the .m3u */
    u32 count;                  /* entries in the playlist */
    u8  name[VS_NAME_MAX];      /* the .m3u's fs-open name (BOM+UTF-16LE) */
    u8  rec[0x100];             /* the virtual dir record served to the engine */
};

/* Fixed addresses in the stock firmware (see docs/reverse-engineering.md).
 * The test build (M3UPLAY_TEST) routes these through pointers the harness
 * installs, so the same source runs natively on the host and under QEMU. */
#ifdef M3UPLAY_TEST
extern volatile struct vstate *test_vs;
extern volatile u32 *test_rec_g;
extern volatile u32 *test_ctxw;
#define VS    (test_vs)
#define REC_G (*test_rec_g)
#define FSCTX (*test_ctxw)
#else
#define VS    ((volatile struct vstate *)0xBFC17274u)   /* exfatn.drv zero run, 4-aligned */
#define REC_G (*(volatile u32 *)0x9FC1573Cu)            /* published record pointer */
#define FSCTX (*(volatile u32 *)0x9FC15748u)            /* fs dir-enum context word */
#endif

/* Entry points (linked into the browser.ap bank 0x400D4C00 tail blob). */
u32 m3uplay_click(u32 row, u32 idx);
u32 m3uplay_fetch(u32 ctx, u32 idx, u32 a2, u32 x, u32 op);

#endif /* M3UPLAY_H */
