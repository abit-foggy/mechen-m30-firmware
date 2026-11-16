/* Test for the M3U play-on-click hook. Dual-mode:
 *
 *   host (default gcc):  runs the scenario logic against m3uplay.c/m3u.c
 *                        compiled natively with -DM3UPLAY_TEST; clicks call
 *                        m3uplay_click directly (the trampoline's index math
 *                        is covered by the QEMU mode below).
 *   MIPS (-D__mips__):   the QEMU build: the actual blob (m3uplay_tramp.S +
 *                        m3uplay.c + m3u.c) links at 0x400D4CD0 and the
 *                        patched click-site jal (60 18 34 53) at 0x40D15194,
 *                        so clicks execute the real patched bytes. Fixed
 *                        firmware addresses are remapped to test RAM:
 *                        0x10001000 vstate, 0x10001100 REC_G,
 *                        0x10001104 CTXW, 0x10001108 desc.
 *
 * Mocks: test_fs implements the kernel fs ABI over an in-memory playlist
 * (op 1 returns fake dir records; op 5/9/0xB/0xD/7 serve the .m3u file),
 * test_classify records calls and returns 2, and test_fetch mimics the
 * stock wrapper 0x780DB460 (call the hooked stub, publish the result to
 * REC_G, return (ptr != 0)).
 */
#ifdef __mips__
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
static long sys3(long n, long a, long b, long c)
{
    register long v0 asm("v0") = n, a0 asm("a0") = a, a1 asm("a1") = b, a2 asm("a2") = c, a3 asm("a3");
    asm volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2) : "memory", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "hi", "lo");
    return v0;
}
static char obuf[8192];
static int olen;
static void puts_(const char *s) { while (*s) obuf[olen++] = *s++; }
static void putu(u32 v) { char t[12]; int i = 0; do t[i++] = '0' + v % 10; while (v /= 10); while (i) obuf[olen++] = t[--i]; }
static void flush_out(void) { sys3(4004, 1, (long)obuf, olen); }
static void done(int rc) { sys3(4001, rc, 0, 0); for (;;) ; }
#define T_VSTATE 0x10001000u
#define T_REC_G  0x10001100u
#define T_CTXW   0x10001104u
#define T_DESC   0x10001108u
#define T_FSLOG  0x10001110u
#else
#include <stdio.h>
#include <stdlib.h>
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
static void puts_(const char *s) { fputs(s, stdout); }
static void putu(u32 v) { printf("%u", v); }
static void flush_out(void) { fflush(stdout); }
static void done(int rc) { exit(rc); }
#endif

#include "m3uplay.h"

/* the pointers the test build of m3uplay.c uses */
volatile struct vstate *test_vs;
volatile u32 *test_rec_g;
volatile u32 *test_ctxw;

/* the blob's entry point */
extern u32 m3uplay_click(u32, u32);
extern u32 m3uplay_fetch(u32, u32, u32, u32, u32);

#ifdef __mips__
static u32 (*volatile entryp)(u32);
static u32 (*volatile fetchp)(u32, u32, u32, u32, u32);
#endif

/* ---- mock kernel fs ----------------------------------------------------- */

#ifdef __mips__
struct fslog { u32 op, a1, a2, a3; };
static volatile struct fslog *fslog = (volatile struct fslog *)T_FSLOG;
#else
struct fslog { u32 op, a1, a2, a3; };
static struct fslog fslog_[64];
static volatile struct fslog *fslog = fslog_;
#endif
static u32 fs_n;
static u32 kpos;
static int playlist_present = 1;

static const char pl_text[] =
    "#EXTM3U\r\n"
    "#EXTINF:123,Song One\r\n"
    "../Music/song one.mp3\r\n"
    "song2.flac\r\n";
#define PL_SIZE ((u32)sizeof pl_text - 1)
static const char pl_empty[] = "#EXTM3U\r\n#EXTINF:1,x\r\n";

