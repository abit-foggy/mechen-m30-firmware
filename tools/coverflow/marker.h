/* Optional comment on the second line of a prepared UTF-8 playlist.
 * The M3U scanner has already skipped a leading UTF-8 BOM. */
static u32 flow_header(const u8 *p,u32 n)
{
    static const char header[]="#EXTM3U";
    static const char prefix[]="#CF7=";
    if (n<21) return 0;
    for (unsigned i=0;i<7;i++) if (*p++!=header[i]) return 0;
    if (*p=='\r') {p++;n--;}
    if (n<21 || *p++!='\n') return 0;
    for (unsigned i=0;i<5;i++) if (*p++!=prefix[i]) return 0;
    u32 pack=0;
    for (int i=0;i<7;i++) {
        unsigned c=*p++,value=c-'0';
        if (value>9) {
            value=(c|32)-'a';
            if (value>5) return 0;
            value+=10;
        }
        pack=pack*16+value;
    }
    return (*p=='\n' || *p=='\r')?pack:0;
}
