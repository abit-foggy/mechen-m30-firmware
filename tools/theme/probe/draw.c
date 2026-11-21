/* Rebound services for three unmodified stock instruction ranges.
 * File reads use Linux syscalls. LCD submissions go to standard output. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
struct rect { u16 x, y, width, height; };
struct resource { int fd; u32 table, strings, style, pictures; };
struct resource app_resource, common_resource;
struct rect screen = {0, 0, 320, 240};
u8 buffer[128];
u8 *buffer_ptr = buffer;
u16 chunk_size = sizeof(buffer);
static u32 emitted, regions;
static int failed;
extern long linux_call(long number, long a, long b, long c);
typedef int (*picture_fn)(const void *, const void *, const void *);
extern picture_fn picture_entry;

int resource_io(int fd, u32 arg, u32 size_or_offset, int op)
{
    long result;
    if (op == 15 && arg == 0) {
        result = linux_call(4019, fd, size_or_offset, 0);
        if (result == (long)size_or_offset) return 0;
    } else if (op == 17) {
        result = linux_call(4003, fd, arg, size_or_offset);
        if (result == (long)size_or_offset) return result;
    }
    failed = 1;
    return -1;
}

static int set_region(const struct rect *area, int mode)
{
    ++regions;
    if (mode || area->x != 160 || area->y != 40 ||
        area->width != 20 || area->height != 20) failed = 1;
    return !failed;
}

static int submit(u32 pixels, u32 width)
{
    u32 bytes = pixels * 2;
    if (failed || width != 20 || bytes > sizeof(buffer) ||
        linux_call(4004, 1, (long)buffer, bytes) != (long)bytes) return 0;
    emitted += bytes;
    return 1;
}

int (*region_callback)(const struct rect *, int) = set_region;
int (*dma_callback)(u32, u32) = submit;

typedef int (*transfer_fn)(int, u32, const struct rect *);
extern transfer_fn stock_transfer;
static int theme_fd = -1;

/* Trial interception at the bitmap transfer callback. The Python harness
 * validates the pack before supplying this path. Other draws use stock. */
static int draw(int fd, u32 offset, const struct rect *area)
{
    if (theme_fd >= 0 && fd == app_resource.fd && offset == 0x191cc &&
        area->width == 20 && area->height == 20) fd = theme_fd;
    return stock_transfer(fd, offset, area);
}
transfer_fn draw_callback = draw;

int run(int argc, char **argv)
{
    const u16 widget[2] = {0x1007, 0};
    if (argc != 2 && argc != 3) return 2;
    app_resource.fd = linux_call(4005, (long)argv[1], 0, 0);
    if (app_resource.fd < 0) return 3;
    /* Stock music.sty offsets established by the atlas. The target probe
     * starts after resource-open has populated the app resource context. */
    app_resource.table = 0x400;
    app_resource.pictures = 0x50690;
    if (argc == 3) theme_fd = linux_call(4005, (long)argv[2], 0, 0);
    (void)picture_entry(widget, 0, 0);
    if (theme_fd >= 0) linux_call(4006, theme_fd, 0, 0);
    linux_call(4006, app_resource.fd, 0, 0);
    return failed || regions != 1 || emitted != 800;
}
