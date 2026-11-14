/* Bounded streaming M3U reader for the M30 firmware.
 *
 * UI-independent on purpose: this module knows about bytes, lines and paths and
 * nothing about list views or playback, so it can be compiled freestanding for
 * the player and unit-tested on a host build with the same source.
 *
 * Design notes that the tests pin:
 *  - input is consumed a chunk at a time; no whole playlist is ever resident;
 *  - LF and CRLF line endings, and a final line with no terminator;
 *  - a leading UTF-8 BOM is skipped, so a playlist written by a Windows editor
 *    still has its '#EXTM3U' line recognised as a comment and its first path
 *    unpoisoned;
 *  - '#' begins a comment (covers EXTINF and EXTM3U) and is skipped;
 *  - blank lines are skipped, not returned;
 *  - a path is stored relative-resolved: the caller passes the playlist's own
 *    directory and it is prefixed here, so the caller never has to;
 *  - every buffer is fixed size and overflow is a defined, reported failure,
 *    never a silent truncate;
 *  - order is preserved exactly.
 */
#ifndef M3U_H
#define M3U_H

#include <stddef.h>

/* Longest single line the parser will hold, including the terminator it
 * replaces. Chosen for the M30's SRAM: the firmware's own file paths are short,
 * and anything longer is reported as too-long rather than truncated. */
#define M3U_PATH_MAX 128
/* Directory prefix length, including the trailing '/'. The player's paths are
 * short but nested; a playlist nested more deeply than this fails closed. */
#define M3U_DIR_MAX   64
/* Total playlist length in entries. Matches the stock playlist limit; a
 * playlist longer than this stops parsing with a truncation status rather than
 * growing without bound. */
#define M3U_MAX_ENTRIES 4000

/* Status codes. Callers must check status, not just the path buffer. */
enum m3u_status {
    M3U_OK = 0,          /* entry filled in */
    M3U_END = 1,         /* no more entries, playlist exhausted */
    M3U_SKIPPED = 2,     /* line consumed but nothing to report (blank/comment) */
    M3U_ERR_IO = -1,     /* read() failed */
    M3U_ERR_TOO_LONG = -2,   /* path or directory did not fit */
    M3U_ERR_TRUNCATED = -3,  /* more than M3U_MAX_ENTRIES entries */
    M3U_ERR_STATE = -4       /* used after an error */
};

/* Fill callbacks so the parser is independent of any filesystem. `cookie` is
 * passed through untouched. read() must return bytes read, 0 on EOF, negative
 * on error. */
struct m3u_io {
    long (*read)(void *cookie, char *buf, unsigned long n);
    void *cookie;
};

struct m3u {
    struct m3u_io io;
    char dir[M3U_DIR_MAX];   /* directory prefix, already '/' terminated */
    unsigned dir_len;
    char line[M3U_PATH_MAX + M3U_DIR_MAX];  /* assembled path, for the caller */
    unsigned line_len;
    char buf[M3U_PATH_MAX];  /* read-ahead buffer */
    unsigned buf_len;        /* bytes currently in buf */
    unsigned buf_pos;        /* consumed up to here */
    int at_eof;              /* read() has returned 0 */
    unsigned entries;        /* entries handed out so far */
    int done;                /* error or END already reported */
    int status;              /* last error, for M3U_ERR_STATE */
    int bom_checked;         /* the leading UTF-8 BOM was looked for already */
};

/* Initialise. `dir` must not be NULL; "" means "no prefix". The trailing '/'
 * is added if missing. Returns M3U_OK or M3U_ERR_TOO_LONG. */
int m3u_init(struct m3u *m, const struct m3u_io *io, const char *dir);

/* Next entry. On M3U_OK, m->line/m->line_len hold a NUL-terminated path.
 * Comments and blank lines are consumed internally, so a successful call never
 * returns one; the caller just loops. */
int m3u_next(struct m3u *m);

/* Entries returned so far. */
unsigned m3u_count(const struct m3u *m);

#endif /* M3U_H */
