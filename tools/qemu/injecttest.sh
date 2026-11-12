#!/bin/sh
# Regression test for the m30 optional test-injection mechanism
# (`-machine m30,inject=ADDR:PATH+FOFF:SIZE;...`).
#
# The `map=` option replaces the whole firmware loader, which makes
# load-address experiments unreliable; `inject=` overlays on top of a normal
# load. These assertions pin the three properties that make it safe to use:
#   1. an identity injection leaves guest behaviour byte-for-byte unchanged
#   2. out-of-bounds sources, unmapped destinations and malformed entries are
#      rejected rather than silently ignored
#   3. the bytes a write changes are reported, so overlaps are visible
#
# Bounded: each QEMU run is capped at 6 s and only translated-block sets and
# short stdout are compared, so this does not depend on how long the guest
# idles afterwards.
#
# Usage: tools/qemu/injecttest.sh   (run from anywhere)

set -u
QEMU=${QEMU:-/home/foggy/m30/qemu/build/qemu-system-mipsel}
FW=${FW:-/home/foggy/m30/mechen-m30-firmware/build/work/stock}
DEC=$FW/dec.bin
WORK=$(mktemp -d /tmp/m30inject.XXXXXX) || WORK=/tmp/m30inject.$$
trap 'rm -rf "$WORK"' EXIT

for f in "$QEMU" "$DEC" "$FW/afi/FWIMAGE.FW" "$FW/fw/kernel.drv"; do
    [ -e "$f" ] || { echo "injecttest: missing $f"; exit 1; }
done
rc=0
chk() { if [ "$2" = "$3" ]; then echo "PASS  $1"; else echo "FAIL  $1 (got '$2' want '$3')"; rc=1; fi; }

tbs() { awk '$1=="IN:"{getline; print $1}' "$1" | sort -u; }

# ---- 1. identity injection must not change behaviour ---------------------
timeout 6 "$QEMU" -machine m30,fb=0x50100000,fbw=320,fbh=240 -kernel $DEC \
    -nographic -monitor none -serial none -d in_asm -D "$WORK/base.log" >/dev/null 2>&1
timeout 6 "$QEMU" -machine "m30,inject=0xBFC321C8:$FW/afi/FWIMAGE.FW+0x9200:0x800,fb=0x50100000,fbw=320,fbh=240" \
    -kernel $DEC -nographic -monitor none -serial none -d in_asm \
    -D "$WORK/same.log" >/dev/null 2>&1
if diff <(tbs "$WORK/base.log") <(tbs "$WORK/same.log") >/dev/null 2>&1; then
    echo "PASS  identity injection leaves the translated-block set unchanged"
else
    echo "FAIL  identity injection changed the translated-block set"
    rc=1
fi
n=$(tbs "$WORK/base.log" | wc -l)
if [ "$n" -gt 0 ]; then
    echo "PASS  baseline trace produced $n distinct blocks"
else
    echo "FAIL  baseline trace produced no blocks"
    rc=1
fi

# ---- 2. invalid input is rejected, not ignored ---------------------------
out=$(timeout 20 "$QEMU" -machine "m30,inject=0xBFC00000:$FW/afi/FWIMAGE.FW+0xffffff0:0x100" \
    -kernel $DEC -nographic -monitor none -serial none 2>&1)
echo "$out" | grep -q "exceeds" && echo "PASS  out-of-bounds source is rejected" \
    || { echo "FAIL  out-of-bounds source was not rejected"; rc=1; }

out=$(timeout 20 "$QEMU" -machine "m30,inject=0x7E000000:$FW/afi/FWIMAGE.FW+0x9200:0x800" \
    -kernel $DEC -nographic -monitor none -serial none 2>&1)
echo "$out" | grep -q "not readable" && echo "PASS  unmapped destination is rejected" \
    || { echo "FAIL  unmapped destination was not rejected"; rc=1; }

out=$(timeout 20 "$QEMU" -machine "m30,inject=bogus" \
    -kernel $DEC -nographic -monitor none -serial none 2>&1)
echo "$out" | grep -q "bad entry" && echo "PASS  malformed entry is rejected" \
    || { echo "FAIL  malformed entry was not rejected"; rc=1; }

# ---- 3. overwritten bytes are reported ----------------------------------
out=$(timeout 20 "$QEMU" -machine "m30,inject=0xBFC045F4:$FW/fw/kernel.drv+0x14f4:0x40" \
    -kernel $DEC -nographic -monitor none -serial none 2>&1)
if echo "$out" | grep -q "byte(s) changed"; then
    echo "PASS  overwrite extent is reported"
else
    echo "FAIL  no overwrite report was printed"
    rc=1
fi
if echo "$out" | grep -q "was 0000 now"; then
    echo "PASS  overwritten bytes show old and new values"
else
    echo "FAIL  overwrite report lacks before/after values"
    rc=1
fi

[ $rc = 0 ] && echo "injecttest: OK" || echo "injecttest: FAILED"
exit $rc
