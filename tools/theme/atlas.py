"""Generate a standalone HTML map from an unpacked M30 fw directory (requires Pillow)."""
import argparse
import base64
import hashlib
import io
import struct
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

from PIL import Image
import sty


GUIDE = {
    'common': 'Shared UI. 1–3 playback and volume symbols, 4–13 digits, 14–15 large battery icons, 16–17 confirmation and warning, 27–32 smaller battery states, 38–45 checkmark sequence, 72–79 folder and music icons, 80 red bar, 81–83 locks, 102–111 large digits, 122 speaker backdrop.',
    'config': 'Dark backdrop at 0 and six increasingly full charging batteries at 1–6.',
    'logo': 'Seven full-screen logo frames.',
    'end': 'Power-off icon with English lettering baked into the pixels.',
    'mainmenu': 'Dial artwork at 0, 15, 19, 21–23. Slot 20 is an orange alternate. Slots 2–9 contain equalizer graphs. The stock red dial frames contain icons and no item names.',
    'music': '0 album-art placeholder, 2–4 metadata icons, 6 EQ label, 7–8 seek, 11–15 folder and playback-mode symbols, 18–27 time digits, 29–30 pause/play, 34–35 shuffle, 37 track icon.',
    'browser': 'Localized browser labels. Find shared folder and focus art in common.',
    'setting': 'Localized settings labels. Its style header declares 128 × 160, unlike the 320 × 240 display. Treat its dimensions as resource metadata.',
    'playlist': 'Dot indicator states at 4–11 plus bars and backgrounds.',
    'udisk': 'USB connection artwork, battery levels, connection labels and MSC/MTP labels.',
    'upgrade': 'Paired indicator images at 0–9 and progress artwork at 10–12.',
    'usound': 'USB/player icons, MSC/MTP lettering and paired indicators.',
}


def preview(data, width, height):
    words = struct.unpack('<%dH' % (width * height), data)
    img = Image.frombytes('RGB', (width, height), sty.to_rgb888(words))
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def music_layout(data, groups, bits):
    """Decode the music scene lists and the widget fields shared with PD196."""
    scenes = {}
    start, count = groups[0]
    for scene in range(count):
        length, members = struct.unpack_from('<HI', data, start + 20 * scene + 12)
        for index in range(length):
            visible, widget = struct.unpack_from('<HH', data, members + index * 4)
            scenes.setdefault(widget, []).append(f'{scene} (flag {visible})')

    dimensions = {i: (w, h) for i, _, _, w, h in bits}
    rows = []
    for group, kind, stride in [(2, 'Text', 20), (3, 'Number', 28),
                                (4, 'Time', 36), (5, 'Progress', 36)]:
        start, count = groups[group]
        for index in range(count):
            address = start + index * stride
            if group == 2:
                _, x, y, w, h, bx, by, back, ink, flags = struct.unpack_from('<HhhHHhhHHH', data, address)
                detail = f'Foreground {ink:#06x} · backdrop word {back:#06x} at {bx}, {by} · flags {flags:#06x}'
            elif group == 5:
                base, x, y, track, fill, empty = struct.unpack_from('<HhhHHH', data, address)
                w = struct.unpack_from('<H', data, address + 28)[0]
                h = dimensions[track][1]
                detail = f'Base {base} · track {track} · fill {fill} · unfilled {empty}. Height from track bitmap.'
            else:
                x, y, w, h, digit, separator = struct.unpack_from('<hhHHHH', data, address)
                detail = f'First digit {digit} · separator {separator}'
            widget = group * 4096 + index
            membership = ', '.join(scenes.get(widget, [])) or '—'
            rows.append(f'<tr><td>{kind} {widget:#06x}<td>{membership}<td>{address:#x}'
                        f'<td>{x}, {y}<td>{w} × {h}<td>{detail}')
    return ('<h3>Playback layout</h3><p>Scene membership comes from the compiled scene lists. '
            'The bounds describe the stock resource before app-side drawing.</p><table>'
            '<tr><th>Widget<th>Scene<th>File offset<th>Local x, y<th>Size<th>Style fields'
            + ''.join(rows) + '</table>')


