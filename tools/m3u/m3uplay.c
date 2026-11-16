/* M3U play-on-click target code. See m3uplay.h for the design.
 *
 * Freestanding blob rules: no writable data (the build asserts it), no
 * string literals, no libc - every buffer lives on the stack or in the
 * shared vstate at A_VSTATE. All stock entry points are called through
 * function-pointer constants (jalr), never direct jal, because some of
 * them (0x780DB461, 0xBFC16A2D) live in other 256 MB regions than this
 * blob (bank 0x400D4C00, region 0x4).
 *
 * The host/QEMU test compiles this with -DM3UPLAY_TEST, which remaps the
 * fixed addresses to test RAM and routes the fs/classify/fetch calls
 * through mock pointers defined by the harness.
 */
#include "m3uplay.h"
#include "m3u.h"

typedef long (*fs_fn)(u32, u32, u32, u32, u32);

#ifdef M3UPLAY_TEST
/* the harness installs these (m3uplaytest.c) */
extern fs_fn test_fs;
extern u32 (*test_classify)(u32);
extern u32 (*test_fetch)(u32, u32);
#define FS_CALL   (test_fs)
#define CLASSIFY  (test_classify)
#define FETCHFN   (test_fetch)
#else
#define FS_CALL   ((fs_fn)0xBFC16A2Du)    /* browser.ap resident module-0x11 stub */
#define CLASSIFY  ((u32 (*)(u32))0x40D14E01u)   /* stock classifier 0x40D14E00 */
#define FETCHFN   ((u32 (*)(u32, u32))0x780DB461u)  /* record fetch wrapper */
#endif

#ifdef M3UPLAY_PROBE
/* diagnostic build (--probe-m3uplay): on any failure after the record fetch,
 * force the engine launch (class 0) instead of the stock dialog, so the
 * on-device outcome shows whether the hook chain ran at all */
#define FALLBACK(row)  return 0
#else
#define FALLBACK(row)  return CLASSIFY(row)
#endif

/* fs op ids (tools/fw/m30fs.h) */
#define OP_OPEN  5
#define OP_CLOSE 7
#define OP_SEEK  0xB
#define OP_READ  0xD

static long fs_open(const volatile u8 *name16) { return FS_CALL(FSCTX, (u32)name16, 0, 0, OP_OPEN); }
static long fs_seek(u32 h, u32 pos)        { return FS_CALL(FSCTX, pos, 0, h, OP_SEEK); }
static long fs_read(u32 h, u8 *b, u32 n)   { return FS_CALL(FSCTX, (u32)b, n, h, OP_READ); }
static long fs_close(u32 h)                { return FS_CALL(FSCTX, h, 0, 0, OP_CLOSE); }

static u8 lc8(u8 c) { return (c >= 'A' && c <= 'Z') ? (u8)(c + 0x20) : c; }

/* ---- m3u test on a UTF-16LE name (BOM optional) --------------------------
 * The file's record name always carries the extension, so test the name
 * suffix: ".m3u" or ".m3u8", any case. The on-device row struct layout is
 * not pinned down, so the record name is the witness we rely on. */
static int name_is_m3u(const volatile u8 *nm)
{
    u32 i = 0;

    if (nm[0] == 0xFF && nm[1] == 0xFE) {
        i = 1;                          /* skip the BOM (character index) */
    }
    while (nm[2 * i] != 0 || nm[2 * i + 1] != 0) {
        if (nm[2 * i + 1] != 0 || i >= 0x38) {
            return 0;                   /* non-ASCII or absurdly long */
        }
        i++;
    }
    /* i = character length; match the ".m3u" / ".m3u8" suffix */
    if (i >= 4 && nm[2 * (i - 4)] == '.'
            && lc8(nm[2 * (i - 3)]) == 'm' && nm[2 * (i - 2)] == '3'
            && lc8(nm[2 * (i - 1)]) == 'u') {
        return 1;
    }
    return i >= 5 && nm[2 * (i - 5)] == '.'
        && lc8(nm[2 * (i - 4)]) == 'm' && nm[2 * (i - 3)] == '3'
        && lc8(nm[2 * (i - 2)]) == 'u' && nm[2 * (i - 1)] == '8';
}

