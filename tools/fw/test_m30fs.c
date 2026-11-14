/* Host harness for the firmware filesystem adapter (tools/fw/m30fs.c).
 *
 * This is a MOCK. It replaces the kernel syscall stub with a fake that serves
 * bytes from a real file, so the adapter's own logic -- path bounding, the
 * open/size/read/close sequence, cursor behaviour, double-close safety -- can be
 * exercised on the host. It does NOT establish that the firmware ABI works;
 * that rests on the disassembly in docs/reverse-engineering.md.
 *
 * The mock's syscall function has the same five-argument shape the adapter
 * calls with, and it interprets the operation ids the same way the kernel is
 * believed to. Where the mock's interpretation is an assumption, the test says
 * so rather than presenting the result as firmware behaviour.
 *
 * Usage: test_m30fs <fixture-file>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "m30fs.h"

static FILE *backing;          /* the fake file the mock serves from */
static long   mock_opens;      /* how many times op 5 was seen */
static long   mock_closes;     /* how many times op 7 was seen */
static long   mock_chdirs;     /* how many times op 8 was seen */
static long   mock_badclose;   /* closes with a bogus handle */

/* A fake kernel: same five-argument shape, interpreted per the documented ops.
 * The mock is deliberately strict about argument positions so that a mistake in
 * the adapter's call shape shows up as a wrong result rather than as silence. */
static long mock_fs(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    switch (op) {
    case M30FS_OP_CHDIR:
        /* the stock creator passes ':' and nothing else; anything else is a
         * call-shape mistake worth reporting */
        if ((int)a1 != ':') { return -1; }
        mock_chdirs++;
        return 0;
    case M30FS_OP_OPEN: {
        /* the adapter sends BOM + UTF-16LE; decode back to a host path. This
         * is host-side convenience, NOT a claim about the kernel. */
        const unsigned char *nm = (const unsigned char *)a1;
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
        fprintf(stderr, "[mock] decoded %d chars: %s -> %p\n", qi, name, (void*)backing);
        mock_opens++;
        return backing ? 0x1234u : 0;   /* a nonzero handle, 0 on failure */
    }
    case M30FS_OP_SIZE: {
        long sz;
        u32 *out = (u32 *)a1;
        if (a2 != 0x1234u || !out) { return -1; }
        long here = ftell(backing);
        fseek(backing, 0, SEEK_END);
        sz = ftell(backing);
        fseek(backing, here, SEEK_SET);   /* size must not move the cursor */
        *out = (u32)sz;
        return 0;
    }
    case M30FS_OP_READ: {
        /* the adapter always passes the context as arg0, so the buffer, count
         * and handle arrive in a1, a2 and a3 */
        u32 n = a2;
        if (a3 != 0x1234u || !a1) { return -1; }
        return (long)fread((void *)(uintptr_t)a1, 1, n, backing);
    }
    case M30FS_OP_CLOSE:
        if (a1 != 0x1234u) { mock_badclose++; return -1; }
        mock_closes++;
        return 0;
    default:
        return -1;
    }
}

/* Pull the adapter's source in so the mock can reach its statics. The stub
 * "address" is meaningless on the host, so install_mock() installs the mock
 * through m30fs_set_stub, the same entry point a real module would use. */
#undef main
#include "m30fs.c"

static void install_mock(void)
{
    m30fs_set_stub(0, 0);
    fs = mock_fs;
    fs_ctx = 0;
}

static int fails;

static void check(int ok, const char *what)
{
    printf("%s  %s\n", ok ? "PASS" : "FAIL", what);
    if (!ok) { fails++; }
}

