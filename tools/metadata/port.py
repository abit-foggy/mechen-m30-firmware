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

def port_library_finder(playlist, stock_music, music):
    # The library scanner has its own copy of the FLAC block finder. Its
    # read and seek functions occupy the same offsets in a different bank.
    start, end = 0x1C66C, 0x1C6E0
    target = 0xE56C
    stock = bytes(stock_music[start:end])
    new = bytes(music[start:end])
    def relocate(code):
        for tail in (bytes.fromhex("f06c"), bytes.fromhex("366d")):
            source = bytes.fromhex("f018") + tail
            if code.count(source) != 1:
                raise ValueError("unexpected FLAC reader call")
            code = code.replace(source, bytes.fromhex("3018") + tail)
        return code
    if playlist[target:target + len(stock)] != relocate(stock):
        raise ValueError("unexpected library FLAC block finder")
    playlist[target:target + len(stock)] = relocate(new)


def main(path, playlist_path):
    module = bytearray(path.read_bytes())
    result = bps.apply(collect(module), (Path(__file__).parent / "community.bps").read_bytes())
    cursor = 0
    for start, _, size in BANKS:
        module[start:start + size] = result[cursor:cursor + size]
        cursor += size
    playlist = bytearray(playlist_path.read_bytes())
    port_library_finder(playlist, path.read_bytes(), module)
    playlist_path.write_bytes(playlist)
    path.write_bytes(module)

if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