/* ---- copy the record's name into vstate->name ---------------------------
 * Dir-stream record names are BOM+UTF-16LE; the BOM is (re-)written even if
 * the source lacks it, because fs_open expects a BOM name. The buffer is
 * pre-zeroed, so a single UTF-16 NUL also terminates safely. 0 on success. */
static int copy_name(const u8 *nm)
{
    u32 i = 0;
    u32 j;
    volatile u8 *d = VS->name;

    for (j = 0; j < VS_NAME_MAX; j++) {
        d[j] = 0;
    }
    if (nm[0] == 0xFF && nm[1] == 0xFE) {
        i = 1;
    }
    d[0] = 0xFF;
    d[1] = 0xFE;
    for (j = 0; 2 + 2 * j + 1 < VS_NAME_MAX; j++) {
        u8 lo = nm[2 * i];
        u8 hi = nm[2 * i + 1];
        d[2 + 2 * j] = lo;
        d[3 + 2 * j] = hi;
        if (lo == 0 && hi == 0) {
            return 0;                   /* NUL seen; rest stays zeroed */
        }
        i++;
    }
    return -1;                          /* too long */
}

/* ---- sector-buffered reader for the m3u parser --------------------------
 * Kernel transfers must start sector-aligned, use whole sectors and not
 * cross a 4 KB boundary (tools/library/index.c rule), so reads go one
 * 512-byte sector at a time; the kernel clamps each read to the file size,
 * and a zero-byte read marks EOF (a 64 KB cap in rd->size bounds the loop). */

struct rd {
    u32 h;
    u32 size;
    u32 pos;        /* logical cursor */
    u32 slen;       /* valid bytes in sec */
    u32 spos;       /* cursor within sec */
    u8  sec[512];
};

static long rd_read(void *cookie, char *buf, unsigned long n)
{
    struct rd *r = (struct rd *)cookie;
    unsigned long got = 0;

    while (n) {
        u32 k;
        if (r->spos >= r->slen) {
            u32 off = r->pos & ~511u;
            if (off >= r->size) {
                break;
            }
            long n;
            if (fs_seek(r->h, off) < 0) {
                return got ? (long)got : -1;
            }
            n = fs_read(r->h, r->sec, 512);
            if (n <= 0) {
                break;              /* EOF: the kernel clamps reads to file size */
            }
            r->slen = (u32)n;
            r->spos = r->pos - off;
            if (r->spos >= r->slen) {
                break;
            }
        }
        k = r->slen - r->spos;
        if (k > n) {
            k = n;
        }
        {
            u32 i;
            for (i = 0; i < k; i++) {
                buf[i] = (char)r->sec[r->spos + i];
            }
        }
        r->spos += k;
        r->pos += k;
        buf += k;
        n -= k;
        got += k;
    }
    return (long)got;
}

/* ---- playlist access ---------------------------------------------------- */

static int playlist_open(struct rd *r, struct m3u *m, struct m3u_io *io)
{
    long h;

    h = fs_open(VS->name);
    if (h <= 0) {
        return -1;
    }
    r->h = (u32)h;
    r->size = 0x40000;      /* sanity cap only; reads stop at EOF via fs_read == 0 */
    r->pos = 0;
    r->slen = 0;
    r->spos = 0;
    io->read = rd_read;
    io->cookie = r;
    /* empty dir prefix: entries are used as-is, relative to the current
     * dir - which is the playlist's own dir, exactly where the stock
     * engine opens record names from */
    if (m3u_init(m, io, 0) != M3U_OK) {   /* NULL dir prefix: entries used as-is */
        fs_close((u32)h);
        return -1;
    }
    return 0;
}

/* Walk the playlist in VS->name. With rec == 0, count all entries and
 * return the count (0xFFFFFFFF on any error). With rec != 0, build the
 * 0x100-byte virtual dir record for entry `want` into rec and return 0,
 * or 0xFFFFFFFF if the entry does not exist or is too long. */
