/* M3U play-on-click: shared state and kernel VFS definitions.
 *
 * Architecture (verified by IDA Pro / Hex-Rays disassembly of browser.ap,
 * playlist.ap, mengine.ap, and exfatn.drv):
 *
 *   1. The ATJ2137 VFS driver (exfatn.drv / fat_32n.drv, module 0x11) has NO
 *      multi-component path open and rejects vfs_dir (op 1) commands < 0x80
 *      with error 21. Instead, files are located by walking path components
 *      with op 0 (vfs_cd: ':', '|', '/'), op 1 (vfs_dir: 0x82 first, 0x80
 *      next), and op 2 (vfs_get_name: UTF-16LE with FEFF BOM on LFN/exFAT,
 *      8.3 on FAT short names, or 4-byte packed ext when max_len == 0), then
 *      snapshotting the 73-byte directory cluster stack + 8-byte entry offset
 *      via op 3 (vfs_file_dir_offset, set=0) or opening the current entry via
 *      op 5 (vfs_open, name=0).
 *
 *   2. browser.ap passes the selected file to music.ap -> mengine.ap as a
 *      0xA4-byte file_location_t at 0x9FC1540C (arg0 + 4 of dispatcher
 *      0x40D14F14): +0 disk, +1 dir_layer, +4 ext[4], +8 file_off[8],
 *      +0x10 dir_stack[73], +0x5C total, +0x5E index.
 *
 *   3. On clicking a .m3u/.m3u8 row and choosing Play (0x801E):
 *      - m3uplay_tramp (0x400D4CD0) calls m3uplay_click(row, idx, arg0).
 *      - m3uplay_click steps to the .m3u via stock 0x780DB49C, snapshots its
 *        81-byte VFS location into vstate (0xBFC17274, exfatn.drv resident
 *        zero run, survives app switches), counts its entries, resolves the
 *        first playable track (supporting '/', '\\', '..', UTF-8 -> UTF-16LE),
 *        populates the 0xA4-byte file_location_t at arg0 + 4, arms vstate, and
 *        returns 0x8001.
 *      - m3uplay_tramp writes 0x8001 to 4($s1) and jumps to 0x40D15200 so
 *        stock 0x780DB2F8 does not overwrite the resolved track location.
 *
 *   4. mengine.ap runs in its own address space (VFS stub 0xBFC11CCD, context
 *      *0x9FC15F34). Four mode-0 entries in mengine's fsel table (0x7A052D00)
 *      redirect through m3u_meng_tramp (0x7A053338) to m3u_meng_step
 *      (unused group-0x7B bank 9 at 0x7B268000):
 *      - set_location[0] keeps vstate armed when desc+8 matches cur_off (setting
 *        COUNT/POS to the playlist's total/index and reseeding shuffle over the
 *        playlist), or disarms vstate when any other song is selected.
 *      - get_nextfile[0], get_prevfile[0], and get_byno[0] walk the .m3u
 *        entries across folders (honoring Repeat One, Repeat All, Repeat Off,
 *        and Shuffle) using mengine's own VFS context.
 */
#ifndef M3UPLAY_H
#define M3UPLAY_H

#define M3UPLAY_MAGIC_RAW 0x4D335650
#define M3U_LINE_CAP      240           /* max UTF-8 track path bytes (card max: 168) */

#ifdef __ASSEMBLER__
#define M3UPLAY_MAGIC M3UPLAY_MAGIC_RAW
#else
#define M3UPLAY_MAGIC 0x4D335650u   /* 'M3VP' */

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

typedef long (*fs_fn)(u32, u32, u32, u32, u32);

/* VFS module 0x11 operation IDs (5th o32 stack arg at 0x10($sp)). */
#define OP_CD       0x0
#define OP_DIR      0x1
#define OP_GETNAME  0x2
#define OP_OFFSET   0x3
#define OP_OPEN     0x5
#define OP_CLOSE    0x7
#define OP_SEEK     0xB
#define OP_READ     0xD

#define DIR_NEXT    0x80u
#define DIR_HEAD    0x82u
#define EXT_DIRS    1u
/* Stock audio extension mask with the repurposed M3U/M3U8 slots (bits 5,8,10,12)
 * cleared so playlist files themselves are never matched as audio tracks. */
#define AUDIO_MASK  0x7E190A80u

/* Shared state in the exfatn.drv resident zero run (guest 0xBFC17274..0xBFC173F8,
 * file 0x874..0x9F8 = 0x184 = 388 bytes). Total sizeof(struct vstate) = 0x15C
 * (348 bytes), 4-byte aligned, fits inside 0x184 with 40 bytes to spare. */
struct vstate {
    u32  magic;                 /* +0x00: M3UPLAY_MAGIC when a playlist is active */
    u16  pos;                   /* +0x04: 1-based current entry index (1..count) */
    u16  count;                 /* +0x06: total entries in the playlist */
    u8   pl_layer;              /* +0x08: directory depth of the .m3u file */
    u8   disk;                  /* +0x09: disk byte from browser (e.g. 'H') */
    u16  shuf_key;              /* +0x0A: Feistel key (0 = needs seed) */
    u32  cur_off[2];            /* +0x0C: 8-byte VFS file_off of the active track */
    u8   pl_off[8];             /* +0x14: 8-byte VFS file_off of the .m3u file */
    u8   pl_dir[76];            /* +0x1C: 73-byte VFS dir_stack of the .m3u (+3 pad) */
    u32  shuf_pos;              /* +0x68: current Feistel domain cursor */
    char line[M3U_LINE_CAP];    /* +0x6C: UTF-8 path buffer for the current entry */
};

#ifdef M3UPLAY_TEST
extern volatile struct vstate *test_vs;
#define VS (test_vs)
#else
#define VS ((volatile struct vstate *)0xBFC17274u)
#endif

/* Entry points. */
u32 m3uplay_click(u32 row, u32 idx, u8 *arg0);
u32 m3u_meng_step(u32 *out, u32 arg, u32 op);

#endif /* !__ASSEMBLER__ */
#endif /* M3UPLAY_H */
