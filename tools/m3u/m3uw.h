/* Bounded streaming M3U writer: the exact inverse of m3u.h's reader.
 *
 * The stock firmware can already *read* playlists (playlist.ap holds the
 * parser, the M3U.LIB library type, and the M30-FW-007 line-ending fix) but
 * nothing produces them, so a playlist cannot be created for the player to
 * open. This module writes one from a plain array of paths, and is the
 * reader's mirror image by construction so a round trip is lossless.
 *
 * UI- and filesystem-independent: it only needs a write() callback, so it
 * compiles freestanding for the player and is unit-tested from a host build
 * of the same source.
 *
 * Design notes that the tests pin:
 *  - output is a stream: nothing larger than the fixed flush buffer is ever
 *    resident, and the entry array is the caller's, not ours;
 *  - every path is validated on the way in, so a file that cannot be read
 *    back unambiguously is refused, not written broken;
 *  - the line ending and the #EXTM3U header are policy, chosen by the caller,
 *    because the stock reader accepts both and hosts differ;
 *  - output is deterministic: no timestamps, no locale, so a byte compare is
 *    a valid test;
 *  - m3uw_size() predicts the exact byte count before anything is written.
 */
#ifndef M3UW_H
#define M3UW_H

#include <stddef.h>

/* Per-entry byte budget, including the terminator the writer appends. Must be
 * at least M3U_PATH_MAX - 1 for a round trip to be lossless: the reader holds
 * M3U_PATH_MAX - 1 bytes of path. */
#define M3UW_PATH_MAX 128
/* Entries a single writer will accept. Must not exceed M3U_MAX_ENTRIES, or it
 * would produce a playlist the reader reports as truncated. */
#define M3UW_MAX_ENTRIES 4000
/* Flush buffer size. Independent of both limits above. */
#define M3UW_OUT_MAX 256

/* Line-ending policy. CRLF is what the M3U spec says; LF is what the stock
 * firmware's own writer produced before M30-FW-007, and the fix in
 * docs/firmware-m3u-fw007.md is what lets it accept either. */
enum m3uw_eol {
    M3UW_EOL_LF = 0,
    M3UW_EOL_CRLF = 1
};

/* Fill callback so the writer is independent of any filesystem. write() must
 * take the whole buffer and return n, or return negative on error. */
struct m3uw_io {
    long (*write)(void *cookie, const char *buf, unsigned long n);
    void *cookie;
};

/* Status codes. Every rejection happens before a byte is emitted. */
enum m3uw_status {
    M3UW_OK = 0,
    M3UW_ERR_IO = -1,       /* write() failed or short */
    M3UW_ERR_TOO_LONG = -2, /* path or playlist does not fit */
    M3UW_ERR_FULL = -3,     /* more than cap, or more than M3UW_MAX_ENTRIES */
    M3UW_ERR_UNSAFE = -4,   /* path contains a byte that breaks the format */
    M3UW_ERR_STATE = -5     /* used after an error */
};

struct m3uw {
    struct m3uw_io io;
    char (*paths)[M3UW_PATH_MAX];  /* caller-owned storage for the entries */
    unsigned cap;
    unsigned n;
    enum m3uw_eol eol;
    int header;                    /* emit "#EXTM3U" before the first entry */
    char out[M3UW_OUT_MAX];         /* flush buffer; never larger than this */
    unsigned olen;
    int done;                       /* an error was already reported */
    int status;                     /* sticky copy of it */
};

/* Initialise. `io` and `paths` must be non-NULL; `cap` is the entry count
 * `paths` can hold and is clamped to M3UW_MAX_ENTRIES. Paths are relative to
 * the playlist's own directory, matching what the reader prefixes onto every
 * entry. Returns M3UW_OK. */
int m3uw_init(struct m3uw *w, const struct m3uw_io *io,
              char (*paths)[M3UW_PATH_MAX], unsigned cap,
              enum m3uw_eol eol, int header);

/* Append one path. Rejected before it is stored if it would not survive a
 * round trip through the reader: a leading blank (the reader trims it and
 * cannot report how many), a leading '#' (read back as a comment), a leading
 * '/' (the reader prefixes the playlist's own directory), an embedded
 * terminator, or a path of M3UW_PATH_MAX bytes or more. Returns M3UW_OK or a
 * negative status. */
int m3uw_add(struct m3uw *w, const char *path);

/* Entries accepted so far. */
unsigned m3uw_count(const struct m3uw *w);

/* Exact byte count this writer will emit with its current policy. Lets a
 * caller preallocate a file, and lets a test assert the layout without
 * writing anything. */
unsigned m3uw_size(const struct m3uw *w);

/* Emit the playlist. Any earlier rejection is reported again rather than
 * being silently dropped. Returns M3UW_OK or a negative status. */
int m3uw_write(struct m3uw *w);

#endif /* M3UW_H */
