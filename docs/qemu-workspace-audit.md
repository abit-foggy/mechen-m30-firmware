# M30 local development workspace and QEMU audit

Audit of the MECHEN M30 custom-firmware workspace, dated 2026-11-09.
Everything in this report was executed and verified on this machine; nothing is
inferred from documentation alone. No firmware checksum, security check, or
hardware assumption was modified. No player was flashed, and no hardware was
touched.

## Workspace

Root: `/home/foggy/.zcode/workspace/41fdbbb3-78b9-44da-8ce6-222c04adaf0e/m30-workspace`

```
m30-workspace/
├── firmware/
│   └── MECHEN_M30.HEX              11,662,336 bytes, sha256 6c7e27c8c90c4942… (stock 2025-06-26)
└── mechen-m30-firmware/            git clone of abit-foggy/mechen-m30-firmware
    ├── build/                      build output (gitignored)
    │   ├── MECHEN_M30.HEX          patched build, sha256 697b240e97608f97…
    │   └── work/                   intermediates: stock/, verify/, t_shuffle/, t_playall/,
    │                               t_scroll/, t_keys/, t_library/, test_*.txt
    ├── docs/                       library-builder.md, theme-gallery.html, this report
    ├── patches/                    MECHEN_M30-v3.bps, -v4.bps, -v5.bps
    ├── tools/                      patch tools + 5 QEMU harnesses
    └── rockbox  →  (sibling) ../rockbox
m30-workspace/rockbox/              sibling clone of Rockbox/rockbox (--depth 1)
```

The firmware is deliberately kept outside the git repository, in
`m30-workspace/firmware/`. `.gitignore` already excludes `*.HEX` everywhere, so
the working tree stayed clean through the entire audit (`git status --porcelain`
is empty).

### Git

| Remote | URL |
|---|---|
| `origin` | `https://github.com/abit-foggy/mechen-m30-firmware.git` (the fork) |
| `upstream` | `https://github.com/averagenative/mechen-m30-firmware.git` (original) |

- Branch: `main`, tracking `origin/main`, working tree clean.
- HEAD: `16eeeb41a02530fee0d1aad83023364dd13e62dd` — "Whole-card library: build
  MUSIC.LIB for every song on the player" (averagenative, 2026-11-03).
- Fork and upstream are **in sync** — `git rev-list --left-right --count
  origin/main...upstream/main` reports `0 0`, so there are no local commits and
  no upstream commits the fork is missing.
- Tags `v3`, `v4`, `v5` were fetched from upstream (read-only). Nothing was
  pushed, no pull request opened, nothing committed.

## Dependencies

Host: Fedora Linux 44 (Workstation), x86_64, dnf. `zsh` is the shell.

| Dependency | Status | Version / location |
|---|---|---|
| git | present (preinstalled) | 2.56.0 |
| python3 | present (preinstalled) | 3.14.8 |
| make | present (preinstalled) | GNU Make 4.4.1 |
| host gcc | present (preinstalled) | 16.2.1 |
| zlib dev headers | present | `zlib-ng-compat-devel` provides `/usr/include/zlib.h` + `/usr/lib64/libz.so` |
| IDA Pro (headless) | present | `/home/foggy/ida-pro-9.4/idat` 9.4 |
| MIPS cross GCC | **installed this session** | 16.2.1 (Red Hat Cross 16.2.1-1) |
| MIPS cross binutils | **installed this session** | 2.46.1-1.fc44 |
| `qemu-mipsel-static` | **installed this session** | 10.2.2 |
| `qemu-system-mipsel` | **installed this session** (Phase 4 only) | 10.2.2 |
| `atjboottool` | **built this session** | `m30-workspace/rockbox/utils/atj2137/atjboottool/atjboottool` |
| SDL2 runtime | present | `/usr/lib64/libSDL2.so` |
| SDL2 headers | present | `/usr/include/SDL2/SDL.h` |

Installed with (authorised by the user):

```sh
sudo dnf install gcc-mips64-linux-gnu binutils-mips64-linux-gnu qemu-user-static-mips qemu-system-mips
```

Fedora 44 no longer ships `zlib-devel`; `zlib-ng-compat-devel` (already
installed) provides the ABI-compatible headers and library, which is why
`atjboottool` builds with plain `-lz`.

### Toolchain verification (executable checks, not "package installed")

- All six `mips64-linux-gnu-*` binaries resolve in `/usr/sbin`.
- **MIPS16e support actually works**: compiling with
  `-mabi=32 -march=mips32 -mips16` produces 16-bit instructions — verified by
  disassembly (`64c3 save 24,ra`, `6f35 li a3,53`), not by trusting `-v`.
- **Cross-ISA mode switch works**: a MIPS16e blob called from a MIPS32 o32
  harness links and runs correctly under `qemu-mipsel-static -cpu 24Kc`
  (result 153, exit 0).
- `qemu-mipsel-static -cpu 24Kc` is accepted: `24Kc` is listed by
  `qemu-mipsel-static -cpu help`.
- Two real gotchas found while probing, both matching existing repo conventions:
  - `syscall` does **not** exist in MIPS16e — the repo splits blobs (MIPS16e)
    from harnesses (MIPS32) precisely so that `sys3()` lives in the MIPS32 unit.
  - A bare `.text`-only link fails with
    `section .MIPS.abiflags LMA overlaps section .text LMA` — which is why every
    `tools/*/test.ld` ends with `/DISCARD/ : { *(.MIPS.abiflags) … }`.

### Firmware

Only the **patched v5 release** (`af999b7bf15e4a6412e7fc119bff3e59a4a3cfd2079bcf0e47b9662bdd40936c`)
existed locally, in `~/Downloads/MECHEN_M30.HEX`. The stock 2025-06-26 file was
downloaded from the public Google Drive link documented in the README and its
SHA-256 verified against `6c7e27c8c90c4942664d66a0d6c9f9e48f8d3bc7d2d24223568255e233551258`
— **exact match**, so the build ran against genuine stock firmware. Nothing was
substituted and no hash check was bypassed. `tools/bps.py` only applies patches
forward (stock → patched), so it cannot reconstruct stock from the patched file;
downloading was the only route.

## Existing QEMU infrastructure

**Five harnesses, all QEMU *user-mode*, all launched as
`qemu-mipsel-static -cpu 24Kc …` from `build/work/`.** There is no full-system
harness, no display, and no machine model anywhere in the repository.

| # | Harness | What it runs | Source | Runs real stock code? | Needs stock firmware? |
|---|---|---|---|---|---|
| 1 | `tools/shuffle/harness.c` | MIPS16e shuffle blob at `0x7b1a808c` | compiled from source | no | **no** |
| 2 | `tools/playall/harness.c` | play-all units A–E + mock FS/engine | compiled from source | no | **no** |
| 3 | `tools/scroll/harness.c` | real `browser.ap` dirlist bank `0x48714400` | extracted from stock `.ap` | **yes** | **yes** |
| 4 | `tools/keys/harness.c` | real common key filter bank `0x48694600` in 5 apps | extracted from stock `.ap` | **yes** | **yes** |
| 5 | `tools/library/harness.c` | stock `playlist.ap` MUSIC.LIB index passes + new file-backed passes | mixed | **yes (stock mode)** | **yes (banks)**; library *data* can be synthetic |

Answers to the audit questions:

1. **Binary / CPU**: `qemu-mipsel-static`, emulating `-cpu 24Kc`, guest ELF is
   little-endian MIPS32 o32 with MIPS16e blobs.
2. **Mode**: **user-mode only.** Not one component uses `qemu-system-*`.
3. **Firmware routines executed real**: the `browser.ap` folder-list next/prev
   handlers (`0x487144a8` / `0x487146cc`), the common key filter
   (`FUN_48694658`) across browser/music/mainmenu/playlist/setting, and the
   stock `playlist.ap` MUSIC.LIB index-pass banks (`0x400d4c00`, `0x40114c00`,
   `0x40194c00`, `0x40294c00`, `0x48014400`, `0x71812500`).
4. **Tests on real extracted stock code**: scroll (stock *and* patched side by
   side) and keys (stock *and* patched side by side); plus library in `stock`
   mode.
