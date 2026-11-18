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
static u32 fallback(u32 row) { (void)row; return 0; }
#else
static u32 fallback(u32 row) { return CLASSIFY(row); }
#endif
#define FALLBACK(row)  return fallback(row)

/* fs op ids (tools/fw/m30fs.h) */
#define OP_OPEN  5
#define OP_CLOSE 7
#define OP_CHDIR 8
#define OP_SEEK  0xB
#define OP_READ  0xD


/* ---- m3u test on a UTF-16LE name (BOM optional) --------------------------
 * The file's record name always carries the extension, so test the name
 * suffix: ".m3u" or ".m3u8", any case (ASCII letters fold via | 0x20). The
 * on-device row struct layout is not pinned down, so the record name is the
 * witness we rely on. */
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
    if (i < 4) {
        return 0;
    }
    /* ".m3u" only, from the NUL anchor ('.', '3' are fold-invariant; 'm'/'u'
     * fold via | 0x20). ".m3u8" acceptance is dropped to fit the blob's
     * 0x730-byte budget - a .m3u8 click then takes the stock classifier
     * path exactly as an unpatched firmware does. */
    nm += 2 * i;
    return nm[-8] == '.' && (nm[-6] | 0x20) == 'm' && nm[-4] == '3'
        && (nm[-2] | 0x20) == 'u';
}

/* ---- copy the record's name into vstate->name ---------------------------
 * Dir-stream record names are BOM+UTF-16LE; the BOM is (re-)written even if
 * the source lacks it, because fs_open expects a BOM name. No pre-zeroing:
 * the UTF-16 double NUL written here terminates the name for fs_open, and
 * bytes beyond it are never read (only plh/mode overlay name[0..7] later). */
