"""Execute the stock slot-37 draw on a 24Kc with host-backed file/LCD services."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

import sdtheme
import sty

HERE = Path(__file__).resolve().parent


def main(fw):
    stock = fw / 'music.sty'
    for path, digest in [
        (fw / 'drv_ui.drv', '011f4e6a50738026ac641370f493c5df2e59adc435871d8a213e717604d2576a'),
        (stock, '85c88fb159ae3dbbe19fb31282afb8f7831d541be9b8d931678e815320ea4ca1'),
    ]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'{path}: unsupported stock image for these instruction offsets')
    stock_bytes = stock.read_bytes()
    _, offset, size, _, _ = sty.bitmaps(stock_bytes)[37]
    original = stock_bytes[offset:offset + size]
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        exe = work / 'draw'
        subprocess.run(['mips64-linux-gnu-gcc', '-mabi=32', '-EL', '-march=mips32r2',
                        '-mno-abicalls', '-fno-pic', '-G0', '-static', '-no-pie',
                        '-nostdlib', '-Os', '-Wl,-e,_start', HERE / 'probe/draw.S',
                        HERE / 'probe/draw.c', '-o', exe], cwd=fw, check=True)
        cmd = ['qemu-mipsel-static', '-cpu', '24Kc', exe, stock]
        card = work / 'card'
        card.mkdir()
        sdtheme.install(fw, HERE / 'examples/skytrack', card, 'skytrack')
        sdtheme.select(fw, card, 'skytrack')
        _, resources = sdtheme.active(fw, card)
        themed = resources['music.sty']
        replacement = themed.read_bytes()[offset:offset + size]
        assert original != replacement
        assert subprocess.check_output(cmd) == original
        assert subprocess.check_output([*cmd, themed]) == replacement
        themed.unlink()
        assert subprocess.check_output([*cmd, themed]) == original
        print('PASS: stock note, SD star, and missing-file fallback; 800 RGB565 bytes each')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
