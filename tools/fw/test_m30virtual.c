/* Host self-test for the M3U virtual-folder engine (mocked kernel).
 *
 * Pulls in m30virtual.c, m30playlist.c and m30fs.c, so the chain under test is
 * the source the player will run; the parser (m3u.c) is linked alongside. The
 * kernel syscall is the same fake test_m30playlist.c uses: any host file is
 * served, a missing file opens as failure.
 *
 * The checks run in-process (so they can compare bytes and orderings directly)
 * and write their own fixtures into the directory given on the command line:
 *   test_m30virtual WORKDIR
 * Exit status is non-zero on any failure; every check prints PASS/FAIL.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/stat.h>

#include "m30virtual.h"

static FILE *backing;

static long mock_fs(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    switch (op) {
    case M30FS_OP_CHDIR:
        return 0;
    case M30FS_OP_OPEN: {
        const unsigned char *nm = (const unsigned char *)(uintptr_t)a1;
        char name[600];
        u32 qi = 0;
        if (!nm || nm[0] != 0xFF || nm[1] != 0xFE || a2 != 0 || a3 != 0) {
            return 0;
        }
        nm += 2;
        while (nm[qi * 2] || nm[qi * 2 + 1]) {
            name[qi] = (char)nm[qi * 2];
            qi++;
            if (qi >= sizeof name - 1) { return 0; }
        }
        name[qi] = 0;
        if (backing) { fclose(backing); }
        backing = fopen(name, "rb");
        return backing ? 0x1234u : 0;
    }
    case M30FS_OP_SIZE: {
        long here, sz;
        u32 *out = (u32 *)(uintptr_t)a1;
        if (!backing || !out) { return -1; }
        here = ftell(backing);
        fseek(backing, 0, SEEK_END);
        sz = ftell(backing);
        fseek(backing, here, SEEK_SET);
        *out = (u32)sz;
        return 0;
    }
    case M30FS_OP_READ:
        if (!backing) { return -1; }
        return (long)fread((void *)(uintptr_t)a1, 1, a2, backing);
    case M30FS_OP_CLOSE:
        return 0;
    default:
        return -1;
    }
}

static int fails, total;

static void check(int ok, const char *what)
{
    total++;
    if (!ok) { fails++; }
    printf("%s  %s\n", ok ? "PASS" : "FAIL", what);
}

/* printf-flavoured variant, so the failure text can carry the actual value */
#include <stdarg.h>
static void checkf(int ok, const char *fmt, ...)
{
    char buf[300];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    check(ok, buf);
}

static void write_fix(const char *path, const void *data, unsigned len)
{
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(2); }
    fwrite(data, 1, len, f);
    fclose(f);
}

#define MOCK ((u32)(uintptr_t)mock_fs)

/* the chain under test: engine -> playlist reader -> fs adapter, the source
 * the player will run (the parser is linked alongside by the build) */
#include "m30fs.c"
#include "m30playlist.c"
#include "m30virtual.c"

static void test_extensions(void)
{
    /* the rule is "the name ends with the suffix": anything else about the
     * stem (spaces, case, dots) is the file's own business */
    check(virtual_is_playlist("idk.m3u"), ".m3u accepted");
    check(virtual_is_playlist("idk.M3U"), ".M3U accepted (case-insensitive)");
    check(virtual_is_playlist("idk.M3u8"), ".M3u8 accepted (mixed case)");
    check(virtual_is_playlist("idk 2.m3u8"), ".m3u8 accepted with a space in the stem");
    check(virtual_is_playlist("js minecraft.m3u"), "a stem with spaces is fine");
    check(virtual_is_playlist(".m3u"), "a bare suffix name still matches (suffix rule)");
    check(!virtual_is_playlist("x.m3u8x"), "a suffix mid-name does not match");
    check(!virtual_is_playlist("M3U"), "a name without the dot is not a playlist");
    check(!virtual_is_playlist("m3u"), "bare m3u without dot rejected");
    check(!virtual_is_playlist("x.m3u.bak"), "a backup extension does not match");
    check(!virtual_is_playlist("x.mp3"), "MP3 files are not playlists");
    check(!virtual_is_playlist("x.MP3"), "case-folded MP3 too");
    check(!virtual_is_playlist(""), "an empty name is not a playlist");
    check(!virtual_is_playlist(0), "NULL is not a playlist");
}

