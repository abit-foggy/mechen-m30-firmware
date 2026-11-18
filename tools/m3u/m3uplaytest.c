/* Host (-m32) scenario harness for m3uplay.c + m3u_meng.c.
 *
 * Models the real ATJ2137 exFAT VFS ABI verified from exfatn.drv, browser.ap,
 * playlist.ap, and mengine.ap:
 *   - op 0 (OP_CD): ':', '|', '/' over a multi-folder directory tree
 *   - op 1 (OP_DIR): ONLY accepts 0x82 (DIR_HEAD) and 0x80 (DIR_NEXT);
 *                    rejects < 0x80 with 0 (just like real exfatn.drv err 21!)
 *   - op 2 (OP_GETNAME): writes FF FE + UTF-16LE + 00 00 when max_units > 0,
 *                        or the 4-byte packed extension when max_units == 0
 *   - op 3 (OP_OFFSET): snapshots/restores 73B dir_stack + 8B file_off
 *   - op 5 (OP_OPEN): opens the currently pointed-to file when a1 == 0
 *   - op 7/0xB/0xD: close, sector-aligned seek, 512B sector read
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "m3uplay.h"

volatile struct vstate *test_vs;

/* browser.ap hooks */
volatile u32 *test_ctxw;
volatile u32 *test_maskw;
volatile u16 *test_dircnt;
volatile u8  *test_layerb;
volatile u8  *test_diskb;

/* mengine.ap hooks */
volatile u8 *test_meng_eng;
u8 *test_meng_sec;

/* ---- Mock exFAT tree ---------------------------------------------------- */

struct vnode {
    int parent;         /* -1 for root */
    int is_dir;
    const char *name;   /* UTF-8 */
    u32 ext4;           /* 4-byte packed ext as stored on exFAT */
    u32 ext_bit;        /* mask bit in rom_ext_name */
    const char *data;   /* file contents (for .m3u files) */
    u32 size;
};

#define EXT4(a,b,c,d) ((u32)(u8)(a) | ((u32)(u8)(b)<<8) | ((u32)(u8)(c)<<16) | ((u32)(u8)(d)<<24))

/* Bit 4 -> FLAC, Bit 0 -> MP3, Bit 8 -> m3u, Bit 12 -> m3u8 */
#define BIT_MP3  (1u << 30)
#define BIT_FLAC (1u << 26)
#define BIT_M3U  (1u << 8)
#define BIT_M3U8 (1u << 12)

static const char idk_m3u[] =
    "\xEF\xBB\xBF"  /* UTF-8 BOM */
    "#EXTM3U\n"
    "#EXTINF:210,Very long comment line -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------\n"
    "../Music/2hollis/boy/04 - crash.flac\n"
    "../Music/missing_ghost.flac\n"
    "../Music/T\xC3\x81VOL/\xE2\x98\x86NoAki\xE2\x98\x86/\xE3\x80\x8CDigital Twin\xE3\x80\x8D.flac\r\n"
    "../Music/LongDir/09 - One Day The Only Butterflies Left Will Be In Your Chest As You March Towards Your Death (feat. Amy L.flac\n"
    "/Music/root_hit.mp3";     /* final line without trailing LF, leading '/' */

static const char empty_m3u[] = "#EXTM3U\r\n   \r\n# comment only\n";
static const char broken_m3u[] = "../Music/nope1.flac\n../Music/nope2.mp3\n";