5. **Tests on newly compiled code**: shuffle, play-all, and library in `new`
   mode. `tools/library/libmodel.py` supplies an independent Python model of the
   new passes.
6. **How memory is modelled**: linker scripts (`tools/*/test.ld`) place the
   harness at `0x00400000`, host-side stub functions in dedicated stub sections
   at fixed addresses (e.g. `0x00500000` stub_rand, `0x00505000` stub_vfs,
   `0x00700000`/`0x00700100` for scroll timer/libc), a `.testram` scratch region
   at `0x10000000`, and each firmware bank/blob at its **real firmware address**
   (`0x48694600`, `0x48714400`, `0x7b1a808c`, `0x400d4c00`, …). Guest `syscall`
   instructions are the *Linux* o32 ABI (4001 exit, 4004 write, 4210 mmap),
   **not** the firmware's `li v1,MODULE; break` kernel calls — user-mode QEMU
   cannot execute those, so the harnesses **replace them with host-side stubs**
   by planting the stub at the address the firmware code jumps to and calling it
   via a function pointer.
7. **Application overlays**: Yes, partially. `tools/scroll/testbank.py`,
   `tools/keys/patch_keys.py --testbanks`, and `tools/library/testbanks.py`
   extract individual banks out of the stock `.ap` files and relink them for the
   harness. There is **no generic overlay loader** and no bank-group emulation —
   each harness hardcodes the banks it needs.
8. **Do tests need the original firmware?** scroll, keys and library do. Without
   stock firmware they are blocked.
9. **Can they work from synthetic fixtures?** Partly. The shuffle and play-all
   harnesses need no firmware at all (verified below). For library, the *record
   data* can be synthetic (`tools/library/mklib.py 6000 …` is exactly what
   `build.sh --test` uses), but the *bank code* still comes from stock
   `playlist.ap`. There is no synthetic-fixture path for scroll or keys, because
   those tests' whole point is running the real stock bank.
10. **Regression testing**: `build.sh --test` is the single regression gate. It
    runs all five harnesses, then asserts (a) every `test_*.txt` contains a
    `^ALL PASS` line, (b) every scroll run prints
    `^events 30000 .* failures 0$`, and (c) the slow-click scroll run is
    **byte-identical to stock** (differential regression against real stock
    behaviour). Any of these failing makes the build exit non-zero. Run time is a
    few minutes.

### Test commands

Everything runs from `build/work/`, where `$QEMU = qemu-mipsel-static`:

```sh
# full documented build + all five harnesses + verification
ATJBOOTTOOL=../rockbox/utils/atj2137/atjboottool/atjboottool \
  ./build.sh --test ../firmware/MECHEN_M30.HEX

# individual harnesses, after a build (from build/work/)
$QEMU -cpu 24Kc t_shuffle/test.elf          # shuffle
$QEMU -cpu 24Kc t_playall/test.elf          # play-all
$QEMU -cpu 24Kc ./run_stock_1.elf           # scroll, stock, slow clicks only
$QEMU -cpu 24Kc ./run_patched_0.elf         # scroll, patched, mixed clicks
$QEMU -cpu 24Kc ./test_browser.elf          # keys (also music, mainmenu, playlist, setting)
```
```sh
# library harness standalone: CROSS/QEMU/PYTHON as for build.sh
tools/library/test.sh build/work/stock/fw/playlist.ap some.lib WORKDIR new|stock|both
```
`build.sh --library-replay`, `--library-bench`, `--library-probe`, and
`--library-iotest` swap in other `tools/library/*.c` diagnostics.

### Results — all passed

The full documented command was run end to end against genuine stock firmware.
Verbatim tail:

```
== unpack stock firmware
   AFI 19/0 FW 201/0 (ok/mismatch)
== QEMU tests
   shuffle:  ALL PASS, failures: 0
   playall:  ALL PASS, failures: 0
   scroll:   patched, mixed clicks: events 30000 multi-step 26744 failures 0
   scroll:   slow clicks identical to stock
   keys:     browser: cases 448, changed by the patch 60 ALL PASS, failures: 0
   keys:     music: cases 448, changed by the patch 60 ALL PASS, failures: 0
   keys:     mainmenu: cases 448, changed by the patch 60 ALL PASS, failures: 0
   keys:     playlist: cases 448, changed by the patch 60 ALL PASS, failures: 0
   keys:     setting: cases 448, changed by the patch 60 ALL PASS, failures: 0
   library:  library reproduced byte for byte
== done: build/MECHEN_M30.HEX
```

Notable detail: the patched build's SHA-256 is `697b240e97608f97…`, **not** the
documented v5 release hash `af999b7b…`. This is expected and documented in the
README: my cross-GCC is Fedora's 16.2.1-1 but a different *build* (20260819) than
the one used for the release, and the README states "A different compiler version
can produce a different but valid file." A byte-level diff of my build against the
official v5 release shows **5,992 differing bytes in 27 ranges**, all confined to
the patched app payloads and their surrounding AFI/FWU bookkeeping — consistent
with compiler codegen differences in the injected blobs, not with a wrong or
corrupt build. `build.sh`'s own verification confirms exactly the six expected
`.ap` files changed from stock (`browser.ap mainmenu.ap mengine.ap music.ap
playlist.ap setting.ap`), the FWU trailer sum checks out, and every extracted
checksum is `ok/mismatch = ok`. All five harnesses pass on this build.

**Independent run without firmware** (asked for in the audit): compiling and
running just the shuffle harness, with no firmware present anywhere, reproduces
`ALL PASS, failures: 0`. The play-all harness is equally firmware-free. So the
parts of the suite that *can* run without stock firmware do; the parts that need
it were run with the genuine, hash-verified article.

## GUI investigation

**No graphical interface currently exists.** The repository contains no
graphical frontend whatsoever, and no framebuffer, LCD, or display-controller
emulation. Searched for SDL, GTK, Qt, VNC, GTK UI, framebuffer emulation, LCD
drawing routines, UI screenshot generation, display-controller simulation, menu
rendering tests, simulated button/wheel input, and graphical debugging utilities
across every `.py`, `.c`, `.h`, `.S`, `.sh`, `.ld`, `.md` and `.java` file in the
repository. The only hits are the dnf line in the README and a prose paragraph
describing the screen-off message. `docs/theme-gallery.html` is a static
hand-authored HTML page of embedded base64-PNG and SVG *mockups* — it contains no
emulation, no QEMU, and no code that runs firmware. It is not a GUI and must not
be mistaken for one.

### Can QEMU's built-in UI display M30 firmware graphics? No — tested and disproved

This was tested empirically, as requested.

- **`qemu-mipsel-static` has no display capability at all.** It links no SDL,
  GTK, or pixman, and rejects the option outright: `qemu-mipsel-static -display
  help` → `qemu: unknown option 'display'`. Since the project's harnesses are
  user-mode, QEMU's built-in UI is simply unavailable to them.
- **QEMU's built-in SDL and GTK frontends do work on this host** — verified by
  launching `qemu-system-mipsel -M malta -vga cirrus -display sdl` and
  `-display gtk`; both ran for the full 20 s timeout and produced no error
  (GTK emitted a harmless theme warning). So the capability exists.
- **But it cannot show M30 graphics**, for four independent reasons, each tested:
  1. **No ATJ2127 machine model.** `qemu-system-mipsel -machine help` lists only
     `malta` and `none`. QEMU has no Actions ATJ2127 device at all.
  2. **The firmware's addresses do not fit a mipsel machine.** `info mtree` on
     Malta shows RAM only at `0x00000000–0x0fffffff` and `0x80000000–0x8fffffff`.
     The overlay banks live at `0x48694600` / `0x48714400` (≈1.2 GB) and
     `mengine.ap` banks at `0x7b068484`–`0x7b1a808c` (≈2 GB), with firmware RAM
     at `0x9fc15bf4` (≈2.7 GB). All far outside any mipsel machine's map.
  3. **The existing test ELFs cannot even be loaded in system mode.**
     `qemu-system-mipsel -M malta -kernel t.elf` fails with
     `Trap-and-Emul kernels (Linux CONFIG_KVM_GUEST) are not supported` — these
     bare freestanding ELFs are built for user-mode, not for `-kernel`.
  4. The harnesses' output is text on stdout, which a QEMU display would not
     render anyway; the display would show an unrelated VGA screen.

