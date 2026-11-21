"""Host prototype for selecting SD-card M30 bitmap themes. See docs/sd-themes.md."""
import argparse
import hashlib
import json
import struct
import os
from pathlib import Path
import re
import tempfile
from zlib import crc32

import sty


def theme_id(value):
    if not re.fullmatch('[a-z][a-z0-9_]{0,7}', value) or value == 'stock':
        raise ValueError('theme ID must be 1–8 lowercase ASCII letters/digits/underscores, start with a letter and differ from stock')
    return value


def install(fw, art, card, name):
    parent = card / 'themes'
    dest = parent / theme_id(name)
    if dest.exists():
        raise ValueError('theme already installed')
    sources = sorted(fw.glob('*.sty'))
    requested = {p.name for p in art.glob('*.ppm')}
    if not requested:
        raise ValueError('no PPM artwork found')
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as temp:
        stage = Path(temp) / name
        stage.mkdir()
        lines = ['M30THEME 1']
        for src in sources:
            base = src.read_bytes()
            names = {f'{src.stem}_{i}.ppm' for i, *_ in sty.bitmaps(base)}
            if not names.intersection(requested):
                continue
            requested -= names
            output = stage / src.name
            sty.cmd_apply([str(src), str(art), str(output)])
            lines.append(f'{src.name} {hashlib.sha256(base).hexdigest()} {crc32(output.read_bytes()):08x}')
        if requested:
            raise ValueError('unknown bitmap slots: ' + ', '.join(sorted(requested)))
        (stage / 'theme.cfg').write_bytes(('\n'.join(lines) + '\n').encode('ascii'))
        wall = art / 'wall.json'
        if wall.exists():
            design = json.loads(wall.read_text(encoding='utf-8'))
            colors = []
            for key in ('sky','distant','mountain','accent'):
                color = design[key]
                if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
                    raise ValueError(f'invalid {key} color')
                colors.extend(bytes.fromhex(color[1:]))
            ridge = design['ridge']
            if len(ridge)!=6 or not all(type(y) is int and 0<=y<240 for y in ridge):
                raise ValueError('ridge needs six heights from 0 through 239')
            (stage / 'wall.bin').write_bytes(struct.pack('<5H6B',0x3157,*sty.to_rgb565(colors),*ridge))
        stage.rename(dest)


def catalog(fw, card, name):
    folder = card / 'themes' / theme_id(name)
    with (folder / 'theme.cfg').open('rb') as f:
        raw = f.read(2049)
    if len(raw) > 2048:
        raise ValueError('oversize manifest')
    lines = raw.decode('ascii').splitlines()
    if len(lines) < 2 or lines[0] != 'M30THEME 1':
        raise ValueError('invalid manifest')
    entries = {}
    for line in lines[1:]:
        filename, digest, checksum = line.split()
        if not re.fullmatch(r'[a-z0-9_]{1,8}\.sty', filename) or filename in entries:
            raise ValueError('invalid or duplicate resource')
        stock = (fw / filename).read_bytes()
        if hashlib.sha256(stock).hexdigest() != digest:
            raise ValueError('incompatible firmware resource')
        candidate = folder / filename
        with candidate.open('rb') as f:
            data = f.read(len(stock) + 1)
        if len(data) != len(stock) or f'{crc32(data):08x}' != checksum:
            raise ValueError('damaged resource')
        # v1 accepts repaints only. Parse trusted firmware and compare every
        # non-pixel region, including style tables and language data.
        cursor = 0
        for _, offset, length, _, _ in sorted(sty.bitmaps(stock), key=lambda slot: slot[1]):
            if data[cursor:offset] != stock[cursor:offset]:
                raise ValueError('changed resource structure')
            cursor = offset + length
        if data[cursor:] != stock[cursor:]:
            raise ValueError('changed resource structure')
        entries[filename] = candidate
    return entries


def active(fw, card):
    try:
        try:
            with (card / 'm30' / 'settings.cfg').open('rb') as f:
                record = f.read(513)
            if len(record) > 512:
                return 'stock', {}
            lines = record.removeprefix(b'\xef\xbb\xbf').splitlines()
            values = [line[6:] for line in lines if line.startswith(b'theme=')]
            if len(values) != 1:
                return 'stock', {}
            raw = values[0]
        except FileNotFoundError:
            with (card / 'themes' / 'active.cfg').open('rb') as f:
                raw = f.read(513)
        if len(raw) == 512:
            raw = raw.rstrip(b"\0")
        if len(raw) > 512:
            return 'stock', {}
        raw = raw.removeprefix(b'\xef\xbb\xbf').rstrip(b' \t\r\n')
        if not re.fullmatch(rb'[a-z][a-z0-9_]{0,7}', raw):
            return 'stock', {}
        name = raw.decode('ascii')
        if name != 'stock':
            return name, catalog(fw, card, name)
    except (OSError, ValueError):
        pass
    return 'stock', {}


def select(fw, card, name):
    if name != 'stock':
        catalog(fw, card, name)
    folder = card / 'm30'
    folder.mkdir(exist_ok=True)
    target = folder / 'settings.cfg'
    try:
        with target.open('rb') as f:
            record = f.read(513)
        if len(record) > 512:
            raise ValueError('settings.cfg exceeds one sector')
    except FileNotFoundError:
        record = b''
    lines = record.decode('utf-8-sig').rstrip(' \r\n').splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith('theme=')]
    if len(matches) > 1:
        raise ValueError('duplicate theme key')
    if matches:
        lines[matches[0]] = 'theme=' + name
    else:
        lines.append('theme=' + name)
    output = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(output) > 512:
        raise ValueError('settings.cfg exceeds one sector')
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as f:
        temp = Path(f.name)
    try:
        with temp.open('wb') as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fw', type=Path, help='unpacked stock fw directory')
    parser.add_argument('card', type=Path, help='mounted card root or scratch directory')
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('install')
    pack.add_argument('id')
    pack.add_argument('art', type=Path)
    commands.add_parser('list')
    commands.add_parser('select').add_argument('id')
    commands.add_parser('status')
    args = parser.parse_args()
    try:
        if args.command == 'install':
            install(args.fw, args.art, args.card, args.id)
        elif args.command == 'select':
            select(args.fw, args.card, args.id)
        elif args.command == 'list':
            print('stock')
            for item in sorted((args.card / 'themes').glob('*')):
                try:
                    catalog(args.fw, args.card, item.name)
                except (ValueError, OSError):
                    continue
                print(item.name)
        else:
            name, entries = active(args.fw, args.card)
            print(name)
            for path in sorted(args.fw.glob('*.sty')):
                print(path.name, entries.get(path.name, path))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
