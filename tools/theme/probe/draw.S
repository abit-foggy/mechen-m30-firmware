/* Stock MIPS16e code with its external literal-pool pointers rebound for
 * the Linux user-mode harness. Build from the unpacked driver's directory. */
.text
.balign 4
.globl picture_box
picture_box:
.incbin "drv_ui.drv", 0xde00, 0x110
.word app_resource, common_resource, resource_io, show_picture+1

.balign 4
show_picture:
.incbin "drv_ui.drv", 0x3ac, 0x5c
.word common_resource, app_resource, resource_io, draw_callback

.balign 4
.globl bitmap_transfer
bitmap_transfer:
.incbin "drv_ui.drv", 0x418, 0x9c
.word buffer_ptr, screen, region_callback, chunk_size, resource_io, dma_callback

.data
.globl picture_entry, stock_transfer
picture_entry: .word picture_box+1
stock_transfer: .word bitmap_transfer+1
.text
.set noreorder
.globl _start
_start:
    lw $a0, 0($sp)
    addiu $a1, $sp, 4
    addiu $sp, $sp, -24
    jal run
    nop
    move $a0, $v0
    li $v0, 4001
    syscall

/* Linux o32 raw syscall(number, arg1, arg2, arg3). */
.globl linux_call
linux_call:
    move $v0, $a0
    move $a0, $a1
    move $a1, $a2
    move $a2, $a3
    syscall
    beqz $a3, 1f
    nop
    li $v0, -1
1:  jr $ra
    nop
