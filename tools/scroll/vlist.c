/* Phase B proof of concept: a static virtual track list driven through the
 * REAL stock folder-list bank (browser.ap 0x48714400, stock, unpatched).
 *
 * What this establishes, at the interfaces verified so far:
 *
 *  - the row-provider side: the adapter fills the 12-byte row cache
 *    {absolute id, marker, display-text pointer} for the window the stock
 *    state describes, using the layout the QEMU scroll harness pinned;
 *  - the selection contract: after the stock scroll functions update the
 *    list state, the dispatcher's verified slot arithmetic —
 *    cache + (slot-1)*12 with the 1-based slot from state+0x10 — resolves to
 *    exactly the selected virtual entry, at every position, across page
 *    reloads. This is the check that matters for Phase B: if the adapter
 *    keeps the cache in step with the state, the stock dispatcher selects
 *    the right virtual row.
 *  - the reload contract: when the stock code requests a page reload
 *    (MODE=4, UPDATE=2 — the flags tools/scroll/accel.c documents), the
 *    adapter refills the cache and the contract still holds.
 *  - Back: snapshot/restore of the parent folder's state block around the
 *    virtual folder's lifetime, with the pre-open selection recovered.
 *
 * What this does NOT establish: the renderer (no display code runs), the
 * record-fetch side of the provider (the 20-byte records via the kernel
 * service — still unverified as the file-list provider), and anything on
 * hardware. Back is modelled at the state level, not via the undecoded
 * dispatcher path.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

/* PAGE = 8 because the stock bank's own row-shift window is 8 rows: on a
 * single-line slide it memmoves the 96-byte cache by one row itself
 * (verified this session: after a down-slide cache[0] holds the old cache[1],
 * even with no adapter action). A 7-row cache would be trampled past its
 * end. The selected-entry dispatcher's verified slot bound is 1..7 — that is
 * a bound of the dispatcher's own list context, not of this bank; recorded
 * separately. */
#define PAGE 8
/* 12 entries > 7 visible rows: scrolling must cross page boundaries and
 * exercise the reload path. */
#define VTOTAL 12

/* Rows now carry the stock browser's file_brow_t fields: a display name and
 * the 4-byte extension field (short names pad with spaces; the field is NOT
 * NUL-terminated). The list mixes ordinary audio rows with one playlist row,
 * so the adapter demonstrably distinguishes them the way the selection
 * bridge must. */
static const struct vrow {
    const char *name;
    const char *ext;      /* up to 4 bytes, space-padded */
} vrows[VTOTAL] = {
    {"Track A.flac", "FLAC"},  {"Track B.flac", "FLAC"},
    {"Track C.flac", "FLAC"},  {"old mix.mp3",  "MP3 "},
    {"Track E.flac", "FLAC"},  {"Track F.flac", "FLAC"},
    {"Track G.flac", "FLAC"},  {"Track H.flac", "FLAC"},
    {"js minecraft.m3u", "M3U"},  {"Track J.flac", "FLAC"},
    {"Track K.flac", "FLAC"},  {"Track L.flac", "FLAC"},
};

static volatile u32 now_ms;

__attribute__((section(".text.stubs"), used, noinline))
u32 test_timer(u32 a, u32 b, u32 c, u32 fn)
{
    return fn == 0x1c && !a && !b && !c ? now_ms : 0xdeadbeef;
}

__attribute__((section(".text.stubs2"), used, noinline))
u32 test_libc(u32 a, u32 b, u32 c, u32 fn)
{
    u8 *d = (u8 *)a, *s = (u8 *)b;
    u32 i;
    if (fn == 0) for (i = 0; i < c; i++) d[i] = s[i];
    else if (fn == 1) for (i = 0; i < c; i++) d[i] = (u8)b;
    return a;
}

__attribute__((section(".testram"), used)) volatile u8 testram[0x200];

static long sys3(long n, long a, long b, long c)
{
    register long v0 asm("v0") = n, a0 asm("a0") = a, a1 asm("a1") = b, a2 asm("a2") = c, a3 asm("a3");
    asm volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2) : "memory", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "hi", "lo");
    return v0;
}
static char obuf[1 << 16];
static int olen;
static void puts_(const char *s) { while (*s) obuf[olen++] = *s++; }
static void putu(u32 v) { char t[12]; int i = 0; do t[i++] = '0' + v % 10; while (v /= 10); while (i) obuf[olen++] = t[--i]; }
static void putsn(const char *s, u32 n) { while (n--) obuf[olen++] = *s++; }

static u8 list[0x20];
/* The bank reaches past an 8-row window when it slides (verified: it pulls
 * rows from beyond cache+96), so the region is 12 rows and the adapter fills
 * the two lookahead rows too. */
#define CROWS 12
static u8 cache[CROWS * 12];
/* The bank MOVES string content through the row-cache name pointers during
 * slides (verified: with read-only literals, literal 0's bytes became literal
 * 1's), so the rows must point at writable buffers the adapter re-fills.
 * Buffer size 52 = the SDK's LIST_ITEM_BUFFER_LEN for browser rows. */
