/* Trampoline for the path-B classify call in browser.ap (Phase D/E).
 *
 * Patch site: bank 0x40D14E00 (file 0x12500), the dispatcher's file branch
 * at 0x40D15194 (file 0x12894), whose stock `jal 0x40D14E00` (bytes
 * 81 1a 80 53) is replaced by `jal m3uplay_tramp` (bytes 60 18 34 53 for
 * the link address 0x400D4CD0, produced by the cross assembler).
 *
 * At the call site $a0 = the selected row (ext[4] at +0) and $s1 = the
 * dispatcher's frame; the row's dir index is list_no - count with
 * state = 0x2C($s1), list_no = u16[state+0xE], desc = 0x9FC155F8,
 * count = u16[desc+2] - the same values the dispatcher recomputes after the
 * call at 0x40D151AA. The trampoline computes idx, calls the C handler and
 * returns its class in $v0; the dispatcher then proceeds exactly as stock
 * (status lookup, engine launch at 0x40D151AA-0x40D151CA for class 0).
 *
 * $t8/$t9 are dead at the call site (the dispatcher writes $t8 right after
 * it), $s0/$s1 are live, so the trampoline saves only $ra/$s0 and reads $s1
 * before the call (the C handler preserves it as callee-saved).
 *
 * The blob links at 0x400D4CD0 (bank 0x400D4C00 zero tail, region 0x4 - the
 * only free region-0x4 tail big enough, and direct jal from 0x40D15194 can
 * only reach region 0x4). patch_m3uplay.py asserts all of this.
 *
 * Assembled with -x assembler-with-cpp; M3UPLAY_TEST remaps the desc pool
 * word for the QEMU harness.
 */
#ifdef M3UPLAY_TEST
#define M3UPLAY_DESC M3UPLAY_TEST_DESC
#else
#define M3UPLAY_DESC 0x9FC155F8
#endif

	.set	noreorder
	.set	mips16
	.text
	.globl	m3uplay_tramp
	.type	m3uplay_tramp, @function
m3uplay_tramp:
	save	0x18, $ra, $s0
	move	$s0, $a0		/* row */
	lw	$a1, 0x2C($s1)		/* state */
	lhu	$a1, 0xE($a1)		/* list_no */
	lw	$v0, 1f			/* desc */
	lhu	$v1, 2($v0)		/* count */
	subu	$a1, $a1, $v1		/* idx = list_no - count */
	move	$a0, $s0
	jal	m3uplay_click
	nop
	restore	0x18, $ra, $s0
	jrc	$ra
	.balign	4
1:	.word	M3UPLAY_DESC		/* 0x9FC155F8 (test: M3UPLAY_TEST_DESC) */
	.size	m3uplay_tramp, . - m3uplay_tramp
