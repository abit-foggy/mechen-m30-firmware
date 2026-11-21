"""Install an extracted Nightbay bundle and migrate the two preference formats."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

def put(path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        with tmp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if path.read_bytes() != data:
            raise OSError(f'copy verification failed for {path}')
    finally:
        tmp.unlink(missing_ok=True)

def config(card, installed):
    destination = card/'m30/settings.cfg'
    if destination.exists():
        data = destination.read_bytes()
        if len(data)>512:
            raise ValueError('existing settings.cfg exceeds 512 bytes')
        try:
            data.decode('utf-8-sig')
        except UnicodeDecodeError:
            # Earlier picker builds could append the intended ID with a binary
            # key from a displaced overlay. Recover only this recognizable case.
            lines=data.rstrip(b' \r\n').split(b'\n')
            key, sep, value=lines[-1].partition(b'=')
            if not sep or not re.fullmatch(rb'[a-z][a-z0-9_]{0,7}',value):
                raise ValueError('unrecognized damaged settings.cfg')
            choice=value.decode()
            if choice!='stock' and choice not in installed:
                raise ValueError('damaged setting does not identify an installed theme')
            if not any(c<32 or c>=128 for c in key):
                raise ValueError('unrecognized damaged settings key')
            prefix=b'\n'.join(lines[:-1]).decode('utf-8-sig')
            entries=prefix.splitlines()
            indices=[i for i,line in enumerate(entries) if line.startswith('theme=')]
            if len(indices)!=1:
                raise ValueError('cannot identify the original theme setting')
            entries[indices[0]]='theme='+choice
            data=('\n'.join(entries)+'\n').encode('utf-8')

    else:
        legacy = card/'themes/active.cfg'
        theme = 'stock'
        if legacy.exists():
            raw = legacy.read_bytes()
            if len(raw)==512:
                raw=raw.rstrip(b'\0')
            candidate=raw.removeprefix(b'\xef\xbb\xbf').rstrip(b' \t\r\n')
            if not re.fullmatch(rb'[a-z][a-z0-9_]{0,7}',candidate):
                raise ValueError('invalid legacy theme ID; existing files preserved')
            theme = candidate.decode()
        data = f'theme={theme}\n'.encode()
    if len(data)<512:
        data=(data+b'\n').ljust(512,b' ')
    return data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('card',nargs='?',type=Path,help='mounted card directory')
    args=parser.parse_args()
    card=args.card
    if card is None:
        devices=json.loads(subprocess.check_output(
            ['lsblk','--json','--list','--output','PATH,LABEL'],text=True))
        matches=[d for d in devices['blockdevices'] if d['label']=='MECHEN M30']
        if len(matches)!=1:
            raise SystemExit('Connect the M30 in USB storage mode, or pass its mount directory.')
        dev=Path(matches[0]['path'])
        def mountpoint():
            return subprocess.check_output(['lsblk','-dn','-o','MOUNTPOINT',dev.resolve()],text=True).strip()
        if not mountpoint():
            subprocess.run(['udisksctl','mount','-b',dev.resolve()],check=True)
        mounted=mountpoint()
        if not mounted or not os.path.ismount(mounted):
            raise SystemExit('The M30 is not mounted.')
        card=Path(mounted)
    if not card.is_dir():
        raise SystemExit('Card directory does not exist.')
    base=Path(__file__).resolve().parent
    packs=sorted(p for p in (base/'themes').iterdir() if p.is_dir())
    installed={p.name for p in (card/'themes').glob('*') if p.is_dir()}
    prefs=config(card,installed | {p.name for p in packs})
    for pack in packs:
        for asset in sorted(pack.iterdir()):
            put(card/'themes'/pack.name/asset.name,asset.read_bytes())
    put(card/'MECHEN_M30.HEX',(base/'MECHEN_M30.HEX').read_bytes())
    put(card/'m30/settings.cfg',prefs)
    os.sync()
    print(f'Copied and verified firmware, theme packs and m30/settings.cfg on {card}')

if __name__=='__main__':
    main()