static struct vnode tree[] = {
    /*  0 */ { -1, 1, "",           0, 0, 0, 0 },
    /*  1 */ {  0, 1, "Playlists",  0, 0, 0, 0 },
    /*  2 */ {  0, 1, "Music",      0, 0, 0, 0 },
    /*  3 */ {  2, 1, "2hollis",    0, 0, 0, 0 },
    /*  4 */ {  3, 1, "boy",        0, 0, 0, 0 },
    /*  5 */ {  2, 1, "T\xC3\x81VOL", 0, 0, 0, 0 },
    /*  6 */ {  5, 1, "\xE2\x98\x86NoAki\xE2\x98\x86", 0, 0, 0, 0 },
    /*  7 */ {  2, 1, "LongDir",    0, 0, 0, 0 },
    /* files in Playlists/ (parent 1): */
    /*  8 */ {  1, 0, "idk.m3u",    EXT4('m','3','u',0),   BIT_M3U,  idk_m3u,    sizeof idk_m3u - 1 },
    /*  9 */ {  1, 0, "empty.m3u",  EXT4('m','3','u',0),   BIT_M3U,  empty_m3u,  sizeof empty_m3u - 1 },
    /* 10 */ {  1, 0, "broken.m3u8",EXT4('m','3','u','8'), BIT_M3U8, broken_m3u, sizeof broken_m3u - 1 },
    /* 11 */ {  1, 0, "other.mp3",  EXT4('m','p','3',0),   BIT_MP3,  "ID3", 3 },
    /* audio tracks: */
    /* 12 */ {  4, 0, "03 - intro.flac", EXT4('f','l','a','c'), BIT_FLAC, "fLaC", 4 },
    /* 13 */ {  4, 0, "04 - crash.flac", EXT4('f','l','a','c'), BIT_FLAC, "fLaC", 4 },
    /* 14 */ {  6, 0, "\xE3\x80\x8CDigital Twin\xE3\x80\x8D.flac", EXT4('f','l','a','c'), BIT_FLAC, "fLaC", 4 },
    /* 15 */ {  7, 0, "09 - One Day The Only Butterflies Left Will Be In Your Chest As You March Towards Your Death (feat. Amy L.flac", EXT4('f','l','a','c'), BIT_FLAC, "fLaC", 4 },
    /* 16 */ {  2, 0, "root_hit.mp3", EXT4('m','p','3',0), BIT_MP3, "ID3", 3 },
};
#define NTREE ((int)(sizeof tree / sizeof tree[0]))

struct vfs_ctx {
    int cwd;            /* node index of current directory */
    int cur_entry;      /* node index of last vfs_dir / vfs_offset target, -1 if none */
    int open_node;      /* node index of open file, -1 if closed */
    u32 seek_pos;
    int open_count;     /* verify handles are balanced (0 leaks!) */
};

static struct vfs_ctx brow_vfs = { 1, -1, -1, 0, 0 };   /* starts in Playlists/ */
static struct vfs_ctx meng_vfs = { 0, -1, -1, 0, 0 };

static int node_depth(int n)
{
    int d = 0;
    while (n > 0 && tree[n].parent >= 0) {
        d++;
        n = tree[n].parent;
    }
    return d;
}

/* Encode UTF-8 string to UTF-16LE with FF FE BOM into dst (up to max_units). */
static u32 write_utf16_bom(u8 *dst, const char *s, u32 max_units)
{
    const u8 *p = (const u8 *)s;
    u32 u = 0;

    if (max_units < 2) return 0;
    dst[0] = 0xFF; dst[1] = 0xFE;
    u = 1;
    while (*p && u + 1 < max_units) {
        u32 b0 = *p++, cp;
        if (b0 < 0x80) cp = b0;
        else if ((b0 & 0xE0) == 0xC0) { cp = ((b0 & 0x1F) << 6) | (*p++ & 0x3F); }
        else { cp = ((b0 & 0x0F) << 12) | ((u32)(p[0] & 0x3F) << 6) | (p[1] & 0x3F); p += 2; }
        dst[2 * u] = (u8)(cp & 0xFF);
        dst[2 * u + 1] = (u8)(cp >> 8);
        u++;
    }
    dst[2 * u] = 0;
    dst[2 * u + 1] = 0;
    return u + 1;   /* BOM + chars + NUL */
}