static u32 playlist_walk(u32 want, u8 *rec)
{
    struct rd r;
    struct m3u m;
    struct m3u_io io;
    u32 i = 0;
    int rc;

    if (playlist_open(&r, &m, &io) != 0) {
        return 0xFFFFFFFFu;
    }
    for (;;) {
        rc = m3u_next(&m);
        if (rc == M3U_END) {
            break;
        }
        if (rc < 0) {
            fs_close(r.h);
            return 0xFFFFFFFFu;
        }
        if (rec != 0 && i == want) {
            u32 k;
            volatile u8 *rp = (volatile u8 *)rec;
            volatile u8 *nm;
            for (k = 0; k < 0x100; k++) {
                rp[k] = 0;
            }
            *(volatile u32 *)(rec + 4) = (u32)(rec + 0x10);  /* name ptr */
            if (m.line_len > (0x100 - 0x10 - 4) / 2) {
                fs_close(r.h);
                return 0xFFFFFFFFu;
            }
            nm = (volatile u8 *)(rec + 0x10);
            nm[0] = 0xFF;
            nm[1] = 0xFE;
            for (k = 0; k < m.line_len; k++) {
                nm[2 + 2 * k] = (u8)m.line[k];
                nm[3 + 2 * k] = 0;
            }
            nm[2 + 2 * m.line_len] = 0;             /* UTF-16 double NUL */
            nm[3 + 2 * m.line_len] = 0;
            nm[4 + 2 * m.line_len] = 0;
            nm[5 + 2 * m.line_len] = 0;
            fs_close(r.h);
            return 0;
        }
        i++;
    }
    fs_close(r.h);
    return rec ? 0xFFFFFFFFu : i;
}

/* ---- the record-fetch hook (pool word of 0x780DB460) --------------------
 * Called with the fs stub's arguments: (ctx, zeb(idx), 0, x, op). The stock
 * wrapper publishes the return value to 0x9FC1573C. */
u32 m3uplay_fetch(u32 ctx, u32 idx, u32 a2, u32 x, u32 op)
{
    if (op != 1 || VS->magic != M3UPLAY_MAGIC || VS->flag != 1) {
        return (u32)FS_CALL(ctx, idx, a2, x, op);   /* stock passthrough */
    }
    idx &= 0xFF;
    if (idx >= 0x80) {
        /* parent/child markers: behave exactly as stock */
        return (u32)FS_CALL(ctx, idx, a2, x, op);
    }
    if (idx < VS->base || idx >= VS->base + VS->count) {
        return (u32)FS_CALL(ctx, idx, a2, x, op);   /* outside the playlist */
    }
    if (playlist_walk(idx - VS->base, (u8 *)VS->rec) != 0) {
        return 0;   /* read/parse failure: the wrapper flags end-of-list */
    }
    return (u32)&VS->rec[0];
}

/* ---- the click handler (reached via m3uplay_tramp) ----------------------
 * row = the selected row (ext[4] at +0), idx = its dir index (list_no-count,
 * computed by the trampoline). Returns the class for the dispatcher. */
u32 m3uplay_click(u32 row, u32 idx)
{
    u32 rec;
    u32 count;

    VS->flag = 0;                       /* every file click resets serving */
    FETCHFN(idx, 0);                    /* flag==0: real fetch, publishes the row's record */
    rec = REC_G;
    if (rec == 0) {
        return CLASSIFY(row);           /* fetch itself broken: stay safe */
    }
#ifndef M3UPLAY_PROBE
    /* m3u test on the fetched record's name (the row layout is not pinned
     * down on hardware; the record name always carries the extension) */
    if (!name_is_m3u(*(const volatile u8 * const *)(rec + 4))) {
        return CLASSIFY(row);
    }
#endif
    if (copy_name(*(const u8 * const *)(rec + 4)) != 0) {
        FALLBACK(row);
    }
    count = playlist_walk(0, 0);
    if (count == 0xFFFFFFFFu || count == 0) {
        FALLBACK(row);                  /* unreadable or empty */
    }
    VS->base = idx;
    VS->count = count;
    VS->magic = M3UPLAY_MAGIC;
    VS->flag = 1;
    FETCHFN(idx, 0);                    /* flag==1: hook serves track 0 */
    if (REC_G == 0) {
        VS->flag = 0;
        VS->magic = 0;
        FALLBACK(row);
    }
    return 0;                           /* class 0: stock engine launch */
}
