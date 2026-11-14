/* M3U virtual folder for the stock file browser. See m30virtual.h.
 *
 * One folder is ever open, so the state is one static object; the table is the
 * whole design. virtual_open is the only writer: it reads the playlist once
 * through m30playlist (which is m30fs + the parser) and closes the file
 * immediately afterwards, because every row is resident after that and the
 * handle is a scarce resource the kernel will not hand back twice.
 */
#include "m30virtual.h"
#include "m30playlist.h"

static struct {
    struct m30pl pl;                                 /* the playlist while open */
    char path[M30VIRTUAL_REF_MAX];                   /* as the caller named it */
    char dir[M3U_DIR_MAX];                           /* its own directory */
    unsigned dir_len;                                /* 0 when at the root */
    int open;
    unsigned count;
    unsigned truncated;
    int error;
    char ref[M30VIRTUAL_MAX_ENTRIES][M30VIRTUAL_REF_MAX];
} v;

static unsigned vlen(const char *s)
{
    unsigned n = 0;
    while (s[n]) {
        n++;
    }
    return n;
}

static int fold(int c)
{
    return (c >= 'A' && c <= 'Z') ? c + ('a' - 'A') : c;
}

/* The playlist's own directory: everything up to the last '/'. A playlist at
 * the root has no prefix, and the parser is told so. */
static void split_dir(const char *path, char *dir, unsigned *dir_len,
                      unsigned cap)
{
    unsigned n = vlen(path);
    unsigned i;

    while (n && path[n - 1] != '/') {
        n--;
    }
    if (n >= cap) {
        n = cap - 1;            /* cannot happen for a path the fs can open */
    }
    for (i = 0; i < n; i++) {
        dir[i] = path[i];
    }
    dir[n] = 0;
    *dir_len = n;
}

/* The file-name part of a reference, for display: whatever follows the last
 * '/'. Byte-based, so UTF-8 names survive intact. */
static const char *base_name(const char *ref)
{
    const char *p = ref;
    const char *last = ref;

    while (*p) {
        if (*p == '/') {
            last = p + 1;
        }
        p++;
    }
    return last;
}

/* Trailing blanks and slashes are editor debris, not part of a path. */
static unsigned trim_tail(const char *s, unsigned len)
{
    while (len && (s[len - 1] == ' ' || s[len - 1] == '\t' ||
                   s[len - 1] == '/')) {
        len--;
    }
    return len;
}

int virtual_open(u32 fs_stub, u32 fs_ctx, const char *path)
{
    unsigned i, plen;
    int rc;

    if (!path || !path[0]) {
        return VIRTUAL_ERR;
    }
    virtual_close();                    /* one folder at a time */

    plen = vlen(path);
    if (plen >= sizeof v.path) {
        return VIRTUAL_ERR;
    }
    split_dir(path, v.dir, &v.dir_len, sizeof v.dir);
    for (i = 0; i < plen; i++) {
        v.path[i] = path[i];
    }
    v.path[plen] = 0;

    if (m30pl_open(&v.pl, fs_stub, fs_ctx, path, v.dir) != M30PL_OK) {
        v.path[0] = 0;
        return VIRTUAL_ERR_OPEN;
    }

    v.count = 0;
    v.truncated = 0;
    v.error = 0;
    for (;;) {
        const char *rel, *src;
        unsigned len;

        rc = m30pl_next(&v.pl);
        if (rc == M3U_END) {
            break;
        }
        if (rc != M3U_OK) {
            v.error = rc;              /* keep what was read, report the rest */
            break;
        }
        /* The parser prefixes every entry with the playlist's directory, which
         * already ends in '/', so the relative part starts at dir_len. An entry
         * naming the drive root is absolute and is used as it stands. */
        rel = v.pl.parser.line + v.dir_len;
        src = (rel[0] == ':') ? rel : v.pl.parser.line;
        len = trim_tail(src, vlen(src));
        if (!len || len >= M30VIRTUAL_REF_MAX) {
            continue;                  /* unusable reference: not a row */
        }
        if (v.count >= M30VIRTUAL_MAX_ENTRIES) {
            v.truncated = 1;
            break;
        }
        for (i = 0; i < len; i++) {
            v.ref[v.count][i] = src[i];
        }
        v.ref[v.count][len] = 0;
        v.count++;
    }

    /* Every row is resident, so the file is not needed any more. Closing here
     * hands the kernel handle back while the folder is still listable. */
    m30pl_close(&v.pl);
    v.open = 1;
    return VIRTUAL_OK;
}

unsigned virtual_count(void)
{
    return v.open ? v.count : 0;
}

int virtual_entry(int index, struct virtual_entry *out)
{
    const char *ref;

    if (!v.open || !out || index < 0 || (unsigned)index >= v.count) {
        return VIRTUAL_ERR_STATE;
    }
    ref = v.ref[index];
    out->ref = ref;
    out->name = base_name(ref);
    return VIRTUAL_OK;
}

unsigned virtual_truncated(void)
{
    return v.open ? v.truncated : 0;
}

int virtual_error(void)
{
    return v.open ? v.error : 0;
}

const char *virtual_path(void)
{
    return v.open ? v.path : 0;
}

int virtual_is_playlist(const char *name)
{
    unsigned n;

    if (!name) {
        return 0;
    }
    n = vlen(name);
    if (n >= 5) {
        const char *e = name + n - 5;
        if (e[0] == '.' && fold(e[1]) == 'm' && fold(e[2]) == '3' &&
            fold(e[3]) == 'u' && fold(e[4]) == '8') {
            return 1;
        }
    }
    if (n >= 4) {
        const char *e = name + n - 4;
        if (e[0] == '.' && fold(e[1]) == 'm' && fold(e[2]) == '3' &&
            fold(e[3]) == 'u') {
            return 1;
        }
    }
    return 0;
}

virtual_ext_class_t virtual_ext_class(const unsigned char *ext4)
{
    unsigned e[4], i;

    if (!ext4) {
        return VIRTUAL_EXT_OTHER;
    }
    /* fold case and ignore trailing spaces: short names pad the field */
    for (i = 0; i < 4; i++) {
        e[i] = fold(ext4[i]);
        if (e[i] == ' ') {
            e[i] = 0;
        }
    }
    if (e[0] == 'm' && e[1] == '3' && e[2] == 'u' && e[3] == 0) {
        return VIRTUAL_EXT_M3U;
    }
    if (e[0] == 'm' && e[1] == '3' && e[2] == 'u' && e[3] == '8') {
        return VIRTUAL_EXT_M3U8;
    }
    return VIRTUAL_EXT_OTHER;
}

void virtual_close(void)
{
    m30pl_close(&v.pl);        /* no-op when the playlist was already closed */
    v.open = 0;
    v.count = 0;
    v.truncated = 0;
    v.error = 0;
    v.path[0] = 0;
}