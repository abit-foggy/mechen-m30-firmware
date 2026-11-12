/* Host test harness for the MIPS16e M3U parser and writer (hosted build).
 *
 * Both modules are freestanding and only need callbacks; this harness supplies
 * file-backed ones, so the *same* source is exercised on the host and can
 * later be compiled as the player's MIPS16e blob unchanged.
 *
 * Usage:
 *   harness FIXTURE DIR                        read: parse FIXTURE, prefix DIR
 *   harness --write PATHS OUT EOL HDR          write: one path per line in PATHS
 *   harness --add-one PATHFILE OUT EOL HDR     write: PATHFILE is one whole path
 *   harness --roundtrip PATHS OUT EOL HDR DIR  write OUT, parse it back with
 *                                              DIR prefixed, compare with the input
 * EOL is "lf" or "crlf"; HDR is 0 or 1. PATHFILE lets the tests hand the
 * writer a path no line-based format could carry, such as an empty one.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "m3u.h"
#include "m3uw.h"

/* one slot past the writer's own cap, so a test can prove the cap is the
 * writer's decision and not the harness's */
#define HARNESS_SLOTS (M3UW_MAX_ENTRIES + 8)

static unsigned char buf[1 << 20];
static unsigned len, pos;
static FILE *out;

static long io_read(void *cookie, char *dst, unsigned long n)
{
    unsigned long avail;
    (void)cookie;
    avail = len - pos;
    if (avail == 0) {
        return 0;
    }
    if (n > avail) {
        n = avail;
    }
    memcpy(dst, buf + pos, n);
    pos += n;
    return (long)n;
}

static long io_write(void *cookie, const char *src, unsigned long n)
{
    (void)cookie;
    if (fwrite(src, 1, n, out) != n) {
        return -1;
    }
    return (long)n;
}

static void read_fixture(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        exit(2);
    }
    len = (unsigned)fread(buf, 1, sizeof buf, f);
    fclose(f);
    pos = 0;
}

/* One path per line. A path cannot contain '\n' (the writer refuses it), so
 * this is lossless for anything the writer will accept. Reads past the
 * writer's cap so the overflow is the writer's to refuse. */
static unsigned read_paths(char (*paths)[M3UW_PATH_MAX], const char *path)
{
    FILE *f = fopen(path, "rb");
    char line[M3UW_PATH_MAX + 1];
    unsigned n = 0;
    if (!f) {
        exit(2);
    }
    while (n < HARNESS_SLOTS && fgets(line, sizeof line, f)) {
        size_t l = strlen(line);
        while (l && (line[l - 1] == '\n' || line[l - 1] == '\r')) {
            line[--l] = 0;
        }
        if (!l) {
            continue;
        }
        memcpy(paths[n], line, l + 1);
        n++;
    }
    fclose(f);
    return n;
}

/* The whole file is one path, minus at most one trailing newline. */
static unsigned read_one(char (*paths)[M3UW_PATH_MAX], const char *path)
{
    FILE *f = fopen(path, "rb");
    unsigned n;
    if (!f) {
        exit(2);
    }
    n = (unsigned)fread(paths[0], 1, M3UW_PATH_MAX, f);
    fclose(f);
    if (n && paths[0][n - 1] == '\n') {
        n--;
        if (n && paths[0][n - 1] == '\r') {
            n--;
        }
    }
    paths[0][n] = 0;
    return 1;
}

static enum m3uw_eol parse_eol(const char *s)
{
    return (s[0] == 'c' || s[0] == 'C') ? M3UW_EOL_CRLF : M3UW_EOL_LF;
}

/* Feed every path to the writer and emit. Reports the first refusal as
 * "ADD_ERR n" and an emission failure as "ERR n". */
