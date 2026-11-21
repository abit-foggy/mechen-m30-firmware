#include "flow.h"
#ifndef FLOW_REGION
#define FLOW_REGION (*(int (*volatile *)(struct flow_region *,u32))0x9fc0bf98u)
#define FLOW_SEND (*(int (*volatile *)(u32,u32))0x9fc0bf84u)
#endif
/* Draw back to front. Outer panel edges taper toward the horizon and
 * reflections use the corresponding cover row below the bottom edge. */
int flow_render(const struct flow_window *window,u16 *row)
{
    static const u8 order[]={0,4,1,3,2};
    static const u8 left[]={0,13,36,101,126};
    static const u8 widths[]={24,36,78,36,24};
    struct flow_region area={0,28,FLOW_WIDTH,FLOW_HEIGHT};
    if (!FLOW_REGION || !FLOW_SEND) return 0;
    FLOW_REGION(&area,0);
    for (int y=0;y<FLOW_HEIGHT;y++) {
        for (int x=0;x<FLOW_WIDTH;x++) row[x]=0x0842;
        for (unsigned depth=0;depth<5;depth++) {
            int slot=order[depth],width=widths[slot];
            const struct flow_tile *tile=window->visible[slot];
            if (!tile) continue;
            for (int dx=0;dx<width;dx++) {
                int t=slot<2?width-1-dx:dx;
                int inset=slot==2?0:7+t*9/width+(depth<2?8:0);
                int top=27+inset,height=78-2*inset;
                int dy=y-top;
                if (dy<0 || dy>=height+height/3) continue;
                int reflection=dy>=height;
                if (reflection) dy=height-1-(dy-height)*2;
                int tx=dx*FLOW_PIXELS/width,ty=dy*FLOW_PIXELS/height;
                int palette=(tx>=FLOW_PIXELS/2?16:0)+(ty>=FLOW_PIXELS/2?32:0);
                int pixel=ty*FLOW_PIXELS+tx;
                u8 pair=tile->pixels[pixel>>1];
                u16 color=tile->palette[palette+((pixel&1)?pair>>4:pair&15)];
                if (reflection) color=(color&0xe79c)>>2;
                else if (slot!=2) color=(color&0xf7de)>>1;
                row[left[slot]+dx]=color;
            }
        }
        if (!FLOW_SEND(FLOW_WIDTH,FLOW_WIDTH)) return 0;
    }
    return 1;
}
