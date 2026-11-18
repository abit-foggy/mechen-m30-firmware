/* Trampoline for the file-row click call in browser.ap.
 *
 * Patch site: bank 0x40D14E00 (file 0x12500), the dispatcher's file-row
 * prompt call at 0x40D15108 (file 0x12808), whose stock `jal 0x4875493C`
 * (bytes b0 1b 4f 52) is replaced by `jal m3uplay_tramp` (bytes 60 18 34 53
 * for link address 0x400D4CD0).
 *
 * At 0x40D15108:
 *   $a0 = arg0 (0x28($s1): mode byte at +0, 0xA4-byte file_location_t at +4)
 *   $a1 = state (0x2C($s1): list_no at +0xE, sel at +0x10, redraw flags +0x14..+0x16)
 *   $s1 = dispatcher frame
 *
 * m3u_file_click(arg0, state) returns:
 *   0x8001 : track clicked inside an open .m3u virtual folder; arg0+4 and VS
 *            are populated -> store 0x8001 into 4($s1) and jump to 0x40D15200.
 *   0xFFFE : ordinary non-.m3u file in a normal folder -> tail-call stock
 *            0x4875493C(arg0, state) (Play/Delete prompt) unchanged.
 *   0xFFFD : empty .m3u or unresolvable track dialog already shown -> set
 *            6($s1) = 1 and return 0 to 0x40D1510E (stores 0 to 4($s1) and
 *            branches to 0x40D15200).
 *   0      : .m3u virtual folder opened (state redraw flags set) -> return 0
 *            to 0x40D1510E (stores 0 to 4($s1) and branches to 0x40D15200).
 */
#ifdef M3UPLAY_TEST
#define M3UPLAY_DONE   M3UPLAY_TEST_DONE
#define M3UPLAY_PROMPT m3u_test_stock_prompt
#else
#define M3UPLAY_DONE   0x40D15201
#define M3UPLAY_PROMPT 0x4875493D
#endif

	.set	noreorder
	.set	mips16
	.text
	.globl	m3uplay_tramp
	.type	m3uplay_tramp, @function
m3uplay_tramp:
	save	0x10, $ra
	jal	m3u_file_click
	nop
	lw	$v1, .Llaunch		/* 0x8001 = launch music.ap */
	cmp	$v0, $v1
	btnez	1f
	sh	$v0, 4($s1)
	lw	$v1, .Ldone
	restore	0x10, $ra
	jrc	$v1
1:	lw	$v1, .Lstock		/* 0xFFFE = ordinary file prompt */
	cmp	$v0, $v1
	btnez	2f
	lw	$a0, 0x28($s1)
	lw	$a1, 0x2C($s1)
	lw	$v1, .Lprompt
	restore	0x10, $ra
	jrc	$v1
2:	lw	$v1, .Lpopup		/* 0xFFFD = dialog shown */
	cmp	$v0, $v1
	btnez	3f
	li	$v0, 1
	sb	$v0, 6($s1)
	li	$v0, 0
3:	restore	0x10, $ra
	jrc	$ra
	.balign	4
.Llaunch:	.word	0x00008001
.Lstock:	.word	0x0000FFFE
.Lpopup:	.word	0x0000FFFD
.Ldone:		.word	M3UPLAY_DONE
.Lprompt:	.word	M3UPLAY_PROMPT
	.size	m3uplay_tramp, . - m3uplay_tramp
