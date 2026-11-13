/* Firmware filesystem adapter: open a file by path through the stock kernel.
 *
 * The ABI below is verified from `playlist.ap:0x40194c78`, the stock
 * library-file creator that `docs/library-builder.md` documents and that the
 * expanded-library build exercises, so it is known-working by construction.
 * See docs/reverse-engineering.md for the disassembly.
 *
 *   fs_cd  (ctx, ':', 0, 0, 0)          op 8  — change to the root drive
 *   fs_open(ctx, name, 0, 0, 5)         op 5  — open; returns a handle, 0 on fail
 *   fs_size(ctx, &size, h, 0, 9)        op 9  — size of the opened file
 *   fs_read(ctx, buf, h, 0, 0xD)        op 0xD — read
 *   fs_close(ctx, h, 0, 0, 7)           op 7  — close
 *
 * The function id is the LAST argument — a fifth, stack-passed word at
 * 0x10($sp) — matching the README's "the function ID as the last argument".
 *
 * What this module does NOT do: it does not touch the engine state block, the
 * extension masks, or the indexed-location ABI. It opens files by pathname,
 * which is all the M3U feature needs and which avoids the unresolved
 * `get_location` contract entirely.
 *
 * The syscall stub address is per-module: `0xBFC1640D` in playlist.ap's resident
 * mapping, `0xBFC11CCC` in mengine.ap's. The function ids are the kernel's and
 * are shared; the stub addresses are not. The context pointer is read from RAM
 * rather than hard-coded, so the same source works from any module that has
 * initialised the filesystem.
 */
#ifndef M30FS_H
#define M30FS_H

typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

/* Filesystem operation ids, from docs/library-builder.md. */
#define M30FS_OP_NEXTENTRY 0x01
#define M30FS_OP_OPEN      0x05
#define M30FS_OP_CREATE    0x06
#define M30FS_OP_CLOSE     0x07
#define M30FS_OP_CHDIR     0x08
#define M30FS_OP_SIZE      0x09
#define M30FS_OP_SEEK      0x0B
#define M30FS_OP_READ      0x0D
#define M30FS_OP_WRITE     0x0E
#define M30FS_OP_SETSIZE   0x13

/* Result codes. The stock creator treats a zero handle as failure. */
#define M30FS_OK            0
#define M30FS_ERR           (-1)
#define M30FS_ERR_NOMEM     (-2)
#define M30FS_ERR_TOOBIG    (-3)
#define M30FS_ERR_BADPATH   (-4)

/* A bounded path. The stock name buffer is 12 bytes per library entry, but a
 * playlist path needs more; keep this well under a sector so a caller can
 * still use fixed 512-byte buffers elsewhere. */
#define M30FS_PATH_MAX 96
#define M30FS_SECTOR   512

/* One open file: the handle the kernel returned plus the read cursor. */
struct m30fs_file {
    u32 handle;
    u32 size;      /* from op 9, so reads can be bounded */
    u32 pos;
};

/* Point the adapter at a module's filesystem stub and context.
 *
 * The stub address is per-module -- 0xBFC1640D in playlist.ap's resident
 * mapping, 0xBFC11CCC in mengine.ap's -- while the function ids are the
 * kernel's, so this has to be set at run time rather than baked in. Call it
 * once before the first m30fs_init; m30fs_init no longer resets it, which is
 * what let a test mock be clobbered.
 *
 * `stub` is the address of the `li v1,0x11; break` pair, and `ctx` the word the
 * stock creator reads from RAM (0x9FC15410 in playlist.ap's mapping). */
void m30fs_set_stub(u32 stub, u32 ctx);

/* Initialise from the resident filesystem context. Returns M30FS_OK. */
int m30fs_init(struct m30fs_file *f, u32 ctx, const char *path);

/* Read up to `n` bytes at the current cursor into `buf`. Returns the byte
 * count read, 0 at end of file, or a negative M30FS_ERR. */
long m30fs_read(struct m30fs_file *f, void *buf, u32 n);

/* Current read offset. */
u32 m30fs_tell(const struct m30fs_file *f);

/* Close the file. Safe to call twice; the second call does nothing. */
void m30fs_close(struct m30fs_file *f);

#endif /* M30FS_H */
