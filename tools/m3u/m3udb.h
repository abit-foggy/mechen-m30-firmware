/* M3U.LIB record adapter: an index becomes an ordered playlist.
 *
 * The firmware already indexes the card's playlists into M3U.LIB (see
 * tools/m3u/m3ulib.py and docs/m3u-visibility.md). What is missing is the
 * half that turns one of those records into something a list view can show and
 * a player can play. This module is that half, and it is deliberately the only
 * part of the chain that does not already exist in the firmware.
 *
 * It is UI-independent and filesystem-independent: it takes a sector-read
 * callback (the same shape the firmware's own record reader uses, a 512-byte
 * sector per unit) and an open-by-location callback, and hands the playlist's
 * bytes to m3u.c, the reader that already parses the user's files.
 *
 * What it does not do is invent a filesystem ABI. The 16-byte location field is
 * carried through untouched, because how a firmware-side resolver interprets it
 * is not established; the host test supplies a resolver of its own and says so.
 *
 * M3U.LIB layout, established from the card's own copy:
 *   +0x000  4   magic "M3U\0"
 *   +0x008  2   record count            (the high half is a fixed 1)
 *   +0x010  8   the one section name, "ALLFILE\0"
 *   +0x200  .   256-byte records, two per 512-byte sector
 *     +0x00  64  title, BOM + UTF-16LE + terminator
 *     +0xa3   1  tag-ok flag
 *     +0xa4   4  extension, "M3U\0"
 *     +0xa8   1  always 1
 *     +0xa9  16  file location
 */
#ifndef M3UDB_H
#define M3UDB_H

#include "m3u.h"

#define M3UDB_SECTOR 512
#define M3UDB_RECORD 256
#define M3UDB_FIRST 0x200       /* byte offset of record 0 */
#define M3UDB_PER_SECTOR 2      /* records per 512-byte sector */

/* Title field: 64 bytes is a BOM plus 30 UTF-16LE units plus the terminator, so
 * a longer name is truncated on the card. The value is kept raw on purpose --
 * the firmware's own name converter writes UTF-16LE, so decoding here would
 * only make the display layer's job harder. */
#define M3UDB_TITLE 64
#define M3UDB_LOC 16
#define M3UDB_EXT 4

struct m3udb_rec {
    unsigned char title[M3UDB_TITLE];
    unsigned title_len;
    unsigned char ext[M3UDB_EXT];
    unsigned char loc[M3UDB_LOC];
    unsigned char flag;
};

/* Sector reads and file opens, so neither the filesystem nor the card driver is
 * assumed. sector() must fill the whole 512 bytes and return 0, or negative. */
struct m3udb_io {
    long (*sector)(void *cookie, unsigned sector, char *buf);
    /* open() turns a record's location into a readable playlist. `index` is the
     * record's position, which a caller iterating the database already knows
     * and which is enough to resolve a location without interpreting it here.
     * It fills io, sets opened to a non-NULL cookie, and returns 0. */
    long (*open)(void *cookie, unsigned index, const unsigned char *loc,
                 struct m3u_io *io, void **opened);
    void (*close)(void *cookie, void *opened);
    void *cookie;
};

struct m3udb {
    struct m3udb_io io;
    char sector[M3UDB_SECTOR];
    unsigned count;      /* records in this database */
    unsigned seen;
};

/* Initialise from the header sector. Returns M3U_OK, or M3U_ERR_TOO_LONG if the
 * envelope is not M3U.LIB's. On success db->count is the record count. */
int m3udb_init(struct m3udb *db, const struct m3udb_io *io);

/* Records this database holds. */
unsigned m3udb_count(const struct m3udb *db);

/* Read one record by index into *rec. */
int m3udb_read(struct m3udb *db, unsigned index, struct m3udb_rec *rec);

/* Open the playlist a record points at and return its first entry. `dir` is
 * the directory the playlist itself lives in, which the caller resolves from
 * the record's location; the entries come back already relative to it. On
 * M3U_OK m->line/m->line_len hold the first path, on M3U_END the playlist is
 * empty but well-formed. */
int m3udb_first(struct m3udb *db, unsigned rec_index,
               const struct m3udb_rec *rec,
               const char *dir, struct m3u *m, void **opened);

/* Advance an opened playlist. */
int m3udb_next(struct m3u *m);

/* Close what m3udb_first opened. */
void m3udb_close(struct m3udb *db, void *opened);

#endif /* M3UDB_H */
