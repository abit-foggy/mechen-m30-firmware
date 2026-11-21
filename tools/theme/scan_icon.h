/* Included in the playlist builder after name(). At this point its own card
 * context is initialized and setup is already about to select the root. */
#include "icon_cache.h"
#include "theme_id.h"
#include "settings_line.h"

static u32 icon_open(const char *filename, u32 *length)
{
    name(filename);
    u32 h = FS_OP(G.ctx, (u32)NAMEBUF, 0, 0, 5);
    *length = 0;
    if (h) FS_OP(G.ctx, (u32)length, h, 0, 9);
    return h;
}

static u32 icon_read(u32 handle, u32 length)
{
    return FS_OP(G.ctx, (u32)ARENA, length, handle, 13);
}

static void load_sd_icon(void)
{
    volatile struct icon_cache *cache = ICON_CACHE;
    if (cache->signature != ICON_SIGNATURE) return;
    cache->ready = 0;
    FS_OP(G.ctx, ':', 0, 0, 0);
    u32 size;
    char id[9];
    unsigned a,b;
    name("m30");
    if (!FS_OP(G.ctx,'/',(u32)NAMEBUF,0,0)) return;
    u32 h=icon_open("settings.cfg",&size);
    if (!h) return;
    if (size>512 || !icon_read(h,512) || setting_line(ARENA,size,"theme",&a,&b)!=1 ||
        !parse_theme_id(ARENA+a,b-a,id)) goto close;
    FS_OP(G.ctx,h,0,0,7);
    if (id[0]=='s' && id[1]=='t' && id[2]=='o' && id[3]=='c' && id[4]=='k' && !id[5]) return;
    FS_OP(G.ctx,':',0,0,0);
    name("themes");
    if (!FS_OP(G.ctx,'/',(u32)NAMEBUF,0,0)) return;
    name(id);
    if (!FS_OP(G.ctx, '/', (u32)NAMEBUF, 0, 0)) return;
    h = icon_open("theme.cfg", &size);
    if (!h) return;
    static const char prefix[] = "M30THEME 1\nmusic.sty 85c88fb159ae3dbbe19fb31282afb8f7831d541be9b8d931678e815320ea4ca1 ";
    u32 expected = 0;
    if (size != sizeof(prefix)-1+9 || !icon_read(h,512)) goto close;
    for (u32 i=0; i<sizeof(prefix)-1; i++) if (ARENA[i] != (u8)prefix[i]) goto close;
    for (u32 i=0; i<8; i++) {
        u8 c = ARENA[sizeof(prefix)-1+i];
        if (c >= '0' && c <= '9') c -= '0';
        else if (c >= 'a' && c <= 'f') c -= 'a'-10;
        else goto close;
        expected = expected*16 + c;
    }
    if (ARENA[size-1] != '\n') goto close;
    FS_OP(G.ctx, h, 0, 0, 7);
    h = icon_open("music.sty", &size);
    if (!h) return;
    if (size != 330240) goto close;
    u32 crc = ~0u, colors = 0;
    for (u32 pos=0; pos<size; pos+=4096) {
        u32 count = size-pos < 4096 ? size-pos : 4096;
        if (!icon_read(h,count)) goto close;
        for (u32 j=0; j<count; j++) {
            crc ^= ARENA[j];
            for (u32 bit=0; bit<8; bit++) crc = (crc>>1) ^ ((0u-(crc&1)) & 0xedb88320u);
        }
        /* Slot 37 is entirely inside this block in the pinned stock resource. */
        if (pos == 0x19000) {
            for (u32 i=0; i<400; i++) {
                u16 color = rd16(ARENA + 0x1cc + 2*i);
                u32 k=0;
                while (k<colors && cache->palette[k]!=color) k++;
                if (k==colors) {
                    if (colors==4) goto close;
                    cache->palette[colors++]=color;
                }
                u32 shift = 2*(i&3);
                if (!shift) cache->indices[i>>2]=0;
                cache->indices[i>>2] |= k<<shift;
            }
        }
    }
    if (~crc == expected) cache->ready = 1;
close:
    FS_OP(G.ctx, h, 0, 0, 7);
}
