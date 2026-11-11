#!/bin/sh
# Boot-chain regression test for the custom ATJ2127 QEMU machine (hw/mips/m30.c).
#
# The kernel/driver overlay collision at 0xBFC30000 silently regresses: if the
# drivers are placed after the kernel, udisk.drv/usound.drv overwrite
# ker_xsys.bin+0x5C and `jal 0xbfc32224` faults on overlay garbage. Nothing
# errors, the emulator just loops, so it needs an explicit assertion.
#
# Asserts three things about the guest's own disassembly, all of which were
# verified by hand against the firmware image:
#   1. 0xBFC32224 is ker_xsys.bin+0x5C: `beqz k0,0xbfc3223c`
#   2. the exception handler saves EPC/ra to 0x13DD8/0x13DDC and reaches the
#      dispatcher at 0xBFC06D6C
#   3. the dispatcher at 0xBFC06D6C is `mfc0 k0,$14`, not a nop sled
#
# Usage: tools/qemu/boottest.sh   (run from anywhere; exits non-zero on failure)

set -u
QEMU=${QEMU:-/home/foggy/m30/qemu/build/qemu-system-mipsel}
FW=${FW:-/home/foggy/m30/mechen-m30-firmware/build/work/stock/dec.bin}
LOG=$(mktemp /tmp/m30boot-XXXXXX) 2>/dev/null || LOG=/tmp/m30boot-$$.log
trap 'rm -f "$LOG"' EXIT

for f in "$QEMU" "$FW"; do
    [ -e "$f" ] || { echo "boottest: missing $f"; exit 1; }
done

# Short and bounded: the chain under test is the first few dozen instructions.
timeout 6 "$QEMU" -machine m30,fb=0x50100000,fbw=320,fbh=240 -kernel "$FW" \
    -nographic -monitor none -serial none -d in_asm,int -D "$LOG" >/dev/null 2>&1

[ -s "$LOG" ] || { echo "boottest: no trace produced"; exit 1; }
rc=0

# 1. the jal target must decode as the ker_xsys handler entry
got=$(awk '/^0xbfc32224:/{sub(/^[^ \t]*[ \t]+/,""); print; exit}' "$LOG")
if [ "$got" = "beqz	k0,0xbfc3223c" ]; then
    echo "PASS  0xBFC32224 is ker_xsys.bin+0x5C: beqz k0,0xbfc3223c"
else
    echo "FAIL  0xBFC32224 should be ker_xsys.bin+0x5C ('beqz k0,0xbfc3223c'), got '$got'"
    echo "      (a garbage op here means a driver overlay clobbered ker_xsys.bin)"
    rc=1
fi

# 2. the handler must reach the dispatcher, i.e. the EPC/ra save path ran
if grep -q '^0xbfc3223c:' "$LOG"; then
    echo "PASS  handler reached the EPC/ra save block at 0xBFC3223C"
else
    echo "FAIL  handler never reached 0xBFC3223C (the mfc0 \$k0,\$14 block)"
    rc=1
fi

# 3. the dispatcher must be real code, not the nop sled of empty SRAM
got=$(awk '/^0xbfc06d6c:/{sub(/^[^ \t]*[ \t]+/,""); print; exit}' "$LOG")
if [ "$got" = "mfc0	k0,\$14" ]; then
    echo "PASS  0xBFC06D6C is the dispatcher: mfc0 k0,\$14"
else
    echo "FAIL  0xBFC06D6C should be the dispatcher ('mfc0 k0,\$14'), got '$got'"
    echo "      (a 'nop' here means KER_TEXT is not at 0xBFC06BEC)"
    rc=1
fi

# 4. the boot must not fault at the jal target itself
if grep -q 'PC bfc32224 ' "$LOG"; then
    echo "FAIL  the CPU took an exception at 0xBFC32224 (the original fault is back)"
    rc=1
else
    echo "PASS  no exception taken at the jal target 0xBFC32224"
fi

[ $rc = 0 ] && echo "boottest: OK" || echo "boottest: FAILED"
exit $rc