static int copy_name(const u8 *nm)
{
    const u8 *s = nm;
    volatile u8 *d = VS->name;
    u32 j;

    if (s[0] == 0xFF && s[1] == 0xFE) {
        s += 2;                         /* source already has the BOM */
    }
    d[0] = 0xFF;
    d[1] = 0xFE;
    d += 2;
    for (j = 0; 2 + 2 * j + 1 < VS_NAME_MAX; j++, s += 2, d += 2) {
        u8 lo = s[0];
        u8 hi = s[1];
        d[0] = lo;
        d[1] = hi;
        if (lo == 0 && hi == 0) {
            d[2] = 0;
            d[3] = 0;                   /* complete the double NUL: a shorter
                                           name must leave no stale tail bytes */
            return 0;
        }
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
            long got2;
            if (off >= r->size) {
                break;
            }
            if (FS_CALL(FSCTX, off, 0, r->h, OP_SEEK) < 0) {
                return -1;
            }
            got2 = FS_CALL(FSCTX, (u32)r->sec, 512, r->h, OP_READ);
            if (got2 <= 0) {
                break;              /* EOF: the kernel clamps reads to file size */
            }
            r->slen = (u32)got2;
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

/* Open the playlist, or reuse the handle persisted in vstate. The handle is
 * kept open across serves: after the cd to the root drive the playlist's
 * relative name is no longer reachable, and re-parsing per serve only needs
 * a fresh rd cursor over the same handle. The click path closes a previous
 * playlist's handle before opening a new one. Returns 0 on success. */
static int pl_open(u32 *hout)
{
    long h;

    if (VS->plh) {
        *hout = VS->plh;
        return 0;
    }
    h = FS_CALL(FSCTX, (u32)VS->name, 0, 0, OP_OPEN);   /* fs_open, inlined */
    if (h <= 0) {
        return -1;
    }
    VS->plh = (u32)h;               /* the name is dead from here on */
    *hout = (u32)h;
    return 0;
}

/* Release the persistent playlist handle (a no-op when none is open). */
static void pl_close(void)
{
    if (VS->plh) {
        FS_CALL(FSCTX, VS->plh, 0, 0, OP_CLOSE);    /* fs_close, inlined */
        VS->plh = 0;
    }
}

/* Walk the playlist through the persistent handle. With rec == 0, count all
 * entries and return the count (0xFFFFFFFF on any error), also latching
 * VS_MODE from the first entry. With rec != 0, build the 0x100-byte virtual
 * dir record for entry `want` into rec and return 0, or 0xFFFFFFFF if the
 * entry does not exist or is too long. Never closes the handle. */
static u32 playlist_walk(u32 want, u8 *rec)
{
    struct rd r;
    struct m3u m;
    struct m3u_io io;
    u32 h;
    u32 i = 0;
    int rc;

    if (pl_open(&h) != 0) {
        return 0xFFFFFFFFu;
    }
    r.h = h;
    r.size = 0x40000;      /* sanity cap only; reads stop at EOF via fs_read == 0 */
    r.pos = 0;
    r.slen = 0;
    r.spos = 0;
    io.read = rd_read;
    io.cookie = &r;
    if (m3u_init(&m, &io, 0) != M3U_OK) {
        return 0xFFFFFFFFu;
    }
    for (;;) {
        rc = m3u_next(&m);
        if (rc == M3U_END) {
            break;
        }
        if (rc < 0) {
            return 0xFFFFFFFFu;
        }
        if (rec == 0) {
            if (i == 0) {
                VS_MODE = (m.line_len >= 3 && m.line[0] == '.' && m.line[1] == '.'
                           && m.line[2] == '/') ? 1u : 0u;
            }
        } else if (i == want) {
            const u8 *line = (const u8 *)m.line;
            u32 len = m.line_len;
            u32 k;
            volatile u8 *rp = (volatile u8 *)rec;
            volatile u8 *nm;
            if (VS_MODE && len >= 3 && line[0] == '.' && line[1] == '.'
                    && line[2] == '/') {
                line += 3;              /* the fs cwd is the drive root now */
                len -= 3;
            }
            if (len > (0x100 - 0x10 - 4) / 2) {
                return 0xFFFFFFFFu;
            }
            for (k = 0; k < 0x100 / 4; k++) {
                ((volatile u32 *)rp)[k] = 0;
            }
            /* The engine resolves the file through the record before it
             * opens anything: sys(rec, op 0x11), then rec[0] (op 0x13), then
             * the name at rec+4 (op 0x14). A zeroed +0 selects no entry, so
             * carry the .m3u's own valid dir-stream index (VS->base). */
            *(volatile u32 *)(rec + 0) = VS->base;
            *(volatile u32 *)(rec + 4) = (u32)(rec + 0x10);  /* name ptr */
            nm = (volatile u8 *)(rec + 0x10);
            nm[0] = 0xFF;
            nm[1] = 0xFE;
            for (k = 0; k < len; k++) {
                nm[2 + 2 * k] = line[k];
                nm[3 + 2 * k] = 0;
            }
            *(volatile u32 *)&nm[2 + 2 * len] = 0;   /* UTF-16 double NUL */
            return 0;
        }
        i++;
    }
    return rec ? 0xFFFFFFFFu : i;
}

/* ---- the record-fetch hook (pool word of 0x780DB460) --------------------
 * Called with the fs stub's arguments: (ctx, zeb(idx), 0, x, op). The stock
 * wrapper publishes the return value to 0x9FC1573C. One passthrough exit at
 * the end keeps the blob's constant pools small. */
u32 m3uplay_fetch(u32 ctx, u32 idx, u32 a2, u32 x, u32 op)
{
    if (op == 1 && VS->magic == M3UPLAY_MAGIC && VS->flag == 1) {
        idx &= 0xFF;
        if (idx < 0x80) {               /* markers behave exactly as stock */
            if (idx < VS->base || idx >= VS->base + VS->count) {
                /* A child fetch outside the playlist means the browser is
                 * listing (or has left) the folder: stop serving. */
                VS->flag = 0;
                VS->magic = 0;
            } else {
                if (playlist_walk(idx - VS->base, (u8 *)VS->rec) != 0) {
                    return 0;   /* read/parse failure: end-of-list flag */
                }
                return (u32)&VS->rec[0];
            }
        }
    }
    return (u32)FS_CALL(ctx, idx, a2, x, op);
}

/* ---- the click handler (reached via m3uplay_tramp) ----------------------
 * row = the selected row (ext[4] at +0), idx = its dir index (list_no-count,
 * computed by the trampoline). Returns the class for the dispatcher. */
u32 m3uplay_click(u32 row, u32 idx)
{
    u32 rec;
    u32 count;

    /* Re-clicking the same row (the play prompt re-enters here, or the user
     * picks the row again) must keep the handle: after the cd to the drive
     * root the m3u's own relative name can no longer be re-opened. A click
     * on a different row releases the old playlist first. */
    if (VS->magic != M3UPLAY_MAGIC || idx != VS->base) {
        pl_close();
    }
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
        return fallback(row);
    }
#endif
    if (copy_name(*(const u8 * const *)(rec + 4)) != 0) {
        FALLBACK(row);
    }
    count = playlist_walk(0, 0);        /* opens the m3u, cwd still its dir */
    if (count == 0xFFFFFFFFu || count == 0) {
        pl_close();                     /* open failed or empty: release it */
        FALLBACK(row);                  /* unreadable or empty */
    }
    VS->base = idx;
    VS->count = count;
    VS->magic = M3UPLAY_MAGIC;
    VS->flag = 1;
    if (VS_MODE) {
        /* Entries are ../-relative and the fs has no '..' support: play from
         * the drive root (the stock library's fs_cd(ctx, ':', ...) op 8). */
        FS_CALL(FSCTX, 0x3Au /* ':' = root drive */, 0, 0, OP_CHDIR);
    }
    FETCHFN(idx, 0);                    /* flag==1: hook serves track 0 */
    if (REC_G == 0) {
        VS->flag = 0;
        VS->magic = 0;
        FALLBACK(row);
    }
    return 0;                           /* class 0: stock engine launch */
}