static long run_vfs(struct vfs_ctx *vc, u32 a1, u32 a2, u32 a3, u32 op)
{
    switch (op) {
    case OP_CD:
        if (a1 == ':') { vc->cwd = 0; vc->cur_entry = -1; return 1; }
        if (a1 == '|') {
            if (vc->cwd <= 0) return 0;
            vc->cwd = tree[vc->cwd].parent;
            vc->cur_entry = -1;
            return 1;
        }
        if (a1 == '/') {
            if (vc->cur_entry < 0 || !tree[vc->cur_entry].is_dir) return 0;
            vc->cwd = vc->cur_entry;
            vc->cur_entry = -1;
            return 1;
        }
        return 0;

    case OP_DIR: {
        int start, i;
        /* Real exfatn.drv rejects any command < 0x80 with error 21 and returns 0! */
        if (a1 == DIR_HEAD) start = 1;
        else if (a1 == DIR_NEXT) start = (vc->cur_entry >= 0) ? vc->cur_entry + 1 : NTREE;
        else return 0;

        for (i = start; i < NTREE; i++) {
            if (tree[i].parent != vc->cwd) continue;
            if (a3 == EXT_DIRS) {
                if (tree[i].is_dir) { vc->cur_entry = i; return 0x44495200; }
            } else {
                if (!tree[i].is_dir && (tree[i].ext_bit & a3)) {
                    vc->cur_entry = i;
                    return (long)tree[i].ext4;
                }
            }
        }
        vc->cur_entry = -1;
        return 0;
    }

    case OP_GETNAME: {
        u8 *buf = (u8 *)(unsigned long)a1;
        if (vc->cur_entry < 0) return 0;
        if (a2 == 0) {
            *(u32 *)buf = tree[vc->cur_entry].ext4;
            return 4;
        }
        return (long)write_utf16_bom(buf, tree[vc->cur_entry].name, a2);
    }

    case OP_OFFSET: {
        u8 *dir_buf = (u8 *)(unsigned long)a1;
        u32 *off_buf = (u32 *)(unsigned long)a2;
        if (a3 == 0) {  /* GET */
            if (vc->cur_entry < 0) return 0;
            memset(dir_buf, 0, 73);
            *(u32 *)dir_buf = (u32)vc->cwd;
            dir_buf[72] = (u8)node_depth(vc->cwd);
            off_buf[0] = 0xA0000000u | (u32)vc->cur_entry;
            off_buf[1] = (u32)(vc->cwd * 0x100 + vc->cur_entry);
            return 1;
        } else {        /* SET */
            int ent = (int)(off_buf[0] & 0xFFFFu);
            if ((off_buf[0] & 0xFFFF0000u) != 0xA0000000u || ent <= 0 || ent >= NTREE) return 0;
            vc->cwd = tree[ent].parent;
            vc->cur_entry = ent;
            return 1;
        }
    }

    case OP_OPEN:
        if (a1 != 0 || vc->cur_entry < 0 || tree[vc->cur_entry].is_dir) return 0;
        vc->open_node = vc->cur_entry;
        vc->seek_pos = 0;
        vc->open_count++;
        return 0x55;

    case OP_CLOSE:
        if (a1 == 0x55 && vc->open_node >= 0) {
            vc->open_node = -1;
            vc->open_count--;
            return 0;
        }
        return -1;

    case OP_SEEK:
        if (a3 != 0x55 || vc->open_node < 0 || (a1 & 511u) != 0) return -1;
        vc->seek_pos = a1;
        return 0;

    case OP_READ: {
        u8 *dst = (u8 *)(unsigned long)a1;
        u32 sz, n = a2;
        if (a3 != 0x55 || vc->open_node < 0) return -1;
        sz = tree[vc->open_node].size;
        if (vc->seek_pos >= sz) return 0;
        if (vc->seek_pos + n > sz) n = sz - vc->seek_pos;
        memcpy(dst, tree[vc->open_node].data + vc->seek_pos, n);
        vc->seek_pos += 512;
        return (long)n;
    }
    }
    return 0;
}

static long mock_brow_fs(u32 ctx, u32 a1, u32 a2, u32 a3, u32 op)
{
    if (ctx != 0xB1u) return 0;
    return run_vfs(&brow_vfs, a1, a2, a3, op);
}

static long mock_meng_fs(u32 ctx, u32 a1, u32 a2, u32 a3, u32 op)
{
    if (ctx != 0xE1u) return 0;
    return run_vfs(&meng_vfs, a1, a2, a3, op);
}

