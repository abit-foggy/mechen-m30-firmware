#ifndef M30_SHUFFLE_INDEX_H
#define M30_SHUFFLE_INDEX_H
/* Shared by the M3U engine and its read-only Now Playing preview. */
static inline u32 m3u_shuffle_index(u32 cursor,u32 h,u32 mask,u32 key)
{
    u32 index=cursor-1u, l=index>>h, r=index&mask;
    for (u32 round=0;round<4;round++) {
        u32 f=(r^key^(round*0x9du))*0x9e37u;
        u32 next=l^((f^(f>>8))&mask);
        l=r;
        r=next;
    }
    return (l<<h)|r;
}
#endif
