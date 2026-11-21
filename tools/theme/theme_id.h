#ifndef M30_THEME_ID_H
#define M30_THEME_ID_H
/* Read one UTF-8 line containing an ASCII theme directory name. Older
 * 512-byte picker records used NUL padding following the line. */
static int parse_theme_id(const unsigned char *p, unsigned int size, char id[9])
{
    if (size > 512) return 0;
    unsigned int i=0, n=0;
    if (size>=3 && p[0]==0xef && p[1]==0xbb && p[2]==0xbf) i=3;
    while (i<size && n<8) {
        unsigned char c=p[i];
        if (!(c>='a' && c<='z') && !(n && ((c>='0' && c<='9') || c=='_'))) break;
        id[n++]=c;
        i++;
    }
    id[n]=0;
    while (i<size && (p[i]==' ' || p[i]=='\t' || p[i]=='\r' || p[i]=='\n')) i++;
    if (size==512) while (i<size && !p[i]) i++;
    return n && i==size;
}
#endif