static int emit_playlist(char (*paths)[M3UW_PATH_MAX], unsigned n,
                         const char *out_path, enum m3uw_eol eol, int header)
{
    struct m3uw w;
    struct m3uw_io io;
    unsigned i;
    int rc;

    io.write = io_write;
    io.cookie = NULL;
    out = fopen(out_path, "wb");
    if (!out) {
        return 2;
    }
    rc = m3uw_init(&w, &io, paths, n, eol, header);
    if (rc != M3UW_OK) {
        fclose(out);
        printf("INIT_ERR %d\n", rc);
        return 1;
    }
    for (i = 0; i < n; i++) {
        rc = m3uw_add(&w, paths[i]);
        if (rc != M3UW_OK) {
            fclose(out);
            printf("ADD_ERR %d\n", rc);
            return 1;
        }
    }
    rc = m3uw_write(&w);
    fclose(out);
    if (rc != M3UW_OK) {
        printf("ERR %d\n", rc);
        return 1;
    }
    printf("WROTE %u %u\n", m3uw_count(&w), m3uw_size(&w));
    return 0;
}

static int parse_and_report(const char *fixture, const char *dir)
{
    struct m3u_io io;
    struct m3u m;
    int rc;

    read_fixture(fixture);
    io.read = io_read;
    io.cookie = NULL;
    if (m3u_init(&m, &io, dir) != M3U_OK) {
        printf("INIT_ERR\n");
        return 1;
    }
    while ((rc = m3u_next(&m)) == M3U_OK) {
        printf("E %s\n", m.line);
    }
    if (rc == M3U_END) {
        printf("END %u\n", m3u_count(&m));
        return 0;
    }
    printf("ERR %d\n", rc);
    return 1;
}

/* Write, then read the result back exactly as the player would, with the
 * playlist's own directory prefixed, and compare each entry with its input.
 * The invariant under test: anything the writer accepts is returned by the
 * reader unchanged, in order. */
static int roundtrip(char (*paths)[M3UW_PATH_MAX], unsigned n,
                     const char *out_path, enum m3uw_eol eol, int header,
                     const char *dir)
{
    static char want[M3UW_PATH_MAX + M3U_DIR_MAX];
    struct m3u_io io;
    struct m3u m;
    unsigned i, seen = 0, bad = 0;
    int rc;

    rc = emit_playlist(paths, n, out_path, eol, header);
    if (rc) {
        return rc;
    }

    read_fixture(out_path);
    io.read = io_read;
    io.cookie = NULL;
    if (m3u_init(&m, &io, dir) != M3U_OK) {
        printf("READ_INIT_ERR\n");
        return 1;
    }
    while ((rc = m3u_next(&m)) == M3U_OK) {
        if (seen >= n) {
            printf("EXTRA [%u] %.*s\n", seen, (int)m.line_len, m.line);
            bad++;
            continue;
        }
        snprintf(want, sizeof want, "%s%s%s", dir,
                 (dir[0] && dir[strlen(dir) - 1] == '/') ? "" : "/",
                 paths[seen]);
        if (m.line_len != strlen(want) || memcmp(m.line, want, m.line_len)) {
            printf("MISMATCH [%u] got %.*s want %s\n", seen,
                   (int)m.line_len, m.line, want);
            bad++;
        }
        seen++;
    }
    if (rc != M3U_END) {
        printf("READ_ERR %d\n", rc);
        return 1;
    }
    if (seen != n) {
        printf("COUNT got %u want %u\n", seen, n);
        bad++;
    }
    printf("%s %u\n", bad ? "RTBAD" : "RTOK", n);
    return bad ? 1 : 0;
}

int main(int argc, char **argv)
{
    static char paths[HARNESS_SLOTS][M3UW_PATH_MAX];
    unsigned n;

    if (argc == 3) {
        return parse_and_report(argv[1], argv[2]);
    }
    if (argc == 7 && !strcmp(argv[1], "--roundtrip")) {
        n = read_paths(paths, argv[2]);
        return roundtrip(paths, n, argv[3], parse_eol(argv[4]), atoi(argv[5]),
                         argv[6]);
    }
    if (argc == 6 && !strcmp(argv[1], "--write")) {
        n = read_paths(paths, argv[2]);
        return emit_playlist(paths, n, argv[3], parse_eol(argv[4]),
                             atoi(argv[5]));
    }
    if (argc == 6 && !strcmp(argv[1], "--add-one")) {
        n = read_one(paths, argv[2]);
        return emit_playlist(paths, n, argv[3], parse_eol(argv[4]),
                             atoi(argv[5]));
    }
    return 2;
}
