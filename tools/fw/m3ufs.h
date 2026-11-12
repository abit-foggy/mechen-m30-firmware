/* Firmware-side M3U file resolution: what the stock code actually does.
 *
 * Decoded from music.ap bank 0x7805b200, whose two routines at 0x7805b264 and
 * 0x7805b2dc both take two u16s, do the same cluster arithmetic, and call the
 * kernel filesystem entry at 0xBFC16BB5 twice -- op 0xB to seek and op 0xD to
 * read 0x200 bytes into the buffer at guest 0x7805B4B0, with the context taken
 * from the RAM global 0x9fc15980.
 *
 * The arithmetic, in the firmware's own words:
 *
 *     0x7805b270  lhu  v0, 0x14(s1)     ; arg1
 *     0x7805b272  srl  v0, 5            ; arg1 >> 5
 *     0x7805b276  lhu  v0, 0x10(s1)     ; arg0
 *     0x7805b278  addu v0, v1, v0       ; cluster = arg0 + (arg1 >> 5)
 *     0x7805b27a  sh   v0, 2(s1)
 *     0x7805b27c  lhu  v1, 0x14(s1)
 *     0x7805b27e  li   v0, 0x1F
 *     0x7805b280  and  v0, v1           ; arg1 & 0x1F
 *     0x7805b284  sll  v0, 4            ; (arg1 & 0x1F) * 16
 *     0x7805b286  sh   v0, 0(s1)
 *     0x7805b28c  lhu  v0, 2(s1)
 *     0x7805b28e  sll  a1, 8            ; cluster << 8
 *     0x7805b290  sll  a1, 1            ; << 9, i.e. * 512
 *
 * So the location is addressed as a **cluster plus a 32-entry directory
 * index**: 32 entries of 16 bytes fill a 512-byte cluster, and the low 5 bits
 * of arg1 select the entry within it. That is exFAT directory-entry
 * addressing, and it means a record's location points at the playlist's own
 * directory entry, not at the file's data.
 *
 * What is NOT established, and what this module therefore does not pretend:
 * how a directory entry becomes an open file handle. The two routines read the
 * entry; the open is a later, separate step whose ABI (which opcode, which
 * buffer, how the 8.3 name is passed, who owns the handle) was not traced. The
 * open step is isolated in one function so the contract can be filled in
 * without touching anything else.
 */
#ifndef M3UFS_H
#define M3UFS_H

#include "m3u.h"

/* Directory entries are 16 bytes and 32 of them fill one 512-byte cluster, so
 * the entry index occupies the low 5 bits of the second word. */
#define M3UFS_ENTRIES_PER_CLUSTER 32
#define M3UFS_ENTRY_BYTES 16
#define M3UFS_CLUSTER_BYTES 512

struct m3ufs_loc {
    unsigned base;      /* arg0: the cluster the entry chain starts from */
    unsigned entry;     /* arg1: (cluster_delta << 5) | entry_in_cluster */
};

/* Split a record's 16-byte location field into the two words the firmware's
 * routines take.
 *
 * The card's own data fixes the layout: all ten records share their first
 * twelve bytes -- the directory the playlists live in -- and differ only in the
 * last four, which are monotonic across the records. So bytes 0..3 are the
 * directory's base cluster and bytes 12..15 the entry selector, with bytes 4..11
 * constant and evidently reserved. */
int m3ufs_split(const unsigned char *loc, unsigned len, struct m3ufs_loc *out);

/* The verified half: the cluster the directory entry lives in, and the byte
 * offset of that entry within the cluster. Both match the firmware's own
 * arithmetic exactly. */
unsigned m3ufs_cluster(const struct m3ufs_loc *l);
unsigned m3ufs_entry_offset(const struct m3ufs_loc *l);

/* The byte offset of the sector holding that entry, as the firmware computes
 * it: cluster << 9. */
unsigned long m3ufs_sector_offset(const struct m3ufs_loc *l);

/* The unverified half: turn a location into a readable playlist. `open` must
 * fill io and set opened, or return nonzero. Everything above this line is
 * derived from the firmware; this function is the seam where the firmware's
 * own open opcode belongs, and its body is deliberately the only thing a
 * verified contract would replace. */
struct m3ufs_ctx {
    /* context pointer from RAM global 0x9fc15980 */
    void *fs;
    /* the firmware's directory-entry buffer, guest 0x7805B4B0 */
    void *dirent;
};

#endif /* M3UFS_H */