**Conclusion: QEMU's built-in UI is a dead end for actual M30 firmware graphics.**
It requires full-system emulation, an ATJ2127 machine model that does not exist,
a memory map that does not match the firmware, and a boot path that does not
exist. Anything real has to reuse the user-mode harnesses the project already
has. Rockbox's own `uisimulator` was also checked: it is an SDL frontend, but
Rockbox has **no ATJ2127/ATJ2137 firmware target** (only `utils/atj2137/` tools
and a `utils/hwstub/stub/atj213x/` hardware stub), so it cannot run M30
firmware either. It is an architectural reference, not a reusable component.

### The resources are real and reachable — the firmware already contains them

The unpacked stock firmware ships a complete UI resource set, all decodable in
principle:

| File | Magic | Size |
|---|---|---|
| `mainmenu.sty` | `RU3` + version string | 1,853,440 |
| `logo.sty` | `RU3` | 1,077,248 |
| `common.sty` | `RU3` | 963,584 |
| `config.sty` | `RU3` | 468,992 |
| `setting.sty` | `RU3` | 434,176 |
| `music.sty` | `RU3` | 330,240 |
| `playlist.sty` | `RU3` | 102,912 |
| `browser.sty` | `RU3` | 30,720 |
| `upgrade.sty`, `usound.sty`, `udisk.sty`, `end.sty` | `RU3` | 14,848–194,048 |
| `music.mcg`, `setting.mcg`, `browser.mcg` | `ACTMCGGM01` | 2,560–28,672 |
| `mainmenu.mcg` | `ACTMCGGM01` | 512 |
| `new_m.fnt` | `FNT` | 2,138,624 |
| `drv_lcd.drv`, `drv_ui.drv` | — | — |

**No tool in the repository decodes `.sty`, `.mcg`, or `.fnt`.** The only file
that mentions them is `docs/theme-gallery.html`. Writing those decoders is
therefore new work, not reuse.

### The critical engineering questions, answered honestly

| Question | Answer | Basis |
|---|---|---|
| Can existing firmware UI drawing functions execute under QEMU user-mode? | **Partially — proven for list/navigation state, unproven for pixel output.** The scroll and keys harnesses already execute the *real* stock bank code that maintains the selection, list window and key-filter state under user-mode QEMU, and pass. Pixel drawing has never been run. | scroll/keys tests pass |
| How are firmware system calls dispatched? | They are **not** — the harnesses bypass them. Firmware kernel calls are `li v1,MODULE; break` stubs; user-mode QEMU cannot execute those, so each harness plants a host C stub at the address the stock code calls and routes through a function pointer. The harness's own I/O uses the Linux o32 ABI (`syscall` with v0 = 4001/4004/4210). | `tools/*/harness.c` |
| What display routines would need replacement/interception? | **Unknown at this stage — this is the one genuine open question.** The LCD driver is `drv_lcd.drv`; the drawing path is inside it and the `.sty` renderer. Which functions write pixels, and where the framebuffer lives, has not been traced yet. Tracing it (IDA or the Ghidra scripts) is a prerequisite task, not something this audit could assume. | not investigated |
| Can we capture actual LCD drawing commands? | **Hypothesis, not a proven capability.** The mechanism would be the same one already used for kernel calls: intercept the draw call at its stub address and record the parameters / shadow the target buffer. Nothing currently does this. | unverified |
| Can `.sty`, `.mcg` and fonts be decoded and reused? | **Resources: yes, present and reachable. Decoders: do not exist yet.** The formats are identifiable (`RU3…`, `ACTMCGGM01`, `FNT…`) and total ≈4.8 MB, but reverse-engineering them is new work. | repacked and inspected |
| Can we simulate buttons and wheel events? | **Yes for key-filter state — already proven.** `tools/keys/harness.c` drives 14 key codes × 4 event types × 2 screen states × 4 wake states = 448 cases per app and asserts stock-vs-patched behaviour. Key codes are documented in the README (`01` play, `02`/`03` prev/next, `05`/`06` vol, `07` OK, `0a`/`0b` wheel, `80` back, `81` power). For a real UI you would also need to feed the *menu* code, not just the filter. | keys tests pass |
| Can we display a real stock firmware screen without implementing the whole ATJ2127 SoC? | **Plausible but unproven.** Only one narrow path looks viable: run the specific drawing function that paints one screen in isolation, as the scroll/keys harnesses run one bank in isolation, and capture its pixel output via an intercepted draw primitive. That needs no SoC. Booting stock firmware, or navigating menus, would need full-system QEMU plus a machine model that does not exist. | architectural |
| What needs full-system QEMU? | Anything involving the kernel: bank-loading-on-demand, the `li v1,MODULE; break` syscall dispatch, real driver IRQs, the file system, and booting stock firmware. Those are out of reach of user-mode and of QEMU's stock machines. | established |

### Guest → host framebuffer transfer: proven

To de-risk the frontend architecture, the guest→host pixel path was actually
exercised: a MIPS guest running under `qemu-mipsel-static -cpu 24Kc` wrote a
128×128 shadow framebuffer to stdout (the same `write(1, buf, len)` mechanism
`tools/*/harness.c` already uses for its result buffers), the host received
exactly 16,391 bytes, and rendered a valid 128×128 16-colour PNG (ImageMagick:
`128x128 8-bit 16c`). An ASCII render confirmed the intended geometry — 2 px
border ring, 16-row title bar with glyph blocks, list background, and a status
band — so the buffer's contents survive the trip intact.

**Important limitation:** bidirectional shared memory (`mmap(MAP_SHARED)`) was
also attempted and **failed** — the guest segfaults. On MIPS o32, six-argument
syscalls take args 5 and 6 on the stack, which plain inline asm does not set up;
it needs a hand-written assembly stub (the same technique as
`tools/keys/keypass.S`). The **one-way** stdout path used above does work, and is
a sufficient basis for a first milestone. For input (buttons/wheel), stdin
(`read(0, …)`) is the natural bidirectional counterpart and needs no mmap.

### Frontend choice: SDL2

Per your decision, SDL2 is the frontend. It is already present on this host
(`/usr/include/SDL2/SDL.h`, `/usr/lib64/libSDL2.so`), and the architecture it
implies — a host program that renders a framebuffer the guest produces — is the
one the pipeline test above validated. Note that this is a **host-side SDL2
program of our own**, not QEMU's built-in SDL UI: the built-in one was tested and
is unusable here for the four reasons above.

## Recommended next implementation

**Milestone 0 — trace the drawing path before writing any frontend. Do not build
a hardware emulator or a complete emulator, and do not start the SDL2 frontend
yet.** Application-level emulation is not shown to be insufficient; the opposite —
it is the only demonstrated path. The one thing standing in the way is that the
drawing entry point is unknown.

The smallest useful next experiment:

1. **Find the draw entry point.** Using IDA (`~/ida-pro-9.4/idat`, available) or
   the repo's Ghidra scripts, locate the function in `drv_ui.drv` / the `.sty`
   renderer that paints one screen, and identify (a) the framebuffer address,
   (b) the primitive API (fill, blit, text), and (c) the `li v1,MODULE; break`
   stubs it depends on. `tools/apinfo.py` and `tools/refscan.py` are already
   suited to this.
2. **Render one static screen.** Extend the *existing* pattern — a new
   `tools/<name>/harness.c` plus a `test.ld`, linked at the firmware's real
   addresses with host stubs for the kernel calls — call the one drawing
   function, and capture its pixel output through the stdout pipe already proven
   above. No SDL2 yet; write a PGM/PPM to a file.
3. **Add the SDL2 window only once step 2 produces a recognisable screen**:
   read the pipe, map the palette, `SDL_CreateWindow` + `SDL_CreateRenderer` +
   `SDL_UpdateTexture`.

Suggested work area, if you want it: a new `tools/gui/` directory, keeping the
host-side frontend cleanly separated from the firmware-side code as the
development rules require.

