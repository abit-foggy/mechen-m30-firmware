/* Firmware-side location arithmetic: what is actually established.
 *
 * CORRECTION. An earlier version of this header claimed the routines at
 * 0x7805b264 and 0x7805b2dc were directory readers and that a record's
 * location addressed an exFAT directory entry. Both claims are withdrawn.
 *
 * The routines then call what an earlier pass took for a shared kernel
 * filesystem entry at 0xBFC16BB5. It is not one: 0xBFC16BB5 falls inside
 * music.ap's resident trap table, a run of `li $v1,N ; break`, so it is an
 * error path. That is also why these routines are unreachable -- invoking them
 * would trap. Nothing about a filesystem ABI follows.
 *
 * What is verified:
 *
 *   - music.ap's bank 0x7805b200 (1208 bytes) holds, as its only ASCII strings,
 *     "MUSIC.LIB" and "M3U.LIB" -- a library-access bank, not a tag reader
 *     despite an offhand note in docs/library-builder.md. It carries no ID3,
 *     vorbis, FLAC or APE tag strings.
 *   - Six modules (browser, config, mainmenu, music, playlist, setting) each
 *     declare that bank at file +0x710, so it is a shared library bank.
 *   - The bank entry 0x7805b200 is what those six declarations point at. The
 *     routines at 0x7805b264, 0x7805b2dc and 0x7805b370 are pointed at by
 *     nothing at all, in the bank or anywhere else in the image. The only
 *     in-bank branch that is a call is `jal loc_7805B200` at 0x7805b402.
 *
 * So the arithmetic below is a faithful transcription of instructions that
 * nothing invokes. It is not evidence about how the firmware resolves a record
 * to a file, and it must not be used as such.
 *
 * What the arithmetic is, stated plainly:
 *
 *     0x7805b270  lhu  v0, 0x14(s1)     ; arg1
 *     0x7805b272  srl  v0, 5            ; arg1 >> 5
 *     0x7805b276  lhu  v0, 0x10(s1)     ; arg0
 *     0x7805b278  addu v0, v1, v0       ; arg0 + (arg1 >> 5)
 *     0x7805b27c  lhu  v1, 0x14(s1)
 *     0x7805b27e  li   v0, 0x1F
 *     0x7805b280  and  v0, v1           ; arg1 & 0x1F
 *     0x7805b284  sll  v0, 4            ; << 4
 *     0x7805b28c  lhu  v0, 2(s1)
 *     0x7805b28e  sll  a1, 8            ; << 8
 *     0x7805b290  sll  a1, 1            ; << 1, i.e. * 512
 *
 * That is sector = arg0 + (arg1 >> 5), slot = (arg1 & 0x1F) * 16, and the
 * sector number is then multiplied by 512 to reach a byte. 512 is a sector
 * size, not necessarily a cluster size, and 16 is not the exFAT directory-entry
 * size of 32, so nothing about exFAT directory entries follows.
 *
 * All ten of the user's playlist selectors are multiples of 32, so
 * (arg1 & 0x1F) is zero for every one of them: these instructions never even
 * exercise their own low-bit path. Whether that is meaningful, or simply means
 * the field means something else, is unresolved.
 */
#ifndef M3UFS_H
#define M3UFS_H

struct m3ufs_loc {
    unsigned base;      /* arg0 */
    unsigned entry;     /* arg1 */
};

/* Split a record's 16-byte location field into the two words the firmware's
 * routines would take.
 *
 * The card's own data fixes the layout: all ten records share their first
 * twelve bytes -- 0x07000012, 0x00000540, 0x00135eac -- and differ only in the
 * last four, which are 800, 1056, 1280, 1408, 1504, 1632, 1760, 1888, 2016 and
 * 2208. Bytes 0..11 are therefore constant across the ten and bytes 12..15
 * carry the per-record value; what bytes 4..11 mean is not established. */
int m3ufs_split(const unsigned char *loc, unsigned len, struct m3ufs_loc *out);

/* The transcription, kept because it is the only firm evidence there is. */
unsigned m3ufs_sector_of(const struct m3ufs_loc *l);
unsigned m3ufs_slot_of(const struct m3ufs_loc *l);
unsigned long m3ufs_byte_offset(const struct m3ufs_loc *l);

/* True when this record's selector leaves the slot field zero, which holds for
 * all ten of the user's playlists. */
int m3ufs_slot_is_zero(const struct m3ufs_loc *l);

#endif /* M3UFS_H */
