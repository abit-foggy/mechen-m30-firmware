/* Offsets relative to browser bank 0x40D14E00. Only the conditional
 * branch and the new code at gate are copied into the firmware. */
.set noreorder
.set mips16
.text
.org 0x2fc
.insn
beqz $v0, gate
.org 0x300
file_click:
    nop
.org 0x400
stock_exit:
    nop
.org 0x5a0
gate:
    lw $v0, 0($s1)       /* stock saved the selected row at 0x40D15020 */
    lbu $v1, 0($v0)
    li $a2, 32
    or $v1, $a2
    cmpi $v1, 109
    btnez stock_exit
    lbu $v1, 1($v0)
    cmpi $v1, 51
    btnez stock_exit
    lbu $v1, 2($v0)
    or $v1, $a2
    cmpi $v1, 117
    btnez stock_exit
    lbu $v1, 3($v0)
    beqz $v1, file_click
    cmpi $v1, 32
    bteqz file_click
    cmpi $v1, 56
    bteqz file_click
    b stock_exit
