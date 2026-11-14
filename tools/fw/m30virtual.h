/* M3U/M3U8 virtual folder for the stock file browser.
 *
 * The browser lists directories and audio files; this module makes a playlist
 * behave like one more directory: opening "Playlists/idk.m3u" yields a list of
 * rows -- one per playlist entry, in playlist order -- whose resolved
 * references can be handed to the stock playback path exactly as if the user
 * had selected the file in a real folder.
 *
 * Nothing here is written to the SD card: there are no physical folders, no
 * extraction, and no rename. The playlist file is read once at open time and
 * the rows live in RAM for as long as the folder is open.
 *
 * Memory is bounded by construction: one fixed-size table, no allocation, no
 * growth. A playlist with more entries than the table holds is truncated with
 * a reported status instead. Entries longer than the filesystem adapter can
 * open are dropped rather than truncated silently -- a row that cannot be
 * opened is worse than a missing row, because it looks usable.
 *
 * The engine is deliberately UI-independent: it knows nothing about list views,
 * row caches, or the stock browser's state block. That is Phase B/D work; this
 * module only turns a playlist into rows and answers questions about them.
 */
#ifndef M30VIRTUAL_H
#define M30VIRTUAL_H

#include "m30fs.h"      /* u32 and the adapter's own limits */
#include "m3u.h"

/* Row-table limits. Every number here is a RAM cost, so they are deliberate:
 *
 *   M30VIRTUAL_MAX_ENTRIES -- rows held at once. The stock playlist system's
 *       own cap is 4000, but it stores an integer index per track, not a path;
 *       a path costs ~100 bytes, and 4000 of those would be 400 KB. 256 rows
 *       is 24 KB, which is a size the browser's own data can plausibly share.
 *       A longer playlist still opens: it is cut at the cap and the caller is
 *       told so.
 *   M30VIRTUAL_REF_MAX -- equals M30FS_PATH_MAX on purpose. A reference longer
 *       than that cannot be opened through the adapter, so keeping it buys
 *       nothing; the row is dropped instead.
 */
#define M30VIRTUAL_MAX_ENTRIES 256
#define M30VIRTUAL_REF_MAX     M30FS_PATH_MAX

/* Status codes. */
#define VIRTUAL_OK          0
#define VIRTUAL_ERR        (-1)   /* bad argument, or used when not open */
#define VIRTUAL_ERR_OPEN   (-2)   /* the playlist could not be opened */
#define VIRTUAL_ERR_STATE  (-3)   /* index out of range, or used after close */

/* One row of the virtual folder. Both pointers point into the engine's table
 * and stay valid until virtual_close; nothing needs to be copied out. */
struct virtual_entry {
    const char *ref;     /* resolved reference, NUL-terminated */
    const char *name;    /* display name: the reference's file-name part */
};

/* Open `playlist_path` as a virtual folder and enumerate it.
 *
 * `fs_stub` and `fs_ctx` are the module's own filesystem stub and context,
 * exactly as for m30pl_open: the stub address is per-module and cannot be
 * baked in, so the caller passes what it found.
 *
 * Returns VIRTUAL_OK (including for an empty playlist -- an empty folder is a
 * legitimate folder), or a negative VIRTUAL_ERR. */
int virtual_open(u32 fs_stub, u32 fs_ctx, const char *playlist_path);

/* Rows currently held. */
unsigned virtual_count(void);

/* Row `index`. On VIRTUAL_OK, *out points into the engine's table. */
int virtual_entry(int index, struct virtual_entry *out);

/* Non-zero when the playlist held more rows than the table could take. */
unsigned virtual_truncated(void);

/* The parser's last hard status, or 0 when the whole playlist was read. A
 * short read leaves the rows gathered so far in place rather than emptying the
 * folder, so the caller can warn without losing the list. */
int virtual_error(void);

/* The playlist that is open, or NULL. Stored verbatim, not resolved. */
const char *virtual_path(void);

/* True when `name` ends in ".m3u" or ".m3u8", case-insensitively. The full
 * five-byte suffix is tested first, so ".m3u8" never matches as ".m3u". */
int virtual_is_playlist(const char *name);

/* Close. The table is dropped, so entry pointers must not be used afterwards.
 * Safe to call when nothing is open. */
void virtual_close(void);

#endif /* M30VIRTUAL_H */