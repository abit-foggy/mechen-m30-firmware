/* Shared freestanding M3U line scanner and VFS path resolver.
 *
 * Included by m3uplay.c (browser.ap) and m3u_meng.c (mengine.ap) after
 * defining FS_CALL and VFS_CTX. Routing all VFS calls through a 4-register-arg
 * noinline helper eliminates 5th-stack-arg setup and pool loads at every call
 * site, saving ~150 bytes per MIPS16e blob.
 */
#ifndef M3U_RESOLVE_H
#define M3U_RESOLVE_H

#include "m3uplay.h"

#define NBUF_UNITS 80u   /* 160 bytes on stack: BOM + up to 78 UTF-16 units + NUL */

static __attribute__((noinline)) long vfs(u32 a1, u32 a2, u32 a3, u32 op)
{
    return FS_CALL(VFS_CTX, a1, a2, a3, op);
}

static inline __attribute__((always_inline)) u32 fold_ascii(u32 c)
{
    return (c >= 'A' && c <= 'Z') ? (c | 0x20u) : c;
}

/* Match UTF-8 path component comp[0..clen-1] against an OP_GETNAME buffer
 * (FF FE BOM + UTF-16LE + 00 00, full BMP UTF-8 U+0000..U+FFFF). */
static int name_matches(const u8 *comp, u32 clen, const u8 *nbuf, u32 got_units)
{
    const u8 *p = comp;
    const u8 *end = comp + clen;
    u32 j;

    if (nbuf[0] != 0xFFu || nbuf[1] != 0xFEu) {
        return 0;
    }

    for (j = 0; j < NBUF_UNITS - 2; j++) {
        u32 ud = (u32)nbuf[2 + 2 * j] | ((u32)nbuf[3 + 2 * j] << 8);
        u32 b0, uc;

        if (ud == 0) {
            return p == end;
        }
        if (p >= end) {
            return 0;
        }
        b0 = *p++;
        if (b0 < 0x80u) {
            uc = b0;
        } else if ((b0 & 0xE0u) == 0xC0u && p < end) {
            uc = ((b0 & 0x1Fu) << 6) | (*p++ & 0x3Fu);
        } else if ((b0 & 0xF0u) == 0xE0u && p + 1 < end) {
            uc = ((b0 & 0x0Fu) << 12) | ((u32)(p[0] & 0x3Fu) << 6) | (p[1] & 0x3Fu);
            p += 2;
        } else {
            uc = b0;
        }
        if (fold_ascii(ud) != fold_ascii(uc)) {
            return 0;
        }
    }
    return got_units >= NBUF_UNITS - 1;
}

/* Scan the .m3u file stored at VS->pl_dir / VS->pl_off using 512-byte
 * sector-aligned reads (sec must be 512 bytes, 4-aligned).
 *   want == 0xFFFFFFFFu : count all entries and return the count (0xFFFFFFFFu on I/O error).
 *   want <  0xFFFFFFFFu : copy entry `want` (0-based) into VS->line (NUL-terminated)
 *                         and return its byte length, or 0xFFFFFFFFu if not found.
 * Always closes the file handle before returning. */
