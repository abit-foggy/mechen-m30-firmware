"""Exercise the installed decision paths on QEMU's 24Kc with a mock VM store."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

fw=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    # When a stock continuation is reached return 0/1 to the harness.
    # For the event handler return its actual dispatch result unchanged.
    for name,member,base,hook,allow,skip,gate in [
        ('boot','config.ap',0x1c00,0x1e0c,0x1e0e,0x1e28,0x2210),
        ('usb','udisk.ap',0x1500,0x1908,0x190a,0x191a,0x1a10),
        ('card','mainmenu.ap',0x21d00,0x21dc8,0x220e2,0x21dd2,0x22200),
    ]:
        d=(fw/member).read_bytes()
        b=bytearray(d[base:base+0x800])
        entry=hook-base-2
        b[entry:entry+2]=bytes.fromhex('4467') # move v0,a0
        if name=='card':
            b[allow-base:allow-base+2]=bytes.fromhex('a0e8')
            # Non-insertion falls through to stock's default handler.
            b[skip-base:skip-base+4]=bytes.fromhex('006aa0e8')
        else:
            for pc,ret in ((allow,1),(skip,0)):
                b[pc-base:pc-base+4]=bytes((ret,0x6a,0xa0,0xe8))
        off,size,addr=struct.unpack_from('<III',d,8)
        syscall=addr+d[off:off+size].index(bytes.fromhex('0f6b05e8'))+1
        sub=b[gate-base:gate-base+100]
        ptr=struct.pack('<I',syscall)
        assert sub.count(ptr)==1
        vm=gate-base+sub.index(ptr)
        (root/name).write_bytes(b)
        with (root/'banks.S').open('a') as asm:
            print(f'.section .text\n.balign 4\nbank_{name}:\n.incbin "{name}",0,{vm}\n.word vm\n.incbin "{name}",{vm+4}\n.globl call_{name}\n.set call_{name},bank_{name}+{entry+1}',file=asm)
    (root/'test.c').write_text(r"""
typedef unsigned u32;
static u32 record,reads;
int vm(u32 *buf,u32 key,u32 len,u32 op) {
    if(key!=0x7e00 || len!=4 || op!=18) return -1;
    ++reads;
    *buf=record;
    return 0;
}
extern char call_boot[],call_usb[],call_card[];
int test(void) {
    char *cases[]={call_boot,call_usb,call_card};
    u32 modes[]={0,0x5844494d,0x58444941,0xffffffff};
    for(unsigned i=0;i<3;i++) {
        int (*run)(u32)=(void *)cases[i];
        for(unsigned j=0;j<4;j++) for(unsigned k=0;k<2;k++) {
            reads=0;
            record=modes[j];
            int want=k && j==2 ? (i==2?0x861c:1):0;
            if(run(i==2?(k?0xb0:0xb1):k)!=want || reads!=k) return i+1;
        }
    }
    return 0;
}
""")
    with (root/'banks.S').open('a') as asm:
        print('.set noreorder\n.globl _start\n.balign 4\n_start:\njal test\nnop\nmove $4,$2\nli $2,4001\nsyscall',file=asm)
    subprocess.run([os.getenv('CROSS','mips64-linux-gnu-')+'gcc','-EL','-mabi=32','-march=mips32r2','-G0',
                    '-mno-abicalls','-fno-pic','-ffreestanding','-nostdlib','-static','-Wl,-e,_start',
                    '-O1','test.c','banks.S','-o','test'],cwd=root,check=True)
    subprocess.run([os.getenv('QEMU','qemu-mipsel-static'),'-cpu','24Kc','./test'],cwd=root,check=True)
    print('PASS: 24 MIPS policy cases across config boot, USB disconnect, and card events')
