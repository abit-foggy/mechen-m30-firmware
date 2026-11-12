/* Host harness for the M3U.LIB adapter (hosted build).
 *
 * The adapter is freestanding; this supplies the two callbacks it needs. The
 * sector reader reads the real M3U.LIB copy, and the resolver opens the
 * matching playlist -- paired by the caller-supplied order, because what the
 * firmware's own resolver would do with the 16-byte location field is not
 * established. The test that drives this says so explicitly rather than
 * depending on the pairing silently.
 *
 * Usage: harness_db M3U.LIB PlaylistsDir MAP
 *   MAP is a newline-separated list of "recordindex:filename" pairs -- the
 *   pairing the resolver uses, supplied by the caller rather than inferred. The
 *   separator is a newline because playlist filenames contain commas and
 *   spaces, and a comma-separated list would split inside them.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "m3u.h"
#include "m3udb.h"

static FILE *libfp;
static FILE *plfp;
static const char *pldir;
/* the caller supplies the index-to-filename mapping, because the firmware-side
 * meaning of a record's location field is not established */
#define MAXMAP 64
static int map_idx[MAXMAP];
static const char *map_name[MAXMAP];   /* points into argv, not NUL-terminated */
static int nmap;

static unsigned char lbuf[1 << 20];
static unsigned llen, lpos;

static long rd_sector(void *cookie, unsigned sector, char *buf)
{
    long got;
    (void)cookie;
    if (fseek(libfp, (long)sector * M3UDB_SECTOR, SEEK_SET)) {
        return -1;
    }
    got = (long)fread(buf, 1, M3UDB_SECTOR, libfp);
    return got < 0 ? -1 : got;
}

static long rd_playlist(void *cookie, char *dst, unsigned long n)
{
    unsigned long avail;
    (void)cookie;
    avail = llen - lpos;
    if (avail == 0) {
        return 0;
    }
    if (n > avail) {
        n = avail;
    }
    memcpy(dst, lbuf + lpos, n);
    lpos += n;
    return (long)n;
}

/* binary fields hold NULs, so print them as hex rather than as C strings */
static const char *hexof(const unsigned char *p, unsigned n)
{
    static char out[256];
    unsigned k = 0, pos = 0;
    while (k < n && pos + 3 < sizeof out) {
        pos += (unsigned)snprintf(out + pos, sizeof out - pos, "%02x",
                                  p[k]);
        k++;
        if (k < n && pos + 1 < sizeof out) {
            out[pos++] = ' ';
        }
    }
    out[pos] = 0;
    return out;
}

/* the caller's string is argv, so its pointers are not NUL-terminated at the
 * separator; copy into a bounded buffer instead of trusting it */
static const char *lookup(unsigned index)
{
    static char name[128];
    const char *src;
    int k;
    unsigned n = 0;
    for (k = 0; k < nmap; k++) {
        if (map_idx[k] == (int)index) {
            src = map_name[k];
            while (src[n] && src[n] != '\n' && n + 1 < sizeof name) {
                name[n] = src[n];
                n++;
            }
            name[n] = 0;
            return name;
        }
    }
    return NULL;
}

static long op_open(void *cookie, unsigned index, const unsigned char *loc,
                    struct m3u_io *io, void **opened)
{
    char path[512];
    const char *name = lookup(index);
    (void)cookie;
    (void)loc;

    /* the location field is carried through untouched; the pairing between a
     * record and its file is supplied by the caller and stated in the test */
    if (!name) {
        return -1;
    }
    snprintf(path, sizeof path, "%s/%s", pldir, name);
    plfp = fopen(path, "rb");
    if (!plfp) {
        return -1;
    }
    llen = (unsigned)fread(lbuf, 1, sizeof lbuf, plfp);
    lpos = 0;
    io->read = rd_playlist;
    io->cookie = NULL;
    *opened = plfp;
    return 0;
}

static void op_close(void *cookie, void *opened)
{
    (void)cookie;
    if (opened) {
        fclose((FILE *)opened);
    }
}

int main(int argc, char **argv)
{
    struct m3udb db;
    struct m3udb_io io;
    struct m3udb_rec rec;
    struct m3u m;
    unsigned i, k;
    int rc;

    if (argc != 4) {
        return 2;
    }
    libfp = fopen(argv[1], "rb");
    if (!libfp) {
        return 2;
    }
    pldir = argv[2];
    /* argv[3] is "idx:filename,idx:filename,..." */
    {
        const char *p = argv[3];
        while (*p && nmap < MAXMAP) {
            map_idx[nmap] = atoi(p);
            while (*p && *p != ':') {
                p++;
            }
            if (*p == ':') {
                p++;
            }
            map_name[nmap] = p;
            while (*p && *p != '\n') {
                p++;
            }
            nmap++;
            if (*p == '\n') {
                p++;
            }
        }
    }

    io.sector = rd_sector;
    io.open = op_open;
    io.close = op_close;
    io.cookie = NULL;
    rc = m3udb_init(&db, &io);
    if (rc != M3U_OK) {
        printf("INIT_ERR %d\n", rc);
        return 1;
    }
    printf("RECORDS %u\n", m3udb_count(&db));
    for (i = 0; i < db.count; i++) {
        rc = m3udb_read(&db, i, &rec);
        if (rc != M3U_OK) {
            printf("READ_ERR %u %d\n", i, rc);
            return 1;
        }
        printf("NAME %u %s\n", i, hexof(rec.title, rec.title_len));
        printf("EXT  %u %.4s\n", i, (char *)rec.ext);
        printf("LOC  %u %s\n", i, hexof(rec.loc, M3UDB_LOC));

        { void *op; rc = m3udb_first(&db, i, &rec, "", &m, &op); plfp = (FILE *)op; }
        if (rc != M3U_OK && rc != M3U_END) {
            printf("OPEN_ERR %u %d\n", i, rc);
            return 1;
        }
        k = 0;
        /* m3udb_first already returned the first entry, so print it before
         * stepping, or the playlist loses its first track */
        if (rc == M3U_OK) {
            printf("T %u %u %s\n", i, k++, m.line);
        }
        while ((rc = m3udb_next(&m)) == M3U_OK) {
            printf("T %u %u %s\n", i, k++, m.line);
        }
        if (rc != M3U_END) {
            printf("PARSE_ERR %u %d\n", i, rc);
            return 1;
        }
        m3udb_close(&db, plfp);
    }
    fclose(libfp);
    return 0;
}
