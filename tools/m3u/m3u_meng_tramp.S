/* mengine.ap fsel trampolines for active .m3u playback.
 *
 * Linked at 0x7A053338 in the 200-byte zero tail of mengine.ap's fsel
 * bank 0x7A052D00 (file 0x5600, stock size 0x638 -> raised to cover this
 * blob, staying within 0x700). Because these stubs live inside 0x7A052D00
 * (overlay window 0x7A), they can safely call both the stock group-0x7B
 * handlers (0x7B0685F4, 0x7B068000, 0x7B0A8000, 0x7B0E81F8) and our
 * group-0x7B M3U stepper at 0x7B268000 without any overlay window conflict.
 *
 * Four mode-0 pointer slots in 0x7A052D00 are redirected here:
 *   0x7A0530B4 (set_location[0]) -> m3u_setloc_0 | 1
 *   0x7A0530C0 (get_byno[0])     -> m3u_byno_0   | 1
 *   0x7A0530CC (get_prevfile[0]) -> m3u_prev_0   | 1
 *   0x7A0530D8 (get_nextfile[0]) -> m3u_next_0   | 1
 */
#include "m3uplay.h"

#ifdef M3UPLAY_TEST
#define M_VSTATE        M3UPLAY_TEST_VS
#define M_ENG           M3UPLAY_TEST_ENG
#define STOCK_SETLOC    m3u_test_stock_setloc
#define STOCK_NEXT      m3u_test_stock_next
#define STOCK_PREV      m3u_test_stock_prev
#define STOCK_BYNO      m3u_test_stock_byno
#define M3U_STEP        m3u_meng_step
#else
#define M_VSTATE        0xBFC17274
#define M_ENG           0x9FC15F20
#define STOCK_SETLOC    0x7B0685F4
#define STOCK_NEXT      0x7B068000
#define STOCK_PREV      0x7B0A8000
#define STOCK_BYNO      0x7B0E81F8
#define M3U_STEP        0x7B268000
#endif

	.set	noreorder
	.set	mips16
	.text

	.globl	m3u_setloc_0
	.type	m3u_setloc_0, @function
m3u_setloc_0:
	save	0x18, $ra, $s0, $s1
	move	$s0, $a0		/* desc */
	jal	STOCK_SETLOC		/* positions HANDLE on desc, checks ext */
	nop
	move	$s1, $v0		/* ok */
	lw	$a2, .Lvs
	beqz	$s1, .Ldisarm
	lw	$v0, 0($a2)		/* VS->magic */
	lw	$v1, .Lmagic
	cmp	$v0, $v1
	btnez	.Lset_out
	lw	$v0, 8($s0)		/* desc->file_off[0..3] */
	lw	$v1, 0xC($a2)		/* VS->cur_off[0] */
	cmp	$v0, $v1
	btnez	.Ldisarm
	lw	$v0, 0xC($s0)		/* desc->file_off[4..7] */
	lw	$v1, 0x10($a2)		/* VS->cur_off[1] */
	cmp	$v0, $v1
	btnez	.Ldisarm
	/* Match: override folder count/pos with playlist count/pos. */
	lw	$a3, .Leng		/* 0x9FC15F20 */
	lhu	$v0, 6($a2)		/* VS->count */
	lhu	$v1, 4($a2)		/* VS->pos */
	sh	$v0, 6($a3)		/* COUNT (0x9FC15F26) */
	sh	$v1, 4($a3)		/* POS   (0x9FC15F24) */
	b	.Lset_out
.Ldisarm:
	li	$v0, 0
	sw	$v0, 0($a2)		/* VS->magic = 0 */
.Lset_out:
	move	$v0, $s1
	restore	0x18, $ra, $s0, $s1
	jrc	$ra
	.size	m3u_setloc_0, . - m3u_setloc_0

	.globl	m3u_byno_0
	.type	m3u_byno_0, @function
m3u_byno_0:
	li	$a2, 0			/* op = 0: byno ($a1 = 1-based num) */
	b	.Lenter
	.size	m3u_byno_0, . - m3u_byno_0

	.globl	m3u_next_0
	.type	m3u_next_0, @function
m3u_next_0:
	li	$a2, 1			/* op = 1: next */
	b	.Lenter
	.size	m3u_next_0, . - m3u_next_0

	.globl	m3u_prev_0
	.type	m3u_prev_0, @function
m3u_prev_0:
	li	$a2, 2			/* op = 2: prev */
.Lenter:
	save	0x10, $ra
	lw	$v0, .Lvs
	lw	$v0, 0($v0)
	lw	$v1, .Lmagic
	cmp	$v0, $v1
	btnez	.Lstock
	jal	M3U_STEP		/* m3u_meng_step(out, a1, op) */
	nop
	b	.Ldone
.Lstock:
	beqz	$a2, 1f
	cmpi	$a2, 1
	bteqz	2f
	jal	STOCK_PREV
	nop
	b	.Ldone
1:	jal	STOCK_BYNO
	nop
	b	.Ldone
2:	jal	STOCK_NEXT
	nop
.Ldone:
	restore	0x10, $ra
	jrc	$ra
	.size	m3u_prev_0, . - m3u_prev_0

	.balign	4
.Lvs:		.word	M_VSTATE
.Lmagic:	.word	M3UPLAY_MAGIC
.Leng:		.word	M_ENG
