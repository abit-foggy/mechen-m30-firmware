#include "icon_cache.h"
#include "wallpaper.h"
typedef unsigned int u32;
typedef unsigned short u16;
struct region { u16 x, y, width, height; };
typedef int (*region_fn)(struct region *, u32);
typedef int (*dma_fn)(u32, u32);
typedef int (*picture_fn)(u32, u32, u32);

int show_icon(u32 id, u32 x, u32 y)
{
    volatile struct icon_cache *cache = ICON_CACHE;
    if (id != 37 || x != 160 || y != 40 || cache->ready != 1 ||
        *(volatile u32 *)0x9fc0bff8u != 0x50690)
        return ((picture_fn)0xbfc0a9adu)(id,x,y);
    u16 *pixels = (u16 *)(unsigned long)*(volatile u32 *)0x9fc0bf50u;
    u32 capacity = *(volatile u16 *)0x9fc0bf54u / 2;
    region_fn set = (region_fn)(unsigned long)*(volatile u32 *)0x9fc0bf98u;
    dma_fn submit = (dma_fn)(unsigned long)*(volatile u32 *)0x9fc0bf84u;
    if (!pixels || !capacity || !set || !submit) return ((picture_fn)0xbfc0a9adu)(id,x,y);
    struct region area = {(u16)x,(u16)y,20,20};
    set(&area,0);
    for (u32 pos=0; pos<400;) {
        u32 n = 400-pos < capacity ? 400-pos : capacity;
        for (u32 j=0;j<n;j++,pos++) {
            u16 color=cache->palette[(cache->indices[pos>>2] >> (2*(pos&3))) & 3];
            if (WALL->magic==WALL_MAGIC && color==0x39e7) {
                u32 screen_x=x+pos%20;
                color=wall_pixel(screen_x,y+pos/20,wall_ridge(screen_x));
            }
            pixels[j]=color;
        }
        if (!submit(n,20)) return 0;
    }
    return 1;
}

