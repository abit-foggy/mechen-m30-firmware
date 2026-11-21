"""Add a stock-format Settings submenu and place its callbacks in a free bank tail."""
import struct
import sys
from pathlib import Path

desc = struct.Struct('<HHIHH')
row = struct.Struct('<HHIIII')
app, style, menu, blob, discovery = map(Path, sys.argv[1:6])
enter, *actions = [int(s,16) | 1 for s in sys.argv[6:]]
ap = bytearray(app.read_bytes())
code = blob.read_bytes()
assert len(code)<=0x5b0 and not any(ap[0x5e50:0x6400])
assert struct.unpack_from('<II',ap,0x14d0)==(0x9fc1550c,0xbfc1658d)
ap[0x5e50:0x5e50+len(code)]=code

# Extend the application-owned zero-initialized segment for the directory ID
# and its menu display string. The text segment starts at 0xbfc16400.
assert struct.unpack_from('<II',ap,0x38)==(0x4ac,0x9fc15408)
struct.pack_into('<I',ap,0x38,0x4ac+44)
browse=discovery.read_bytes()
assert len(browse)<=0x600 and not any(ap[0x4e00:0x5400])
ap[0x4e00:0x4e00+len(browse)]=browse

mcg = bytearray(menu.read_bytes())
assert mcg[0x980:0x989]==b'ACTMCGGM0' and struct.unpack_from('<HH',mcg,12)==(16,18)
entries=[]
for i in range(18):
    label,n,ptr,parent,index=desc.unpack_from(mcg,16+i*desc.size)
    entries.append((label,bytes(mcg[ptr:ptr+n*row.size]),parent,index))
option=0x40154c01
label,root,parent,index=entries[0]
assert len(root)==10*row.size
entries[0]=(label,root+row.pack(18,164,0,enter,0,option),parent,index)
entries.append((164,b''.join(row.pack(0xffff,165+i,0,fn,0,option) for i,fn in enumerate(actions)),0,10))
struct.pack_into('<H',mcg,14,len(entries))
cursor=16+desc.size*len(entries)
seen={}
for i,(label,data,parent,index) in enumerate(entries):
    if data not in seen:
        seen[data]=cursor
        mcg[cursor:cursor+len(data)]=data
        cursor+=len(data)
    desc.pack_into(mcg,16+i*desc.size,label,len(data)//row.size,seen[data],parent,index)
assert cursor<=0x980

sty=bytearray(style.read_bytes())
for at in (0x10,0x20):
    table,n=struct.unpack_from('<IH',sty,at)
    for i in range(n):
        base,size,kind,count=struct.unpack_from('<IIHH',sty,table+16*i)
        if kind!=1: continue
        pairs=[struct.unpack_from('<II',sty,base+8*j) for j in range(count)]
        assert count>167 and all(base+8*count<=p<=p+k<=base+size for p,k in pairs)
        strings=[bytes(sty[p:p+k]) for p,k in pairs]
        strings[165:168]=[(text+'\0').encode('utf-16-le') for text in ('Stock','Select theme','Next theme')]
        cursor=base+8*count
        seen={}
        for j,data in enumerate(strings):
            if data not in seen:
                seen[data]=cursor
                sty[cursor:cursor+len(data)]=data
                cursor+=len(data)
            struct.pack_into('<II',sty,base+8*j,seen[data],len(data))
        assert cursor<=base+size
app.write_bytes(ap)
style.write_bytes(sty)
menu.write_bytes(mcg)
