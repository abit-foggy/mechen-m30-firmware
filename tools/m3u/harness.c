/* Host test harness for the MIPS16e M3U parser (hosted build).
 *
 * The parser itself is freestanding and only needs a read() callback; this
 * harness supplies one backed by a real file, so the *same* parser source is
 * exercised on the host and can later be compiled as the player's MIPS16e blob
 * unchanged. The fixture is the argv[1] file; the directory prefix is argv[2].
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "m3u.h"

static unsigned char buf[1 << 20];
static unsigned len, pos;

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

int main(int argc, char **argv)
{
    struct m3u_io io;
    struct m3u m;
    FILE *f;
    int rc;

    if (argc != 3) {
        return 2;
    }
    f = fopen(argv[1], "rb");
    if (!f) {
        return 2;
    }
    len = (unsigned)fread(buf, 1, sizeof buf, f);
    fclose(f);
    pos = 0;

    io.read = io_read;
    io.cookie = NULL;
    if (m3u_init(&m, &io, argv[2]) != M3U_OK) {
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
