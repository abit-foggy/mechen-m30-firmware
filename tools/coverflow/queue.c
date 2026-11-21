#include "flow.h"
#include "../m3u/shuffle_index.h"

/* Never ask the engine to advance, seed the next shuffle epoch, or seek.
 * Unknown neighbours stay empty. Repeat-one still shows the surrounding
 * playlist entries, leaving the engine in charge of transport. */
void flow_tracks(u16 tracks[7],u32 pos,u32 count,u32 shuffle,u32 loop,u32 key,u32 cursor)
{
    for (int i=0;i<7;i++) tracks[i]=0;
    if (!pos || pos>count) return;
    tracks[3]=pos;
    int wrap=loop==2 || loop==4;
    if (shuffle!=1) {
        for (int i=0;i<7;i++) {
            int n=(int)pos+i-3;
            if (wrap) {
                while (n<1) n+=count;
                while (n>(int)count) n-=count;
            }
            if (n>=1 && n<=(int)count) tracks[i]=n;
        }
        return;
    }
    u32 h=1;
    while ((1u<<(2*h))<count) h++;
    u32 end=1u<<(2*h),mask=(1u<<h)-1;
    if (!key || !cursor || cursor>end || m3u_shuffle_index(cursor,h,mask,key)+1!=pos) return;
    for (int dir=-1;dir<=1;dir+=2) {
        u32 p=cursor;
        for (int i=1;i<=3;) {
            if (dir>0 && p==end) break;
            if (dir<0 && p==1) {
                if (!wrap) break;
                p=end;
            } else p+=dir;
            u32 n=m3u_shuffle_index(p,h,mask,key)+1;
            if (n<=count) tracks[3+dir*i++]=n;
        }
    }
}
