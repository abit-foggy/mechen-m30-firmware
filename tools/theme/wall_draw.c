#ifndef WALL_DRAW_FIXTURE
typedef unsigned int u32;
typedef unsigned short u16;
struct region { u16 x, y, width, height; };
typedef int (*region_fn)(struct region *, u32);
typedef int (*dma_fn)(u32, u32);

#endif
#include "wallpaper.h"
typedef int (*transfer_fn)(u32,u32,const struct region *);
#ifndef RESOURCE
#define RESOURCE ((int (*)(u32,u32,u32,u32))0xbfc09c05u)
#endif
#ifndef STOCK_TRANSFER
#define STOCK_TRANSFER ((transfer_fn)0xbfc0aa19u)
#endif
#ifndef STOCK_CLEAR
#define STOCK_CLEAR ((int (*)(const struct region*,u32,u32))0x36119d81u)
#endif
/* Shift warm dial accents to the theme color while retaining the
 * brightness of the original edges, shadows and white highlights. */
static u16 dial_color(u16 source)
{
    unsigned red=source>>11, green=(source>>6)&31, blue=source&31;
    if (red<=green+2 || red<=blue+2) return source;
    unsigned neutral=green<blue?green:blue;
    unsigned intensity=red-neutral;
    u16 accent=WALL->accent;
    red=neutral+((accent>>11)*intensity+15)/31;
    green=neutral*2+(((accent>>5)&63)*intensity+15)/31;
    blue=neutral+((accent&31)*intensity+15)/31;
    return (red<<11)|(green<<5)|blue;
}

static int paint(const struct region *area,int selected,int use_source,u32 fd,u32 offset,u16 matte)
{
    u32 w=area->width,h=area->height;
    u16 *pixels=(u16 *)(unsigned long)*(volatile u32 *)0x9fc0bf50u;
    u32 capacity=*(volatile u16 *)0x9fc0bf54u/2;
    region_fn set=(region_fn)(unsigned long)*(volatile u32 *)0x9fc0bf98u;
    dma_fn submit=(dma_fn)(unsigned long)*(volatile u32 *)0x9fc0bf84u;
    if (area->x+w>320 || area->y+h>240 || !pixels || !capacity || !set || !submit)
        return 0;
    set((struct region *)area,0);
    /* Calculate each ridge column once; row draws use screen coordinates. */
    unsigned char ridge[320];
    for (unsigned i=0;i<w;i++) ridge[i]=wall_ridge(area->x+i);
    if (use_source && RESOURCE(fd,0,offset,15)<0) return 0;
    unsigned n=0, available=0, remaining=w*h;
    for (unsigned j=0;j<h;j++) {
        unsigned y=j+area->y;
        for (unsigned i=0;i<w;i++) {
            unsigned x=i+area->x;
            u16 color=selected?(i<3?WALL->accent:WALL->distant):wall_pixel(x,y,ridge[i]);
            if (use_source) {
                if (!n) {
                    available=remaining<capacity?remaining:capacity;
                    if (RESOURCE(fd,(u32)pixels,available*2,17)<0) return 0;
                    remaining-=available;
                }
                if (pixels[n]!=matte)
                    color=use_source==2?dial_color(pixels[n]):pixels[n];
            }
            pixels[n++]=color;
            if (n==capacity) {
                if (!submit(n,w)) return 0;
                n=0;
            }
        }
    }
    return !n || submit(n,w);
}

int draw_wall(u32 fd,u32 offset,const struct region *area)
{
    u32 w=area->width,h=area->height;
    if (WALL->magic!=WALL_MAGIC) return STOCK_TRANSFER(fd,offset,area);
    u32 style=*(volatile u32 *)0x9fc0bff8u;
    if (fd==*(volatile u32 *)0x9fc0bfd4u) {
        int selected=offset==0x47090;
        if ((offset==0x8e40 && w==320 && h==240) ||
            (w==310 && h==29 && (selected ||
              (offset>=0xadda4 && offset<=0xc830c && (offset-0xadda4)%0x463c==0)))) {
            if (paint(area,selected,0,0,0,0)) return 1;
        }
        else if (offset==0x3e5c8 && w==110 && h==20 && area->y==2) {
            /* common.sty slot 49 backs the changing list position. */
            if (paint(area,0,0,0,0,0)) return 1;
        }
        else if (area->y+h<=29 &&
                 h<=24 && w<=51 && ((offset>=0xea0 && offset<=0x89c0) ||
                                    (offset>=0x2e640 && offset<=0x30bc0))) {
            if (paint(area,0,1,fd,offset,0x18c3)) return 1;
        }
#ifdef LIST_ICON_ENTRY
        else if (w<=40 && h<=30) return ((transfer_fn)LIST_ICON_ENTRY)(fd,offset,area);
#endif
    } else if (fd==*(volatile u32 *)0x9fc0bfe8u) {
        if (style==0x1c4330 && w==320 &&
            ((area->y==29 && (h==211 || h==176)) || (area->y==0 && h==29))) {
            if (h==176 && area->y==29) {
                const struct region bottom={0,205,320,35};
                paint(&bottom,0,0,0,0,0);
            }
            if (paint(area,0,area->y==29?2:1,fd,offset,0x18c3)) return 1;
        } else if (style==0x1c4330 &&
                   (offset==0x10cfc0 || offset==0x110bc0 || offset==0x1147c0)) {
            /* These three assets contain only matte. Extend the topmost
             * full-width 24px backdrop to the dial's first row at y=29. */
            static const struct region header={0,0,320,29};
            if (offset==0x10cfc0 && area->x==0 && area->y==0 &&
                w==320 && h==24) area=&header;
            if (paint(area,0,0,0,0,0)) return 1;
        } else if (style==0x50690) {
            int metadata=(offset>=0xca78 && offset<=0xd0b8 && w==20 && h==20) ||
                         offset==0x191cc || offset==0x10798 || offset==0xb808;
            if (metadata || (offset>=0xd3d8 && offset<=0x194ec && w<=129)) {
                if (paint(area,0,1,fd,offset,metadata?0x39e7:0x18c3)) return 1;
            }
        }
    }
    return STOCK_TRANSFER(fd,offset,area);
}
int clear_wall(const struct region *area,u32 a,u32 b)
{
    if (area && area->x==0 && area->width==320 && WALL->magic==WALL_MAGIC) {
        u32 style=*(volatile u32 *)0x9fc0bff8u;
        int background=style==0x1c4330 &&
            (area->y+area->height<=29 || (area->y==0 && area->height==240));
        if (style==0x50690)
            background=(area->y==0 && area->height==28) ||
                (area->y==28 && area->height==151) || (area->y==179 && area->height==61);
        if (background && paint(area,0,0,0,0,0)) return 1;
    }
    return STOCK_CLEAR(area,a,b);
}