static u8 name_idk[32];    /* BOM+UTF-16LE "idk.m3u" + double NUL */
static u8 name_empty[32];  /* BOM+UTF-16LE "empty.m3u" */
static u8 name_mp3[32];    /* BOM+UTF-16LE "x.mp3" */

static void mkname16(u8 *d, const char *s)
{
    u32 i;
    d[0] = 0xFF; d[1] = 0xFE;
    for (i = 0; s[i]; i++) { d[2 + 2 * i] = (u8)s[i]; d[3 + 2 * i] = 0; }
    d[2 + 2 * i] = 0; d[3 + 2 * i] = 0; d[4 + 2 * i] = 0; d[5 + 2 * i] = 0;
}
static int name_eq(const volatile u8 *a, const u8 *b)
{
    u32 i;
    for (i = 0; i < 32; i++) if (a[i] != b[i]) return 0;
    return 1;
}

/* fake dir records: +0 attr, +4 name pointer */
struct frec { u8 attr; u8 r[3]; const u8 *name; u16 x; };
static struct frec recs[8];
static struct frec rec_parent;

static u32 fake_rec(u32 idx)
{
    if (idx >= 0x80 || idx >= 8) return (u32)(unsigned long)&rec_parent;
    return (u32)(unsigned long)&recs[idx];
}

static long mock_fs(u32 a0, u32 a1, u32 a2, u32 a3, u32 op)
{
    (void)a0;
    if (fs_n < 64) { fslog[fs_n].op = op; fslog[fs_n].a1 = a1; fslog[fs_n].a2 = a2; fslog[fs_n].a3 = a3; fs_n++; }
    switch (op) {
    case 1:
        return (long)fake_rec(a1 & 0xFF);
    case 5:
        if (a1 < 0x1000) return 0;   /* an index, not a name: fetch passthrough */
        if (playlist_present && name_eq((const volatile u8 *)a1, name_idk)) return 0x100;
        if (name_eq((const volatile u8 *)a1, name_empty)) return 0x101;
        return 0;
    case 9:
        if (a2 == 0x100) { *(volatile u32 *)a1 = PL_SIZE; return 0; }
        if (a2 == 0x101) { *(volatile u32 *)a1 = (u32)sizeof pl_empty - 1; return 0; }
        return -1;
    case 0xB:
        if (a3 == 0x100 || a3 == 0x101) { kpos = a1; return 0; }
        return -1;
    case 0xD: {
        u32 n = a2, i;
        const char *src;
        u32 sz;
        if (a3 == 0x100) { src = pl_text; sz = PL_SIZE; }
        else if (a3 == 0x101) { src = pl_empty; sz = (u32)sizeof pl_empty - 1; }
        else return -1;
        if (kpos >= sz) return 0;
        if (kpos + n > sz) n = sz - kpos;
        for (i = 0; i < n; i++) ((u8 *)(unsigned long)a1)[i] = (u8)src[kpos + i];
        kpos += 512;                 /* the kernel advances whole sectors */
        return (long)n;
    }
    case 7:
        return 0;
    }
    return 0;
}

long (*test_fs)(u32, u32, u32, u32, u32) = mock_fs;

static u32 classify_calls;
static u32 mock_classify(u32 row)
{
    (void)row;
    classify_calls++;
    return 2;
}
u32 (*test_classify)(u32) = mock_classify;

/* mimics the stock wrapper 0x780DB460 around the hooked pool word */
static u32 wrap_fetch(u32 idx, u32 x)
{
#ifdef __mips__
    u32 r = fetchp(0xC7u, idx, 0, x, 1);
#else
    u32 r = m3uplay_fetch(0xC7u, idx, 0, x, 1);
#endif
    *test_rec_g = r;
    return r != 0;
}
u32 (*test_fetch)(u32, u32) = wrap_fetch;

/* ---- helpers ------------------------------------------------------------ */