Firmware-dependent items deliberately **not** done: no firmware flashing, no USB
recovery, no interaction with any physical player, and no partial-hardware
write path. All work was read-only against firmware images.

---

## Postscript: QEMU boot attempt (2026-11-11)

Work after the audit above went beyond the theme work into trying to boot the real
firmware under a custom QEMU machine. It is reported here because it changes the
recommended next step. Nothing in this section has been merged anywhere; the
machine model lives in `m30-workspace/qemu/hw/mips/m30.c` (~660 lines, builds clean
with `-Werror`).

### What is working and measured

A `qemu-system-mipsel -machine m30` that places the firmware correctly and boots it:

- **KER_INIT.BIN** (0x1800, MIPS32) at `0xBFC00000`, the reset vector.
- **KER_XSYS.BIN** (0x800, MIPS32) at `0xBFC321C8`. *Derived, not guessed*:
  KER_INIT's first real call (at `0xBFC00038`, before any exception can be taken)
  is `jal 0xbfc32224`, and `ker_xsys.bin+0x5C` under that base is the MIPS32
  handler body (`beqz k0` → `mfc0 k0,$14` → save EPC/`$ra` to `0x13DD8`/`0x13DDC`
  → `jr` the dispatcher at `0xBFC06D6C`), so the component must link at
  `0xBFC32224 - 0x5C`. Decoding `ker_xsys.bin` as MIPS16e yields cop2/ldc1 garbage,
  which rules out the older `0xBFC045C0` base.
- **KER_TEXT.BIN** (0xC00) at `0xBFC06BEC`, *derived the same way*: the `jr` that
  ends `ker_xsys.bin`'s handler targets `0xBFC06D6C`, and the identical dispatcher
  sequence lives in exactly two components (`ker_text.bin+0x180` and
  `kernel.drv+0x180`, the latter being a 0x200-byte-header body offset of 0x380).
  `kernel.drv`'s body is already at its header-declared `0xBFC08000`, so the copy
  that must reach `0xBFC06D6C` is `ker_text.bin`'s: `0xBFC06D6C - 0x180`.
- The AFI directory is now parsed and the NOR boot blobs are placed:
  `NORHWSC.BIN`/`NORFWSC.BIN` at `0xBFC1E000`.
- Kernel, drivers, apps and their data segments are placed from the header triples.
- **The kernel is placed in a second pass, after all drivers and apps.** `udisk.drv`
  and `usound.drv` both declare `0xBFC30000` (0x2e50 / 0x26b0), which overlaps
  `ker_xsys.bin` at `0xBFC321C8`; loading in directory order put the overlays last
  and they silently overwrote `ker_xsys.bin+0x5C` with `usound.drv+0x2224`
  (`ldl t7,26466(s0)`), which is the original `jal 0xbfc32224` reserved-instruction
  fault. That overlap is not corruption — it is the firmware's on-demand overlay
  model — but the resident kernel has to win it.
- Kernels/driver code execute with **1 nop** in the traced window, the clock
  register RMW succeeds (`read 0x1c -> 0`, `write 0x1c <- 0x1`), and the whole
  exception-handler chain now runs: `jal 0xbfc32224` → `ker_xsys` handler
  (save EPC/`$ra` to 0x13DD8/0x13DDC) → dispatcher at `0xbfc06d6c` (save
  EPC/`$ra`/Cause to 0x13DCC/0x13DD0/0x13DD4, index the handler table at
  `0x9FC1A9A4`) → `jr k0` → MIPS16e at `0x5C082D12`.

Ten fixes were needed to get there, each of which silently stalled or looped rather
than erroring: kseg2 must be unmapped in `SegCtl0` (QEMU defaults it to TLB-mapped);
the CPU needs a boot stack; the map parser must accept hex addresses; `-machine`
properties must be instance-level; link addresses are virtual while
`address_space_write` is physical; scratch RAM exists at physical 0 (the handler
saves EPC to absolute `0x13DD8`); and the peripheral window is at `0x00120000`,
not `0xB0000000`.

### The remaining blockers (updated 2026-11-11, exception dispatch verified)

The `jal 0xbfc32224` reserved-instruction fault is **fixed and verified**; see
"What is working and measured" for the corrected placements. The first exception
after that fix was then characterised end to end, via the HMP monitor and
`-d in_asm,int`:

#### The exact first exception

| CP0 field | value | meaning |
|---|---|---|
| Cause | `0x00000018` | ExcCode = `(0x18 >> 2) & 0x1f` = **6 = IBE** |
| Status | `0x00400006` | BEV = 1, **ERL = 1, EXL = 1**, IE = 0 |
| EPC | `0x5C082D13` | odd, so the CPU was in **MIPS16e mode** |
| BadVAddr | `0x00000000` | not updated for fetch faults |
| ErrorEPC / DEPC | `0x00000000` | unused |

> **A numbering trap worth recording.** QEMU logs this fault as
> `do_raise_exception_err: 15 (instruction bus error)`. That `15` is QEMU's
> *internal* `EXCP_IBE` enum index, not a CP0 ExcCode; the architectural ExcCode
> is 6. CP0 ExcCode 15 is FPE. Earlier reports calling this "ExcCode 15" mixed the
> two up. The `-d int` line `mips_cpu_do_interrupt: PC bfc00380 EPC 5c082d13
> cause 6` gives the architectural code directly.

1. **The handler table dispatches to an unmapped address.** The dispatcher at
   `0xBFC06D6C` runs correctly and indexes a table at **`0x9FC1A9A4`** — *not*
   `0x9FC25AA4`, which reads as all zeros; that earlier figure was an arithmetic
   slip (`0x9FC20000 + 0x5AA4` instead of `0x9FC20000 - 0x565C`). The table sits
   inside `kernel.drv`'s data segment (`0x9FC1A400..0x9FC1ABF4`, FWIMAGE file
   0x2d00, offset `+0x5A4`, verified live with `xp /32xw 0x1fc1a9a4`).
   The index is `(Cause & 0x7c) >> 2` = ExcCode, and at the call Cause is 0, so
   entry 0 is used: `0x5C082D13`, odd, so `jr k0` clears bit 0 and enters
   MIPS16e at `0x5C082D12`, which is kuseg and unmapped.

   **The value is firmware-backed but lonely.** `0x5C082D13` occurs *exactly once*
   in the entire 11 MB image — at the table entry itself — and `0x5C082D12`
   occurs *zero* times. There is no relocation table and no second reference. All
   443 bank triples across every `.ap`/`.drv` declare load addresses in
   `0x40000000`–`0x48D14600`; **none** is in `0x5C000000`–`0x5CFFFFFF`. `31` of
   `32` table entries are not plausible code pointers. So this is not a properly
   populated handler table at this point in the boot.

   **Note what the registers then do, because it explains the loop shape.** The
   take of the exception sets EXL, and QEMU's `set_EPC` only writes EPC *while
   EXL is clear* — so EPC is frozen at `0x5C082D13` forever after. The measured
   trace is exactly one IBE followed by ~2.9 M reserved-instruction faults, all
   reporting that frozen EPC. The storm is a consequence, not a separate bug.

   **`0x5Cxxxxxx` is nonetheless a real firmware region.** `setting.sty` declares
   large decode buffers at `0x5C140000` (1.75 MB), `0x5C3C0000`, `0x5C400000`,
   `0x5C440000`, `0x5C480000`, `0x5C4C0000`, `0x5CD80000`, `0x5CE80000`. The
   emulator models none of them (`xp` returns "Cannot access memory"). The
   firmware therefore does treat `0x5C000000` upward as DRAM; no fix has been
   made here, since nothing establishes that *handler code* belongs at
   `0x5C082D12` at reset time.

2. **The general exception vector at `0xBFC00380` cannot recover.** It computes
   `0xBFC04635` and jumps to MIPS16e at `0xBFC04634`, which is inside the missing
   region below, so it nop-walks and faults again with EXL latched. This is the
   immediate second blocker: without a handler there the CPU has no way to
   resume, whatever is installed at `0x5C08xxxx`.