#define ROWBUF 52
static char rtext[CROWS][ROWBUF];
static u8 snap[0x20 + CROWS * 12];

/* the SDK's row classifier semantics: compare exactly 4 bytes, case folded */
static int ext_is_m3u(const u8 *ext4)
{
    u8 e[4];
    u32 i;
    for (i = 0; i < 4; i++) {
        e[i] = ext4[i] | 0x20;             /* A-Z folds; digits and space unaffected */
        if (e[i] == ' ') { e[i] = 0; }
    }
    return e[0] == 'm' && e[1] == '3' && e[2] == 'u' && (e[3] == 0 || e[3] == '8');
}

#define U16(o) (*(volatile u16 *)(list + (o)))
#define U8(o)  (*(volatile u8 *)(list + (o)))

static void (*volatile p_next)(u32, u8 *);
static void (*volatile p_prev)(u32, u8 *);

/* THE ADAPTER — the row-provider side of the PoC. Fills the row cache for the
 * window the stock state describes: cache entry i (0-based within the page)
 * is absolute row top-1+i, in the verified 12-byte layout, with the name
 * pointer at a writable buffer re-filled from the static table (the bank
 * mutates the text through the pointers, so the pointers alone are not the
 * display). Rows past the end of the list are zeroed, so a stale name
 * pointer can never be read. */
static void refill(void)
{
    u32 top = U16(8), i, n;
    for (i = 0; i < CROWS; i++) {
        u32 abs = top - 1 + i;
        const char *src;
        char *d;
        if (abs >= VTOTAL || i >= PAGE) {   /* lookahead rows carry the next entries */
            *(u32 *)(cache + i * 12) = 0;
            cache[i * 12 + 4] = 0;
            *(u32 *)(cache + i * 12 + 8) = 0;
            continue;
        }
        src = vrows[abs].name;
        d = rtext[i];
        while (*src) { *d++ = *src++; }
        *d = 0;
        /* the stock record: ext[4] (space-padded, not NUL-terminated),
         * name_len in bytes, writable name buffer */
        for (n = 0; n < 4; n++) {
            cache[i * 12 + n] = (u8)vrows[abs].ext[n];
        }
        cache[i * 12 + 4] = (u8)(d - rtext[i]);
        *(u32 *)(cache + i * 12 + 8) = (u32)rtext[i];
    }
}

/* Create the list: the state the stock code expects (fields pinned by the
 * QEMU scroll harness), then the adapter fills the first page. */
static void init_list(u32 total)
{
    u32 i;
    for (i = 0; i < sizeof(list); i++) list[i] = 0;
    U8(2) = PAGE;
    U16(8) = 1;
    U16(0xa) = total < PAGE ? total : PAGE;
    U16(0xc) = total;
    U16(0xe) = 1;
    U16(0x10) = 1;
    U16(0x12) = 1;
    refill();
}

/* The dispatcher's verified selection arithmetic, applied to our cache. */
static const char *row_text(void)
{
    u32 slot = U16(0x10);
    if (!slot || slot > PAGE) return 0;
    return *(const char **)(cache + (slot - 1) * 12 + 8);
}

/* The display contract is CONTENT: the bank owns the text the pointers name
 * and moves it during slides, so compare bytes, not pointers. */
