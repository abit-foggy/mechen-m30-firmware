/* The stock menulist supports one runtime string. Keep that row's text
 * in Settings BSS so it survives overlay switches and asynchronous draws. */
#ifndef PICKER_FIXTURE
typedef unsigned int u32;
typedef unsigned short u16;
#define FS ((u32 (*)(u32,u32,u32,u32,u32))0xbfc1658du)
#define CTX (*(volatile u32 *)0x9fc1550cu)
#define APPLY ((int (*)(const char *))(PICK_APPLY|1u))
#endif
struct discovery {
    char id[9];
    char label[16];
};
#ifndef PICKER_FIXTURE
#define STATE ((struct discovery *)0x9fc158b4u)
#else
static struct discovery discovery_fixture;
#define STATE (&discovery_fixture)
#define APPLY choose
#endif
static int compare_id(const char *a,const char *b)
{
    while (*a && *a==*b) { a++; b++; }
    return (unsigned char)*a-(unsigned char)*b;
}
static void copy_id(char *dst,const char *src)
{
    while ((*dst++=*src++)) {}
}
static int open_themes(void)
{
    static const u16 path[]={0xfeff,'t','h','e','m','e','s',0};
    return CTX!=~0u && FS(CTX,':',0,0,0) && FS(CTX,'/',(u32)path,0,0);
}
static int folder_id(char *id)
{
    u16 path[12]={0};
    if (!FS(CTX,(u32)path,12,0,2) || path[0]!=0xfeff) return 0;
    for (unsigned i=0;i<=8;i++) {
        u16 c=path[i+1];
        if (!c) { id[i]=0; return i!=0 && compare_id(id,"stock")!=0; }
        if (c>='A' && c<='Z') c+='a'-'A';
        if (i==8 || (!(c>='a' && c<='z') && !(i && ((c>='0' && c<='9') || c=='_')))) return 0;
        id[i]=(char)c;
    }
    return 0;
}
static int file_size(const u16 *path,u32 expected)
{
    u32 h=FS(CTX,(u32)path,0,0,5), size=0;
    if (!h) return 0;
    FS(CTX,(u32)&size,h,0,9);
    FS(CTX,h,0,0,7);
    return size==expected;
}
static int installed(const char *id)
{
    static const u16 cfg[]={0xfeff,'t','h','e','m','e','.','c','f','g',0};
    static const u16 sty[]={0xfeff,'m','u','s','i','c','.','s','t','y',0};
    u16 name[10], *p=name;
    *p++=0xfeff;
    while (*id) *p++=*id++;
    *p=0;
    return FS(CTX,'/',(u32)name,0,0) && file_size(cfg,95) && file_size(sty,330240);
}
/* Each step takes the least ID after the cursor. This makes enumeration
 * independent of FAT ordering and avoids allocating a fixed folder table. */
static int advance(void)
{
    while (open_themes()) {
        char best[9]={0}, candidate[9];
        for (u32 cmd=0x82;FS(CTX,cmd,0,1,1);cmd=0x80) {
            if (folder_id(candidate) && compare_id(candidate,STATE->id)>0 &&
                (!best[0] || compare_id(candidate,best)<0)) copy_id(best,candidate);
        }
        if (!best[0]) break;
        copy_id(STATE->id,best);
        if (installed(best)) return 1;
    }
    STATE->id[0]=0;
    return 0;
}
static void display_id(void)
{
    const char *s=STATE->id[0]?STATE->id:"No SD themes";
    /* Runtime menu text uses the current language byte encoding. */
    copy_id(STATE->label,s);
    if (CTX!=~0u) FS(CTX,':',0,0,0);
}
int theme_menu(u16 *title)
{
    STATE->id[0]=0;
    advance();
    display_id();
    title[1]=title[3]=0xffff;
    title[6]=166;
    ((u32 *)title)[2]=(u32)STATE->label;
    return 0x8202;
}
int theme_next(void)
{
    if (!advance()) advance();
    display_id();
    return 0x8014;
}
int theme_apply(void)
{
    return STATE->id[0]?APPLY(STATE->id):0x8014;
}