static u32 m3u_scan_entry(u8 *sec, u32 want)
{
    long h, got;
    u32 off;
    u32 idx = 0;
    u32 len = 0;
    u32 res = 0xFFFFFFFFu;
    int in_comment = 0;
    int too_long = 0;

    if (!vfs((u32)VS->pl_dir, (u32)VS->pl_off, 1u, OP_OFFSET)) {
        return res;
    }
    h = vfs(0, 0, 0, OP_OPEN);
    if (h <= 0) {
        return res;
    }

    for (off = 0; off < 0x40000u; off += 512u) {
        u32 pos = 0, n, lim;
        if (vfs(off, 0, (u32)h, OP_SEEK) < 0) {
            goto out;
        }
        got = vfs((u32)sec, 512u, (u32)h, OP_READ);
        if (got < 0) {
            goto out;
        }
        n = (u32)got;
        if (off == 0 && n >= 3 && sec[0] == 0xEFu && sec[1] == 0xBBu && sec[2] == 0xBFu) {
            pos = 3;    /* skip UTF-8 BOM */
        }
        lim = (n == 0) ? 1u : n;
        while (pos < lim) {
            u8 c = (n == 0) ? (u8)'\n' : sec[pos];
            pos++;
            if (c == '\r' || c == '\n') {
                if (!in_comment && !too_long && len > 0) {
                    while (len > 0 && (VS->line[len - 1] == ' ' || VS->line[len - 1] == '\t')) {
                        len--;
                    }
                    if (len > 0) {
                        if (want == idx) {
                            VS->line[len] = 0;
                            res = len;
                            goto out;
                        }
                        idx++;
                    }
                }
                len = 0;
                in_comment = 0;
                too_long = 0;
            } else if (!in_comment) {
                if (len == 0 && (c == ' ' || c == '\t')) {
                    /* skip leading whitespace */
                } else if (len == 0 && c == '#') {
                    in_comment = 1;
                } else if (len < M3U_LINE_CAP - 1) {
                    VS->line[len++] = (char)c;
                } else {
                    too_long = 1;
                }
            }
        }
        if (n == 0) {
            break;
        }
    }
    if (want == 0xFFFFFFFFu) {
        res = idx;
    }
out:
    vfs((u32)h, 0, 0, OP_CLOSE);
    return res;
}

/* Resolve the NUL-terminated UTF-8 path in VS->line[0..len-1] starting from
 * the playlist's directory (VS->pl_dir / VS->pl_off).
 * On success, leaves VFS_CTX positioned on the audio file, writes its exact
 * 4-byte VFS extension to *out_ext and directory layer to *out_layer, and
 * returns 1. Returns 0 on any missing folder/file. */
static int m3u_resolve(u32 len, u32 *out_ext, u8 *out_layer)
{
    u8 nbuf[NBUF_UNITS * 2];
    const u8 *local_line = (const u8 *)VS->line;
    u32 i;
    u32 layer;

    if (len == 0 || len >= M3U_LINE_CAP) {
        return 0;
    }

    if (!vfs((u32)VS->pl_dir, (u32)VS->pl_off, 1u, OP_OFFSET)) {
        return 0;
    }
    layer = VS->pl_layer;

    i = 0;
    if (len >= 2 && local_line[1] == ':') {
        i = 2;
        if (i < len && (local_line[i] == '/' || local_line[i] == '\\')) {
            i++;
        }
        vfs(':', 0, 0, OP_CD);
        layer = 0;
    } else if (local_line[0] == '/' || local_line[0] == '\\') {
        i = 1;
        vfs(':', 0, 0, OP_CD);
        layer = 0;
    }

    while (i < len) {
        u32 start = i;
        u32 clen, cmd, mask;
        int is_dir, found = 0;

        while (i < len && local_line[i] != '/' && local_line[i] != '\\') {
            i++;
        }
        clen = i - start;
        is_dir = (i < len);
        if (is_dir) {
            i++;
            if (clen == 0 || (clen == 1 && local_line[start] == '.')) {
                continue;
            }
            if (clen == 2 && local_line[start] == '.' && local_line[start + 1] == '.') {
                if (layer == 0 || !((u8)vfs('|', 0, 0, OP_CD))) {
                    return 0;
                }
                layer--;
                continue;
            }
            if (layer >= 8) {
                return 0;
            }
            mask = EXT_DIRS;
        } else {
            if (clen == 0) {
                return 0;
            }
            mask = AUDIO_MASK;
        }

        cmd = DIR_HEAD;
        while (vfs(cmd, 0, mask, OP_DIR) != 0) {
            u32 got = (u32)vfs((u32)nbuf, NBUF_UNITS, 0, OP_GETNAME);
            if (name_matches(&local_line[start], clen, nbuf, got)) {
                found = 1;
                break;
            }
            cmd = DIR_NEXT;
        }
        if (!found) {
            return 0;
        }
        if (is_dir) {
            if (!((u8)vfs('/', 0, 0, OP_CD))) {
                return 0;
            }
            layer++;
        } else {
            *out_ext = 0;
            vfs((u32)out_ext, 0, 0, OP_GETNAME);
            *out_layer = (u8)layer;
            return 1;
        }
    }
    return 0;
}

#endif /* M3U_RESOLVE_H */
