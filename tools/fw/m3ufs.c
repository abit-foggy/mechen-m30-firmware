/* Firmware-side M3U file resolution. See m3ufs.h for the derivation. */
#include "m3ufs.h"

static unsigned rd32(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8)
           | ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}

int m3ufs_split(const unsigned char *loc, unsigned len, struct m3ufs_loc *out)
{
    if (!loc || !out || len < 8) {
        return -1;
    }
    out->base = rd32(loc);
    /* the entry index is the 32-bit word at +4, but only the low 5 bits that
     * select an entry within a cluster are used by the firmware's arithmetic,
     * and the upper bits are a cluster delta */
    out->entry = rd32(loc + 12);
    return 0;
}

unsigned m3ufs_cluster(const struct m3ufs_loc *l)
{
    /* 0x7805b270-0x7805b27a: arg0 + (arg1 >> 5) */
    return l->base + (l->entry >> 5);
}

unsigned m3ufs_entry_offset(const struct m3ufs_loc *l)
{
    /* 0x7805b27c-0x7805b286: (arg1 & 0x1F) << 4 */
    return (l->entry & (M3UFS_ENTRIES_PER_CLUSTER - 1)) * M3UFS_ENTRY_BYTES;
}

unsigned long m3ufs_sector_offset(const struct m3ufs_loc *l)
{
    /* 0x7805b28c-0x7805b290: cluster << 8, then << 1, i.e. cluster * 512 */
    return (unsigned long)m3ufs_cluster(l) * M3UFS_CLUSTER_BYTES;
}
