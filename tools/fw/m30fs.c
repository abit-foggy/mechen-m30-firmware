/* Firmware filesystem adapter. See m30fs.h for the verified ABI.
 *
 * Call shapes come from `tools/library/index.c` -- the upstream expanded
 * library builder, which is working code on the player -- rather than from
 * symmetry with the write path:
 *
 *   open   FS_OP(ctx, name,   0,   0, 5)
 *   read   FS_OP(ctx, buffer, len, h, 0xD)
 *   seek   FS_OP(ctx, pos,    0,   h, 0xB)
 *   close  FS_OP(ctx, h,      0,   0, 7)
 *   size   FS_OP(ctx, &size,  h,   0, 9)   (op 9 in the builder's create path)
 *
 * The builder also documents the hardware constraint that shaped its own
 * `fs_io`: kernel transfers are problematic unless they start at a
 * sector-aligned offset, use whole-sector sizes, and do not cross a 4 KB
 * boundary in one call. `index.c` implements that by splitting every transfer
 * into pieces that stop at the next 4096-byte boundary, and it issues a seek
 * only when the handle's position is not already there. This adapter does the
 * same, and adds a sector buffer on top so callers get an ordinary byte stream
 * while the kernel only ever sees aligned whole-sector reads.
 *
 * Padding behind the logical end of file is never exposed: `m30fs_read` clamps
 * to the size reported by op 9.
 */
#include "m30fs.h"

#define BLOCK 4096u        /* no kernel call may cross a boundary of this */
#define PIECE BLOCK         /* one block per call: what the builder verified */

typedef long (*fs_fn)(u32 a0, u32 a1, u32 a2, u32 a3, u32 op);

static fs_fn fs;                 /* the module-0x11 stub */
static u32   fs_ctx;             /* the filesystem context */
static u32   cur;                /* the handle's kernel position, builder-style */

/* the read buffer: one sector, so a whole-sector kernel transfer never hands
 * the caller padding it did not ask for */
static u8   sbuf[M30FS_SECTOR];
static u32  sbase;               /* file offset of sbuf[0] */
static u32  slen;                /* valid bytes in sbuf */
static u32  spos;                /* cursor within sbuf */

static void copy(u8 *d, const u8 *s, u32 n) { while (n--) { *d++ = *s++; } }

void m30fs_set_stub(u32 stub, u32 ctx)
{
    fs = (fs_fn)stub;
    fs_ctx = ctx;
    cur = 0xFFFFFFFFu;
    sbase = 0;
    slen = 0;
    spos = 0;
}

#ifdef M30FS_TEST_HOOK
/* host tests install their mock through this, since there is no kernel to
 * point at; it is compiled out of the target build */
void m30fs_test_install(long (*fn)(u32, u32, u32, u32, u32))
{
    fs = fn;
    fs_ctx = 0;
}
#endif

static long fscall(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    return fs(a0, a1, a2, a3, op);
}

/* Position the handle. Issues op 0xB only when the handle is not already
 * there, exactly as `index.c`'s fs_seek does. */
static int seek_to(u32 handle, u32 pos)
{
    if (cur == pos) {
        return M30FS_OK;
    }
    /* the builder's seek: FS_OP(ctx, pos, 0, h, 0xB) -- handle is the FOURTH
     * argument, not a register afterthought */
    if (fscall(fs_ctx, pos, 0, handle, M30FS_OP_SEEK) < 0) {
        return M30FS_ERR;
    }
    cur = pos;
    return M30FS_OK;
}

/* One aligned kernel read of whole sectors covering [pos, pos+n).
 * Returns the byte count asked for, or a negative M30FS_ERR. The destination
 * must have room for the rounded-up byte count, because the kernel hands back
 * whole sectors including any padding behind the logical end of file. */
static long raw_read(u32 handle, u32 pos, u8 *dst, u32 n)
{
    long total = 0;

    if (seek_to(handle, pos) != M30FS_OK) {
        return M30FS_ERR;
    }
    while (n) {
        u32 k = BLOCK - (pos & (BLOCK - 1));   /* bytes to the next boundary */
        long got;

        if (k > PIECE) {
            k = PIECE;
        }
        if (k > n) {
            k = n;
        }
        /* the builder's read: FS_OP(ctx, buffer, len, h, 0xD) -- the handle is
         * the FOURTH argument. Passing 0 here was the bug the host test caught:
         * the kernel would read from no file at all. */
        got = fscall(fs_ctx, (u32)dst, k, handle, M30FS_OP_READ);
        if (got < 0) {
            return M30FS_ERR;
        }
        dst += k;                 /* the kernel fills whole sectors, so the   */
        pos += k;                 /* destination advances by what was asked   */
        n   -= k;
        cur  = pos;
        total += k;
    }
    return total;
}

