#ifndef M30_ICON_CACHE_H
#define M30_ICON_CACHE_H
/* drv_ui resident segment file offset 0x1474 maps to uncached 0xbfc09e74.
 * The marker is part of this build. Both users access the uncached alias. */
struct icon_cache {
    unsigned int signature, ready;
    unsigned short palette[4];
    unsigned char indices[100];
};
#define ICON_CACHE ((volatile struct icon_cache *)0xbfc09e74u)
#define ICON_SIGNATURE 0x3154484du
#endif
