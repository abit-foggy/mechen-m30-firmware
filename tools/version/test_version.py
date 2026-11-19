#!/usr/bin/env python3
"""Test the channel versioning: tools/version/version.py + patch_version.py.

usage: test_version.py STOCK_setting.ap PATCHED_setting.ap VERSION IDENT CHANNEL

Group A checks the build's own patched setting.ap (arguments 1-5):
  - only the two `la` halfwords and the two 0x20-byte tail slots differ from stock;
  - the .ap header and bank table are untouched (vendor metadata preserved);
  - the stock strings stay in place and the model-row `la` is unchanged;
  - the new `la` instructions decode to the new strings, which equal VERSION/IDENT;
  - VERSION matches the channel (BASE-dev / BASE-nightly / BASE-release);
  - the patch is deterministic and refuses to run on non-stock bytes.

Group B runs version.py in a throwaway git repo (the real repo is never touched):
  - dev: identical inputs -> identical build ID; config, source edits, and
    uncommitted files change it; build/ outputs do not;
  - nightly: dirty tree rejected; clean tree -> short SHA of HEAD, and a new
    commit changes the ID;
  - release: missing/mismatched tag and dirty tree rejected; exact tag <base>
    -> identifier <base>;
  - --json / --out produce the same metadata for the release automation.

Prints PASS/FAIL lines; exits non-zero if any check fails.
"""
import ast
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import patch_version as pv  # noqa: E402

VERSION_PY = os.path.join(HERE, 'version.py')
PATCH_PY = os.path.join(HERE, 'patch_version.py')
GITENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
              GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t',
              GIT_CONFIG_NOSYSTEM='1', HOME=os.environ.get('HOME', '/tmp'))

fails = []


def check(ok, msg):
    print(('PASS  ' if ok else 'FAIL  ') + msg)
    if not ok:
        fails.append(msg)


def git(repo, *args):
    return subprocess.run(['git', '-C', repo] + list(args),
                          capture_output=True, text=True, env=GITENV)


def make_repo(work):
    repo = os.path.join(work, 'repo')
    os.makedirs(os.path.join(repo, 'tools', 'version'))
    open(os.path.join(repo, 'VERSION'), 'w').write('0.1.0\n')
    open(os.path.join(repo, 'build.sh'), 'w').write('# dummy build script\n')
    shutil.copy(VERSION_PY, os.path.join(repo, 'tools', 'version', 'version.py'))
    git(repo, 'init', '-q')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'c1')
    return repo


def patch(stock, out, version, ident):
    return subprocess.run([sys.executable, '-I', PATCH_PY, stock, out, version, ident],
                          capture_output=True, text=True)


