/* Bounded streaming M3U writer. See m3uw.h for the contract. */
#include "m3uw.h"

static int set_error(struct m3uw *w, int err)
{
    w->done = 1;
    w->status = err;
    return err;
}

int m3uw_init(struct m3uw *w, const struct m3uw_io *io,
              char (*paths)[M3UW_PATH_MAX], unsigned cap,
              enum m3uw_eol eol, int header)
{
    if (!w || !io || !io->write || !paths) {
        return M3UW_ERR_IO;
    }
    if (cap > M3UW_MAX_ENTRIES) {
        cap = M3UW_MAX_ENTRIES;
    }
    w->io = *io;
    w->paths = paths;
    w->cap = cap;
    w->n = 0;
    w->eol = eol;
    w->header = header ? 1 : 0;
    w->olen = 0;
    w->done = 0;
    w->status = M3UW_OK;
    return M3UW_OK;
}

unsigned m3uw_count(const struct m3uw *w)
{
    return w->n;
}

/* A path that will not come back out of the reader unchanged is refused
 * rather than written. The reader trims leading blanks before it tests for
 * '#', and it cannot report how many it trimmed, so a leading blank is not
 * recoverable either: the player would open a path that was never in the
 * file. Refusing it here keeps the round trip total. */
static int safe(const char *p, unsigned len)
{
    unsigned i;
    if (!len) {
        return 0;               /* an empty line is dropped by the reader */
    }
    if (p[0] == ' ' || p[0] == '\t') {
        return 0;               /* the reader trims it and cannot report it */
    }
    if (p[0] == '#') {
        return 0;               /* it would be read back as a comment */
    }
    if (p[0] == '/') {
        return 0;               /* absolute: the reader prefixes a directory */
    }
    for (i = 0; i < len; i++) {
        char c = p[i];
        if (c == '\0' || c == '\n' || c == '\r') {
            return 0;           /* would terminate the line early */
        }
    }
    return 1;
}

int m3uw_add(struct m3uw *w, const char *path)
{
    unsigned len;

    if (!w) {
        return M3UW_ERR_STATE;
    }
    if (w->done) {
        return w->status ? w->status : M3UW_ERR_STATE;
    }
    if (w->n >= w->cap) {
        return set_error(w, M3UW_ERR_FULL);
    }

    len = 0;
    while (path[len]) {
        len++;
    }
    if (len >= M3UW_PATH_MAX) {
        return set_error(w, M3UW_ERR_TOO_LONG);
    }
    if (!safe(path, len)) {
        return set_error(w, M3UW_ERR_UNSAFE);
    }

    {
        unsigned i;
        for (i = 0; i < len; i++) {
            w->paths[w->n][i] = path[i];
        }
        w->paths[w->n][len] = 0;
    }
    w->n++;
    return M3UW_OK;
}

/* Number of bytes one terminator occupies under the current policy. */
static unsigned eol_len(const struct m3uw *w)
{
    return w->eol == M3UW_EOL_CRLF ? 2u : 1u;
}

unsigned m3uw_size(const struct m3uw *w)
{
    unsigned total = 0;
    unsigned i, j;

    if (w->header) {
        total += 7u + eol_len(w);        /* "#EXTM3U" */
    }
    for (i = 0; i < w->n; i++) {
        j = 0;
        while (w->paths[i][j]) {
            j++;
        }
        total += j + eol_len(w);
    }
    return total;
}

/* --- emitting: accumulate into the fixed flush buffer, never more --- */

static int flush(struct m3uw *w)
{
    if (w->olen) {
        if (w->io.write(w->io.cookie, w->out, w->olen) != (long)w->olen) {
            return M3UW_ERR_IO;
        }
        w->olen = 0;
    }
    return M3UW_OK;
}

static int emit(struct m3uw *w, const char *s, unsigned n)
{
    while (n) {
        unsigned room = M3UW_OUT_MAX - w->olen;
        unsigned take = n < room ? n : room;
        unsigned i;
        for (i = 0; i < take; i++) {
            w->out[w->olen + i] = s[i];
        }
        w->olen += take;
        s += take;
        n -= take;
        if (w->olen == M3UW_OUT_MAX) {
            int rc = flush(w);
            if (rc < 0) {
                return rc;
            }
        }
    }
    return M3UW_OK;
}

static int emit_str(struct m3uw *w, const char *s)
{
    unsigned n = 0;
    while (s[n]) {
        n++;
    }
    return emit(w, s, n);
}

static int emit_eol(struct m3uw *w)
{
    static const char crlf[2] = { '\r', '\n' };
    static const char lf[1] = { '\n' };
    if (w->eol == M3UW_EOL_CRLF) {
        return emit(w, crlf, 2);
    }
    return emit(w, lf, 1);
}

int m3uw_write(struct m3uw *w)
{
    unsigned i;
    int rc;

    if (!w) {
        return M3UW_ERR_STATE;
    }
    if (w->done) {
        return w->status ? w->status : M3UW_ERR_STATE;
    }

    if (w->header) {
        rc = emit_str(w, "#EXTM3U");
        if (rc < 0) {
            return set_error(w, rc);
        }
        rc = emit_eol(w);
        if (rc < 0) {
            return set_error(w, rc);
        }
    }
    for (i = 0; i < w->n; i++) {
        unsigned j = 0;
        while (w->paths[i][j]) {
            w->out[w->olen] = w->paths[i][j];   /* fast path, usually full */
            w->olen++;
            j++;
            if (w->olen == M3UW_OUT_MAX) {
                rc = flush(w);
                if (rc < 0) {
                    return set_error(w, rc);
                }
            }
        }
        rc = emit_eol(w);
        if (rc < 0) {
            return set_error(w, rc);
        }
    }
    rc = flush(w);
    if (rc < 0) {
        return set_error(w, rc);
    }
    w->done = 1;
    w->status = M3UW_OK;
    return M3UW_OK;
}