3. **The `0xBFC04xxx`–`0xBFC08xxx` region is missing ~4.2 KB of MIPS16e code.**
   `kernel.drv`'s data segment holds real function pointers into it:
   `0xBFC04635` (exactly the value the general exception vector computes),
   `0xBFC045F5`, `0xBFC04699`, `0xBFC05125`, `0xBFC05369`, `0xBFC064B0`,
   `0xBFC064BC`, `0xBFC07BF9`, `0xBFC07C75`, `0xBFC08771`. KER_INIT also calls
   MIPS16e at `0xBFC045F4` and `0xBFC033D4`. Nothing in the currently-placed
   component set covers that span.

#### Where that code is *not* (2026-11-11, second pass)

The source of the `0xBFC04xxx`–`0xBFC08xxx` MIPS16e region was searched for
across every unpacked component, every boot blob and every bank declaration:

- **`ker_text.bin` and `kernel.drv`'s resident body are the same module.**
  `ker_text.bin` is byte-identical to `kernel.drv[0x200:0xD00]` plus 0x100 zero
  bytes. Placing them at two different addresses is therefore wrong, and the
  module's own header triple (`+0x08/+0x0c/+0x10` = 0x200 / 0xB00 / 0xBFC08000)
  says where it belongs: `0xBFC08000`.
- **That module holds no MIPS32 code at all** — zero `jr $ra` and zero `eret`
  — so it is a pure pointer table (80 pointers, 50 of them odd = MIPS16e,
  spanning `0xBFC04391`–`0xBFC08845`). `kernel.drv` as a whole also holds zero
  of both markers, so no part of it can be relocated into the hole.
- **Only `ker_init.bin` (7 markers) and `ker_xsys.bin` (1 each of `jr $ra` and
  `eret`) contain MIPS32 code.** `upgrade.ap` and `adhifi.al` contain code too
  but are app/DSP blobs, not kernel.
- **`NORHWSC.BIN` (2048 bytes, 8 `jr $ra`) and `NORFWSC.BIN` (10752 bytes, 6
  `jr $ra`) are the only boot-stage code, and they are two different stages.**
  `NORHWSC.BIN` begins with the *same* prologue as KER_INIT
  (`addiu sp,sp,-24; sw ra,20(sp); sw s8,16(sp); move s8,sp`) and does register
  read-modify-writes with delay loops at `0xC0100000`/`0xC012001C`, writing an
  `"HW"` marker at `0x9FC24008` — hardware init. `NORFWSC.BIN` instead carries
  `"checksum"`, `"head sum"`, `"param sector"`, `"usb_sn: "` — the USB /
  firmware-upgrade path. **The AFI directory gives both the same load address,
  `0xBFC1E000`, and directory order lets the upgrade blob overwrite the boot
  stage.** Entering `NORHWSC` at `0xBFC1E000` does execute its own functions
  (59 TBs across `0xBFC1E000`–`0xBFC1E5B4`) but it runs past its own 0x800
  bytes into `NORFWSC`'s region and faults with ExcCode 7 (DBE) at
  `0xBFC1EF63`, so it does not fill the hole either.
- **`NORBREC.BIN` is a boot record, and its layout is now partly decoded.**
  It carries a filename table — `KER_TEXTBIN` @0xAFC, `KER_DATABIN` @0xB08,
  `KER_INITBIN` @0xB14, `KER_XSYSBIN` @0xB20, each `\0`-terminated — followed
  immediately by an address array @0xB2C: `0x9fc12000, 0xbfc10138,
  0xbfc02600, 0xbfc08000, 0x9fc1a400, 0xbfc32000, 0xbfc19580`. Two of those
  are already confirmed placements (`0xBFC08000` = kernel.drv resident,
  `0x9FC1A400` = its data). The records before the filename table embed the
  same addresses as 32-bit values (e.g. `0x9FC27000`, `0xBFC02600`,
  `0xBFC10138` at +0xA60). `NORBREC.BIN` itself contains no code markers.
- **All 443 bank triples across every `.ap`/`.drv` load into
  `0x40000000`–`0x48D14600`; none into `0xBFC04xxx`.** The `.sty` files declare
  decode buffers in `0x5Cxxxxxx` only. So the code is not a `.ap`-, `.drv`- or
  `.sty`-based overlay.

**Conclusion: the MIPS16e code at `0xBFC04391`–`0xBFC08845` (~17.6 KB) is not
present in the unpacked firmware package.** It is referenced by the kernel's own
table and by KER_INIT, but no component, boot blob or bank carries it, so it
must come from a stage this analysis cannot see — a mask-ROM stage, the ADFU
recovery path, or a transformed/compressed section that has not been decoded.
This is the state to record, not a gap to paper over with a mapping.

   `ker_xsys.bin` also contains a *bank-switch* dispatch its own header-relative
   table drives: `lui k1,0xbfc2; addu k1,k1,4*flag; lw k1,-26252(k1)` selects an
   IRQ bank from a table at `0xBFC19980`, indexed by the byte flag at
   `0x9FC1A485`. That table is also unplaced.

   The 12-byte bank table exists only in the 11 `.ap` files and every bank load
   address is in SDRAM (`0x40xxxxxx`–`0x48D14600`); all 14 `.drv` files have no
   bank table. So this is *not* `.ap`-style bank loading.

`NORBREC.BIN` (166,400 bytes, AFI load address 0) contains an address array at
`0xB2C` — `0x9fc12000, 0xbfc10138, 0xbfc02600, 0xbfc08000, 0x9fc1a400,
0xbfc32000, 0xbfc19580` — plus a string table at `0x0AFC` naming
`KER_TEXTBIN`, `KER_DATABIN`, `KER_INITBIN`, `KER_XSYSBIN`, so it is a
boot-record / placement table rather than code. Decoding it is the next concrete
step: it is what the real boot chain uses to place the kernel image, and it is the
only identified source that could fill the `0xBFC04xxx` hole.

#### Regression coverage

`tools/qemu/boottest.sh` asserts the six invariants above, including the exact
first-exception state (one IBE, `EPC 5c082d13 cause 6`, EPC frozen). It was
verified to fail loudly both when the kernel deferral is removed and when
`KER_TEXT_ADDR` is put back at `0xBFC33030`.

### Consequence for the recommendation above

The "render one static screen" plan is still the right end goal, but it is now
blocked earlier than assumed: the UI driver's code region has no identified source,
so the drawing entry point cannot be traced until the boot placement question is
resolved. The next milestone is therefore **decode the NORBREC boot-record table**
to complete the memory map, not the SDL2 frontend.

---

## Diagnostic: the 0xBFC32224 boot fault (2026-11-11)

### Verified memory placement map

AFI container (`dec.bin`, 11,659,776 bytes, magic `AFI\0`), 32-byte directory entries
from 0x20 ({name8, ext3, pad, u32 load, u32 foff, u32 size}):

| entry | file offset | size | load address |
|---|---|---|---|
| `NORHWSC.BIN` | 0x5800 | 0x800 | `0xBFC1E000` |
| `NORFWSC.BIN` | 0x6000 | 0x2A00 | `0xBFC1E000` |
| `CARDMBRC.BIN` | 0x8A00 | 0x200 | 0 |
| `NORMBREC.BIN` | 0x8C00 | 0x200 | 0 |
| `CARDPRDU.BIN` | 0x8E00 | 0x2BE00 | 0 |
| `NORBREC.BIN` | 0x34C00 | 0x28A00 | 0 |
| `NOR_ID.BIN` | 0x5D600 | 0x5200 | 0 |
| `FWIMAGE.FW` | 0x62800 | 0xABC200 | 0 (walked recursively) |

FWIMAGE placements, in loader order (later entries overwrite earlier ones at the same
address): `kernel.drv` res `0x002200/0xB00 -> 0xBFC08000`, data `0x002D00/0x7F4 ->
0x9FC1A400`; `ker_text.bin` `0x006C00/0xC00 -> 0xBFC32000`; `ker_init.bin` `0x007800/
0x1800 -> 0xBFC00000`; `ker_xsys.bin` `0x009200/0x800 -> 0xBFC045C0`; then card.drv +
res2, cards.drv, nor_ud.drv, fat_32n.drv, exfatn.drv, udisk.drv, uhost.drv,
usound.drv, aud_dev.drv, drv_lcd.drv, drv_ui.drv (+res2), drv_dac.drv, key.drv, and
the nine `.ap` apps — 28 components in total.

