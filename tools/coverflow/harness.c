/* QEMU user-mode fixture for the packed music.ap code. Only LCD, VFS,
 * system services and their globals are replaced by the test loader. */
#include "flow.h"
extern u8 pack_start[],pack_end[];
extern void run_refresh(u32 artwork_dirty);
#define SECTION(s) __attribute__((section(s),used))
volatile struct vstate shared SECTION(".shared");
u8 hardware[0x20000] SECTION(".hardware");
#define REG(type,offset) (*(type *)(hardware+(offset)))
static u16 lcd[4096], frame[150][150];
static unsigned line, reads, stock, opened, mounts, installs, selected, failure;
static u16 expected_marker;
static int capture, metadata_status, marker, marked, missing;
static int write_out(const void *p,u32 size)
{
    register u32 v0 asm("$2")=4004;
    register u32 a0 asm("$4")=1;
    register const void *a1 asm("$5")=p;
    register u32 a2 asm("$6")=size;
    asm volatile("syscall":"+r"(v0):"r"(a0),"r"(a1),"r"(a2):"memory","$7");
    return v0;
}
static void check(int yes) { if (!yes) failure++; }
u32 SECTION(".sysmock") sys_mock(u32 a,u32 b,u32 c,u32 op)
{
    (void)a;(void)b;(void)c;
    if (op==10) installs++;
    else if (op==11) installs--;
    else if (op==41) {mounts++;return 2;}
    else if (op==42) mounts--;
    else failure++;
    return 0;
}
long SECTION(".fsmock") fs_mock(u32 ctx,u32 a,u32 b,u32 c,u32 op)
{
    check(ctx==2 && mounts==1 && installs==1);
    if (op==OP_CD) return a==':';
    if (op==OP_OPEN) {
        u16 *name=(u16 *)a;
        u32 pack=0;
        for (int i=2;i<9;i++)
            pack=(pack<<4)|(name[i]<='9'?name[i]-'0':name[i]-'A'+10);
        check(name[0]==0xfeff && name[1]=='F' && name[9]=='.' && name[10]=='C' &&
              name[11]=='F' && name[12]=='7' && !name[13] && pack==shared.flow_pack);
        if (missing) return 0;
        opened++;return 3;
    }
    if (op==OP_CLOSE) {check(a==3);opened--;return 1;}
    if (op==OP_SIZE) {check(b==3);*(u32 *)a=pack_end-pack_start;return metadata_status;}
    if (op==OP_SEEK) {check(c==3 && !(a%1024));selected=a;return metadata_status;}
    if (op==OP_READ) {
        check(c==3 && opened==1 && b==512);
        if (b!=512) return 0;
        if (selected+512>(u32)(pack_end-pack_start)) return 0;
        u32 *src=(u32 *)(pack_start+selected),*dst=(u32 *)a;
        for (int i=0;i<128;i++) dst[i]=src[i];
        selected+=512;
        if (!(selected%1024)) reads++;
        return 1;
    }
    failure++;return 0;
}
u32 SECTION(".stockmock") stock_mock(void) { stock++;return 0; }
static int region(struct flow_region *r,u32 mode)
{
    marker=r->width==24;
    if (marker) {check(!mode && !r->x && r->y==28 && r->height==8);return 1;}
    check(!mode && r->x==0 && r->y==28 && r->width==150 && r->height==150);
    line=0;return 1;
}
static int send(u32 n,u32 width)
{
    if (marker) {
        check(n==192 && width==24);
        for (unsigned i=0;i<192;i++) check(lcd[i]==expected_marker);
        marked++;return 1;
    }
    check(n==150 && width==150 && line<150);
    if (line>=150) return 0;
    if (capture) for (unsigned i=0;i<150;i++) frame[line][i]=lcd[i];
    line++;return 1;
}
void _start(void)
{
    const struct flow_tile *first=(const void *)pack_start;
    shared.count=first->count; shared.flow_pack=first->pack; shared.pos=4;
    REG(u32,0xbf50)=(u32)lcd;
    REG(u16,0xbf54)=sizeof(lcd);
    REG(u32,0xbf84)=(u32)send;
    REG(u32,0xbf98)=(u32)region;
    REG(u32,0x15418)=4;
    expected_marker=0x07ff;
    run_refresh(8);check(stock==1 && !reads);
    shared.magic=M3UPLAY_WAITING;expected_marker=0xf800;
    run_refresh(0);
    shared.magic=0;shared.handoff=M3U_HANDOFF_MISMATCH;expected_marker=0xfd20;
    run_refresh(0);
    shared.handoff=M3U_HANDOFF_CLICK;expected_marker=0x781f;
    run_refresh(0);
    shared.handoff=0;REG(u32,0x15b20)=M3UVD_MAGIC;
    REG(u32,0x15bb0)=first->pack;expected_marker=0x001f;
    run_refresh(0);check(marked==5 && !reads);
    expected_marker=0xffff;
    shared.magic=M3UPLAY_MAGIC;shared.flow_pack=0;
    run_refresh(0);check(stock==1 && !reads && marked==6);
    marked=0;shared.flow_pack=first->pack;capture=1;
    run_refresh(0);check(stock==1 && reads==7 && line==150);
    /* Check the actual visible slots against independent textured samples. */
    static const int xs[]={6,24,75,115,144}, left[]={0,13,36,101,126}, w[]={24,36,78,36,24};
    for (int i=0;i<5;i++) {
        const struct flow_tile *tile=first+i+1; /* centre track 4 */
        int dx=xs[i]-left[i],t=i<2?w[i]-1-dx:dx;
        int inset=i==2?0:7+t*9/w[i]+((i==0 || i==4)?8:0);
        int ty=(60-27-inset)*40/(78-2*inset),tx=dx*40/w[i];
        int index=40*ty+tx,base=(ty>=20?32:0)+(tx>=20?16:0);
        int byte=tile->pixels[index/2];
        int color=tile->palette[base+((index&1)?byte>>4:byte&15)];
        check(frame[60][xs[i]]==(i==2?color:(color&0xf7de)>>1));
    }
    capture=0; metadata_status=1; shared.pos=5;
    run_refresh(8);check(reads==8 && line==150);
    shared.pos=4;run_refresh(8);check(reads==9);
    shared.pos=1;run_refresh(8);check(reads==9 && line==150);
    expected_marker=0xffe0;REG(u16,0xbf54)=1024;
    run_refresh(8);check(stock==2 && reads==9 && marked==1);
    REG(u32,0x15418)=0;
    run_refresh(8);check(stock==2 && !opened && !installs && !mounts);
    expected_marker=0xf81f;missing=1;REG(u16,0xbf54)=sizeof(lcd);
    run_refresh(8);check(marked==3 && !opened && !installs && !mounts);
    if (!failure) write_out(frame,sizeof(frame));
    register u32 v0 asm("$2")=4001;
    register u32 a0 asm("$4")=failure?1:0;
    asm volatile("syscall"::"r"(v0),"r"(a0));
    __builtin_unreachable();
}