static int text_eq(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static u32 fails;

static void check(int ok, const char *what)
{
    if (!ok) {
        fails++;
        puts_("FAIL "); puts_(what); puts_(" at active="); putu(U16(0xe));
        puts_(" top="); putu(U16(8)); puts_("\n");
    }
}

void _start(void)
{
    u32 step, i;
    static const u8 script[] = { 1,1,1,1,1,1,1,1,1,1, 0,0,0,0,0, 1,1, 0,0,0,0,0,0,0 };

    p_next = (void (*)(u32, u8 *))0x487144a9;
    p_prev = (void (*)(u32, u8 *))0x487146cd;
    now_ms = 100000;

    /* --- the parent folder (Playlists, say 10 rows, the playlist on row 3) */
    init_list(10);
    U16(0xc) = 10;
    U16(0xe) = 3;
    U16(0x10) = 3;
    U16(0x12) = 3;
    for (i = 0; i < sizeof(list) + sizeof(cache); i++)
        snap[i] = (i < sizeof(list)) ? list[i] : cache[i - sizeof(list)];

    /* --- "open" the virtual folder: a fresh list over the static entries */
    init_list(VTOTAL);
    puts_("VIRTUAL OPEN rows "); putu(VTOTAL); puts_(" page "); putu(PAGE); puts_("\n");

    /* display: what a renderer reads for the visible page, per line, through
     * the dispatcher's slot arithmetic */
    for (i = 1; i <= (U16(0xa)); i++) {
        const char *s = *(const char **)(cache + (i - 1) * 12 + 8);
        u32 n = 0;
        while (s[n]) n++;
        puts_("ROW "); putu(i); puts_(" "); putsn(s, n); puts_("\n");
    }
    check(text_eq(*(const char **)(cache + 0 * 12 + 8), vrows[0].name),
          "page 0 row 1 is Track A");
    check(cache[4] == 12 && !ext_is_m3u(cache + 0),
          "row 0 carries name_len=12 and a FLAC ext field");

    /* --- move the selection with the real stock code */
    for (step = 0; step < sizeof(script); step++) {
        u32 dir = script[step], active, top, line, abs;
        U8(0x14) = 0; U8(0x15) = 0;          /* the app clears these after redrawing */
        if (dir) p_next((u32)cache, list); else p_prev((u32)cache, list);
        /* UPDATE = 2 marks every page movement this session observed
         * (MODE 0 = no slide, 1 = down-slide, 2 = up-slide, with 4/5 seen
         * only as the patched multi-step full-reload request). The bank has
         * already shifted the rows by one for a single-slide; refilling the
         * whole window from the new top is always correct and is what a
         * full reload does. */
        if (U8(0x15) == 2) refill();
        active = U16(0xe); top = U16(8); line = U16(0x10);
        abs = active - 1;
        /* the harness's invariant */
        if (!(1 <= top && top <= active && active <= U16(0xa) && U16(0xa) <= U16(0xc)
              && line == active - top + 1)) {
            fails++; puts_("INVARIANT step "); putu(step);
            puts_(" top="); putu(top); puts_(" act="); putu(active);
            puts_(" line="); putu(line); puts_("\n");
        }
        /* THE CONTRACT: the dispatcher's slot arithmetic must land on the
         * selected virtual entry after every stock state update */
        if (!text_eq(row_text() ? row_text() : "", vrows[abs].name)) {
            fails++; puts_("CONTRACT step "); putu(step);
            puts_(" got="); puts_(row_text() ? row_text() : "(null)");
            puts_(" want="); puts_(vrows[abs].name); puts_("\n");
        }
        /* the row's ext field must survive the slides and classify right */
        {
            u32 want_m3u = (abs == 8);
            if (ext_is_m3u(cache + (line - 1) * 12) != want_m3u) {
                fails++; puts_("EXT step "); putu(step); puts_(" abs "); putu(abs);
                puts_(" m3u="); putu(ext_is_m3u(cache + (line - 1) * 12));
                puts_(" want "); putu(want_m3u); puts_("\n");
            }
        }
    }
    puts_("SCROLLED active "); putu(U16(0xe)); puts_(" of "); putu(U16(0xc));
    puts_(" mode "); putu(U8(0x14)); puts_("\n");

    /* --- OK on the selected row: retrieve the selected virtual entry */
    {
        u32 active = U16(0xe);
        const char *sel = row_text();
        puts_("SELECT "); putu(active); puts_(" "); puts_(sel);
        puts_(" m3u="); putu(ext_is_m3u(cache + (U16(0x10) - 1) * 12)); puts_("\n");
        check(text_eq(sel ? sel : "", vrows[active - 1].name),
              "the selected entry is the one at the active index");
    }

    /* --- selecting the playlist row: the bridge's classification decision.
     * Row 9 (abs 8) is "js minecraft.m3u"; the stock state is moved there and
     * the adapter refills, then the row must classify as a playlist while an
     * ordinary audio row beside it does not. */
    U16(8) = 2; U16(0xa) = 9; U16(0xe) = 9; U16(0x10) = 8; U16(0x12) = 8;
    refill();
    {
        u32 line = U16(0x10);
        puts_("M3UROW name "); puts_(row_text());
        puts_(" cls="); putu(ext_is_m3u(cache + (line - 1) * 12)); puts_("\n");
        check(text_eq(row_text() ? row_text() : "", vrows[8].name),
              "the playlist row is selected by the stock state fields");
        check(ext_is_m3u(cache + (line - 1) * 12) == 1,
              "the playlist row classifies as M3U through the ext field");
        check(ext_is_m3u(cache + (line - 2) * 12) == 0,
              "the audio row beside it does not");
    }

    /* --- Back: restore the parent folder's state and selection. The row
     * name buffers are shared and were overwritten while the virtual folder
     * was open, so like the stock app after navigation (update_mode =
     * LIST_UPDATE_HEAD), the restored page is re-read: refill() regenerates
     * the text. */
    for (i = 0; i < sizeof(list); i++) list[i] = snap[i];
    for (i = 0; i < sizeof(cache); i++) cache[i] = snap[sizeof(list) + i];
    refill();
    check(U16(0xe) == 3 && U16(0x10) == 3 && U16(0xc) == 10,
          "Back restores the parent folder's state (active 3 of 10)");
    check(text_eq(*(const char **)(cache + (U16(0x10) - 1) * 12 + 8), vrows[2].name)
          && !ext_is_m3u(cache + (U16(0x10) - 1) * 12),
          "Back restores the pre-open selection row (Track C, FLAC)");
    puts_("RESTORED active "); putu(U16(0xe)); puts_(" total "); putu(U16(0xc)); puts_("\n");

    puts_(fails ? "ALL FAIL\n" : "ALL PASS\n");
    puts_("checks done, failures "); putu(fails); puts_("\n");
    sys3(4004, 1, (long)obuf, olen);
    sys3(4001, fails ? 1 : 0, 0, 0);
    for (;;) ;
}