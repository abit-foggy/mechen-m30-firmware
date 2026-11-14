/* M3U selection hook for the stock file browser (Phase C, first hardware
 * candidate).
 *
 * Patch site: browser.ap bank 0x40D14E00, the selected-file wrapper's first
 * instruction at 0x40D15270 (`save 0x38, $ra,$s1`, halfword 0x64d7). The
 * wrapper has exactly one caller — the dispatcher's file branch at
 * 0x40D1503C, which passes (descriptor, list_no-1) and keeps the selected
 * row's file_brow_t pointer at 0($s1) (frame). This hook branches in front
 * of the wrapper, reads the row's 4-byte extension field, and:
 *
 *   M3U / M3U8  -> the stock dialog (0x8000, 3, 0x8018 — the same
 *                  gui_dialog_msg call the stock empty-directory path makes),
 *                  then returns 0, so the dispatcher exits its file branch
 *                  through the clean redraw path. The custom path is
 *                  observable (a dialog ordinary rows never show) and safe
 *                  (nothing reaches the audio decoder).
 *   everything else -> replays the displaced `save 0x38, $ra,$s1` and
 *                  branches into the wrapper's second instruction, so ordinary
 *                  directory and audio selection behave exactly as stock.
 *
 * Registers: at the wrapper's entry only $a0 (descriptor) and $a1 (row
 * index) are live arguments and $s1 holds the dispatcher's frame; $a2/$a3
 * are free, so the check runs on $v0/$v1/$a2/$a3 and $a0/$a1 reach the
 * wrapper intact. MIPS16e's register file has no $t1/$t2.
 *
 * Placement: bank tail +0x54C (stock bytes +0x546..+0x600 are zero; the live
 * content ends at +0x545). Same bank as the wrapper, so every branch is
 * within MIPS16e's range and no overlay window is crossed.
 *
 * The branch back into the wrapper is emitted as a placeholder halfword
 * (BRANCH_SLOT): its target 0x40D15272 is outside this assembly's symbol
 * world, so patch_m3uhook.py encodes it.
 *
 * Known limitation, stock-inherited: the record's ext field is 4 bytes, so a
 * file whose extension is longer than 4 characters (e.g. "x.m3u8x") is
 * truncated by the filesystem to "M3U8" before this code runs — the same
 * truncation the stock classifier would see. Full-extension checking needs
 * the long name, which the record carries as BOM+UTF-16 or 8.3; deferred
 * until virtual-folder opening replaces this dialog.
 *
 * Assembled with the cross toolchain at -Ttext=0x40D1534C; patch_m3uhook.py
 * verifies the stock bytes and the zero tail before writing.
 */
	.set	noreorder
	.set	mips16
	.text
	.globl	m30u_hook
	.type	m30u_hook, @function

m30u_hook:
	/* the selected row's record: cur_file = *(u32*)0($s1) */
	lw	$v0, 0($s1)
	lbu	$v1, 0($v0)		/* ext[0] */
	lbu	$a2, 1($v0)		/* ext[1] */
	lbu	$a3, 2($v0)		/* ext[2] */
	lbu	$v0, 3($v0)		/* ext[3]; the record base is no longer needed */

	/* e0 == 'M' or 'm' */
	cmpi	$v1, 0x4d
	bteqz	1f
	cmpi	$v1, 0x6d
	bteqz	1f
	b	9f
1:	/* e1 == '3' */
	cmpi	$a2, 0x33
	bteqz	2f
	b	9f
2:	/* e2 == 'U' or 'u' */
	cmpi	$a3, 0x55
	bteqz	3f
	cmpi	$a3, 0x75
	bteqz	3f
	b	9f
3:	/* e3 == 0 or ' ' (M3U) or '8' (M3U8) */
	beqz	$v0, 4f
	cmpi	$v0, 0x20
	bteqz	4f
	cmpi	$v0, 0x38
	bteqz	4f
	b	9f

	/* --- the custom path: stock dialog, then a clean exit */
4:	save	8, $ra
	li	$a0, 0x8000
	li	$a1, 3
	li	$a2, 0x8018
	lw	$v0, 6f			/* gui_dialog_msg, from the hook's pool */
	jalr	$v0
	li	$v0, 0			/* the dispatcher's clean redraw exit */
	restore 8, $ra
	jrc	$ra

	/* --- ordinary rows: replay the displaced prologue, enter the wrapper */
9:	save	0x38, $ra, $s1
	.globl	m30u_branch_slot
	.type	m30u_branch_slot, @object
m30u_branch_slot:
	.half	0x0000			/* BRANCH_SLOT: `b 0x40D15272`, encoded by the tool */

	/* the hook's literal pool */
	.balign 4
6:	.word	0x48AD4A2D		/* gui_dialog_msg (stock pool word 0x48ad4a2d & ~1) */

	.size	m30u_hook, . - m30u_hook