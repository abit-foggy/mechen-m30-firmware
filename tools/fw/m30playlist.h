/* Device-side M3U playlist reader: m30fs + the existing parser, nothing else.
 *
 * This is the first firmware-side module that connects the stock filesystem to
 * the portable M3U reader. It exists so the player can walk a playlist's track
 * references without a second filesystem abstraction and without a second
 * parser: it opens a file through m30fs and feeds a byte stream to m3u.
 *
 * Bounded by design: one 512-byte read buffer at a time, no whole-playlist
 * residency, and the parser's own bounds do the rest.
 */
#ifndef M30PLAYLIST_H
#define M30PLAYLIST_H

#include "m30fs.h"
#include "m3u.h"

/* Status codes, combining the adapter's and the parser's. */
#define M30PL_OK            0
#define M30PL_ERR          (-1)
#define M30PL_ERR_TOOBIG   (-2)
#define M30PL_ERR_BADPATH  (-3)
#define M30PL_ERR_TRUNCATED (-4)
#define M30PL_ERR_STATE    (-5)

/* A playlist being read. Owns the adapter handle and the parser state; hand it
 * back to m30pl_close when done. */
struct m30pl {
    struct m30fs_file file;
    struct m3u        parser;
    int               open;
};

/* Open a playlist by path and prepare to enumerate its entries.
 *
 * `dir` is the playlist's own directory, used by the parser to prefix each
 * entry -- the playlists on the card reference their tracks as ../Music/...,
 * so entries are relative to the playlist, not to the root.
 *
 * Returns M30PL_OK, or a negative M30PL_ERR.
 * On failure the file is closed and `pl` is left safe to close again.
 */
int m30pl_open(struct m30pl *pl, u32 fs_stub, u32 fs_ctx, const char *path,
               const char *dir);

/* Next track reference. On M3U_OK, pl->parser.line holds a NUL-terminated
 * path relative to `dir`. Returns M3U_END when the playlist is exhausted. */
int m30pl_next(struct m30pl *pl);

/* Entries handed out so far. */
unsigned m30pl_count(const struct m30pl *pl);

/* Close. Safe to call twice. */
void m30pl_close(struct m30pl *pl);

#endif /* M30PLAYLIST_H */
