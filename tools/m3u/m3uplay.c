/* M3U play-on-click handler for browser.ap (bank 0x400D4C00 tail at 0x400D4CD0).
 *
 * Freestanding blob: no writable globals, no string literals, no libc.
 */
#include "m3uplay.h"

#ifdef M3UPLAY_TEST
extern fs_fn test_fs;
extern u32 (*test_classify)(u32);
extern u32 (*test_step_dir)(u32, u16);
extern volatile u32 *test_ctxw;
extern volatile u32 *test_maskw;
extern volatile u16 *test_dircnt;
extern volatile u8  *test_layerb;
extern volatile u8  *test_diskb;
#define FS_CALL   (test_fs)
#define CLASSIFY  (test_classify)
#define STEP_DIR  (test_step_dir)
#define VFS_CTX   (*test_ctxw)
#define BROW_MASK (*test_maskw)
#define DIR_CNT   (*test_dircnt)
#define CUR_LAYER (*test_layerb)
#define CUR_DISK  (*test_diskb)
#else
#define FS_CALL   ((fs_fn)0xBFC16A2Du)                  /* browser.ap module-0x11 VFS stub */
#define CLASSIFY  ((u32 (*)(u32))0x40D14E01u)           /* stock classifier 0x40D14E00 */
#define STEP_DIR  ((u32 (*)(u32, u16))0x780DB49Du)      /* stock dir stepper 0x780DB49C */
#define VFS_CTX   (*(volatile u32 *)0x9FC15748u)        /* browser VFS context */
#define BROW_MASK (*(volatile u32 *)0x9FC15750u)        /* active browser extension mask */
#define DIR_CNT   (*(volatile u16 *)0x9FC157FCu)        /* subfolders in current dir */
#define CUR_LAYER (*(volatile u8  *)0x9FC15736u)        /* current directory depth */
#define CUR_DISK  (*(volatile u8  *)0x9FC1574Fu)        /* current disk letter (e.g. 'H') */
#endif

#include "m3u_resolve.h"

/* Row +0 carries the 4-byte extension ("M3U\0", "m3u\0", "M3U8", "m3u8"). */
static int is_m3u_row(const u8 *r)
{
    return (r[0] | 0x20u) == 'm' && r[1] == '3' && (r[2] | 0x20u) == 'u'
        && (r[3] == 0 || r[3] == ' ' || r[3] == '8');
}

u32 m3uplay_click(u32 row, u32 idx, u8 *arg0)
{
    u8 sec[512] __attribute__((aligned(4)));
    volatile struct vstate *vs = VS;
    u32 dirc;
    u32 count, k, tries;
    u32 ext = 0;
    u8 layer = 0;
    u8 *desc;
    int ok = 0;

    vs->magic = 0;

    if (!is_m3u_row((const u8 *)row)) {
        return CLASSIFY(row);
    }

    dirc = DIR_CNT;
    if (VFS_CTX == 0 || arg0 == 0 || idx <= dirc) {
        goto fail_no_restore;
    }

    if (!STEP_DIR(BROW_MASK, (u16)(idx - dirc))) {
        goto fail_no_restore;
    }

    if (!vfs((u32)vs->pl_dir, (u32)vs->pl_off, 0, OP_OFFSET)) {
        goto fail_no_restore;
    }
    vs->pl_layer = CUR_LAYER;
    vs->disk = CUR_DISK;

    count = m3u_scan_entry(sec, 0xFFFFFFFFu);
    if (count == 0 || count == 0xFFFFFFFFu) {
        goto restore_out;
    }
    if (count > 0xFFFFu) {
        count = 0xFFFFu;
    }

    tries = count < 16u ? count : 16u;
    for (k = 0; k < tries; k++) {
        u32 len = m3u_scan_entry(sec, k);
        if (len != 0xFFFFFFFFu && m3u_resolve(len, &ext, &layer)) {
            break;
        }
    }
    if (k >= tries) {
        goto restore_out;
    }

    arg0[0] = 0;
    desc = arg0 + 4;
    {
        u32 j;
        for (j = 0; j < 0xA4u / 4u; j++) {
            ((u32 *)desc)[j] = 0;
        }
    }
    if (!vfs((u32)(desc + 0x10), (u32)(desc + 8), 0, OP_OFFSET)) {
        goto restore_out;
    }
    desc[0] = vs->disk;
    desc[1] = layer;
    *(u32 *)(desc + 4) = ext;
    *(u16 *)(desc + 0x5C) = (u16)count;
    *(u16 *)(desc + 0x5E) = (u16)(k + 1);

    vs->cur_off[0] = *(const u32 *)(desc + 8);
    vs->cur_off[1] = *(const u32 *)(desc + 12);
    vs->pos = (u16)(k + 1);
    vs->count = (u16)count;
    vs->shuf_key = 0;
    vs->shuf_pos = 0;
    vs->magic = M3UPLAY_MAGIC;
    ok = 1;

restore_out:
    vfs((u32)vs->pl_dir, (u32)vs->pl_off, 1u, OP_OFFSET);
    if (ok) {
        return 0x8001u;
    }
fail_no_restore:
#ifdef M3UPLAY_PROBE
    return 0;
#else
    return CLASSIFY(row);
#endif
}