static void test_basic(const char *wd)
{
    char path[300];
    struct virtual_entry e;
    u32 stub = MOCK;
    static const char one[] = "#EXTM3U\nTrack 1.flac\n";

    snprintf(path, sizeof path, "one.m3u");
    write_fix(path, one, (unsigned)sizeof one - 1);

    check(virtual_open(stub, 0, path) == VIRTUAL_OK, "a one-track playlist opens");
    check(virtual_count() == 1, "one row held");
    check(virtual_truncated() == 0, "nothing truncated");
    check(virtual_error() == 0, "no parser error");
    check(virtual_path() && !strcmp(virtual_path(), path), "virtual_path round-trips");
    check(virtual_entry(0, &e) == VIRTUAL_OK, "row 0 is readable");
    check(e.ref && !strcmp(e.ref, "Track 1.flac"), "row 0 reference is exact");
    check(e.name && !strcmp(e.name, "Track 1.flac"), "row 0 display name is the file part");
    check(virtual_entry(1, &e) == VIRTUAL_ERR_STATE, "row 1 is out of range");
    check(virtual_entry(-1, &e) == VIRTUAL_ERR_STATE, "a negative index is rejected");
    check(virtual_entry(0, 0) == VIRTUAL_ERR_STATE, "a NULL out pointer is rejected");
    virtual_close();
    check(virtual_count() == 0, "after close the count is zero");
    check(virtual_entry(0, &e) == VIRTUAL_ERR_STATE, "rows are gone after close");
    check(virtual_open(stub, 0, path) == VIRTUAL_OK, "reopen after close works");
    check(virtual_count() == 1, "reopen gives the same rows");
    virtual_close();
    virtual_close();                       /* double close */
    check(virtual_count() == 0, "a double close is harmless");

    check(virtual_open(stub, 0, "nope/missing.m3u") == VIRTUAL_ERR_OPEN,
          "a missing playlist reports VIRTUAL_ERR_OPEN");
    check(virtual_open(0, 0, path) == VIRTUAL_ERR_OPEN,
          "a null fs stub fails cleanly instead of jumping through zero");

    snprintf(path, sizeof path, "empty.m3u");
    write_fix(path, "", 0);
    check(virtual_open(stub, 0, path) == VIRTUAL_OK, "an empty playlist opens");
    check(virtual_count() == 0, "an empty playlist holds zero rows");
    virtual_close();
}

static void test_root_playlist(const char *wd)
{
    char path[300];
    struct virtual_entry e;
    u32 stub = MOCK;

    snprintf(path, sizeof path, "root.m3u");
    write_fix(path, "Song.flac\r\n", 11);

    check(virtual_open(stub, 0, path) == VIRTUAL_OK, "a root playlist opens");
    check(virtual_entry(0, &e) == VIRTUAL_OK, "root row readable");
    check(e.ref && !strcmp(e.ref, "Song.flac"),
          "a root playlist adds no directory prefix");
    check(e.name && !strcmp(e.name, "Song.flac"), "root display name intact");
    virtual_close();
}