def group_a(stock, patched, version, ident, channel):
    base = open(os.path.join(ROOT, 'VERSION')).read().strip()
    check(version == '%s-%s' % (base, channel),
          'build VERSION %r == %s-%s' % (version, base, channel))
    d = open(stock, 'rb').read()
    r = open(patched, 'rb').read()
    check(len(r) == len(d), 'patched setting.ap keeps the stock size %#x' % len(d))
    fo, load, size = pv.bank_of(pv.parse(stock)[2])
    f = lambda g: fo + (g - load)
    allowed = set()
    for g in (pv.LA_VER, pv.LA_DATE):
        allowed.update(range(f(g), f(g) + 2))
    for g in (pv.VER_SLOT, pv.IDENT_SLOT):
        allowed.update(range(f(g), f(g) + pv.SLOT))
    check(d[:fo] == r[:fo],
          '.ap header, bank table and earlier banks untouched (vendor metadata preserved; file %#x..)' % fo)
    for g, want in pv.STOCK_STR.items():
        check(bytes(r[f(g):f(g) + len(want)]) == want,
              'stock string at %#x left in place: %r' % (g, want))
    check(struct.unpack_from('<H', r, f(pv.LA_MODEL))[0] == pv.STOCK_HW[pv.LA_MODEL],
          'model-row la at %#x unchanged (still "M30")' % pv.LA_MODEL)
    hv = struct.unpack_from('<H', r, f(pv.LA_VER))[0]
    hd = struct.unpack_from('<H', r, f(pv.LA_DATE))[0]
    check(pv.la_target(pv.LA_VER, hv) == pv.VER_SLOT, 'version la %#x -> %#x' % (pv.LA_VER, pv.VER_SLOT))
    check(pv.la_target(pv.LA_DATE, hd) == pv.IDENT_SLOT, 'ident la %#x -> %#x' % (pv.LA_DATE, pv.IDENT_SLOT))
    vs = bytes(r[f(pv.VER_SLOT):f(pv.VER_SLOT) + pv.SLOT]).split(b'\x00')[0].decode()
    idd = bytes(r[f(pv.IDENT_SLOT):f(pv.IDENT_SLOT) + pv.SLOT]).split(b'\x00')[0].decode()
    check(vs == version and idd == ident,
          'tail strings are %r / %r (displayed version / build identifier)' % (vs, idd))
    rest = bytes(r[f(pv.IDENT_SLOT) + pv.SLOT:f(pv.TAIL_END)])
    check(rest == b'\x00' * len(rest), 'tail beyond the two slots still zero')
    with tempfile.TemporaryDirectory() as w:
        p1, p2 = os.path.join(w, 'a.ap'), os.path.join(w, 'b.ap')
        r1 = patch(stock, p1, version, ident)
        r2 = patch(stock, p2, version, ident)
        check(r1.returncode == 0 and r2.returncode == 0 and open(p1, 'rb').read() == open(p2, 'rb').read(),
              'patch is deterministic (identical output for identical inputs)')
        d1 = open(p1, 'rb').read()
        diff = [i for i in range(len(d)) if d[i] != d1[i]]
        check(set(diff) <= allowed,
              'patching stock changes only the 2 la halfwords + 2 tail slots (%d bytes)' % len(diff))
        # the built file also carries other patches (e.g. the keys bank), so compare
        # the version regions only: the build must contain exactly this version patch
        check(all(r[i] == d1[i] for i in allowed),
              'built setting.ap carries exactly this version patch in the expected regions')
        bad = os.path.join(w, 'bad.ap')
        bd = bytearray(d)
        bd[f(pv.STR_VER)] ^= 0xff          # corrupt a stock string byte
        open(bad, 'wb').write(bd)
        check(patch(bad, os.path.join(w, 'x.ap'), version, ident).returncode != 0,
              'patch refuses non-stock bytes (stock-string assertion)')
        check(patch(patched, os.path.join(w, 'y.ap'), version, ident).returncode != 0,
              'patch refuses an already-patched file (no double-apply)')


