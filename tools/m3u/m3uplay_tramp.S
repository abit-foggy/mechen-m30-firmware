/* Trampoline for the file-row click call in browser.ap.
 *
 * Linked at 0x485946C0 (start of m3u_brow.bin in bank 0x48594400's verified
 * zero tail, overlay window 0x48 — completely separate from window 0x40 so
 * 0x40CD4C00..0x40CD4E00 row_names[0..6] and 0x40D14E00 are NEVER overwritten!).
 *
 * Patch site: bank 0x40D14E00 (file 0x12500), the dispatcher's file-row
 * prompt call at 0x40D15108 (file 0x12808), whose stock `jal 0x4875493C`
 * (bytes b0 1b 4f 52) is replaced by `jal m3uplay_tramp` (bytes d0 1a b0 51
 * for link address 0x485946C0).
 *
 * m3u_file_click(arg0, state) (in bank 0x71252500, window 0x71) returns:
 *   0x8001 : track clicked inside an open .m3u virtual folder -> store 0x8001
 *            into 4($s1) and jump to 0x40D15200.
 *   0xFFFE : ordinary non-.m3u file in a normal folder -> tail-jump to stock
 *            0x4875493C(arg0, state) (window 0x48, returns directly to $ra in
 *            window 0x40).
 *   0x8018 : empty .m3u -> tail-jump to 0x40D150BC ("Empty folder!" dialog).
 *   0x8019 : unresolvable track -> tail-jump to 0x40D151CE ("File format not
 *            supported!" dialog).
 *   0      : .m3u virtual folder opened (state redraw flags set) -> return 0
 *            to 0x40D1510E (stores 0 to 4($s1) and branches to 0x40D15200).
 */
#ifdef M3UPLAY_TEST
#define M3UPLAY_CLICK  m3u_file_click
#define M3UPLAY_DONE   M3UPLAY_TEST_DONE
#define M3UPLAY_EMPTY  M3UPLAY_TEST_EMPTY
#define M3UPLAY_BADFMT M3UPLAY_TEST_BADFMT
#define M3UPLAY_PROMPT m3u_test_stock_prompt
#else
#define M3UPLAY_CLICK  M3U_SYM_CLICK
#define M3UPLAY_DONE   0x40D15201
#define M3UPLAY_EMPTY  0x40D150BD
#define M3UPLAY_BADFMT 0x40D151CF
#define M3UPLAY_PROMPT 0x4875493D
#endif

	.set	noreorder
	.set	mips16
	.text
	.globl	m3uplay_tramp
	.type	m3uplay_tramp, @function
m3uplay_tramp:
	save	0x10, $ra
	lw	$v0, .Lclick
	jalrc	$v0
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
2:	lw	$v1, .Lempty		/* 0x8018 = Empty folder dialog */
	cmp	$v0, $v1
	btnez	3f
	lw	$v1, .Lempty_dst
	restore	0x10, $ra
	jrc	$v1
3:	lw	$v1, .Lbadfmt		/* 0x8019 = Unsupported format dialog */
	cmp	$v0, $v1
	btnez	4f
	lw	$v1, .Lbadfmt_dst
	restore	0x10, $ra
	jrc	$v1
4:	restore	0x10, $ra
	jrc	$ra
	.balign	4
.Lclick:	.word	M3UPLAY_CLICK
.Llaunch:	.word	0x00008001
.Lstock:	.word	0x0000FFFE
.Lempty:	.word	0x00008018
.Lbadfmt:	.word	0x00008019
.Ldone:		.word	M3UPLAY_DONE
.Lempty_dst:	.word	M3UPLAY_EMPTY
.Lbadfmt_dst:	.word	M3UPLAY_BADFMT
.Lprompt:	.word	M3UPLAY_PROMPT
	.size	m3uplay_tramp, . - m3uplay_tramp
