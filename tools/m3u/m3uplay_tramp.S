/* Trampoline for the path-B classify call in browser.ap.
 *
 * Patch site: bank 0x40D14E00 (file 0x12500), the dispatcher's file branch
 * at 0x40D15194 (file 0x12894), whose stock `jal 0x40D14E00` (bytes
 * 81 1a 80 53) is replaced by `jal m3uplay_tramp` (bytes 60 18 34 53 for
 * the link address 0x400D4CD0).
 *
 * At the call site:
 *   $a0 = selected row (ext[4] at +0)
 *   $s1 = dispatcher's frame:
 *     0x28($s1) = arg0 (mode byte at +0, 0xA4-byte file_location_t at +4)
 *     0x2C($s1) = browser state (list_no = u16[state + 0xE])
 *   desc = 0x9FC155F8 (count = u16[desc + 2])
 *
 * m3uplay_click(row, list_no - count, arg0) returns:
 *   0x8001 : a .m3u/.m3u8 playlist was armed and arg0+4 populated with the
 *            first track's file_location_t; write 0x8001 into 4($s1) and
 *            jump straight to loc_40D15200 (skipping 0x780DB2F8 so stock
 *            code does not overwrite arg0+4 with the .m3u's own location).
 *   0..5   : ordinary file or fallback class; return to 0x40D15198 so the
 *            stock dispatcher proceeds unchanged.
 */
#ifdef M3UPLAY_TEST
#define M3UPLAY_DESC M3UPLAY_TEST_DESC
#define M3UPLAY_DONE M3UPLAY_TEST_DONE
#else
#define M3UPLAY_DESC 0x9FC155F8
#define M3UPLAY_DONE 0x40D15201
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
	lw	$v0, .Ldesc		/* desc */
	lhu	$v1, 2($v0)		/* count */
	subu	$a1, $a1, $v1		/* idx = list_no - count */
	lw	$a2, 0x28($s1)		/* arg0 */
	move	$a0, $s0
	jal	m3uplay_click
	nop
	lw	$v1, .Llaunch		/* 0x8001 = launch with pre-filled desc */
	cmp	$v0, $v1
	btnez	1f
	sh	$v0, 4($s1)		/* 4($s1) = 0x8001 */
	lw	$v1, .Ldone		/* loc_40D15200 | 1 */
	restore	0x18, $ra, $s0
	jrc	$v1
1:	restore	0x18, $ra, $s0
	jrc	$ra
	.balign	4
.Ldesc:		.word	M3UPLAY_DESC
.Llaunch:	.word	0x00008001
.Ldone:		.word	M3UPLAY_DONE
	.size	m3uplay_tramp, . - m3uplay_tramp
