/* Link script for the virtual-list PoC harness (tools/scroll/vlist.c).
 * Same layout as tools/scroll/test.ld: harness at 0x400000, stubs at
 * 0x700000/0x700100, test RAM at 0x10000000, and the stock dirlist bank at
 * its real firmware address 0x48714400. */
ENTRY(_start)
SECTIONS
{
    . = 0x00400000;
    .text : { vlist.o(.text .text.startup) }
    .data : { vlist.o(.data .data.* .rodata .rodata.* .sdata .sbss .bss .bss.* COMMON) }
    . = 0x00700000;
    .stubs : { *(.text.stubs) }
    . = 0x00700100;
    .stubs2 : { *(.text.stubs2) }
    . = 0x10000000;
    .testram : { *(.testram) }
    . = 0x48714400;
    .bank : { bank.o(.bankcode) }
    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) }
}