static void test_card_playlist(const char *wd)
{
    /* shaped like the card's own files: BOM, #EXTM3U header, CRLF endings,
     * ../Music references, duplicates, debris */
    static const char pl[] =
        "\xEF\xBB\xBF#EXTM3U\r\n"
        "#EXTINF:120,T\r\n"
        "../Music/A/01 - first.flac\r\n"
        "../Music/A/02 - second.flac\r\n"
        "\r\n"
        "../Music/A/01 - first.flac\r\n"        /* duplicate */
        "../Music/A/01 - first.flac \t\r\n"     /* duplicate + debris */
        "garbage  \r\n"
        "../Music/A/zz.flac\r\n";
    char path[300];
    struct virtual_entry e;

    snprintf(path, sizeof path, "card.m3u");
    write_fix(path, pl, (unsigned)sizeof pl - 1);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK, "a BOM + CRLF playlist opens");
    check(virtual_error() == 0, "no parser error on the card-shaped playlist");
    checkf(virtual_count() == 6,
           "six rows: the BOM did not poison the first entry (got %u)",
           virtual_count());
    check(virtual_entry(0, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "../Music/A/01 - first.flac"),
          "row 0 is the first track, BOM stripped");
    check(virtual_entry(1, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "../Music/A/02 - second.flac"),
          "row 1 is the second track");
    check(virtual_entry(2, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "../Music/A/01 - first.flac"),
          "row 2 is the duplicate, order preserved");
    check(virtual_entry(3, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "../Music/A/01 - first.flac"),
          "row 3 is the duplicate with trailing blanks trimmed");
    check(e.name && !strcmp(e.name, "01 - first.flac"),
          "display name keeps spaces and extension");
    check(virtual_entry(4, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "garbage"),
          "a malformed line without an extension is still a row");
    check(virtual_entry(5, &e) == VIRTUAL_OK &&
          e.ref && !strcmp(e.ref, "../Music/A/zz.flac"),
          "the last row follows in order");
    virtual_close();
}

static void test_absolute(const char *wd)
{
    char path[300], want[300];
    struct virtual_entry e;

    snprintf(path, sizeof path, "Playlists/abs.m3u");
    if (mkdir("Playlists", 0777)) { perror("Playlists"); }
    write_fix(path, ":Music/absolute.flac\nrel.flac\n", 30);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK, "a mixed playlist opens");
    check(virtual_entry(0, &e) == VIRTUAL_OK && e.ref &&
          !strcmp(e.ref, ":Music/absolute.flac"),
          "a drive-rooted entry is stored without the directory prefix");
    snprintf(want, sizeof want, "Playlists/rel.flac");
    check(virtual_entry(1, &e) == VIRTUAL_OK && e.ref &&
          !strcmp(e.ref, want),
          "a relative entry carries the playlist's directory");
    virtual_close();
}

static void test_missing_track_open(const char *wd)
{
    char path[300];
    struct virtual_entry e;
    struct m30fs_file f;
    int rc;

    snprintf(path, sizeof path, "exists.flac");
    write_fix(path, "x", 1);
    snprintf(path, sizeof path, "missing.m3u");
    write_fix(path, "exists.flac\nnope.flac\n", 22);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK,
          "a playlist with a missing track opens");
    check(virtual_count() == 2, "both rows are held");
    check(virtual_entry(0, &e) == VIRTUAL_OK && e.ref, "row 0 present");
    check(virtual_entry(1, &e) == VIRTUAL_OK && e.ref,
          "row 1 present even though its file is missing");

    /* opening the missing reference fails cleanly at the fs layer */
    rc = m30fs_init(&f, 0, e.ref);
    check(rc != M30FS_OK, "opening the missing reference reports an error");
    m30fs_close(&f);                       /* must be safe after a failed open */
    check(m30fs_init(&f, 0, "exists.flac") == M30FS_OK, "the real track still opens");
    m30fs_close(&f);
    virtual_close();
}

static void test_utf8(const char *wd)
{
    /* "Löwe/Jóga.flac" in UTF-8, byte-exact through the engine */
    static const unsigned char line[] = {
        'L', 0xC3, 0xB6, 'w', 'e', '/', 'J', 0xC3, 0xB3, 'g', 'a',
        '.', 'f', 'l', 'a', 'c'
    };
    char path[300];
    struct virtual_entry e;

    snprintf(path, sizeof path, "utf8.m3u");
    write_fix(path, line, (unsigned)sizeof line);
    { FILE *f = fopen(path, "ab"); fputc('\n', f); fclose(f); }

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK, "a UTF-8 playlist opens");
    check(virtual_entry(0, &e) == VIRTUAL_OK && e.ref &&
          !memcmp(e.ref, line, sizeof line) && e.ref[sizeof line] == 0,
          "UTF-8 bytes pass through unchanged, NUL-terminated");
    check(e.name && !strcmp(e.name, (const char *)line + 6),
          "the UTF-8 display name is the part after the slash");
    virtual_close();
}