**Correction to an earlier claim in this report:** `NORBREC.BIN` and `NOR_ID.BIN` have
load address **0**, not `0xBFC34C00` and `0x560000`. That was an error — the `foff`
field was being read as the load address. Only NORHWSC/NORFWSC carry a load address,
and both are `0xBFC1E000`, so NORFWSC (the later, larger entry) wins the overlap.

### Root cause: KER_TEXT is not code

`KER_TEXT.BIN` is 3072 bytes and disassembles as MIPS32 into `sltiu`/`.word` garbage
from offset 0. It contains **66 embedded `0xBFC0xxxx` addresses**, every one pointing
into `0xBFC04xxx`–`0xBFC08xxx` — the kernel region — stored as interleaved 16-bit
halves of 32-bit pointers. Its only near-code sequence is a single lazy-binding thunk
at `+0x200`: `lui k0,0xbfc2; addiu k0,k0,-27100; jr k0` → `0xBFC19624`.

Placing it at `0xBFC32000` therefore puts a pointer table where code is expected.
`0xBFC32224` = KER_TEXT+`0x224` = `1e1f64e3`, an invalid opcode. That is the first
faulting instruction.

The overlays are **not** the cause: a minimal map placing only ker_init, ker_xsys,
kernel.drv and ker_text reproduces the identical fault.

### First exception, instrumented

```
entry 0xBFC00000 (KER_INIT):
  do_raise_exception_err: 20 (reserved instruction)
  mips_cpu_do_interrupt enter: PC bfc32224 EPC 00000000
  Status 0x00400004  (BEV set, ERL set, interrupts disabled)
```

Control flow: `0xbfc00000` → `0xbfc00030` (lw clock) → `0xbfc00034` → `0xbfc32224`
(fault) → exception vector `0xbfc00380` → `0xbfc04634` → loop. Six distinct PCs total.

### NORFWSC is the real boot chain — and it runs

`NORFWSC.BIN`'s first 0x200 bytes are all zeros; its code begins at `0xBFC1E200`
(`addiu sp,sp,-40`). Starting the CPU there (a new `pc=` machine property in m30.c
makes this configurable without a rebuild) reaches **43 distinct PCs**, executing
genuine scanner code throughout `0xBFC1E200`–`0xBFC1F286` that never executes when
starting at KER_INIT. It then faults:

```
entry 0xBFC1E200 (NORFWSC):
  do_raise_exception_err: 28 (data bus error)
  mips_cpu_do_interrupt enter: PC bfc1ef62 EPC 00000000
```

`0xBFC1EF62` is inside NORFWSC's own `jalx`-target region and decodes as MIPS32
garbage, so NORFWSC is mixed MIPS32/MIPS16e, or the NOR-flash access it performs
needs hardware that is not modelled.

### Conclusion

The kernel code KER_INIT calls at `0xBFC321C8`–`0xBFC32BC8` is placed by the NOR boot
scanner at run time, and KER_TEXT is that scanner's relocation table. Static placement
cannot reach the kernel entry: a memory-copy stage is required that the machine does
not yet model.

The `pc=` machine property is a real, verified improvement — it makes firmware code
run that was previously unreachable — but the exception loop still terminates both
entry points, so the success criterion of reaching a *new verified code path that does
not loop* is not met.

---

## Boot-chain investigation (2026-11-11, third pass)

### A. Normal boot vs ADFU / upgrade, separated

`NORHWSC.BIN` and `NORFWSC.BIN` are **two different stages, not one scanner**:

| blob | size | `jr $ra` | evidence | role |
|---|---|---|---|---|
| `NORHWSC.BIN` | 0x800 | 8 | same prologue as KER_INIT; register RMW + delay loops at `0xC0100000`/`0xC012001C`; writes `"HW"` at `0x9FC24008` | **normal boot, hardware init** |
| `NORFWSC.BIN` | 0x2A00 | 6 | carries `"checksum"`, `"head sum"`, `"param sector"`, `"usb_sn: "` | **ADFU / USB firmware-upgrade path** |

The AFI directory gives both load address `0xBFC1E000`, and directory order lets the
upgrade blob silently overwrite the boot stage. Entering `NORHWSC` at `0xBFC1E000`
does run its own functions (59 TBs over `0xBFC1E000`–`0xBFC1E5B4`) but it runs past
its own 0x800 bytes into `NORFWSC`'s region and faults ExcCode 7 (DBE) at
`0xBFC1EF63`. **It does not fill the `0xBFC04xxx` hole.**

### B. `NORBREC.BIN` structure, parsed

A filename table of four NUL-terminated names followed immediately by an address array:

```
0x0AFC  "KER_TEXTBIN\0"
0x0B08  "KER_DATABIN\0"
0x0B14  "KER_INITBIN\0"
0x0B20  "KER_XSYSBIN\0"
0x0B2C  address array:
          0x9fc12000  0xbfc10138  0xbfc02600  0xbfc08000
          0x9fc1a400  0xbfc32000  0xbfc19580
```

Two of the seven are already confirmed placements (`0xBFC08000` = kernel.drv
resident, `0x9FC1A400` = its data segment), so the array is a load-address table and
the preceding records embed the same addresses as plain 32-bit values (e.g.
`0x9FC27000`, `0xBFC02600`, `0xBFC10138` at `+0xA60`). `NORBREC.BIN` contains no
MIPS code markers of either ISA. **The record boundaries and the name→address
indexing remain unverified** — four names against seven addresses cannot be paired
by adjacency, and no record-length field has been identified, so this is explicitly
not yet a mapping.

### C. Where the missing MIPS16e routines come from

The earlier conclusion — "the code is not in the firmware" — was **an artifact of
scanning with MIPS32 instruction signatures**. MIPS16e `jr $ra` is the 16-bit
`0xE820`, not the 32-bit `0x03E00008`. Re-scanning with the correct marker:

| kernel.drv region | MIPS16e `jr $ra` |
|---|---|
| resident `0x200–0xD00` | 2 |
| data `0xD00–0x14F4` | 4 |
| **unplaced `0x14F4–0x3200`** | **8** |
| unplaced `0x3200–0x4C00` | 2 |

So the unplaced tail of `kernel.drv` **does** contain MIPS16e code.

The resolution is the **overlay-pointer model** from `kilicdev/actions_flash`'s
`RE_NOTES.md`, which this firmware matches structurally. Its documented encoding is
`tag | window | in_bank_offset | isa_bit` with a fixed per-module window base. In
`ker_text.bin`'s table, 34 of the 128 entries carry a tagged form whose high half is
one of `0x1F00/0x1F04/0x1F08/0x1F0C/0x1F10/0x1F14/0x1F18` or
`0x2F00/0x2F04/0x2F08/0x2F0C/0x2F18/0x2F1C/0x2F20` (increments of 4 = bank index),
and whose low half is **always odd and always in `0x9000–0x9FFF`** — i.e. a fixed
window base of `0x9000` plus an in-bank offset, with the ISA bit set. The remaining
entries are ordinary `0xBFC0xxxx` addresses and zeros.

**So `0xBFC045F4` / `0xBFC045F5` is not a flat address to be mapped: it is a tagged
reference into an overlay bank that has to be loaded first.** That is why nothing in
the unpacked image resolves it, and why adding memory at `0x5C08xxxx` would be wrong.

A MIPS16e oracle was built to test bank placements: a 16-byte MIPS32 stub
(`lui v0,0xbfc0; addiu v0,v0,<target>; jalr v0`) placed at `0xBFC04000` with the
candidate at `0xBFC04010` and `pc=` set to the stub, so QEMU enters MIPS16e at the
target and its `-d in_asm` trace gives the decode. This is how the encodings above
were derived (`jr $ra` = `e820`, `nop` = `6500`).