int m30fs_init(struct m30fs_file *f, u32 ctx, const char *path)
{
    u32 i;
    char name[M30FS_PATH_MAX];

    /* `ctx` is accepted for symmetry with m30fs_set_stub but the context was
     * already installed there; the adapter never changes it mid-flight. */
    (void)ctx;

    if (!f || !path) {
        return M30FS_ERR;
    }
    /* zero the state first, so a failed open always leaves the file safe to
     * close; then refuse to run with no stub installed -- a module that
     * forgets m30fs_set_stub gets a clean error, not a jump through zero */
    f->handle = 0;
    f->size = 0;
    f->pos = 0;
    if (!fs) {
        return M30FS_ERR;
    }
    f->size = 0;
    f->pos = 0;

    /* The kernel's open takes the name as UTF-16LE with a BOM, not raw bytes:
     * tools/library/index.c's name() documents itself as "as FUN_40194c00:
     * BOM then UTF-16LE", and it is the same builder this ABI came from. The
     * host mock is byte-transparent and cannot catch a wrong encoding. */
    {
        u8 *out = (u8 *)name;
        u32 w = 0;
        *out++ = 0xFF; *out++ = 0xFE;
        for (i = 0; path[i]; i++) {
            if (i >= M30FS_PATH_MAX / 2 - 1) {
                return M30FS_ERR_TOOBIG;
            }
            *out++ = (u8)path[i];      /* ASCII widens to UTF-16LE */
            *out++ = 0;
            w++;
        }
        if (w == 0) {
            return M30FS_ERR_BADPATH;
        }
        *out++ = 0; *out = 0;
    }

    /* the stock creator changes to the root drive before opening; do the same */
    if (fscall(fs_ctx, (u32)':', 0, 0, M30FS_OP_CHDIR) < 0) {
        return M30FS_ERR;
    }

    /* op 5 = open. The stock creator passes two zero arguments after the name
     * and takes the handle from $v0, treating 0 as failure. */
    f->handle = (u32)fscall(fs_ctx, (u32)name, 0, 0, M30FS_OP_OPEN);
    if (f->handle == 0) {
        return M30FS_ERR;
    }

    /* op 9 = size. The stock creator passes the handle as the third argument
     * and an output buffer as the second. */
    {
        u32 size = 0;
        long r = fscall(fs_ctx, (u32)&size, f->handle, 0, M30FS_OP_SIZE);
        if (r < 0) {
            m30fs_close(f);
            return M30FS_ERR;
        }
        f->size = size;
    }

    cur = 0;
    sbase = 0;
    slen = 0;
    spos = 0;
    return M30FS_OK;
}

long m30fs_read(struct m30fs_file *f, void *buf, u32 n)
{
    u32 got = 0;
    u8 *out = (u8 *)buf;

    if (!f || !buf || !f->handle) {
        return M30FS_ERR;
    }
    if (n > f->size - f->pos) {
        n = f->size - f->pos;      /* never expose padding behind logical EOF */
    }
    if (n == 0) {
        return 0;
    }

    /* serve from the sector buffer first */
    while (n && spos < slen) {
        u32 k = slen - spos;
        if (k > n) {
            k = n;
        }
        copy(out, sbuf + spos, k);
        out += k; n -= k; spos += k; f->pos += k; got += k;
    }

    /* then refill in aligned whole-sector reads */
    while (n) {
        u32 want = M30FS_SECTOR;
        u32 off = f->pos + got;
        long r;

        if (off & (M30FS_SECTOR - 1)) {
            off -= off & (M30FS_SECTOR - 1);      /* back up to the sector  */
        }
        if (off >= f->size) {
            break;                                 /* nothing logical left  */
        }
        if (f->size - off < want) {
            want = f->size - off;                  /* short logical tail    */
        }

        r = raw_read(f->handle, off, sbuf, want);
        if (r < 0) {
            return got ? (long)got : M30FS_ERR;
        }
        sbase = off;
        slen  = want;              /* logical bytes only: the padding the      */
        spos  = 0;                 /* kernel returned is never handed on       */

        while (n && spos < slen) {
            u32 k = slen - spos;
            if (k > n) {
                k = n;
            }
            copy(out, sbuf + spos, k);
            out += k; n -= k; spos += k; f->pos += k; got += k;
        }
        if (spos >= slen) {
            break;                                 /* end of file           */
        }
    }
    return (long)got;
}

u32 m30fs_tell(const struct m30fs_file *f)
{
    return f ? f->pos : 0;
}

void m30fs_close(struct m30fs_file *f)
{
    if (f && f->handle) {
        fscall(fs_ctx, f->handle, 0, 0, M30FS_OP_CLOSE);
        f->handle = 0;
    }
}
