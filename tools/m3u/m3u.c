/* Bounded streaming M3U reader. See m3u.h for the contract. */
#include "m3u.h"

static int set_error(struct m3u *m, int err)
{
    m->done = 1;
    m->status = err;
    return err;
}

int m3u_init(struct m3u *m, const struct m3u_io *io, const char *dir)
{


    if (!m || !io || !io->read) {
        return M3U_ERR_IO;
    }
    m->io = *io;
    m->buf_len = 0;
    m->buf_pos = 0;
    m->at_eof = 0;
    m->entries = 0;
    m->done = 0;
    m->status = M3U_OK;
    m->bom_checked = 0;

    m->dir_len = 0;
#ifndef M3UPLAY_NO_DIR
    /* the play-on-click blob (freestanding, size-critical) never uses a dir
     * prefix and compiles with -DM3UPLAY_NO_DIR to drop this copy loop */
    if (dir) {
        while (dir[m->dir_len]) {
            if (m->dir_len >= M3U_DIR_MAX - 1) {
                /* leave room for the separator and the terminator */
                return M3U_ERR_TOO_LONG;
            }
            m->dir[m->dir_len] = dir[m->dir_len];
            m->dir_len++;
        }
    }
    /* an empty prefix needs no separator */
    if (m->dir_len && m->dir[m->dir_len - 1] != '/') {
        if (m->dir_len + 1 >= M3U_DIR_MAX) {
            return M3U_ERR_TOO_LONG;
        }
        m->dir[m->dir_len++] = '/';
    }
#endif
    m->dir[m->dir_len] = 0;
    (void)dir;
    return M3U_OK;
}

#ifndef M3UPLAY_NO_DIR
unsigned m3u_count(const struct m3u *m)
{
    return m->entries;
}
#endif

/* Pull more bytes in. Compacts the unconsumed tail to the front of the buffer.
 * Returns 0 on success (bytes available, or clean EOF), M3U_ERR_IO on failure. */
static int fill(struct m3u *m)
{
    long got;
    unsigned i;

    if (m->at_eof) {
        return 0;
    }
    for (i = m->buf_pos; i < m->buf_len; i++) {
        m->buf[i - m->buf_pos] = m->buf[i];
    }
    m->buf_len -= m->buf_pos;
    m->buf_pos = 0;

    got = m->io.read(m->io.cookie, m->buf + m->buf_len,
                     sizeof m->buf - m->buf_len);
    if (got < 0) {
        return M3U_ERR_IO;
    }
    if (got == 0) {
        m->at_eof = 1;
    } else {
        m->buf_len += (unsigned)got;
    }
    return 0;
}

/* Skip a UTF-8 BOM at the very start of the stream. A BOM left in place turns
 * the first line into a path that cannot be opened and hides '#EXTM3U' from the
 * comment test, so it has to go before the first line is read. Short inputs are
 * simply not a BOM. Returns 0, or M3U_ERR_IO if the stream fails. */
static int skip_bom(struct m3u *m)
{
    while (m->buf_len - m->buf_pos < 3 && !m->at_eof) {
        int rc = fill(m);
        if (rc < 0) {
            return rc;
        }
    }
    if (m->buf_len - m->buf_pos >= 3 &&
        (unsigned char)m->buf[m->buf_pos] == 0xEF &&
        (unsigned char)m->buf[m->buf_pos + 1] == 0xBB &&
        (unsigned char)m->buf[m->buf_pos + 2] == 0xBF) {
        m->buf_pos += 3;
    }
    return 0;
}

/* Read one line into m->line, NUL-terminated, terminators stripped. Returns
 * M3U_OK, M3U_END (clean, nothing left), or a negative status. */
static int read_line(struct m3u *m)
{
    m->line_len = 0;
    if (!m->bom_checked) {
        int rc = skip_bom(m);
        if (rc < 0) {
            return rc;
        }
        m->bom_checked = 1;
    }
    for (;;) {
        char c;
        if (m->buf_pos >= m->buf_len) {
            int rc = fill(m);
            if (rc < 0) {
                return rc;
            }
            if (m->buf_pos >= m->buf_len) {
                if (m->line_len) {
                    m->line[m->line_len] = 0;
                    return M3U_OK;   /* final line without a newline */
                }
                return M3U_END;
            }
        }
        c = m->buf[m->buf_pos++];
        if (c != '\n' && c != '\r') {
            if (m->line_len >= sizeof m->line - 1) {
                return M3U_ERR_TOO_LONG;
            }
            m->line[m->line_len++] = c;
            continue;
        }
        /* swallow a \r\n pair as one terminator */
        if (c == '\r' && m->buf_pos < m->buf_len && m->buf[m->buf_pos] == '\n') {
            m->buf_pos++;
        }
        m->line[m->line_len] = 0;
        return M3U_OK;
    }
}

int m3u_next(struct m3u *m)
{
    int rc;
    unsigned i, lead;

    if (!m) {
        return M3U_ERR_STATE;
    }
    if (m->done) {
        return m->status ? m->status : M3U_ERR_STATE;
    }

    for (;;) {
        rc = read_line(m);
        if (rc == M3U_END) {
            m->done = 1;
            return M3U_END;
        }
        if (rc < 0) {
            return set_error(m, rc);
        }

        /* trim leading blanks, then drop blank and comment lines silently */
        lead = 0;
        while (lead < m->line_len && (m->line[lead] == ' ' || m->line[lead] == '\t')) {
            lead++;
        }
        if (lead >= m->line_len || m->line[lead] == '#') {
            continue;
        }
        break;
    }

    if (m->entries >= M3U_MAX_ENTRIES) {
        return set_error(m, M3U_ERR_TRUNCATED);
    }

    /* assemble directory prefix + entry, shifting the line contents down */
    m->line_len -= lead;
    for (i = 0; i < m->line_len; i++) {
        m->line[i] = m->line[i + lead];
    }
    if (m->dir_len > sizeof m->line - 1 - m->line_len) {
        return set_error(m, M3U_ERR_TOO_LONG);
    }
    for (i = m->line_len + m->dir_len; i > m->dir_len; i--) {
        m->line[i - 1] = m->line[i - 1 - m->dir_len];
    }
    for (i = 0; i < m->dir_len; i++) {
        m->line[i] = m->dir[i];
    }
    m->line_len += m->dir_len;
    m->line[m->line_len] = 0;
    m->entries++;
    return M3U_OK;
}