**A false positive this method produced, recorded so it is not repeated:** placing
all of `kernel.drv` at `0xBFC04010` shifts its resident dispatcher (file `0x380`,
= resident `+0x180`) onto `0xBC04390`, so `0xBFC04391` decodes as `mfc0 k0,$14` and
27/40 KER_TEXT targets appear "clean". That is the displaced copy of the dispatcher
already known to be at `0xBFC06D6C`, not new code.

### D. Expected CPU/memory state at KER_INIT entry

CP0 `Status = 0x00400006` → **BEV = 1, ERL = 1, EXL = 1**, IE = 0. EPC was
`0x5C082D13`, odd, so the CPU was in **MIPS16e mode**. No stack was installed before
the prologue's `addiu sp,sp,-24`, and BSS clearing happens *after* the first call.
The handler table at `0x9FC1A9A4` holds image data, not runtime-populated entries.

### E. What is still missing, precisely

To execute firmware-backed MIPS16e code at `0xBC045F4`/`0xBFC04634`, the missing
evidence is **the bank table that maps the `0x1F0x`/`0x2F0x` tags to file offsets and
load addresses** — the same structure `RE_NOTES.md` documents for `BTENGINE.AP` at
file offset `0x100` (11 banks, 12-byte triples). No `.drv` in this image exposes one;
the 443 12-byte bank triples found across the `.ap` files all load into
`0x40000000`–`0x48D14600` and none is indexed by these tags.

Resolving this needs one of: a decode of the `kernel.drv` header field at `+0x48`
(`0xE00` file offset / `0x2400` size / `0xBF08000` load — almost certainly the
overlay bank table, never parsed), an `actions_flash` implementation reference for
the `KER_TEXT`-style table, or a boot-record/boot-ROM dump. **No read-only hardware
investigation is proposed here; the player was not touched.**

---

## YQHX descriptor decode and the `+0x48` field (2026-11-12)

A full YQHX header parser now runs over all 25 `.drv`/`.ap` modules
(`tools/qemu/yqhx.py`, exercised by `tools/qemu/yqhxtest.py`). Verified
descriptors for `kernel.drv`:

| segment | file foff | size | load |
|---|---|---|---|
| resident | `0x200` | `0xB00` | `0xBFC08000` |
| data | `0xD00` | `0x7F4` | `0x9FC1A400` |

and `kernel.drv`'s resident body is byte-identical to `ker_text.bin`, so the two
names are one module (`ker_text.bin` = resident + 0x100 trailing zeros).

### The `+0x48` entry is not a loadable code section

`+0x48` appears in **every** module, so it is a real header field, but it is not
a `{foff, size}` pair for a code section:

- it **exceeds the file size** in 8 modules (`key.drv`: `0xD00+0x1000` in a
  `0x1600` file; every `.ap`: `0x1D600` in files of `0x3200`-`0x22400`);
- it **starts inside the already-declared data segment** in 5 modules
  (`kernel.drv`: `0xE00` inside data `0xD00-0x14F4`; `fat_32n`/`exfatn`;
  `drv_dac`/`drv_ui`);
- for `.ap` files it is essentially constant (`0x1D600`), which rules out a
  per-module section offset.

Reproducing the earlier "8 MIPS16e `jr $ra` in the tail" claim requires care:
two of the 16 `0xE820` halfwords in `kernel.drv` fall inside the resident
pointer table, so a single `0xE820` is not evidence of a function, exactly as
the phase brief warned. Disassembling the tail as MIPS16e with objdump
(`-m mips:micromips`) produced mostly `.short` undecodable halfwords, and
cross-checking with the QEMU MIPS16e oracle gave non-coherent decodes
(`slti`, `beqzl`, `bnec`, `balc`).

### What was tried and rejected

A behavioural sweep placed `kernel.drv[0x14F4:0x3200]` at every `0x100` base from
`0xBFC04000` to `0xBFC04600` and scored whether `0xBFC04634` decoded as code and
whether the exception vector stopped storming. The metric was not
discriminatory: the `map=` machine option *replaces* the whole firmware loader,
so those runs were already missing 49 of the 54 placements and every base still
produced ~1M `nop`s. A base search under a broken baseline is not evidence, and
no base is claimed as a result.

### Remaining missing information

To place the `0xBFC045F4`/`0xBFC04634` MIPS16e routines the missing evidence is
the **semantics of `+0x48`**, or equivalently a table mapping the `0x1F0x`/`0x2F0x`
tag families (window base `0x9000`, bank index in steps of 4) to file offsets
and load addresses. A candidate would have to be derived from the firmware, and
no such derivation survived checking, so **no fast-boot placement for that region
was implemented**. The existing loader, `boottest.sh` and `kernelmaptest` are
unchanged and still pass; `m30.c` is byte-identical to its last committed state.

---

## MIPS16e correction, test injection, and pointer classification (2026-11-12)

### 1. The previous MIPS16e disassembly was invalid — here is why

Two decoders were tried and both are wrong for MIPS16e:

* `mips64-linux-gnu-objdump -m mips:micromips` decodes **microMIPS**, a different
  encoding. It prints `.short` for most MIPS16e halfwords, so the "incoherent
  disassembly" of `kernel.drv`'s tail proved only that the wrong decoder was used.
* QEMU's `-d in_asm` **translates** MIPS16e correctly (its `24Kc` model has
  `ASE_MIPS16`, and JR/JALR/JALX switch ISA mode from bit 0 of the target), but its
  disassembler never prints it: `print_insn_mips16()` is inside `#if 0` in
  `disas/mips.c`, and `mips16_opcodes` is not linked at all. So `-d in_asm` shows
  MIPS32-style output while the CPU is executing MIPS16e.

What *was* valid from that path: PC advancing by 2 and `hflags` M16 behaviour,
which is how MIPS16e execution was first observed.

`tools/qemu/m16dis.py` now decodes MIPS16e from a table **derived from GAS**
(`mips64-linux-gnu-as -mmips16 -EL`, 3013 encodings), not from a decoder that
guesses. `tools/qemu/m16distest.py` round-trips a freshly assembled function
containing instructions that were never used to build the table: 0 undecoded,
mnemonics reproduced exactly. The three encodings all earlier analysis leaned on
are pinned by the test: `jr $ra` = `0xE820`, `nop` = `0x6500`,
`addiu $sp,$sp,-24` = `0x63FD`.

**Reinspecting `kernel.drv` with the validated decoder:** the unplaced tail
`0x14F4-0x3200` does not decode as coherent MIPS16e (the first halfwords are not
in the table), and the MIPS16e `jr $ra` markers it contains fall in the same
places as before. Combined with the behavioural test below, this region is not
the missing kernel text.

### 2. Non-destructive test injection (`-machine m30,inject=...`)

`map=` replaces the whole firmware loader, which made load-address experiments
unreliable. `inject=` instead applies semicolon-separated `ADDR:PATH+FOFF:SIZE`
overlays **after** the standard load, validating physical ranges, source bounds
and reporting every byte the write changes. Validated by
`tools/qemu/injecttest.sh`:

* an identity injection of `ker_xsys.bin` back at `0xBFC321C8` leaves the
  translated-block set identical (25 blocks, `diff` clean);
* an out-of-bounds source, an unmapped destination and a malformed entry are
  each rejected with a message rather than silently ignored;
* overwrites print old and new values, so overlaps are visible.

### 3. Address classification, with provenance

| value | class | produced by | bit 0 | bank bits |
|---|---|---|---|---|
| `0xBFC045F5` | **verified absolute** | KER_INIT at `0xBFC00050`: `lui v0,0xbfc0; addiu v0,v0,0x45f5` then `jalr` | MIPS16e | none |
| `0xBFC04635` | **verified absolute** | KER_INIT's general vector at `0xBFC00380`: `lui v0,0xbfc0; addiu v0,v0,0x4635` then `jalr` | MIPS16e | none |
| `0xBFC064B0` | **absolute, table-loaded** | plain u32 in `kernel.drv`'s data segment (`0x9FC1A400..0x9FC1ABF4`), 32 occurrences | no | none |
| `0x1F00..0x2F20` (low half `0x9xxx`) | **tagged / unresolved** | `ker_text.bin`'s table: high half steps by 4 (bank index), low half always odd and always `0x9000-0x9FFF` (window `0x9000` + in-bank offset + ISA bit) | MIPS16e | high half, unresolved |

