"""Install reload on the music file selector's mount operation."""
from pathlib import Path
import struct
import sys

path, blob = map(Path, sys.argv[1:3])
entry = int(sys.argv[3],16)|1
data = bytearray(path.read_bytes())
code = blob.read_bytes()
assert bytes.fromhex('006e296f3fb2c0ea91ea40d8') == data[0xf1f6:0xf202]
assert data[0xf2f4:0xf2f8] == struct.pack('<I',0xbfc16bb1)
assert 0 < len(code) <= 0x700 and not any(data[0x8d00:0x9400])
assert 0x40414d00 <= entry < 0x40414d00+len(code)
data[0x8d00:0x8d00+len(code)] = code
struct.pack_into('<I',data,0xf2f4,entry)
path.write_bytes(data)
