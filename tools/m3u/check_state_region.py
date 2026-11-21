"""Check the physical RAM reserved for the shared playlist against stock module headers."""
from pathlib import Path
import struct
import sys

root = Path(sys.argv[1])
start, end = 0x1fc10880, 0x1fc10a00
owners = []
for module in root.iterdir():
    if not module.is_file():
        continue
    data = module.read_bytes()
    if data[4:8] != b'yqhx':
        continue
    segments = [struct.unpack_from('<III', data, off) for off in (8, 20, 32)]
    segments.extend((None, *struct.unpack_from('<II', data, off)) for off in (0x30, 0x38))
    for file_offset, size, address in segments:
        address &= 0x1fffffff
        if size and address < end and address + size > start:
            owners.append(module.name)
            assert file_offset is not None and address <= start and end <= address + size
            offset = file_offset + start - address
            assert data[offset:offset + end - start] == bytes(end - start)
assert owners == ['key.drv'], owners
