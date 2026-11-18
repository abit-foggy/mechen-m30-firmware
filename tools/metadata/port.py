"""Apply the community tag-reader changes to the existing Music module."""
from pathlib import Path
import sys
import struct

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import bps

# (file offset, overlay address, loaded size) from music.ap's bank table.
BANKS = (
    (0x11F00, 0x781DB200, 0x77C),  # buffered I/O and parser dispatch
    (0x1A600, 0x713D2500, 0x7D8),
    (0x1AE00, 0x71412500, 0x768),
    (0x1B600, 0x71452500, 0x7F8),
    (0x1BE00, 0x71492500, 0x668),
    (0x1C500, 0x714D2500, 0x454),
    (0x1CA00, 0x71512500, 0x41C),
    (0x1CF00, 0x71552500, 0x4AC),
    (0x1D400, 0x71592500, 0x6CC),
    (0x1DC00, 0x71612500, 0x800),  # UTF-8 conversion and ID3 text handling
)

def collect(module):
    for bank in BANKS:
        if struct.pack("<III", *bank) not in module[0x100:0xC00]:
            raise ValueError(f"missing metadata bank {bank[1]:#x}")
    return b"".join(module[start:start + size] for start, _, size in BANKS)

def main(path):
    module = bytearray(path.read_bytes())
    result = bps.apply(collect(module), (Path(__file__).parent / "community.bps").read_bytes())
    cursor = 0
    for start, _, size in BANKS:
        module[start:start + size] = result[cursor:cursor + size]
        cursor += size
    path.write_bytes(module)

if __name__ == "__main__":
    main(Path(sys.argv[1]))
