#!/bin/sh
# Drive IDA headless over M30 firmware banks as MIPS16e.
#
#   m30_ida.sh STOCK|COMM TARGET_ADDR COUNT [BANK_FILE...]
#
# BANK_FILE arguments are raw bank images (no header) to attach as extra
# segments so cross-references resolve; the first is the main image.
# Environment: IDA=/path/to/idat, BANKBASE=paragraph base for the first bank.
set -u
WHICH="${1:-stock}"; TGT="${2:-0}"; CNT="${3:-40}"; shift 3 2>/dev/null || shift $#
IDA=${IDA:-/home/foggy/ida-pro-9.4/idat}
BASE=${BANKBASE:-0x71012500}
HERE=$(dirname "$0")
OUTDIR=$(mktemp -d /tmp/m30ida.XXXXXX)
MAIN="$OUTDIR/main.bin"
if [ $# -gt 0 ]; then cp "$1" "$MAIN"; shift; fi
: > "$OUTDIR/extra.txt"
for f in "$@"; do echo "0 $f" >> "$OUTDIR/extra.txt"; done
printf '%s\n' "$TGT" > /tmp/m30ida_spec.txt
printf '%s\n' "$CNT" >> /tmp/m30ida_spec.txt
cp "$OUTDIR/extra.txt" /tmp/m30ida_extra.txt
B=$(python3 -c "print(hex(0x$(printf %s "$BASE" | sed 's/^0x//')//16))" 2>/dev/null || echo 0x7101250)
rm -f "$OUTDIR/out.i64"
timeout 400 "$IDA" -A -a -c -pmipsl -b"$B" -S"$HERE/m30_mips16e.py" \
    -L"$OUTDIR/ida.log" -o"$OUTDIR/out.i64" "$MAIN" >/dev/null 2>&1
rc=$?
cat /tmp/m30ida_out.txt 2>/dev/null
rm -rf "$OUTDIR"
exit $rc