static void test_too_long(const char *wd)
{
    char path[300];
    struct virtual_entry e;
    FILE *f;
    unsigned i;

    snprintf(path, sizeof path, "long.m3u");
    f = fopen(path, "wb");
    if (!f) { exit(2); }
    fputs("short.flac\n", f);
    for (i = 0; i < 120; i++) { fputc('x', f); }   /* 120 > M30VIRTUAL_REF_MAX */
    fputs(".flac\n", f);
    fputs("after.flac\n", f);
    fclose(f);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK,
          "a playlist with an over-long entry opens");
    checkf(virtual_count() == 2,
           "the over-long entry is dropped, not truncated (got %u)",
           virtual_count());
    check(virtual_entry(0, &e) == VIRTUAL_OK && e.ref &&
          !strcmp(e.ref, "short.flac"), "rows before the long entry survive");
    check(virtual_entry(1, &e) == VIRTUAL_OK && e.ref &&
          !strcmp(e.ref, "after.flac"), "rows after the long entry survive");
    check(virtual_truncated() == 0, "a dropped row is not a truncation");
    virtual_close();
}

static void test_large(const char *wd)
{
    char path[300], line[64];
    struct virtual_entry e;
    FILE *f;
    unsigned i;
    int order_ok = 1, name_ok = 1;

    snprintf(path, sizeof path, "fits.m3u");
    f = fopen(path, "wb");
    if (!f) { exit(2); }
    for (i = 0; i < 200; i++) { fprintf(f, "Music/f%u.flac\n", i); }
    fclose(f);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK, "a 200-row playlist opens");
    checkf(virtual_count() == 200, "all 200 rows held (got %u)", virtual_count());
    check(virtual_truncated() == 0, "200 rows are not a truncation");
    for (i = 0; i < 200; i++) {
        if (virtual_entry((int)i, &e) != VIRTUAL_OK) { order_ok = 0; break; }
        snprintf(line, sizeof line, "Music/f%u.flac", i);
        if (strcmp(e.ref, line)) { order_ok = 0; break; }
        snprintf(line, sizeof line, "f%u.flac", i);
        if (strcmp(e.name, line)) { name_ok = 0; break; }
    }
    check(order_ok, "all 200 rows come back in playlist order");
    check(name_ok, "every row's display name is its file part");

    /* 300 rows: 256 fit, the rest are truncation, never silent */
    snprintf(path, sizeof path, "huge.m3u");
    f = fopen(path, "wb");
    if (!f) { exit(2); }
    for (i = 0; i < 300; i++) { fprintf(f, "M/h%u.flac\n", i); }
    fclose(f);

    check(virtual_open(MOCK, 0, path) == VIRTUAL_OK, "a 300-row playlist opens");
    checkf(virtual_count() == M30VIRTUAL_MAX_ENTRIES,
           "exactly the cap is held (got %u)", virtual_count());
    check(virtual_truncated(), "the overflow is reported as truncation");
    order_ok = 1;
    for (i = 0; i < virtual_count(); i++) {
        if (virtual_entry((int)i, &e) != VIRTUAL_OK) { order_ok = 0; break; }
        snprintf(line, sizeof line, "M/h%u.flac", i);
        if (strcmp(e.ref, line)) { order_ok = 0; break; }
    }
    check(order_ok, "the kept rows are the first ones, in order");
    virtual_close();
}

int main(int argc, char **argv)
{
    char wd[280];

    if (argc != 2) {
        printf("usage: test_m30virtual WORKDIR\n");
        return 2;
    }
    if (chdir(argv[1])) {
        perror(argv[1]);
        return 2;
    }
    snprintf(wd, sizeof wd, "%s", argv[1]);

    test_extensions();
    test_basic(wd);
    test_root_playlist(wd);
    test_card_playlist(wd);
    test_absolute(wd);
    test_missing_track_open(wd);
    test_utf8(wd);
    test_too_long(wd);
    test_large(wd);

    printf("test_m30virtual: %d checks, %d failures\n", total, fails);
    return fails ? 1 : 0;
}