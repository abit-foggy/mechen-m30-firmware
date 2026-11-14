/* QEMU test for the M3U selection hook: runs the ACTUAL patched bytes.
 *
 * The harness places the patched wrapper entry (the 2-byte branch the patch
 * tool writes) at 0x40D15270, the blob at 0x40D1534C, a recording stand-in
 * for gui_dialog_msg at 0x48AD4A2C, and a stand-in for the wrapper's
 * continuation at 0x40D15272 (it replays the stock prologue shape and
 * returns the row-index argument, proving the arguments survive). Each case
 * then calls 0x40D15270 the way the stock dispatcher does — $a0 = descriptor,
 * $a1 = row index, $s1 = the dispatcher frame with the selected row's
 * file_brow_t pointer at 0($s1).
 *
 * Expected: M3U/M3U8 rows (ext M3U+/m3u+/M3U8) take the custom path — the
 * dialog fires with the stock's own (0x8000, 3, 0x8018) and the call returns
 * 0; every other extension reaches the continuation with $a0/$a1 intact and
 * the dialog silent.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

static long sys3(long n, long a, long b, long c)
{
    register long v0 asm("v0") = n, a0 asm("a0") = a, a1 asm("a1") = b, a2 asm("a2") = c, a3 asm("a3");
    asm volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2) : "memory", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "hi", "lo");
    return v0;
}
static char obuf[4096];
static int olen;
static void puts_(const char *s) { while (*s) obuf[olen++] = *s++; }
static void putu(u32 v) { char t[12]; int i = 0; do t[i++] = '0' + v % 10; while (v /= 10); while (i) obuf[olen++] = t[--i]; }
static void putsn(const char *s, u32 n) { while (n--) obuf[olen++] = *s++; }

/* the recording dialog stand-in, at the hook's pool target: entered from
 * MIPS16e context, so it must itself be MIPS16e */
__attribute__((section(".text.dlg"), used, noinline, mips16))
u32 test_dialog(u32 a0, u32 a1, u32 a2)
{
    volatile u32 *rec = (volatile u32 *)0x10000200;
    rec[0]++; rec[1] = a0; rec[2] = a1; rec[3] = a2;
    return 0;
}

/* the wrapper continuation stand-in at 0x40D15272: the stock prologue shape,
 * then return the row index — proving $a0/$a1 arrive intact */
/* the continuation lives in tools/m3u/m3ucont.S */

struct rec { u8 ext[4]; u8 name_len; u8 reserve[3]; const char *name; };

static u32 call_hook(const struct rec *r)
{
    u32 frame[2];
    /* the patched wrapper entry, MIPS16e ISA bit set for the MIPS32 caller */
    u32 (*hook)(u32, u32) = (u32 (*)(u32, u32))0x40D15271u;
    register u32 fp asm("s1");
    u32 v;
    frame[0] = (u32)r;
    frame[1] = 0;
    fp = (u32)frame;
    asm volatile("" : "+r"(fp));
    v = hook(0x9FC155F8u, 7u);
    return v;
}

static u32 fails;

static void expect(const char *name, const struct rec *r, u32 want_dialog, u32 want_ret)
{
    volatile u32 *rec = (volatile u32 *)0x10000200;
    u32 v = call_hook(r);
    if (v != want_ret || rec[0] != want_dialog) {
        fails++;
        puts_("FAIL "); putsn(name, 12);
        puts_(" ret="); putu(v); puts_(" dlg="); putu(rec[0]); puts_("\n");
    }
    rec[0] = 0;
}

/* call the hook body directly (0x40D15351), bypassing the patched entry */
static u32 call_hook_direct(const struct rec *r)
{
    u32 frame[2];
    u32 (*hook)(u32, u32) = (u32 (*)(u32, u32))0x40D15351u;
    register u32 fp asm("s1");
    u32 v;
    frame[0] = (u32)r;
    frame[1] = 0;
    fp = (u32)frame;
    asm volatile("" : "+r"(fp));
    v = hook(0x9FC155F8u, 7u);
    return v;
}

void _start(void)
{
    static const struct rec m3u_sp  = {{'M','3','U',' '}, 7, {0,0,0}, "idk.m3u"};
    static const struct rec m3u_nul = {{'M','3','U',0x00}, 7, {0,0,0}, "idk.m3u"};
    static const struct rec m3u_lc  = {{'m','3','u',' '}, 7, {0,0,0}, "idk.m3u"};
    static const struct rec m3u8    = {{'M','3','U','8'}, 9, {0,0,0}, "idk 2.m3u8"};
    static const struct rec m3u8_lc = {{'m','3','u','8'}, 9, {0,0,0}, "idk 2.m3u8"};
    static const struct rec flac    = {{'F','L','A','C'}, 7, {0,0,0}, "Track A.flac"};
    static const struct rec mp3     = {{'M','P','3',' '}, 5, {0,0,0}, "old.mp3"};
    static const struct rec m3ux    = {{'M','3','U','X'}, 6, {0,0,0}, "x.m3ux"};

    expect("M3U space-pad", &m3u_sp, 1, 0);
    expect("M3U nul-pad   ", &m3u_nul, 1, 0);
    expect("m3u lower     ", &m3u_lc, 1, 0);
    expect("M3U8          ", &m3u8, 1, 0);
    expect("m3u8 lower    ", &m3u8_lc, 1, 0);
    expect("FLAC passthru ", &flac, 0, 7);
    expect("MP3 passthru  ", &mp3, 0, 7);
    expect("M3UX no-match ", &m3ux, 0, 7);

    /* byte-class isolation: only ext[0] varies; a matching e0 must reach the
     * dialog path (ret 0), anything else must pass through */
    {
        static const struct rec cM = {{'M','X','X','X'}, 1, {0,0,0}, "x"};
        static const struct rec cMl = {{'m','X','X','X'}, 1, {0,0,0}, "x"};
        static const struct rec cX = {{'X','3','U',' '}, 1, {0,0,0}, "x"};
        volatile u32 *rec = (volatile u32 *)0x10000200;
        u32 rM = call_hook_direct(&cM), rMl = call_hook_direct(&cMl), rX = call_hook_direct(&cX);
        puts_("ISO M ret="); putu(rM); puts_(" m ret="); putu(rMl);
        puts_(" X ret="); putu(rX); puts_(" rec="); putu((u32)&cM); puts_("\n");
        rec[0] = 0;
    }

    /* the dialog stand-in saw exactly the stock's argument triple */
    {
        volatile u32 *rec = (volatile u32 *)0x10000200;
        rec[0] = 0;
        call_hook(&m3u_sp);
        if (rec[1] != 0x8000 || rec[2] != 3 || rec[3] != 0x8018) {
            fails++;
            puts_("FAIL dialog args\n");
        }
    }

    puts_(fails ? "ALL FAIL\n" : "ALL PASS\n");
    puts_("hook test done, failures "); putu(fails); puts_("\n");
    sys3(4004, 1, (long)obuf, olen);
    sys3(4001, fails ? 1 : 0, 0, 0);
    for (;;) ;
}