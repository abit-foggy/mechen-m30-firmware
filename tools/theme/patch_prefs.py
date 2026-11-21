"""Install guarded post-default callbacks and wrap the two stock shuffle rows."""
from pathlib import Path
import struct
import sys

symbols=[int(x,16)|1 for x in sys.argv[1:]]
for app,bank,va,offset,pointer,callback in [
    ('music',0xcc00,0x40654c00,0x180,0x14d8,symbols[0]),
    ('setting',0xc00,0x40014c00,0x100,0x1558,symbols[1]),
    ('config',0x7600,0x71152500,0x100,0x16a4,symbols[2]),
]:
    path=Path(app+'.ap')
    data=bytearray(path.read_bytes())
    blob=Path('prefs_'+app+'.bin').read_bytes()
    assert struct.pack('<III',bank,va,0x800) in data[:0xc00]
    assert offset+len(blob)<=0x800 and not any(data[bank+offset:bank+offset+len(blob)])
    assert va+offset<=callback<va+offset+len(blob)
    assert struct.unpack_from('<I',data,pointer)[0]==0x48b54691
    struct.pack_into('<I',data,pointer,callback)
    data[bank+offset:bank+offset+len(blob)]=blob
    wall_bank,wall_va,wall_offset={
        'music':(0x7400,0x40354c00,0x200),
        'setting':(0x1c00,0x40094c00,0x300),
        'config':(0x9600,0x71252500,0x100),
    }[app]
    wall=Path('wall_'+app+'.bin').read_bytes()
    assert struct.pack('<III',wall_bank,wall_va,0x800) in data[:0xc00]
    start=wall_bank+wall_offset
    assert wall_offset+len(wall)<=0x800 and not any(data[start:start+len(wall)])
    data[start:start+len(wall)]=wall
    path.write_bytes(data)

path=Path('setting.mcg')
data=bytearray(path.read_bytes())
label,count,rows=struct.unpack_from('<HHI',data,16+14*12)
assert (label,count)==(144,2)
for i,old in enumerate([0x401551c9,0x40155201]):
    pos=rows+i*20+8
    assert struct.unpack_from('<I',data,pos)[0]==old
    struct.pack_into('<I',data,pos,symbols[3+i])
path.write_bytes(data)
