/* Device-side M3U playlist reader. See m30playlist.h. */
#include "m30playlist.h"

/* The parser reads through this callback, which pulls from m30fs. `cookie` is
 * the m30pl that owns the file handle. */
static long pl_read(void *cookie, char *buf, unsigned long n)
{
    struct m30pl *pl = (struct m30pl *)cookie;
    return m30fs_read(&pl->file, buf, (u32)n);
}

int m30pl_open(struct m30pl *pl, u32 fs_stub, u32 fs_ctx, const char *path,
               const char *dir)
{
    int rc;

    if (!pl) {
        return M30PL_ERR;
    }
    pl->open = 0;

    /* the stub is per-module, so it is set here rather than baked in */
    m30fs_set_stub(fs_stub, fs_ctx);

    rc = m30fs_init(&pl->file, fs_ctx, path);
    if (rc != M30FS_OK) {
        /* map the adapter's codes onto ours; they share the same values, but
         * keep the mapping explicit so the two can diverge safely */
        switch (rc) {
        case M30FS_ERR_TOOBIG:   return M30PL_ERR_TOOBIG;
        case M30FS_ERR_BADPATH:  return M30PL_ERR_BADPATH;
        default:                 return M30PL_ERR;
        }
    }

    /* m3u_init validates the io, so the callback must be in place before it
     * runs; m3u_init only copies the io into the parser, it does not read */
    pl->parser.io.read = pl_read;
    pl->parser.io.cookie = pl;
    if (m3u_init(&pl->parser, &pl->parser.io, dir) != M3U_OK) {
        m30fs_close(&pl->file);
        return M30PL_ERR;
    }

    pl->open = 1;
    return M30PL_OK;
}

int m30pl_next(struct m30pl *pl)
{
    if (!pl || !pl->open) {
        return M30PL_ERR_STATE;
    }
    return m3u_next(&pl->parser);
}

unsigned m30pl_count(const struct m30pl *pl)
{
    return pl ? m3u_count(&pl->parser) : 0;
}

void m30pl_close(struct m30pl *pl)
{
    if (pl && pl->open) {
        m30fs_close(&pl->file);
        pl->open = 0;
    }
}
