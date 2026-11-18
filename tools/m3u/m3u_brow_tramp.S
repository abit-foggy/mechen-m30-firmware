/* browser.ap mode-0 fsel trampolines for virtual-folder .m3u browsing.
 *
 * Linked at 0x780DB7E0 in the 544-byte verified zero tail of browser.ap's
 * fsel bank 0x780DB200 (file 0x48E0..0x4B00). Bridges window-0x78 fsel
 * wrappers to window-0x48 (m3u_brow.c at 0x485946C0), window-0x40
 * (m3uplay.c at 0x400D4CD0), and stock window-0x71 fsel handlers.
 *
 * Four mode-0 pointer slots in 0x780DB200 are redirected here:
 *   0x780DB5A4 (file 0x46A4, set_location[0]) -> m3u_b_setloc | 1
 *   0x780DB5BC (file 0x46BC, delete[0])       -> m3u_b_del    | 1
 *   0x780DB5C8 (file 0x46C8, get_items[0])    -> m3u_b_items  | 1
 *   0x780DB5D4 (file 0x46D4, enter_dir[0])    -> m3u_b_dirop  | 1
 */
#include "m3uplay.h"

#ifdef M3UPLAY_TEST
#define B_VD            M3UPLAY_TEST_VD
#define B_STOCK_SETLOC  m3u_test_b_stock_setloc
#define B_STOCK_DEL     m3u_test_b_stock_del
#define B_STOCK_ITEMS   m3u_test_b_stock_items
#define B_STOCK_DIROP   m3u_test_b_stock_dirop
#define B_FN_SETLOC     m3u_vdir_setloc
#define B_FN_ITEMS      m3u_vdir_get_items
#define B_FN_DIROP      m3u_vdir_dir_op
#else
#define B_VD            0x9FC15B20
#define B_STOCK_SETLOC  0x71312815
#define B_STOCK_DEL     0x71352501
#define B_STOCK_ITEMS   0x71352821
#define B_STOCK_DIROP   0x713125DD
#define B_FN_SETLOC     M3U_SYM_SETLOC
#define B_FN_ITEMS      M3U_SYM_ITEMS
#define B_FN_DIROP      M3U_SYM_DIROP
#endif

	.set	noreorder
	.set	mips16
	.text

	.globl	m3u_b_setloc
	.type	m3u_b_setloc, @function
m3u_b_setloc:
	save	0x18, $ra, $s0, $s1
	move	$s0, $a0
	move	$s1, $a1
	lw	$v0, .Lfn_setloc
	jalrc	$v0
	lw	$v1, .Lpass
	cmp	$v0, $v1
	btnez	1f
	move	$a0, $s0
	move	$a1, $s1
	lw	$v1, .Lstock_setloc
	restore	0x18, $ra, $s0, $s1
	jrc	$v1
1:	restore	0x18, $ra, $s0, $s1
	jrc	$ra
	.size	m3u_b_setloc, . - m3u_b_setloc

	.globl	m3u_b_del
	.type	m3u_b_del, @function
m3u_b_del:
	lw	$v0, .Lvd
	lw	$v0, 0($v0)
	lw	$v1, .Lvd_magic
	cmp	$v0, $v1
	btnez	1f
	li	$v0, 0
	jrc	$ra
1:	lw	$v0, .Lstock_del
	jrc	$v0
	.size	m3u_b_del, . - m3u_b_del

	.globl	m3u_b_items
	.type	m3u_b_items, @function
m3u_b_items:
	lw	$v0, .Lvd
	lw	$v0, 0($v0)
	lw	$v1, .Lvd_magic
	cmp	$v0, $v1
	btnez	1f
	lw	$v0, .Lfn_items
	jrc	$v0
1:	lw	$v0, .Lstock_items
	jrc	$v0
	.size	m3u_b_items, . - m3u_b_items

	.globl	m3u_b_dirop
	.type	m3u_b_dirop, @function
m3u_b_dirop:
	lw	$v0, .Lvd
	lw	$v0, 0($v0)
	lw	$v1, .Lvd_magic
	cmp	$v0, $v1
	btnez	.Ldirop_stock
	save	0x18, $ra, $s0, $s1
	move	$s0, $a1
	move	$s1, $a2
	lw	$v0, .Lfn_dirop
	jalrc	$v0
	lw	$v1, .Lpass
	cmp	$v0, $v1
	btnez	1f
	li	$a0, 0
	li	$a1, 0
	move	$a2, $s1
	lw	$v1, .Lstock_dirop
	restore	0x18, $ra, $s0, $s1
	jrc	$v1
1:	lw	$v1, .Lroot
	cmp	$v0, $v1
	btnez	2f
	li	$a0, 3
	move	$a1, $s0
	move	$a2, $s1
	lw	$v1, .Lstock_dirop
	restore	0x18, $ra, $s0, $s1
	jrc	$v1
2:	restore	0x18, $ra, $s0, $s1
	jrc	$ra
.Ldirop_stock:
	lw	$v0, .Lstock_dirop
	jrc	$v0
	.size	m3u_b_dirop, . - m3u_b_dirop

	.balign	4
.Lvd:		.word	B_VD
.Lvd_magic:	.word	M3UVD_MAGIC
.Lpass:		.word	0x0000FFFE
.Lroot:		.word	0x0000FFFD
.Lstock_setloc:	.word	B_STOCK_SETLOC
.Lstock_del:	.word	B_STOCK_DEL
.Lstock_items:	.word	B_STOCK_ITEMS
.Lstock_dirop:	.word	B_STOCK_DIROP
.Lfn_setloc:	.word	B_FN_SETLOC
.Lfn_items:	.word	B_FN_ITEMS
.Lfn_dirop:	.word	B_FN_DIROP