This matches `kilicdev/actions_flash`'s `RE_NOTES.md` pointer encoding
(`tag | window_base | in_bank_offset | isa_bit`), though the M30's bank→file
mapping is unverified and is not assumed to be identical.

### 4. The `0xBFC045F5` memset hypothesis: confirmed, then failed on candidates

Injecting `jr $ra` at `0xBFC32224` makes KER_INIT continue, and it then reaches
`0xBFC045F4` with **`a0 = 0x9FC13D00`, `a1 = 0`, `a2 = 0xE0` (224)** exactly as the
brief hypothesised. So that address really is the BSS-clear entry.

Placing `kernel.drv[0x14F4:0x1D0C]` at `0xBFC045F4` does **not** clear it: with the
BSS pre-filled with `0xFF`, a monitor dump after 2.5 s still reads
`ff ff ff ...` at physical `0x1FC13D00`. That candidate is ruled out.

**No component declares a load address covering `0xBFC045F4`.** Enumerating every
`.drv`/`.ap` resident descriptor in FWIMAGE: none spans `0xBFC045F4`–`0xBFC08845`.
So the ~17.6 KB MIPS16e region is genuinely unrepresented in the unpacked
firmware, and its code must come from a boot stage this analysis cannot see.

---

## Fast boot: early init trace and the first substitute (2026-11-12)

### Phase 1 — the earliest initialisation sequence, measured

`tools/qemu/ktrace.py` turns a bounded `-d in_asm,cpu,int` run into a report of
every block the guest executes before its first exception, with the argument
registers as they stood at entry. The sequence is:

| block | sp | ra | note |
|---|---|---|---|
| `0xbfc00000` | `0x00000000` | `0x00000000` | prologue; saves hit the boot stack |
| `0xbfc00030` | `0x9fc2f000` | `0x00000000` | KER_INIT still on the boot stack |
| `0xbfc00034` | `0x9fc29000` | `0x00000000` | KER_INIT installs its own sp |
| `0xbfc32224` | `0x9fc29000` | **`0xbfc00040`** | the first call, `jal` from `0xBFC00038` |
| `0xbfc3223c` | `0x9fc29000` | `0xbfc00040` | inside the handler, past the `beqz` |
| `0xbfc06d6c` | `0x9fc29000` | `0xbfc00040` | the dispatcher |

At entry to the first call: **`v0 = 0x00000001`** (the clock read-OR'd with 1),
`v1 = 0xC012001C`, `s8 = 0x9FC2EFE8`, and **`Status = 0x00400004` with
`Cause = 0x00000000` and `EPC = 0x00000000`**. At the dispatcher, `k0` holds
`0xBFC00040` (the saved `$ra`) and `k1` the dispatcher address.

So the first kernel call is the exception-system's context-save entry, and
because `Cause` is 0 the dispatcher indexes table entry 0.

### Phase 3 — the BSS-clearing hypothesis is confirmed, and substituted

The call at `0xBFC00050` (after `lui v0,0xbfc0; addiu v0,v0,0x45f5`) reaches
`0xBFC045F4` with **`a0 = 0x9FC13D00`, `a1 = 0`, `a2 = 0xE0`**, i.e. a 224-byte
clear starting at `0x9FC13D00`. That is exactly the expected BSS fill.

Fast boot (`-machine m30,fastboot=on`) fills the *callee slot* at `0xBFC045F4`
with a 12-byte MIPS16e `fill(a0,a1,a2)` assembled from GAS. The caller's `jalr`,
argument setup, return address and ISA mode are untouched real firmware, so from
KER_INIT's side it is an ordinary call. Verified by `fastboottest.py`:

* the target range is zeroed, and memory both before and after a dirtied
  0x400-byte span is left exactly as it was,
* the fill entry executes in three blocks (entry, loop body, return),
* KER_INIT continues to `0xBF00060`, the block after the call,
* **with fast boot off the same transfer happens but the memory stays dirty** —
  the difference is the whole point of the mode,
* `fastboot=on` on its own leaves the executed block set identical to plain
  boot, because the slot is unreachable while the first call still fails.

**Progress achieved:** with fast boot plus a clearly-labelled diagnostic bypass
for the first call, KER_INIT advances past the BSS clear and reaches
**`0xbfc322f8`, real `ker_xsys.bin+0x130` firmware**, which tail-calls
`0xBFC05F90` — a region nothing places. That is a new verified firmware basic
block beyond the previous failure point (`0xbfc32224` → `0xbfc06d6c` only).

### Phase 4 — `0xBFC32224`: what it does, and why it was not bypassed silently

The block is resident `ker_xsys.bin+0x5C`, and the firmware there does
observable work before dispatching:

1. `lb k0, 0x9FC1A482`; if the flag is non-zero, store `sp-176` to `0x9FC1A8A0`
2. `mfc0 k0,$14` → save EPC to `0x13DD8`
3. `move k0,ra` → save `$ra` to `0x13DDC`
4. `jr` to the dispatcher, which indexes the table by `Cause & 0x7c`

Steps 1–3 execute as real firmware and are left alone. Step 4 selects entry 0
(`Cause` is 0), which is `0x5C082D13` → unmapped `0x5C082D12`. That pointer is
firmware, so replacing it would be patching the firmware's own dispatch table,
and the handler that belongs there is absent. **No fast-boot substitution was
made for this call.** The only bypass available is a diagnostic `jr $ra` stub
applied through `inject=`, and it is deliberately kept out of fast boot: the
test asserts fastboot places nothing but the fill routine, so the two can never
quietly merge.

### What is original firmware vs emulated

* original firmware executed: the whole prologue, the clock RMW, the fill
  call site and arguments, `ker_xsys.bin+0x130` at `0xBFC322F8`.
* emulator-supplied: the 12 bytes at `0xBFC045F4` only, and only in fast-boot
  mode. It models one fill operation — no dispatch, no vector, no bank
  loading, and no register it does not already own.

---

## M3U audit: the playlist subsystem is a database reader, not a parser (2026-11-12)

Phase 1 of the custom-firmware work. `tools/m3u_audit.py` answers the question the
brief asked: can a user reach a playlist from the folder browser, and does the
firmware parse `.m3u`?

**The playlist *database* format is real.** `playlist.ap` carries its own
`playlist.sty`, and the firmware names `M3U.LIB`, `MUSIC.LIB` and three
`USERPL1-3.PL` user playlist databases. `browser.ap`, `music.ap`, `playlist.ap`,
`mainmenu.ap`, `mengine.ap`, `setting.ap` and `config.ap` all reference
`M3U.LIB`, so `playlist.ap` renders those databases.

**But `.m3u` files are invisible to the folder browser.** Every `.ap` that
enumerates files carries the same fixed-stride extension array (4 bytes per
slot, three characters plus a NUL). `browser.ap`'s is at file `+0xC188`:

```
MP3 WMA WAV AAC FLAC APE AVI TXT JPG JPEG DSF DFF LRC ASF OGG WMV
AMV AAX AA MP1 MP2 M4A ** ACT ** AIF ** **            (28 slots)
```

`M3U` and `M3U8` are absent from all three arrays. So `.m3u` files are filtered
out by the extension mask -- exactly the case the brief asked to distinguish.
(`M3U` appearing in `playlist.ap` is the *database filename* `M3U.LIB` in a
12-byte-padded name table, not an extension entry; the audit tool asserts both
factss separately so the two cannot be confused again.)

**And there is no `.m3u` parser to reuse.** No `#EXTM3U`, no `#EXTINF`, and no
`.m3u` extension string anywhere in the firmware. `M3U.LIB` is a database built
elsewhere and read directly by the player.

**Consequence:** the README's "M3U handling" is a database *format*, not a
playlist-file parser. A playlist copied to the card is both invisible and
unparseable. The gap is a missing parser, not a missing filter entry, so the
brief's preferred option ("a minimal navigation hook over rewriting the
parser") is not available -- there is nothing to hook into.