def group_b(work):
    repo = make_repo(work)
    vp = os.path.join(repo, 'tools', 'version', 'version.py')

    def V(*args):
        return subprocess.run([sys.executable, '-I', vp] + list(args),
                              capture_output=True, text=True, env=GITENV, cwd=repo)

    def md(r):
        out = {}
        for line in r.stdout.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                try:
                    out[k] = ast.literal_eval(v)
                except (ValueError, SyntaxError):
                    out[k] = v
        return out

    r1, m1 = V('--channel', 'dev', '--config', 'keys=1'), None
    m1 = md(r1)
    r2 = V('--channel', 'dev', '--config', 'keys=1')
    m2 = md(r2)
    check(r1.returncode == 0 and m1 == m2 and len(m1['IDENT']) == 8,
          'dev: identical inputs -> identical 8-hex build ID %s' % m1['IDENT'])
    check(m1['VERSION'] == '0.1.0-dev' and m1['BASE'] == '0.1.0', 'dev: VERSION=0.1.0-dev, BASE=0.1.0')
    m3 = md(V('--channel', 'dev', '--config', 'keys=0'))
    check(m3['IDENT'] != m1['IDENT'], 'dev: different build config -> different build ID')
    bs = os.path.join(repo, 'build.sh')
    open(bs, 'a').write('# source edit\n')
    m4 = md(V('--channel', 'dev', '--config', 'keys=1'))
    check(m4['IDENT'] != m1['IDENT'], 'dev: source change (uncommitted) -> different build ID')
    check(m4['DIRTY'] == 1, 'dev: uncommitted changes are accounted for (DIRTY=1)')
    git(repo, 'checkout', '--', 'build.sh')
    os.makedirs(os.path.join(repo, 'build'))
    open(os.path.join(repo, 'build', 'MECHEN_M30.HEX'), 'wb').write(b'x' * 16)
    m5 = md(V('--channel', 'dev', '--config', 'keys=1'))
    check(m5['IDENT'] == m1['IDENT'], 'dev: generated build/ outputs do not affect the build ID')
    os.remove(os.path.join(repo, 'build', 'MECHEN_M30.HEX'))
    os.rmdir(os.path.join(repo, 'build'))          # keep the tree clean for the nightly checks
    open(os.path.join(repo, 'tools', 'untracked.py'), 'w').write('# untracked\n')
    m6 = md(V('--channel', 'dev', '--config', 'keys=1'))
    check(m6['IDENT'] != m1['IDENT'], 'dev: untracked source file changes the build ID')
    os.remove(os.path.join(repo, 'tools', 'untracked.py'))

    open(os.path.join(repo, 'dirty.txt'), 'w').write('x')
    rn = V('--channel', 'nightly', '--config', 'keys=1')
    check(rn.returncode == 2, 'nightly: dirty tree rejected (exit 2)')
    os.remove(os.path.join(repo, 'dirty.txt'))
    rn = V('--channel', 'nightly', '--config', 'keys=1')
    mn = md(rn)
    sha = git(repo, 'rev-parse', '--short=7', 'HEAD').stdout.strip()
    full = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    check(rn.returncode == 0 and mn['IDENT'] == sha and mn['VERSION'] == '0.1.0-nightly'
          and mn['COMMIT'] == full, 'nightly: clean tree -> short SHA %s, full SHA in COMMIT' % sha)
    git(repo, 'commit', '-qm', 'c2', '--allow-empty')
    mn2 = md(V('--channel', 'nightly', '--config', 'keys=1'))
    check(mn2['IDENT'] != mn['IDENT'], 'nightly: new commit -> new identifier')

    rr = V('--channel', 'release', '--config', 'keys=1')
    check(rr.returncode == 2, 'release: untagged HEAD rejected (exit 2)')
    git(repo, 'tag', '0.2.0')
    rr = V('--channel', 'release', '--config', 'keys=1')
    check(rr.returncode == 2, 'release: tag 0.2.0 != 0.1.0 (VERSION) rejected (exit 2)')
    git(repo, 'tag', '-d', '0.2.0')
    git(repo, 'tag', '0.1.0')
    rr = V('--channel', 'release', '--config', 'keys=1')
    mr = md(rr)
    check(rr.returncode == 0 and mr['IDENT'] == '0.1.0' and mr['VERSION'] == '0.1.0-release',
          'release: exact tag 0.1.0 -> identifier 0.1.0, VERSION=0.1.0-release')
    open(os.path.join(repo, 'dirty.txt'), 'w').write('x')
    check(V('--channel', 'release', '--config', 'keys=1').returncode == 2,
          'release: dirty tree rejected even with the right tag (exit 2)')
    os.remove(os.path.join(repo, 'dirty.txt'))

    rj = V('--channel', 'dev', '--config', 'keys=1', '--json')
    mj = json.loads(rj.stdout)
    outj = os.path.join(work, 'meta.json')
    V('--channel', 'dev', '--config', 'keys=1', '--out', outj)
    check(set(mj) >= {'channel', 'version', 'identifier', 'base', 'commit', 'dirty'}
          and json.load(open(outj)) == mj,
          '--json and --out emit the same metadata for the release automation')

    # per-channel displayed strings, patched into fresh copies of the stock setting.ap
    stock = sys.argv[1]
    for ch, m in (('dev', m1), ('nightly', mn2), ('release', mr)):
        with tempfile.TemporaryDirectory() as w:
            out = os.path.join(w, 's.ap')
            rp = patch(stock, out, m['VERSION'], m['IDENT'])
            ok = rp.returncode == 0
            if ok:
                d = open(out, 'rb').read()
                fo, load, size = pv.bank_of(pv.parse(stock)[2])
                f = lambda g: fo + (g - load)
                vs = bytes(d[f(pv.VER_SLOT):f(pv.VER_SLOT) + pv.SLOT]).split(b'\x00')[0].decode()
                idd = bytes(d[f(pv.IDENT_SLOT):f(pv.IDENT_SLOT) + pv.SLOT]).split(b'\x00')[0].decode()
                ok = vs == m['VERSION'] and idd == m['IDENT']
            check(ok, '%s channel displays version %r + identifier %r on the Information screen'
                  % (ch, m['VERSION'], m['IDENT']))


def main():
    with tempfile.TemporaryDirectory() as work:
        if len(sys.argv) == 6:
            group_a(*sys.argv[1:6])
        group_b(work)
    print('test_version: %s' % ('OK' if not fails else 'FAILED (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
