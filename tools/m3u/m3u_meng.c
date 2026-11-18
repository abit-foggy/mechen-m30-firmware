/* M3U playlist track stepper for mengine.ap (linked at 0x7B268000, bank 9).
 *
 * Called ONLY from m3u_meng_tramp.S (in bank 0x7A052D00, window 0x7A) when
 * VS->magic == M3UPLAY_MAGIC. Calls ONLY resident kernel/VFS syscall stubs
 * (0xBFC11CCD and 0xBFC11CC9), so no overlay window swap ever occurs while
 * this bank runs.
 */
#include "m3uplay.h"

struct eng_state {
    u8  mode;       /* +0x00 (0x9FC15F20) */
    u8  endflag;    /* +0x01 (0x9FC15F21) */
    u8  layer;      /* +0x02 (0x9FC15F22) */
    u8  shuffle;    /* +0x03 (0x9FC15F23) */
    u16 pos;        /* +0x04 (0x9FC15F24) */
    u16 count;      /* +0x06 (0x9FC15F26) */
    u32 ext;        /* +0x08 (0x9FC15F28) */
    u32 pad0[2];    /* +0x0C..+0x13 */
    u32 handle;     /* +0x14 (0x9FC15F34) */
    u8  desc0;      /* +0x18 (0x9FC15F38) */
    u8  loop;       /* +0x19 (0x9FC15F39) */
    u8  pad1[6];    /* +0x1A..+0x1F */
    u16 seccach;    /* +0x20 (0x9FC15F40) */
};

#ifdef M3UPLAY_TEST
extern fs_fn test_meng_fs;
extern u32 (*test_meng_rand)(void);
extern volatile u8 *test_meng_eng;
extern u8 *test_meng_sec;
#define FS_CALL     (test_fs_meng_wrap)
static inline long test_fs_meng_wrap(u32 c, u32 a, u32 b, u32 d, u32 o) { return test_meng_fs(c, a, b, d, o); }
#define RAND_CALL() (test_meng_rand())
#define ENG         ((volatile struct eng_state *)(test_meng_eng + 0x20))
#define SEC_BUF     (test_meng_sec)
#else
#define FS_CALL     ((fs_fn)0xBFC11CCDu)
#define RAND_STUB   ((u32 (*)(u32, u32, u32, u32))0xBFC11CC9u)
#define RAND_CALL() (RAND_STUB(0, 0, 0, 0x35u))
#define ENG         ((volatile struct eng_state *)0x9FC15F20u)
#define SEC_BUF     ((u8 *)0x7A0530E4u)
#endif

#define VFS_CTX     (ENG->handle)

static long vfs(u32 a1, u32 a2, u32 a3, u32 op);
static u32 m3u_scan_entry(u8 *sec, u32 want);
static int m3u_resolve(u32 len, u32 *out_ext, u8 *out_layer);
static u32 shuf_pick(u32 count, u32 op, int repeat_all);

/* Entry point at 0x7B268000 (MUST be the first non-inlined function in this unit!).
 *   op == 0 : seek exact 1-based track `arg` (get_byno)
 *   op == 1 : next track (`arg` unused; reads ENG->loop and ENG->shuffle)
 *   op == 2 : prev track (`arg` unused; reads ENG->loop and ENG->shuffle) */
u32 m3u_meng_step(u32 *out, u32 arg, u32 op)
{
    volatile struct eng_state *e = ENG;
    volatile struct vstate *vs = VS;
    u32 count = vs->count;
    u32 cur = vs->pos;
    u32 loop = e->loop;
    u32 k;
    int repeat_all = 0;

    if (e->handle == 0 || count == 0) {
        return 0;
    }

    if (op == 0) {
        if (arg == 0 || arg > count) {
            e->endflag = 1;
            return 0;
        }
        cur = arg;
    } else {
        if (loop >= 6u) {
            return 0;
        }
        if (loop == 1u && cur >= 1u && cur <= count) {
            if (out) {
                *out = e->ext;
            }
            return 1;
        }
        repeat_all = (loop == 2u || loop == 4u);
    }

    e->seccach = 0xFFFFu;

    for (k = 0; k < count; k++) {
        u32 len, ext;
        u8 layer;

        if (op == 0) {
            if (k > 0) {
                cur = (cur < count) ? (cur + 1u) : 1u;
            }
        } else if (e->shuffle == 1u) {
            cur = shuf_pick(count, op, repeat_all);
            if (cur == 0) {
                return 0;
            }
        } else if (op == 1u) {
            if (cur < count) {
                cur++;
            } else if (repeat_all) {
                cur = 1u;
            } else {
                return 0;
            }
        } else {
            if (cur > 1u) {
                cur--;
            } else if (repeat_all) {
                cur = count;
            } else {
                return 0;
            }
        }

        len = m3u_scan_entry(SEC_BUF, cur - 1u);
        if (len != 0xFFFFFFFFu && m3u_resolve(len, &ext, &layer)) {
            if (vfs((u32)SEC_BUF, (u32)vs->cur_off, 0, OP_OFFSET)) {
                vs->pos = (u16)cur;
                e->pos = (u16)cur;
                e->count = (u16)count;
                e->layer = layer;
                e->ext = ext;
                if (out) {
                    *out = ext;
                }
                return 1;
            }
        }
    }
    return 0;
}

static u32 shuf_pick(u32 count, u32 op, int repeat_all)
{
    volatile struct vstate *vs = VS;
    u32 h = 1u, end, mask, key = vs->shuf_key, p = vs->shuf_pos;

    while ((1u << (2u * h)) < count) {
        h++;
    }
    end = 1u << (2u * h);
    mask = (1u << h) - 1u;

    for (;;) {
        if (key == 0 || (op == 1u && p >= end)) {
            if (key != 0 && !repeat_all) {
                return 0;
            }
            key = ((RAND_CALL() ^ (key + 0x3Du)) & 0xFFFFu) | 1u;
            vs->shuf_key = (u16)key;
            p = 0;
        }
        if (op == 1u) {
            p++;
        } else if (p <= 1u) {
            if (!repeat_all) {
                return 0;
            }
            p = end;
        } else {
            p--;
        }
        {
            u32 idx = p - 1u;
            u32 l = idx >> h;
            u32 r = idx & mask;
            u32 r_i;
            for (r_i = 0; r_i < 4u; r_i++) {
                u32 f = (r ^ key ^ (r_i * 0x9Du)) * 0x9E37u;
                u32 t = l ^ ((f ^ (f >> 8)) & mask);
                l = r;
                r = t;
            }
            idx = (l << h) | r;
            if (idx < count) {
                vs->shuf_pos = p;
                return idx + 1u;
            }
        }
    }
}

#include "m3u_resolve.h"
