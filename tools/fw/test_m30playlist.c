/* Host harness for the device-side playlist reader (mocked kernel).
 *
 * Pulls in m30playlist.c, which pulls in m30fs.c and the parser, so the whole
 * chain is the code the player will run. The kernel syscall is the same fake
 * the m30fs test uses.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "m30playlist.h"

static FILE *backing;

static long mock_fs(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    switch (op) {
    case M30FS_OP_CHDIR:
        return 0;
    case M30FS_OP_OPEN: {
        const char *name = (const char *)(uintptr_t)a1;
        if (backing) { fclose(backing); }
        backing = name ? fopen(name, "rb") : NULL;
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

#undef main
#include "m30fs.c"
#include "m30playlist.c"

int main(int argc, char **argv)
{
    struct m30pl pl;
    int rc;
    unsigned n = 0;

    if (argc != 3) {
        printf("usage: test_m30playlist <playlist> <dir>\n");
        return 2;
    }
    /* On the target, a module passes its own fs stub address here. On the host
     * the mock's address is that stub: m30pl_open forwards it to
     * m30fs_set_stub, so the adapter ends up calling the mock. */
    { u32 stub = (u32)(uintptr_t)mock_fs;
      rc = m30pl_open(&pl, stub, 0, argv[1], argv[2]); }

    /* the stock fs stub address is meaningless on the host; pass 0 and install
     * the mock directly, the way a real module would via m30fs_set_stub */
    if (rc != M30PL_OK) {
        printf("OPEN_ERR %d\n", rc);
        return 1;
    }
    printf("OPEN OK\n");
    while ((rc = m30pl_next(&pl)) == M3U_OK) {
        printf("T %s\n", pl.parser.line);
        n++;
    }
    if (rc != M3U_END) {
        printf("PARSE_ERR %d\n", rc);
        m30pl_close(&pl);
        return 1;
    }
    printf("END %u\n", n);
    m30pl_close(&pl);
    printf("CLOSE\n");
    return 0;
}