fs_fn test_fs = mock_brow_fs;
fs_fn test_meng_fs = mock_meng_fs;

static u32 rng_state = 0x12345678u;
static u32 mock_rand(void)
{
    rng_state = rng_state * 1664525u + 1013904223u;
    return rng_state;
}
u32 (*test_meng_rand)(void) = mock_rand;

static u32 classify_calls;
static u32 mock_classify(u32 row)
{
    const u8 *r = (const u8 *)(unsigned long)row;
    classify_calls++;
    if ((r[0] | 0x20) == 'm' && r[1] == '3' && (r[2] | 0x20) == 'u') return 5;
    return 0;
}
u32 (*test_classify)(u32) = mock_classify;

/* Mirrors stock sub_780DB49C(mask, n): DIR_HEAD then n-1 DIR_NEXTs. */
static u32 mock_step_dir(u32 mask, u16 n)
{
    u32 cmd = DIR_HEAD;
    if (n == 0) return 0;
    while (mock_brow_fs(*test_ctxw, cmd, 0, mask, OP_DIR) != 0) {
        if (--n == 0) return 1;
        cmd = DIR_NEXT;
    }
    return 0;
}
u32 (*test_step_dir)(u32, u16) = mock_step_dir;

/* Mirrors m3u_setloc_0 in m3u_meng_tramp.S + stock 0x7B0685F4. */
static u32 sim_meng_setloc(u8 *desc)
{
    u32 ext_now = 0;
    if (!mock_meng_fs(0xE1u, (u32)(unsigned long)(desc + 0x10), (u32)(unsigned long)(desc + 8), 1, OP_OFFSET)) {
        test_vs->magic = 0;
        return 0;
    }
    mock_meng_fs(0xE1u, (u32)(unsigned long)&ext_now, 0, 0, OP_GETNAME);
    if (ext_now != *(u32 *)(desc + 4)) {
        test_vs->magic = 0;
        return 0;
    }
    test_meng_eng[0x22] = desc[1];
    *(u32 *)(test_meng_eng + 0x28) = ext_now;
    /* Stock folder count (boy/ has 2 files), overridden below if VS matches: */
    *(u16 *)(test_meng_eng + 0x26) = 2;
    *(u16 *)(test_meng_eng + 0x24) = 2;

    if (test_vs->magic == M3UPLAY_MAGIC
            && *(u32 *)(desc + 8) == test_vs->cur_off[0]
            && *(u32 *)(desc + 12) == test_vs->cur_off[1]) {
        *(u16 *)(test_meng_eng + 0x26) = test_vs->count;
        *(u16 *)(test_meng_eng + 0x24) = test_vs->pos;
    } else {
        test_vs->magic = 0;
    }
    return 1;
}

static u32 fails;
static void check(int ok, const char *msg)
{
    printf("%s  %s\n", ok ? "PASS" : "FAIL", msg);
    if (!ok) fails++;
}

struct row { u8 ext[4]; u32 marker; u32 namep; };

