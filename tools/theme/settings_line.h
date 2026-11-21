#ifndef M30_SETTINGS_LINE_H
#define M30_SETTINGS_LINE_H
/* Return a single value as a span. Reject duplicate keys on writes. */
static int setting_line(const unsigned char *data, unsigned size, const char *key,
                        unsigned *start, unsigned *end)
{
    unsigned i=0;
    int found=0;
    if (size>=3 && data[0]==0xef && data[1]==0xbb && data[2]==0xbf) i=3;
    while (i<size) {
        unsigned line=i, k=0;
        while (i<size && data[i]!='\n') i++;
        unsigned stop=i;
        if (stop>line && data[stop-1]=='\r') stop--;
        while (key[k] && line+k<stop && key[k]==data[line+k]) k++;
        if (!key[k] && line+k<stop && data[line+k]=='=') {
            if (found) return -1;
            *start=line+k+1;
            *end=stop;
            found=1;
        }
        if (i<size) i++;
    }
    return found;
}
#endif
