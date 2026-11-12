/* M3U.LIB record adapter. See m3udb.h for the contract. */
#include "m3udb.h"

int m3udb_init(struct m3udb *db, const struct m3udb_io *io)
{
    long got;

    if (!db || !io || !io->sector || !io->open) {
        return M3U_ERR_IO;
    }
    db->io = *io;
    db->seen = 0;

    /* the header is the first 512-byte sector: magic, count and the section
     * name, all inside the same sector the records start in */
    got = db->io.sector(db->io.cookie, 0, db->sector);
    if (got < 0) {
        return M3U_ERR_IO;
    }
    if ((unsigned long)got != M3UDB_SECTOR
        && (unsigned long)got < M3UDB_FIRST + M3UDB_RECORD) {
        return M3U_ERR_TOO_LONG;
    }
    if (db->sector[0] != 'M' || db->sector[1] != '3'
        || db->sector[2] != 'U' || db->sector[3] != 0) {
        return M3U_ERR_TOO_LONG;
    }
    /* count is the low u16 of +0x08; the high half is a fixed 1 */
    db->count = (unsigned char)db->sector[8]
                | ((unsigned char)db->sector[9] << 8);
    if (db->sector[10] != 1 || db->sector[11] != 0) {
        return M3U_ERR_TOO_LONG;
    }
    return M3U_OK;
}

unsigned m3udb_count(const struct m3udb *db)
{
    return db->count;
}

int m3udb_read(struct m3udb *db, unsigned index, struct m3udb_rec *rec)
{
    long got;
    unsigned sector, off, i;

    if (!db || !rec) {
        return M3U_ERR_IO;
    }
    if (index >= db->count) {
        return M3U_END;
    }
    /* record index i lives at byte 0x200 + i*256, which is sector (i/2) at
     * offset (i%2)*256 -- two records share a 512-byte sector */
    sector = (M3UDB_FIRST / M3UDB_SECTOR) + index / M3UDB_PER_SECTOR;
    off = (index % M3UDB_PER_SECTOR) * M3UDB_RECORD;

    got = db->io.sector(db->io.cookie, sector, db->sector);
    if (got < 0) {
        return M3U_ERR_IO;
    }
    if ((unsigned long)got != M3UDB_SECTOR) {
        return M3U_ERR_TOO_LONG;
    }

    for (i = 0; i < M3UDB_TITLE; i++) {
        rec->title[i] = (unsigned char)db->sector[off + i];
    }
    rec->flag = (unsigned char)db->sector[off + 0xa3];
    for (i = 0; i < M3UDB_EXT; i++) {
        rec->ext[i] = (unsigned char)db->sector[off + 0xa4 + i];
    }
    for (i = 0; i < M3UDB_LOC; i++) {
        rec->loc[i] = (unsigned char)db->sector[off + 0xa9 + i];
    }

    /* the title is BOM + UTF-16LE + a NUL pair; its length is where the
     * terminator starts, which is what a caller needs to render it */
    rec->title_len = 0;
    while (rec->title_len < M3UDB_TITLE) {
        if (rec->title[rec->title_len] == 0
            && rec->title_len + 1 < M3UDB_TITLE
            && rec->title[rec->title_len + 1] == 0) {
            break;
        }
        rec->title_len++;
    }
    return M3U_OK;
}

int m3udb_first(struct m3udb *db, unsigned rec_index,
               const struct m3udb_rec *rec,
               const char *dir, struct m3u *m, void **opened)
{
    int rc;

    if (!db || !rec || !m || !opened || !dir) {
        return M3U_ERR_IO;
    }
    *opened = NULL;
    if (db->io.open(db->io.cookie, rec_index, rec->loc, &m->io, opened) != 0
        || !*opened) {
        return M3U_ERR_IO;
    }
    /* The playlist's entries are relative to its own directory, so the caller
     * resolves the record's location to that directory and hands it in. This
     * module deliberately does not try to turn the 16-byte location field into
     * a path: how a firmware-side resolver reads it is not established, and
     * guessing would be inventing an ABI. */
    rc = m3u_init(m, &m->io, dir);
    if (rc != M3U_OK) {
        m3udb_close(db, *opened);
        *opened = NULL;
        return rc;
    }
    return m3u_next(m);
}

int m3udb_next(struct m3u *m)
{
    return m3u_next(m);
}

void m3udb_close(struct m3udb *db, void *opened)
{
    if (db && opened && db->io.close) {
        db->io.close(db->io.cookie, opened);
    }
}
