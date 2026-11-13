/* Firmware filesystem adapter. See m30fs.h for the verified ABI.
 *
 * The syscall is made through a function pointer loaded from a literal, exactly
 * as the stock creator does: it loads the stub address from its own pool rather
 * than calling a fixed address, so the same object code works whichever
 * module's resident mapping is loaded. Callers supply the stub address once at
 * link time via M30FS_STUB.
 *
 * Every call passes four register arguments and the function id as a fifth,
 * stack-passed word at 0x10($sp), matching the stock creator's own sequences.
 */
#include "m30fs.h"

#ifndef M30FS_STUB
#define M30FS_STUB 0xBFC1640Du   /* playlist.ap's resident mapping */
#endif

#ifndef M30FS_CTX
#define M30FS_CTX 0x9FC15410u    /* the context global the stock creator reads */
#endif

/* Five arguments: the compiler emits the o32 sequence for us -- the first four
 * in $a0..$a3 and the fifth at 0x10($sp) -- which is exactly what the stock
 * creator does by hand. Letting the compiler own the ABI means no hand-written
 * asm to get wrong, and it is what makes this safe to call from MIPS16e. */
typedef long (*fs_fn)(u32 a0, u32 a1, u32 a2, u32 a3, u32 op);

static fs_fn fs;          /* the module-0x11 stub */
static u32   fs_ctx;      /* the filesystem context */

void m30fs_set_stub(u32 stub, u32 ctx)
{
    fs = (fs_fn)stub;
    fs_ctx = ctx;
}

static long fscall(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    return fs(a0, a1, a2, a3, op);
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
    f->handle = 0;
    f->size = 0;
    f->pos = 0;

    /* copy the caller's path into our own bounded buffer so a too-long name is
     * refused here rather than handed to the kernel */
    for (i = 0; i < sizeof name - 1 && path[i]; i++) {
        name[i] = path[i];
    }
    name[i] = 0;
    if (path[i] != 0) {
        return M30FS_ERR_TOOBIG;
    }
    if (i == 0 || name[0] == 0) {
        return M30FS_ERR_BADPATH;
    }

    /* the stock creator changes to the root drive before opening; do the same */
    fscall(fs_ctx, (u32)':', 0, 0, M30FS_OP_CHDIR);

    /* op 5 = open. The stock creator passes two zero arguments after the name
     * and takes the handle from $v0, treating 0 as failure. */
    f->handle = (u32)fscall(fs_ctx, (u32)name, 0, 0, M30FS_OP_OPEN);
    if (f->handle == 0) {
        return M30FS_ERR;
    }

    /* op 9 = size. The stock creator passes the handle as the third argument
     * and an output buffer as the second, which is how it learns MUSIC.LIB's
     * size before writing its header. */
    {
        u32 size = 0;
        long r = fscall(fs_ctx, (u32)&size, f->handle, 0, M30FS_OP_SIZE);
        if (r < 0) {
            m30fs_close(f);
            return M30FS_ERR;
        }
        f->size = size;
    }
    return M30FS_OK;
}

long m30fs_read(struct m30fs_file *f, void *buf, u32 n)
{
    long got;

    if (!f || !buf || !f->handle) {
        return M30FS_ERR;
    }
    if (f->pos >= f->size) {
        return 0;                     /* clean end of file */
    }
    if (n > f->size - f->pos) {
        n = f->size - f->pos;         /* never read past the known size */
    }
    if (n == 0) {
        return 0;
    }

    /* op 0xD = read. Argument order follows the stock creator's append-write
     * helper, which passes (buf, len) for op 0xE; reads mirror that with the
     * buffer first and the count second. */
    got = fscall(fs_ctx, (u32)buf, n, f->handle, M30FS_OP_READ);
    if (got < 0) {
        return M30FS_ERR;
    }
    f->pos += (u32)got;
    return got;
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
