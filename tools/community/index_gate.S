#include "index_mode.h"
.set mips16
.set noreorder
.text
.align 2
.globl gate
.ent gate
gate:
#ifndef INSERT_EVENT
    beqz $2,skip
#endif
    save 40,$ra
    sw $4,16($sp)
    sw $5,20($sp)
    sw $6,24($sp)
    sw $7,28($sp)
    li $2,0
    sw $2,32($sp)
    addiu $4,$sp,32
    li $5,INDEX_VM_SLOT
    li $6,4
    li $7,18
    lw $2,vm_entry
    jalrc $2
    lw $2,32($sp)
    lw $3,auto_magic
    xor $2,$3
    lw $4,16($sp)
    lw $5,20($sp)
    lw $6,24($sp)
    lw $7,28($sp)
    restore 40,$ra
    bnez $2,skip
#ifdef INSERT_EVENT
    li $2,0x861c
#endif
.globl allowed
allowed:
    nop /* installer emits branch to stock automatic path */
skip:
#ifdef INSERT_EVENT
    li $2,0
#endif
.globl suppressed
suppressed:
    nop /* installer emits branch to stock skip path */
.align 2
vm_entry: .word 0xfaceca11
auto_magic: .word INDEX_AUTO
.end gate