def section(path):
    data = path.read_bytes()
    bits = sty.bitmaps(data)
    offset = struct.unpack_from('<I', data, 8)[0]
    magic, styles, directory, height, width = struct.unpack_from('<4sIIHH', data, offset)
    if magic != b'sty\0' or styles != 1:
        raise ValueError(f'{path}: unsupported style header')
    groups = list(struct.iter_unpack('<II', data[directory:directory + 88]))
    pictures, count = groups[1]
    xml_offset = struct.unpack_from('<I', data, 48)[0]
    xml_end = data.index(b'</ResDescriptor>', xml_offset) + len(b'</ResDescriptor>')
    languages = ET.fromstring(data[xml_offset:xml_end]).findall(".//ResEntry[@Type='Language']")
    keys = sorted({node.attrib['Name'] for lang in languages for node in lang.findall('String')})
    name = escape(path.stem)
    out = [f'<section id="{name}"><h2>{name}.sty</h2><p>{escape(GUIDE.get(path.stem, ""))}</p>',
           f'<p>{len(bits)} bitmaps · {len(keys)} string keys · {len(languages)} language groups · '
           f'{width} × {height} style canvas · style header <code>{offset:#x}</code></p>',
           f'<small>SHA-256 <code>{hashlib.sha256(data).hexdigest()}</code></small>']
    refs = {i: [] for i, *_ in bits}
    records = []
    for i in range(count):
        addr = pictures + i * 32
        base, x, y, flag, n, *slots = struct.unpack_from('<HhhBB12H', data, addr)
        if n > len(slots):
            raise ValueError(f'{path}: unsupported picture record at {addr:#x}')
        frames = slots[:n]
        for slot in set(frames):
            if slot in refs:
                refs[slot].append(str(i))
        records.append(f'<tr><td>{i}<td>{addr:#x}<td>{x}, {y}<td>{base}<td>{flag}<td>'
                       + ', '.join(map(str, frames)))
    if records:
        out += ['<details><summary>PictureBox placements and frame order</summary><table>'
                '<tr><th>Record<th>File offset<th>Local x, y<th>First word<th>Flag byte<th>Frame slots',
                *records, '</table></details>']
    if name == 'music':
        out.append(music_layout(data, groups, bits))
    if keys:
        out.append('<details><summary>Localized string keys</summary><p>' +
                   ' · '.join(escape(key) for key in keys) + '</p></details>')
    out.append('<div class="grid">')
    for i, pos, length, w, h in bits:
        png = preview(data[pos:pos + length], w, h)
        rec = ', '.join(refs[i]) or '—'
        out.append(f'<figure><div><img loading="lazy" alt="{name} slot {i}" src="data:image/png;base64,{png}"></div>'
                   f'<figcaption><b>{name}_{i}.ppm</b><br>{w} × {h} · {pos:#x}<br>PictureBox {rec}</figcaption></figure>')
    return '\n'.join(out + ['</div></section>'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fw', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    files = sorted(args.fw.glob('*.sty'))
    if not files:
        parser.error('no .sty files found')
    page = ['''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>M30 firmware theme atlas</title><style>
body{background:#14181d;color:#eff3f7;font:16px/1.5 system-ui;margin:2rem auto;padding:0 1rem;max-width:80rem}
a,summary{color:#a6dbff} nav a{margin-right:1em} summary{cursor:pointer} details{margin:.7rem 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px}figure{margin:0;background:#282e35;padding:8px}
figure div{height:110px;display:grid;place-items:center}img{max-width:100%;max-height:110px;image-rendering:pixelated}
figcaption,small{font-size:13px}code{overflow-wrap:anywhere}th,td{text-align:left;padding:.3em .6em}section{margin:3rem 0}
</style><h1>M30 firmware theme atlas</h1>
<p>Each image shows the stock pixels and the replacement filename accepted by the theme builder. Offsets are relative to the named file.
PictureBox coordinates are local to the layout. A dash means the slot has no frame reference in that table. Other widgets and app code can still draw it.</p><nav>''',
            ' '.join(f'<a href="#{escape(p.stem)}">{escape(p.stem)}</a>' for p in files), '</nav>']
    page.extend(section(p) for p in files)
    args.output.write_text('\n'.join(page) + '</html>\n', encoding='utf-8')


if __name__ == '__main__':
    main()
