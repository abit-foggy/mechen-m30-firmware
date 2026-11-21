/* The list renderer repaints the row before drawing its head/tail icons.
 * Send only foreground runs so the actual row underneath remains visible. */
#ifndef LIST_ICON_FIXTURE
typedef unsigned int u32;
typedef unsigned short u16;
struct region { u16 x,y,width,height; };
#define RESOURCE ((int (*)(u32,u32,u32,u32))0xbfc09c05u)
#define WINDOW (*(int (*volatile *)(struct region *,u32))0x9fc0bf98u)
#define SEND (*(int (*volatile *)(u32,u32))0x9fc0bf84u)
#define LCD_BUFFER (*(u16 *volatile *)0x9fc0bf50u)
#define LCD_BYTES (*(volatile u16 *)0x9fc0bf54u)
#define ORIGINAL ((int (*)(u32,u32,const struct region *))0xbfc0aa19u)
#endif

int list_icon(u32 fd,u32 offset,const struct region *area)
{
    u32 width=area->width,height=area->height;
    /* Stock common.sty menu glyphs, folders, songs, and option checks.
     * Skip unrelated square bitmaps such as album covers and volume icons. */
    int matched=(width==26 && offset>=0x41c10 && offset<=0x46b48 &&
                 (offset-0x41c10)%1352==0) ||
                (width==24 && ((offset>=0x6a40 && offset<=0x89c0 &&
                 (offset-0x6a40)%1152==0) || (offset>=0xad024 &&
                 offset<=0xad924 && (offset-0xad024)%1152==0)));
    matched=(matched && height==width) ||
        (width==36 && height==26 && offset>=0x32400 && offset<=0x35730 &&
         (offset-0x32400)%1872==0) ||
        (width==29 && height==28 &&
         (offset==0x7fc44 || offset==0x8309c || offset==0x8428c)) ||
        (width==24 && height==24 && (offset==0x83754 || offset==0x83e0c)) ||
        (width==16 && height==24 && offset>=0x305c0 && offset<=0x30bc0 &&
         (offset-0x305c0)%768==0);
    if (!matched || area->x+width>320 ||
        area->y+height>240 || !WINDOW || !SEND || !LCD_BUFFER || LCD_BYTES<width*2)
        return ORIGINAL(fd,offset,area);
    /* All targeted slots have a flat top-left matte. Keep original RGB565
     * foreground colors, including state-specific and antialiased pixels. */
    u32 aligned[18];
    u16 *row=(u16 *)(void *)aligned;
    u16 matte=0;
    if (RESOURCE(fd,0,offset,15)<0) return ORIGINAL(fd,offset,area);
    for (u32 y=0;y<height;y++) {
        if (RESOURCE(fd,(u32)row,width*2,17)<0) return ORIGINAL(fd,offset,area);
        if (!y) matte=row[0];
        u32 x=0;
        while (x<width) {
            while (x<width && row[x]==matte) x++;
            u32 first=x;
            while (x<width && row[x]!=matte) x++;
            if (x>first) {
                u32 n=x-first;
                struct region span={area->x+first,area->y+y,n,1};
                WINDOW(&span,0);
                for (u32 i=0;i<n;i++) LCD_BUFFER[i]=row[first+i];
                if (!SEND(n,n)) return 0;
            }
        }
    }
    return 1;
}
