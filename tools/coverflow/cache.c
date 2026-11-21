#include "flow.h"

static int valid(const struct flow_tile *tile,u32 pack,u32 count)
{
    if (tile->magic!=FLOW_MAGIC || tile->pack!=pack || tile->count!=count ||
        !tile->track || tile->track>count) return 0;
    const u8 *bytes=(const u8 *)tile;
    u32 hash=2166136261u;
    for (unsigned i=0;i<sizeof(*tile)-sizeof(tile->checksum);i++) hash=(hash^bytes[i])*16777619u;
    return hash==tile->checksum;
}

int flow_cache(struct flow_tile *slots,struct flow_window *window,const u16 tracks[7],
               u32 pack,u32 count,flow_load load,void *ctx)
{
    /* LCD scratch may be reused by stock between refreshes. Validate each
     * resident sector before reuse; pin all hits before evicting any misses. */
    int at[7];
    for (unsigned i=0;i<7;i++) at[i]=-1;
    unsigned pinned=0;
    for (unsigned j=0;j<7;j++) {
        if (!valid(slots+j,pack,count)) continue;
        for (unsigned i=0;i<7;i++) {
            if (tracks[i]==slots[j].track && at[i]<0) {
                at[i]=j;
                pinned|=1u<<j;
            }
        }
    }
    static const u8 priority[]={3,2,4,1,5,0,6};
    for (unsigned k=0;k<7;k++) {
        unsigned i=priority[k];
        if (!tracks[i] || at[i]>=0) continue;
        unsigned j=0;
        while (j<7 && (pinned&(1u<<j))) j++;
        if (j==7) return 0;
        if (!load(tracks[i],slots+j,ctx) || !valid(slots+j,pack,count) ||
            slots[j].track!=tracks[i]) {
            slots[j].magic=0;
            if (i>=1 && i<=5) return 0;
            continue;
        }
        pinned|=1u<<j;
        for (unsigned m=0;m<7;m++) if (tracks[m]==tracks[i]) at[m]=j;
    }
    for (unsigned i=0;i<5;i++) window->visible[i]=at[i+1]<0?0:slots+at[i+1];
    return window->visible[2]!=0;
}
