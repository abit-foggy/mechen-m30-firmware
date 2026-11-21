#ifndef M30_FLOW_H
#define M30_FLOW_H
#include "../m3u/m3uplay.h"

#define FLOW_MAGIC 0x3146434du
enum { FLOW_SLOTS=7, FLOW_PIXELS=40, FLOW_WIDTH=150, FLOW_HEIGHT=150 };
struct flow_tile {
    u32 magic, pack;
    u16 track, count, palette[64];
    u8 pixels[800], padding[80];
    u32 checksum;
};
_Static_assert(sizeof(struct flow_tile)==1024,"two aligned SD sectors per cover");

struct flow_window {
    struct flow_tile *visible[5];
};
struct flow_region { u16 x,y,width,height; };
typedef int (*flow_load)(u32 track,struct flow_tile *tile,void *context);
typedef int (*flow_prepare)(struct flow_tile *slots,struct flow_window *window,
                            const u16 tracks[7],u32 pack,u32 count,flow_load load,void *ctx);
typedef int (*flow_draw)(const struct flow_window *window,u16 *row);
#endif
