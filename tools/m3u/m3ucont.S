/* The wrapper-continuation stand-in for the QEMU hook test — hand-written
 * MIPS16e because it must undo exactly the hook's replayed
 * `save 0x38, $ra,$s1` (the real wrapper does this itself when it completes;
 * the stand-in returns the row index in its place).
 */
	.set	noreorder
	.set	mips16
	.text
	.globl	test_cont
	.type	test_cont, @function
test_cont:
	move	$v0, $a1		/* the stand-in "result" */
	restore	0x38, $ra, $s1		/* undo the hook's replayed prologue */
	jrc	$ra
	.size	test_cont, . - test_cont
