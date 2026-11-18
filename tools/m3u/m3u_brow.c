/* Virtual-folder .m3u navigation + row formatter for browser.ap
 * (linked right after m3uplay_tramp.S at 0x485946C0 in bank 0x48594400's
 * 1344-byte verified zero tail, window 0x48).
 *
 * Never touches any 0x40xx4C00 bank, preserving browser.ap's live row_names
 * string buffers at 0x40CD4C00..0x40CD4E00 (physical 0x9FC14C00..0x9FC14E00).
 */
#include "m3uplay.h"

#ifdef M3UPLAY_TEST
extern fs_fn test_fs;
extern u32 (*test_step_dir)(u32, u16);
extern volatile struct brow_fsel *test_bf;
extern u8 *test_brow_hdr;
#define FS_CALL   (test_fs)
#define STEP_DIR  (test_step_dir)
#define BF        (test_bf)
#define BROW_HDR  (test_brow_hdr)
#else
#define FS_CALL   ((fs_fn)0xBFC16A2Du)
#define STEP_DIR  ((u32 (*)(u32, u16))0x780DB49Du)
#define BF        ((volatile struct brow_fsel *)0x9FC15734u)
#define BROW_HDR  ((u8 *)0x9FC15598u)
#endif

static __attribute__((noinline)) long b_vfs(u32 a1, u32 a2, u32 a3, u32 op)
{
    return FS_CALL(BF->vfs_ctx, a1, a2, a3, op);
}

static __attribute__((noinline)) void b_copy(volatile void *dst, const volatile void *src, u32 n)
{
    volatile u8 *d = (volatile u8 *)dst;
    const volatile u8 *s = (const volatile u8 *)src;
    while (n--) {
        *d++ = *s++;
    }
}

void m3u_format_row(const u8 *line, u32 len, u8 *row)
{
    u32 i, b = 0, dot = 0xFFFFFFFFu;
    const u8 *base, *end = line + len;
    u8 *dst = *(u8 **)(row + 8);
    u32 cap = (u32)(row[4] >> 1);

    for (i = 0; i < len; i++) {
        u8 c = line[i];
        if (c == '/' || c == '\\') {
            b = i + 1u;
            dot = 0xFFFFFFFFu;
        } else if (c == '.') {
            dot = i;
        }
    }
    *(u32 *)row = 0;
    if (dot != 0xFFFFFFFFu) {
        const u8 *ep = line + dot + 1u;
        for (i = 0; i < 4u && ep + i < end; i++) {
            u8 c = ep[i];
            if ((u32)(c - 'a') < 26u) {
                c = (u8)(c - 0x20u);
            }
            row[i] = c;
        }
    }
    if (!dst || cap < 2u) {
        return;
    }
    base = line + b;
    dst[0] = 0xFFu;
    dst[1] = 0xFEu;
    i = 1u;
    while (base < end && i + 1u < cap) {
        u32 b0 = *base++, cp = b0;
        if (b0 >= 0x80u) {
            if ((b0 & 0xE0u) == 0xC0u && base < end) {
                cp = ((b0 & 0x1Fu) << 6) | (*base++ & 0x3Fu);
            } else if ((b0 & 0xF0u) == 0xE0u && base + 1 < end) {
                cp = ((b0 & 0x0Fu) << 12) | ((u32)(base[0] & 0x3Fu) << 6) | (base[1] & 0x3Fu);
                base += 2;
            } else if ((b0 & 0xF8u) == 0xF0u && base + 2 < end) {
                cp = '?';
                base += 3;
            }
        }
        dst[2u * i] = (u8)(cp & 0xFFu);
        dst[2u * i + 1u] = (u8)(cp >> 8);
        i++;
    }
    dst[2u * i] = 0;
    dst[2u * i + 1u] = 0;
}

/* Open a .m3u/.m3u8 row in a normal folder as a virtual folder.
 * Returns 0 on success, 0x8018 when empty/missing ("Empty folder!" popup). */