static u32 fails;
static void check(int ok, const char *what)
{
    if (ok) { puts_("PASS  "); puts_(what); puts_("\n"); }
    else { fails++; puts_("FAIL  "); puts_(what); puts_("\n"); }
}

/* decode the record's UTF-16 name at rec+0x10 into ASCII (0 on mismatch) */
static int rec_name_is(const volatile u8 *rec, const char *want)
{
    const volatile u8 *nm = rec + 0x10;
    u32 i;
    if (nm[0] != 0xFF || nm[1] != 0xFE) return 0;
    for (i = 0; want[i]; i++) {
        if (nm[2 + 2 * i] != (u8)want[i] || nm[3 + 2 * i] != 0) return 0;
    }
    return nm[2 + 2 * i] == 0 && nm[3 + 2 * i] == 0;
}

/* the row: +0 ext[4], +4 marker, +8 name buf ptr */
struct row { u32 ext; u32 marker; u32 namebuf; };
static struct row row_m3u, row_mp3;

#ifdef __mips__
static u32 frame[0x40];
static u8 state[0x20];
/* call the patched site 0x40D15194 exactly as the dispatcher does; the
 * volatile pointer keeps GCC from folding the call into a direct jal,
 * which would drop the ISA bit and run the site as MIPS32 */
static u32 click(const struct row *r, u32 list_no, u32 count)
{
    register u32 fp asm("s1");
    u32 v;
    *(u32 *)((u8 *)frame + 0x2C) = (u32)(unsigned long)state;
    *(volatile u16 *)(state + 0xE) = (u16)list_no;
    *(volatile u16 *)(T_DESC + 2) = (u16)count;
    fp = (u32)(unsigned long)frame;
    asm volatile("" : "+r"(fp));
    v = entryp((u32)(unsigned long)r);
    return v;
}
#else
static u32 click(const struct row *r, u32 list_no, u32 count)
{
    return m3uplay_click((u32)(unsigned long)r, list_no - count);
}
#endif

