#include "index_mode.h"
typedef unsigned int u32;
typedef unsigned short u16;
#define VM ((int (*)(u32*,u32,u32,u32))0xbfc16585u)
static u32 mode(void)
{
    u32 record=0;
    VM(&record,INDEX_VM_SLOT,sizeof(record),18);
    return record;
}
int index_menu(u16 *title)
{
    title[1]=title[6]=0xffff;
    title[3]=mode()==INDEX_AUTO?223:222;
    ((u32 *)title)[2]=0;
    return 0x8202;
}
static int set_mode(u32 value)
{
    u32 record=value;
    VM(&record,INDEX_VM_SLOT,sizeof(record),19);
    return mode()==value?0x8201:0x8203;
}
int index_manual(void) { return set_mode(INDEX_MANUAL); }
int index_auto(void) { return set_mode(INDEX_AUTO); }
