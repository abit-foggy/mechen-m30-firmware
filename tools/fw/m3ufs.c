/* Firmware-side location arithmetic. See m3ufs.h for what is and is not
 * established -- in particular, these routines are unreferenced in the image,
 * so none of this describes live behaviour. */
#include "m3ufs.h"

static unsigned rd32(const unsigned char *p)
{
    return (unsigned)p[0] | ((unsigned)p[1] << 8)
           | ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}

int m3ufs_split(const unsigned char *loc, unsigned len, struct m3ufs_loc *out)
{
    if (!loc || !out || len < 16) {
        return -1;
    }
    /* arg0 is the first word; arg1 the last, per the layout the card shows */
    out->base = rd32(loc);
    out->entry = rd32(loc + 12);
    return 0;
}

unsigned m3ufs_sector_of(const struct m3ufs_loc *l)
{
    /* 0x7805b270-0x7805b27a: arg0 + (arg1 >> 5) */
    return l->base + (l->entry >> 5);
}

unsigned m3ufs_slot_of(const struct m3ufs_loc *l)
{
    /* 0x7805b27c-0x7805b286: (arg1 & 0x1F) << 4 */
    return (l->entry & 0x1F) << 4;
}

unsigned long m3ufs_byte_offset(const struct m3ufs_loc *l)
{
    /* 0x7805b28c-0x7805b290: sector << 8, then << 1 */
    return (unsigned long)m3ufs_sector_of(l) << 9;
}

int m3ufs_slot_is_zero(const struct m3ufs_loc *l)
{
    return m3ufs_slot_of(l) == 0;
}