int main(void)
{
    u32 v;
    u32 cls_before;
#ifdef __mips__
    static u8 vsram[0x200];
    static u32 rec_g, ctxw;
    test_vs = (volatile struct vstate *)(void *)T_VSTATE;
    test_rec_g = (volatile u32 *)T_REC_G;
    test_ctxw = (volatile u32 *)T_CTXW;
    (void)vsram; (void)rec_g; (void)ctxw;
    entryp = (u32 (*)(u32))0x40D15195u;   /* ISA bit: the site is MIPS16e */
    fetchp = m3uplay_fetch;
    *(volatile u32 *)T_CTXW = 0xC7u;
    *(volatile u32 *)T_REC_G = 0;
#else
    static struct vstate vs;
    static u32 rec_g, ctxw;
    test_vs = &vs;
    test_rec_g = &rec_g;
    test_ctxw = &ctxw;
    *test_ctxw = 0xC7u;
    *test_rec_g = 0;
#endif
#define VS (test_vs)
#define REC_G (*test_rec_g)

    mkname16(name_idk, "idk.m3u");
    mkname16(name_empty, "empty.m3u");
    mkname16(name_mp3, "x.mp3");
    recs[2].attr = 0; recs[2].name = name_idk;
    recs[3].attr = 0; recs[3].name = name_empty;
    recs[5].attr = 0; recs[5].name = name_mp3;
    rec_parent.attr = 1; rec_parent.name = name_mp3;
    row_m3u.ext = 0x2055334Du;   /* "M3U " */
    row_mp3.ext = 0x2050334Du;   /* "MP3 " */

    /* 1: click the .m3u row (list_no 5, count 3 -> dir idx 2) */
    cls_before = classify_calls;
    fs_n = 0;
    v = click(&row_m3u, 5, 3);
    check(v == 0, "click m3u returns class 0 (engine launch)");
    check(classify_calls == cls_before, "click m3u does not call the classifier");
    check(VS->magic == M3UPLAY_MAGIC && VS->flag == 1, "server armed (magic+flag)");
    check(VS->base == 2, "base = list_no - count = 2");
    check(VS->count == 2, "playlist counted (2 entries)");
    check(REC_G == (u32)(unsigned long)&VS->rec[0], "track 0 record published to REC_G");
    check(VS->rec[0] == 0 && *(volatile u32 *)(VS->rec + 4) == (u32)(unsigned long)(VS->rec + 0x10),
          "record layout: attr 0, name ptr -> rec+0x10");
    check(rec_name_is(VS->rec, "../Music/song one.mp3"), "track 0 name in record");
    check(name_eq(VS->name, name_idk), "vstate name = the .m3u's UTF-16 name");

    /* 2: next track through the wrapper */
    v = wrap_fetch(3, 0);
    check(v == 1 && REC_G == (u32)(unsigned long)&VS->rec[0], "fetch base+1 serves track 1");
    check(rec_name_is(VS->rec, "song2.flac"), "track 1 name in record");

    /* 3: beyond the playlist -> passthrough to the real dir stream */
    v = wrap_fetch(4, 0);
    check(v == 1 && REC_G == (u32)(unsigned long)&recs[4], "fetch past playlist end passes through");

    /* 4: markers pass through */
    v = wrap_fetch(0x82, 0);
    check(REC_G == (u32)(unsigned long)&rec_parent, "fetch 0x82 marker passes through");

    /* 5: disarmed -> passthrough */
    VS->flag = 0;
    fs_n = 0;
    v = wrap_fetch(2, 0);
    check(v == 1 && REC_G == (u32)(unsigned long)&recs[2], "disarmed fetch passes through");
    check(fs_n > 0 && fslog[fs_n - 1].op == 1, "disarmed fetch reached the real fs (op 1)");

    /* 6: non-m3u row -> classifier, untouched state */
    VS->magic = 0;
    cls_before = classify_calls;
    v = click(&row_mp3, 8, 3);
    check(v == 2 && classify_calls == cls_before + 1, "mp3 row goes to the classifier");
    check(VS->flag == 0, "mp3 click leaves the server disarmed");

    /* 7: m3u row but playlist unreadable -> classifier fallback, no state */
    playlist_present = 0;
    cls_before = classify_calls;
    v = click(&row_m3u, 5, 3);
    check(v == 2 && classify_calls == cls_before + 1, "unreadable playlist falls back to classifier");
    check(VS->flag == 0 && VS->magic == 0, "fallback leaves the server disarmed");
    playlist_present = 1;

    /* 8: empty playlist (comments only) -> fallback */
    v = click(&row_m3u, 6, 3);   /* idx = 3 -> empty.m3u record */
    check(v == 2, "empty playlist falls back to classifier");
    check(VS->flag == 0, "empty playlist leaves the server disarmed");

    /* 9: non-op-1 calls pass through even when armed */
    click(&row_m3u, 5, 3);      /* re-arm */
#ifdef __mips__
    fs_n = 0;
    v = fetchp(0xC7u, 2, 0xAA, 0xBB, 5);
#else
    fs_n = 0;
    v = m3uplay_fetch(0xC7u, 2, 0xAA, 0xBB, 5);
#endif
    check(fs_n > 0 && fslog[fs_n - 1].op == 5 && fslog[fs_n - 1].a1 == 2 &&
          fslog[fs_n - 1].a2 == 0xAA && fslog[fs_n - 1].a3 == 0xBB,
          "op!=1 call passes through with identical args");
    check(v == 0, "op!=1 returns the real fs result unchanged");

    puts_(fails ? "ALL FAIL\n" : "ALL PASS\n");
    puts_("m3uplay test done, failures "); putu(fails); puts_("\n");
    flush_out();
#ifdef __mips__
    done(fails ? 1 : 0);
#else
    done(fails ? 1 : 0);
#endif
    return fails ? 1 : 0;
}
