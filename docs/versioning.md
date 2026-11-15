# Firmware versioning

Every build of this firmware identifies itself on the player under
**Settings > Information**, without touching the vendor metadata:

| row | stock | patched |
|-----|-------|---------|
| model | `M30` | `M30` (unchanged) |
| version | `  V1.101.10` | `0.1.0-dev` / `0.1.0-nightly` / `0.1.0-release` |
| date | `2025-06-25` | build ID / short commit / tag (e.g. `d3e852eb`, `cccdd6e`, `v0.1.0`) |

The original firmware version and date are never displayed, and the
`FWIMAGE.FW` header (magic, `1.101.10`, the `+0x10` checksum that the repacker
recomputes, the NOR ID) is left exactly as the vendor shipped it.

## Channels

The base version lives in the [`VERSION`](../VERSION) file at the repo root —
the single source of truth for the patch, the metadata tool, and CI. Select
the channel with the environment variable:

```sh
BUILD_CHANNEL=dev ./build.sh stock.HEX build        # default
BUILD_CHANNEL=nightly ./build.sh --test stock.HEX build
BUILD_CHANNEL=release ./build.sh --test stock.HEX build
```

| channel | displayed version | displayed identifier | rules |
|---------|-------------------|----------------------|-------|
| `dev` | `<base>-dev` | 8-hex-digit build ID | always allowed; the ID is a deterministic hash of the firmware-relevant source (`VERSION`, `build.sh`, `tools/`, `patches/`) plus the build configuration — identical inputs give an identical ID, any change (committed or not) changes it; no timestamps, no randomness; `build/` output is ignored |
| `nightly` | `<base>-nightly` | short (7-hex) commit SHA of `HEAD` | clean working tree required (dirty tree → build aborts) |
| `release` | `<base>-release` | the tag `v<base>` | clean tree required **and** `HEAD` must be exactly tagged `v<base>` (e.g. `v0.1.0` for `VERSION` `0.1.0`); a mismatch aborts the build |

The suffixes (`-dev` / `-nightly` / `-release`) are shown on the device only;
GitHub tags never carry them. `tools/version/version.py` prints the metadata
as shell lines (`CHANNEL=`, `VERSION=`, `IDENT=`, `BASE=`, `COMMIT=`, `DIRTY=`)
or JSON (`--json`, `--out FILE`); `build.sh` writes the latter to
`OUTDIR/version.json` for the release automation.

## How the Information screen is patched

Reverse-engineered in `setting.ap` (see `docs/reverse-engineering.md`):

- The Information callback is `sub_40115074` in bank `0x40114c00`
  (setting.ap file offset `0x2c00`, size `0x800`). It stores three string
  pointers at struct offsets 72/76/80 and renders three rows.
- The three strings are referenced by PC-relative MIPS16e `la $v0, imm8(PC)`
  instructions — `target = instr + imm8*4 - 2`, imm8 unsigned:
  - `0x4011507a` (file `0x307a`, hw `0x0a23`) → `0x40115104` `"M30"` — **untouched**
  - `0x4011507e` (file `0x307e`, hw `0x0a23`) → `0x40115108` `"  V1.101.10"` — version row
  - `0x40115082` (file `0x3082`, hw `0x0a25`) → `0x40115114` `"2025-06-25"` — date row
- The stock version field is only 12 bytes, far too small for a longer string,
  so the stock strings stay in place as dead data and the two row pointers are
  **redirected** to new strings written into the verified all-zero tail of the
  same bank: guest `0x401153b8..0x40115400` (file `0x33b8..0x3400`, 0x48 bytes;
  the `legal.txt` / `m_type.txt` strings end just before it). The version string
  goes to `0x401153b8`, the identifier to `0x401153d8`, each in a 0x20-byte slot.

`tools/version/patch_version.py` asserts every stock byte it depends on (bank
table entry, the three `la` halfwords and their decoded targets, the three stock
strings, the zero tail) before writing, re-encodes only the two row `la`s
(keeping each instruction's register field), and re-reads the result to prove
that only the two halfwords and the two slots changed. The re-encoded
instructions were verified by disassembling the patched bank in IDA Pro:
`la $v0, "0.1.0-dev"` / `la $v0, "d3e852eb"`.

A successful repack does **not** prove the screen renders correctly — that is
what the hardware checklist below is for.

## CI releases (prepared, not yet enabled)

`.github/workflows/nightly.yml` and `.github/workflows/release.yml` are written
but nothing has been pushed or published. They need, once, in the GitHub repo
settings:

- a secret `STOCK_HEX_B64` — base64 of the official 2025-06-26
  `MECHEN_M30.HEX` (the vendor firmware is not in the repo; `build.sh` refuses
  any file whose sha256 is not `6c7e27c8…51258`, so a wrong secret fails safe);
- Actions write permission for `contents` (to move the `nightly` tag and create
  releases).

**nightly** (push to `main` + manual dispatch): clean checkout →
`BUILD_CHANNEL=nightly ./build.sh --test` → artifact verified → the movable
tag `nightly` is force-moved to the commit and the rolling GitHub release
`nightly` is updated with the artifact `MECHEN_M30.HEX` replaced in place
(`--clobber`); the full commit SHA goes into the release description.

**release** (push of a `v*` tag): the workflow first checks
`tag == v$(cat VERSION)`, then builds from the exact tag with
`BUILD_CHANNEL=release` (which independently refuses a dirty tree or a
tag/VERSION mismatch), verifies, and publishes a release titled with the bare
version (`0.1.0`) on tag `v0.1.0` with `MECHEN_M30.HEX` attached.
`gh release create` fails if the release already exists, so stable tags and
releases are immutable — never overwritten.

## Hardware test checklist (do not flash automatically)

Install a build the normal way (copy `MECHEN_M30.HEX` to the card root, then on
the player **Setting > Auto upgrade**), then on **Settings > Information** check:

1. the model row still reads `M30`;
2. the version row reads the channel's version (`0.1.0-dev`, `0.1.0-nightly`,
   `0.1.0-release`) and is **not clipped** on the right edge of the LCD;
3. the third row reads the identifier: 8-hex build ID (dev), 7-hex commit
   (nightly), or `v0.1.0` (release) — and matches `build/version.json`;
4. two consecutive dev builds with no source change show the **same** build ID;
   after any source edit the ID changes;
5. `BUILD_CHANNEL=nightly` on a dirty tree aborts the build with exit 2;
   `BUILD_CHANNEL=release` without the exact tag `v0.1.0` aborts too;
6. no other Settings screens regressed (the patch touches only the two `la`
   halfwords and the 0x48-byte zero tail of bank `0x40114c00`).

## Tests

`tools/version/test_version.py` (run by `./build.sh --test`) covers: per-channel
displayed version, dev build-ID determinism and sensitivity to source/config/
uncommitted files (and insensitivity to `build/` output), nightly short-SHA and
dirty-tree rejection, release tag match/mismatch and dirty-tree rejection,
JSON metadata, patch determinism, refusal on non-stock or already-patched
bytes, and byte isolation (only the two `la` halfwords + two tail slots change;
header, bank table and stock strings untouched).

## Limitations

- Rendering on the real LCD is not proven by the build; only the hardware
  checklist above confirms it. The longest string (`0.1.0-nightly`, 13 chars)
  is wider than the stock version row (11 chars) — check for clipping.
- The dev build ID covers `VERSION`, `build.sh`, `tools/`, `patches/` only;
  changes to `docs/` or the workflows do not change it (they do not affect the
  firmware image).
- The `nightly` tag is movable by design; only `v*` tags are immutable.
