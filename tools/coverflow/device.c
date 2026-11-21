#include "flow.h"
#define SYS ((u32 (*)(u32,u32,u32,u32))0xbfc16bb1u)
#define FS ((fs_fn)0xbfc16bb5u)
#define STOCK_BLIT ((int (*)(void))0x4805447du)
#define PREPARE ((flow_prepare)FLOW_CACHE_ENTRY)
#define DRAW ((flow_draw)FLOW_DRAW_ENTRY)

struct reader { u32 ctx,file; };
static int load_sector(u32 track,struct flow_tile *tile,void *opaque)
{
    struct reader *r=opaque;
    if (FS(r->ctx,(track-1)*sizeof(*tile),0,r->file,OP_SEEK)<0) return 0;
    return FS(r->ctx,(u32)tile,512,r->file,OP_READ)>0 &&
           FS(r->ctx,(u32)tile+512,512,r->file,OP_READ)>0;
}

static int paint_queue(u32 pack,u32 pos,u32 count)
{
    u16 *buffer=*(u16 *volatile *)0x9fc0bf50u;
    u32 bytes=*(volatile u16 *)0x9fc0bf54u;
    /* First sector holds the LCD scanline. Only the last seven tile slots
     * are used for covers; the separate font cache is outside this buffer. */
    if (!pos || pos>count) return 0;
    if (!buffer || ((u32)buffer&3) || bytes<512+7*sizeof(struct flow_tile)) return -1;
    u16 tracks[7];
    u32 shuffle=*(volatile u8 *)0x9fc15f23u,loop=*(volatile u8 *)0x9fc15f39u;
    u32 key=VS->shuf_key,cursor=VS->shuf_pos;
    ((void (*)(u16 *,u32,u32,u32,u32,u32,u32))FLOW_QUEUE_ENTRY)(
        tracks,pos,count,shuffle,loop,key,cursor);
    /* A separate mounted context keeps menu/engine directory cursors intact. */
    if (SYS(1,0,(u32)"card.drv",10)!=0) return -2;
    int ctx=(signed char)SYS(1,16,0,41);
    int ok=0;
    struct flow_window window;
    if (ctx>=0) {
        u16 name[14];
        name[0]=0xfeff; name[1]='F'; name[9]='.'; name[10]='C';
        name[11]='F'; name[12]='7'; name[13]=0;
        for (unsigned i=0;i<7;i++) {
            unsigned d=(pack>>(4*i))&15;
            name[8-i]=d<10?'0'+d:'A'+d-10;
        }
        FS(ctx,':',0,0,OP_CD);
        struct reader r={ctx,FS(ctx,(u32)name,0,0,OP_OPEN)};
        if (r.file) {
            u32 size=0;
            if (FS(ctx,(u32)&size,r.file,0,OP_SIZE)>=0 && size==count*sizeof(struct flow_tile)) {
                u32 end=bytes & ~511u;
                struct flow_tile *slots=(void *)((u8 *)buffer+end-7*sizeof(*slots));
                ok=PREPARE(slots,&window,tracks,pack,count,load_sector,&r);
            }
            FS(ctx,r.file,0,0,OP_CLOSE);
        }
        SYS(ctx,0,0,42);
    }
    SYS(1,0,0,11);
    if (!ok) return -2;
    if (VS->magic!=M3UPLAY_MAGIC || VS->flow_pack!=pack || VS->pos!=pos ||
        *(volatile u8 *)0x9fc15f23u!=shuffle || *(volatile u8 *)0x9fc15f39u!=loop ||
        VS->count!=count || VS->shuf_key!=key || VS->shuf_pos!=cursor ||
        buffer!=*(u16 *volatile *)0x9fc0bf50u ||
        *(volatile u16 *)0x9fc0bf54u!=bytes) return 0;
    return DRAW(&window,buffer);
}

static void refresh(int stock_art_path)
{
    int result=VS->magic==M3UPLAY_MAGIC?-4:-3;
    if (VS->magic==M3UPLAY_MAGIC && VS->flow_pack)
        result=paint_queue(VS->flow_pack,VS->pos,VS->count);
    if (result>0) return;
    if (stock_art_path && (*(volatile u32 *)0x9fc15418u&4)) STOCK_BLIT();
    /* Diagnostic colors also identify missing browser-to-player state. */
    if (result<=0) {
        u16 *row=*(u16 *volatile *)0x9fc0bf50u;
        int (*region)(struct flow_region *,u32)=*(int (*volatile *)(struct flow_region *,u32))0x9fc0bf98u;
        int (*send)(u32,u32)=*(int (*volatile *)(u32,u32))0x9fc0bf84u;
        if (row && !((u32)row&1) && *(volatile u16 *)0x9fc0bf54u>=384 && region && send) {
            struct flow_region mark={0,28,24,8};
            region(&mark,0);
            u16 color=result==-3?0x07ff:result==-4?0xffff:result==-1?0xffe0:result==-2?0xf81f:0x07e0;
            if (result==-3) {
                if (VS->magic==M3UPLAY_WAITING) color=0xf800;
                else if (VS->handoff==M3U_HANDOFF_MISMATCH) color=0xfd20;
                else if (VS->handoff==M3U_HANDOFF_CLICK) color=0x781f;
                else if (VD->magic==M3UVD_MAGIC && VD->flow_pack) color=0x001f;
            }
            for (unsigned i=0;i<192;i++) row[i]=color;
            send(192,24);
        }
    }
}

void coverflow_refresh(void) { refresh(1); }
void coverflow_bypass(void) { refresh(0); }