int main(int argc, char **argv)
{
    struct m30fs_file f;
    char buf[64];
    long r;
    int i;

    if (argc != 2) {
        printf("usage: test_m30fs <fixture>\n");
        return 2;
    }
    install_mock();

    /* 1. a clean open/read/close round trip */
    check(m30fs_init(&f, 0, argv[1]) == M30FS_OK, "open succeeds");
    check(mock_chdirs == 1, "exactly one chdir to the root drive");
    check(mock_opens == 1, "exactly one open");
    check(f.size > 0, "size was queried and is nonzero");

    r = m30fs_read(&f, buf, sizeof buf);
    check(r > 0, "first read returns bytes");
    check(m30fs_tell(&f) == (u32)r, "cursor advanced by the bytes read");

    /* read to the end and confirm the cursor stops there */
    {
        u32 total = (u32)r;
        while ((r = m30fs_read(&f, buf, sizeof buf)) > 0) { total += (u32)r; }
        check(r == 0, "read returns 0 at end of file");
        check(total == f.size, "total bytes read equals the reported size");
        check(m30fs_tell(&f) == f.size, "cursor rests at the file size");
    }

    m30fs_close(&f);
    check(mock_closes == 1, "exactly one close");
    m30fs_close(&f);
    check(mock_closes == 1 && mock_badclose == 0,
          "a second close is a no-op and passes no bogus handle");

    /* 2. a path that is too long is refused before any syscall */
    {
        char longpath[600];
        memset(longpath, 'x', sizeof longpath - 1);
        longpath[sizeof longpath - 1] = 0;
        check(m30fs_init(&f, 0, longpath) == M30FS_ERR_TOOBIG,
              "an over-long path is refused with M30FS_ERR_TOOBIG");
        check(mock_opens == 1, "no extra open was issued for the bad path");
    }

    /* 3. an empty path is refused */
    check(m30fs_init(&f, 0, "") == M30FS_ERR_BADPATH,
          "an empty path is refused with M30FS_ERR_BADPATH");

    /* 4. a missing file yields a zero handle and an error */
    check(m30fs_init(&f, 0, "/nonexistent/playlist.m3u") == M30FS_ERR,
          "a missing file reports M30FS_ERR");
    check(f.handle == 0, "the failed open leaves no handle behind");

    /* 5. reopening after a close works */
    check(m30fs_init(&f, 0, argv[1]) == M30FS_OK, "reopen after close succeeds");
    r = m30fs_read(&f, buf, 8);
    check(r == 8, "the reopened file reads from its start");
    m30fs_close(&f);

    /* 6. a null descriptor is refused */
    check(m30fs_init(0, 0, argv[1]) == M30FS_ERR,
          "a null descriptor is refused");

    /* (the label buffer is shared with the read buffer above and needs to be
     * big enough for these labels) */
    /* 7. files sized to land exactly on, just past, and just before the
     *    boundaries the builder warns about: a file shorter than one sector,
     *    one ending mid-sector, and one crossing several 4 KB boundaries. */
    {
        static const struct { u32 size; const char *what; } cases[] = {
            { 27,    "a file shorter than one sector" },
            { 511,   "a file one byte short of a sector" },
            { 512,   "a file exactly one sector" },
            { 513,   "a file one byte into the second sector" },
            { 4095,  "a file one byte short of 4 KB" },
            { 4096,  "a file exactly 4 KB" },
            { 4097,  "a file one byte past 4 KB" },
            { 12288, "a file of exactly three 4 KB blocks" },
            { 12289, "a file crossing four 4 KB boundaries" },
        };
        u32 ci;
        for (ci = 0; ci < sizeof cases / sizeof cases[0]; ci++) {
            char name[64];
            FILE *src;
            u32 total = 0;
            u32 sz = cases[ci].size;
            u8 *expect = (u8 *)malloc(sz ? sz : 1);
            u8 *got = (u8 *)malloc(sz ? sz : 1);
            u32 k;

            snprintf(name, sizeof name, "%s.%u", argv[1], sz);
            src = fopen(name, "wb");
            for (k = 0; k < sz; k++) {
                fputc((int)(k & 0xFF), src);      /* a recognisable pattern */
            }
            fclose(src);
            for (k = 0; k < sz; k++) {
                expect[k] = (u8)(k & 0xFF);
            }

            if (m30fs_init(&f, 0, name) == M30FS_OK) {
                int ok = (f.size == sz);
                while (total < sz) {
                    u32 want = sizeof buf;
                    if (want > sz - total) { want = sz - total; }
                    r = m30fs_read(&f, got + total, want);
                    if (r <= 0) { break; }
                    total += (u32)r;
                }
                ok = ok && (total == sz);
                ok = ok && (memcmp(expect, got, sz) == 0);
                m30fs_close(&f);
                snprintf(buf, sizeof buf, "%s: size %u read back intact",
                         cases[ci].what, sz);
                check(ok, buf);
            } else {
                snprintf(buf, sizeof buf, "%s: open failed", cases[ci].what);
                check(0, buf);
            }
            free(expect);
            free(got);
            remove(name);
        }
    }

    /* 8. a size query must not leave the subsequent read at EOF: open, size,
     *    then read, with no seek in between. The builder's own op 9 handler
     *    moves the kernel cursor, which is the trap this guards against. */
    {
        char name[64];
        FILE *src;
        u32 k;
        snprintf(name, sizeof name, "%s.cursor.tmp", argv[1]);
        src = fopen(name, "wb");
        for (k = 0; k < 1500; k++) { fputc('A', src); }
        fclose(src);

        if (m30fs_init(&f, 0, name) == M30FS_OK) {
            /* init already did op 9; read immediately and expect real bytes */
            r = m30fs_read(&f, buf, sizeof buf);
            check(r > 0, "after the size query a read still returns bytes");
            /* and the bytes must be from the start, not from wherever the
             * kernel cursor was left */
            check(buf[0] == 'A' && buf[1] == 'A',
                  "those bytes are from offset 0, not from the cursor");
            m30fs_close(&f);
        } else {
            check(0, "cursor test: open failed");
        }
        remove(name);
    }

    printf("%s\n", fails ? "test_m30fs: FAILED" : "test_m30fs: OK");
    return fails ? 1 : 0;
}