u32 m3u_vdir_open(u32 file_idx, const u8 *row, u8 *state, u32 (*scan_count)(void))
{
    volatile struct brow_fsel *bf = BF;
    struct vdir_state *vd = VD;
    u8 *hdr = BROW_HDR;
    u32 count;
    u8 vlayer;
    (void)row;

    if (bf->vfs_ctx == 0xFFFFFFFFu || hdr[5] >= 8u) {
        return 0u;
    }
    if (!STEP_DIR(bf->mask, (u16)file_idx)) {
        return 0x8018u;
    }
    if (!b_vfs((u32)vd->pl_dir, (u32)vd->pl_off, 0, OP_OFFSET)) {
        return 0u;
    }
    vd->title[0] = 0;
    b_vfs((u32)vd->title, 25u, 0, OP_GETNAME);
    vd->title[50] = 0;
    vd->title[51] = 0;
    vd->pl_layer = hdr[5];
    vd->disk = bf->disk;

    count = scan_count();
    b_vfs((u32)vd->pl_dir, (u32)vd->pl_off, 1u, OP_OFFSET);
    if (count == 0 || count == 0xFFFFFFFFu) {
        return 0x8018u;
    }
    if (count > 0xFFFFu) {
        count = 0xFFFFu;
    }
    vd->count = (u16)count;
    {
        u8 *tbuf = *(u8 **)(hdr + 8);
        if (hdr[4] != 0 && tbuf) {
            b_copy(tbuf, vd->title, 50u);
        }
    }
    vlayer = (u8)(vd->pl_layer + 1u);
    vd->magic = M3UVD_MAGIC;
    bf->dir_cnt = 0;
    bf->file_cnt = (u16)count;
    bf->layer = vlayer;
    bf->sel_item = 0;
    *(u16 *)(hdr + 0) = 0;
    *(u16 *)(hdr + 2) = (u16)count;
    hdr[5] = vlayer;

    state[0x16] = 1u;
    state[0x14] = 4u;
    state[0x15] = 3u;
    return 0u;
}

u32 m3u_vdir_dir_op(u32 cmd, u32 idx, u8 *out)
{
    volatile struct brow_fsel *bf = BF;
    struct vdir_state *vd = VD;
    (void)idx;

    if (cmd == 0u) {
        u8 vlayer = (u8)(vd->pl_layer + 1u);
        bf->dir_cnt = 0;
        bf->file_cnt = vd->count;
        bf->layer = vlayer;
        bf->sel_item = 0;
        if (out) {
            u8 *tbuf = *(u8 **)(out + 8);
            if (out[4] != 0 && tbuf) {
                b_copy(tbuf, vd->title, 50u);
            }
            *(u16 *)(out + 0) = 0;
            *(u16 *)(out + 2) = vd->count;
            out[5] = vlayer;
        }
        return 1u;
    }
    vd->magic = 0;
    if (cmd == 2u) {
        bf->layer = vd->pl_layer;
        b_vfs((u32)vd->pl_dir, (u32)vd->pl_off, 1u, OP_OFFSET);
        return 0xFFFEu;
    }
    return (cmd == 3u) ? 0xFFFDu : 0u;
}

u32 m3u_vdir_setloc(const u8 *loc, u32 flag)
{
    volatile struct brow_fsel *bf = BF;
    volatile struct vstate *vs = VS;
    struct vdir_state *vd = VD;
    (void)flag;

    if (loc && bf->vfs_ctx != 0xFFFFFFFFu && vs->magic == M3UPLAY_MAGIC
            && *(const u32 *)(loc + 8) == vs->cur_off[0]
            && *(const u32 *)(loc + 12) == vs->cur_off[1]
            && b_vfs((u32)vs->pl_dir, (u32)vs->pl_off, 1u, OP_OFFSET)) {
        b_copy(vd->pl_off, vs->pl_off, 84u);
        vd->count = vs->count;
        vd->pl_layer = vs->pl_layer;
        vd->disk = vs->disk;
        vd->title[0] = 0;
        b_vfs((u32)vd->title, 25u, 0, OP_GETNAME);
        vd->title[50] = 0;
        vd->title[51] = 0;
        vd->magic = M3UVD_MAGIC;
        bf->dir_cnt = 0;
        bf->file_cnt = vs->count;
        bf->layer = (u8)(vs->pl_layer + 1u);
        bf->sel_item = vs->pos;
        return 1u;
    }
    vd->magic = 0;
    return 0xFFFEu;
}