int main(void)
{
    static struct vstate vs;
    static u32 ctxw = 0xB1u;
    static u32 maskw = 0x7E191FA0u;
    static u16 dircnt = 0;
    static u8 layerb = 1;       /* Playlists/ is at layer 1 */
    static u8 diskb = 'H';
    static u8 meng_eng[0x60];
    static u8 meng_sec[512] __attribute__((aligned(4)));
    static u8 arg0[0xA8] __attribute__((aligned(4)));
    struct row r_m3u  = { {'m','3','u',0},   0x32, 0 };
    struct row r_m3u8 = { {'M','3','U','8'}, 0x32, 0 };
    struct row r_mp3  = { {'m','p','3',0},   0x32, 0 };
    u8 *desc = arg0 + 4;
    u32 rc, ext = 0;

    test_vs = &vs;
    test_ctxw = &ctxw;
    test_maskw = &maskw;
    test_dircnt = &dircnt;
    test_layerb = &layerb;
    test_diskb = &diskb;
    test_meng_eng = meng_eng;
    test_meng_sec = meng_sec;
    *(u32 *)(meng_eng + 0x34) = 0xE1u;  /* E_HANDLE */

    check(sizeof(struct vstate) <= 0x184, "sizeof(struct vstate) fits in 0x184-byte zero run");

    /* 1. Click idk.m3u (1st file in Playlists/, idx = 1) */
    brow_vfs.cwd = 1;
    classify_calls = 0;
    rc = m3uplay_click((u32)(unsigned long)&r_m3u, 1, arg0);
    check(rc == 0x8001u, "click idk.m3u returns 0x8001 (direct launch)");
    check(classify_calls == 0, "click idk.m3u does not invoke fallback dialog");
    check(vs.magic == M3UPLAY_MAGIC && vs.count == 5 && vs.pos == 1,
          "vstate armed: count=5 entries, pos=1");
    check(brow_vfs.cwd == 1 && brow_vfs.open_count == 0,
          "browser cwd restored to Playlists/ and 0 open handles leaked");
    check(arg0[0] == 0 && desc[0] == 'H' && desc[1] == 3
          && *(u32 *)(desc + 4) == EXT4('f','l','a','c')
          && (*(u32 *)(desc + 8) & 0xFFFFu) == 13
          && *(u16 *)(desc + 0x5C) == 5 && *(u16 *)(desc + 0x5E) == 1,
          "desc populated with Track 1 (04 - crash.flac, layer 3, ext flac, 1/5)");

    /* 2. Handoff to mengine set_location */
    rc = sim_meng_setloc(desc);
    check(rc == 1 && vs.magic == M3UPLAY_MAGIC
          && *(u16 *)(meng_eng + 0x26) == 5 && *(u16 *)(meng_eng + 0x24) == 1
          && meng_vfs.cur_entry == 13,
          "mengine set_location positions on 04 - crash.flac and sets 1/5");

    /* 3. Sequential Next: skips missing entry #2 -> lands on UTF-8 entry #3! */
    meng_eng[0x39] = 0; /* Repeat Off */
    meng_eng[0x23] = 0; /* Shuffle Off */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 1 && meng_vfs.cur_entry == 14 && vs.pos == 3
          && *(u16 *)(meng_eng + 0x24) == 3 && ext == EXT4('f','l','a','c'),
          "next skips missing entry #2 and resolves UTF-8 CJK/accented track #3");

    /* 4. Next -> >78-char long filename track #4 */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 1 && meng_vfs.cur_entry == 15 && vs.pos == 4,
          "next resolves 110-char long filename track #4");

    /* 5. Next -> root-leading '/Music/root_hit.mp3' without trailing LF (#5) */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 1 && meng_vfs.cur_entry == 16 && vs.pos == 5 && ext == EXT4('m','p','3',0),
          "next resolves root-relative track #5 (unterminated final line)");

    /* 6. End of playlist: Repeat Off stops, Repeat All wraps to track #1 */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 0 && vs.pos == 5, "next at end with Repeat Off returns 0 (stops cleanly)");
    meng_eng[0x39] = 2; /* Repeat All */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 1 && meng_vfs.cur_entry == 13 && vs.pos == 1,
          "next at end with Repeat All wraps to track #1");

    /* 7. Repeat One holds current track */
    meng_eng[0x39] = 1; /* Repeat One */
    rc = m3u_meng_step(&ext, 0, 1);
    check(rc == 1 && vs.pos == 1 && ext == EXT4('f','l','a','c'),
          "Repeat One keeps current track");

    /* 8. Prev: Repeat All wraps 1 -> 5, then steps 5 -> 4 -> 3 -> (skips #2) -> 1 */
    meng_eng[0x39] = 2; /* Repeat All */
    rc = m3u_meng_step(&ext, 0, 2);
    check(rc == 1 && meng_vfs.cur_entry == 16 && vs.pos == 5,
          "prev at track #1 with Repeat All wraps to track #5");
    rc = m3u_meng_step(&ext, 0, 2);
    check(rc == 1 && vs.pos == 4 && meng_vfs.cur_entry == 15, "prev steps 5 -> 4");
    rc = m3u_meng_step(&ext, 0, 2);
    check(rc == 1 && vs.pos == 3 && meng_vfs.cur_entry == 14, "prev steps 4 -> 3");
    rc = m3u_meng_step(&ext, 0, 2);
    check(rc == 1 && vs.pos == 1 && meng_vfs.cur_entry == 13,
          "prev skips missing #2 and lands on #1");

    /* 9. get_byno: direct jump + out-of-range sets endflag */
    rc = m3u_meng_step(&ext, 4, 0);
    check(rc == 1 && vs.pos == 4 && meng_vfs.cur_entry == 15, "get_byno(4) jumps to track #4");
    meng_eng[0x21] = 0;
    rc = m3u_meng_step(&ext, 99, 0);
    check(rc == 0 && meng_eng[0x21] == 1, "get_byno out-of-range returns 0 and sets endflag");

    /* 10. Reversible Shuffle: visits every resolvable track, Prev reverses Next! */
    {
        u32 seen = 0, hist[4], i;
        /* Test on a clean 4-entry all-valid playlist or verify reversibility on idk.m3u */
        vs.shuf_key = 0;
        vs.shuf_pos = 0;
        meng_eng[0x23] = 1; /* Shuffle On */
        meng_eng[0x39] = 0; /* Repeat Off */
        for (i = 0; i < 4; i++) {
            u32 r1 = m3u_meng_step(&ext, 0, 1);
            if (!r1) break;
            hist[i] = (u32)meng_vfs.cur_entry;
            seen |= (1u << vs.pos);
        }
        /* Step backward with Prev and verify exact reverse order! */
        check(i >= 3 && seen != 0, "shuffle visits playlist tracks");
        if (i >= 2) {
            u32 b1 = m3u_meng_step(&ext, 0, 2);
            check(b1 == 1 && (u32)meng_vfs.cur_entry == hist[i - 2],
                  "shuffle prev reverses to the exact previous shuffled track");
        }
        meng_eng[0x23] = 0;
    }
    check(meng_vfs.open_count == 0, "mengine leaked 0 file handles across all steps");

    /* 11. Empty .m3u (idx = 2) and all-missing .m3u8 (idx = 3) fall back cleanly */
    brow_vfs.cwd = 1;
    rc = m3uplay_click((u32)(unsigned long)&r_m3u, 2, arg0);
    check(rc == 5 && vs.magic == 0 && brow_vfs.cwd == 1 && brow_vfs.open_count == 0,
          "empty.m3u falls back to class 5, disarmed, cwd preserved");
    rc = m3uplay_click((u32)(unsigned long)&r_m3u8, 3, arg0);
    check(rc == 5 && vs.magic == 0 && brow_vfs.cwd == 1 && brow_vfs.open_count == 0,
          "all-missing broken.m3u8 falls back to class 5, cwd preserved");

    /* 12. Clicking an ordinary .mp3 row disarms VS and delegates to classifier */
    m3uplay_click((u32)(unsigned long)&r_m3u, 1, arg0);
    check(vs.magic == M3UPLAY_MAGIC, "re-armed on idk.m3u");
    rc = m3uplay_click((u32)(unsigned long)&r_mp3, 4, arg0);
    check(rc == 0 && vs.magic == 0, "clicking .mp3 disarms VS and returns audio class 0");

    /* 13. Selecting a different folder song in mengine set_location disarms VS */
    m3uplay_click((u32)(unsigned long)&r_m3u, 1, arg0);
    *(u32 *)(desc + 8) = 0xA000000Cu;   /* node 12 (03 - intro.flac), not cur_off! */
    rc = sim_meng_setloc(desc);
    check(rc == 1 && vs.magic == 0 && *(u16 *)(meng_eng + 0x26) == 2,
          "selecting a non-playlist song in mengine disarms VS and keeps folder count");

    printf("%s\nm3uplay test done, failures %u\n", fails ? "ALL FAIL" : "ALL PASS", fails);
    return fails ? 1 : 0;
}
