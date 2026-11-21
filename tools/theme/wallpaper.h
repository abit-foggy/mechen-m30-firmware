#ifndef M30_WALLPAPER_H
#define M30_WALLPAPER_H
/* The 16 bytes immediately after the existing 116-byte icon cache. */
struct wallpaper {
    unsigned short magic, sky, distant, mountain, accent;
    unsigned char ridge[6];
};
#define WALL ((volatile struct wallpaper *)0xbfc09ee8u)
#define WALL_MAGIC 0x3157
static inline unsigned wall_ridge(unsigned x)
{
    unsigned k=x>>6;
    int a=WALL->ridge[k], b=WALL->ridge[k+1];
    return a+(((b-a)*(int)(x&63))>>6);
}
static inline unsigned short wall_pixel(unsigned x,unsigned y,unsigned level)
{
    if (y>=level+19+(x>>5)) return WALL->mountain;
    if (y>=level) return WALL->distant;
    int dx=(int)x-268, dy=(int)y-52;
    int inner=dx-4, up=dy+2;
    if ((dx*dx+dy*dy<=100 && inner*inner+up*up>81) ||
        (y<105 && (x*149+y*271+x*y)%1583==37)) return WALL->accent;
    return WALL->sky;
}
#endif
