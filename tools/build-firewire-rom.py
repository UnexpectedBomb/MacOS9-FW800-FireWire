#!/usr/bin/env python3
"""build-firewire-rom.py — build a Mac OS ROM whose FireWire speed map is clamped to S400.

    build-firewire-rom.py <base-ROM (fork-ful)> <version-tag> <out.hqx>

Dumps the base ROM with tbxi, applies patch-fwservices-speed.py to the FWServicesLib
parcel, rebuilds, and then VERIFIES the rebuild rather than trusting it.

WHY .hqx AND WHY NO VERSION STAMP -- both learned the hard way on this project:
  * .hqx via `tbxi build` preserves BOTH FORKS. The ROM file's resource fork *is* the
    System Enabler's; a MacBinary wrapper replaces it and silently discards ~185 KB of
    enabler, which produced ROMs that booted to a grey screen.
  * NOTHING is ever stamped into that fork. Adding a `vers` (1) resource mis-versions the
    enabler -- "No File System Access modules could be found" then grey screen -- because
    `vers` (1) is a claim about the ENABLER, not about us. The build tag lives in the
    FILENAME only.

GUARDS (the build refuses rather than shipping something subtly broken):
  1. the base must be fork-ful (a SysEnabler must dump out of it);
  2. output SysEnabler size must equal the base's;
  3. output SysEnabler.rdump must be BYTE-IDENTICAL to the base's -- we add nothing to
     any fork, ever;
  4. the patched parcel must differ from the base parcel by exactly ONE byte;
  5. the rebuilt ROM must dump back cleanly.

Note: `tbxi build` re-serialises the parcel blob and rewrites ~64 bytes of crc32 fields
as 0x99999999 placeholders. That is inherent to tbxi and not caused by this patch -- the
stock ROM round-trips with the identical drift at the identical offset, and every USB2 /
eSATA ROM ever shipped on this project went through the same path and boots.
"""
import os, shutil, subprocess, sys, tempfile
from os import path

HERE = path.dirname(path.abspath(__file__))
TBXI = path.expanduser('~/Developer/rom-tools/venv/bin/tbxi')
PATCHER = path.join(HERE, 'patch-fwservices-speed.py')


def run(*args):
    r = subprocess.run(list(args))
    if r.returncode != 0:
        raise SystemExit('FAILED: %s' % ' '.join(args))


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    base, tag, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if not out.lower().endswith('.hqx'):
        raise SystemExit('output must end in .hqx (that is the fork-safe format)')
    if not path.isfile(TBXI):
        raise SystemExit('tbxi not found at %s' % TBXI)

    work = tempfile.mkdtemp(prefix='fwrom')
    try:
        dump = path.join(work, 'dump')
        print('1. dumping %s ...' % base)
        run(TBXI, 'dump', base, '-o', dump)

        se = path.join(dump, 'SysEnabler')
        rd = path.join(dump, 'SysEnabler.rdump')
        if not path.isfile(rd):
            raise SystemExit('no SysEnabler.rdump: this base has no resource fork, so a '
                             'built ROM would lose the System Enabler. Rehydrate one with '
                             'usb2-ehci/scripts/rehydrate-rom-fork.py and use that.')
        base_se_size = path.getsize(se)
        base_rdump = open(rd, 'rb').read()
        print('   base SysEnabler %d bytes, rdump %d bytes' % (base_se_size, len(base_rdump)))

        parcel = path.join(dump, 'Parcels.src', 'FWServicesLib.pef')
        if not path.isfile(parcel):
            raise SystemExit('no Parcels.src/FWServicesLib.pef in the dump -- this ROM does '
                             'not carry the FireWire family parcel, so there is nothing to patch.')
        before = open(parcel, 'rb').read()

        print('2. patching the FWServicesLib parcel ...')
        tmp = parcel + '.patched'
        run(sys.executable, PATCHER, parcel, tmp)
        after = open(tmp, 'rb').read()
        if len(after) != len(before):
            raise SystemExit('parcel length changed -- refusing to build')
        ndiff = sum(a != b for a, b in zip(before, after))
        if ndiff not in (0, 1):
            raise SystemExit('parcel differs by %d bytes, expected 1 -- refusing' % ndiff)
        if ndiff == 0:
            print('   (base was already patched)')
        os.replace(tmp, parcel)

        print('3. building %s ...' % out)
        run(TBXI, 'build', '-o', out, dump)

        print('4. verifying ...')
        chk = path.join(work, 'verify')
        run(TBXI, 'dump', out, '-o', chk)
        out_se = path.getsize(path.join(chk, 'SysEnabler'))
        if out_se != base_se_size:
            raise SystemExit('SysEnabler CHANGED: base %d -> output %d. The fork was damaged. '
                             'Do NOT ship this ROM.' % (base_se_size, out_se))
        if open(path.join(chk, 'SysEnabler.rdump'), 'rb').read() != base_rdump:
            raise SystemExit('the ROM resource fork CHANGED between base and output. This tool '
                             'must never modify that fork. Do NOT ship this ROM.')
        rebuilt = open(path.join(chk, 'Parcels.src', 'FWServicesLib.pef'), 'rb').read()
        if rebuilt != after:
            raise SystemExit('the FWServicesLib parcel did not survive the rebuild intact')
        n2 = sum(a != b for a, b in zip(before, rebuilt))
        print('   SysEnabler %d bytes preserved; resource fork byte-identical' % out_se)
        print('   FWServicesLib differs from base by exactly %d byte' % n2)
        print('\nOK: %s   (build tag %r is in the FILENAME only, never in the ROM)' % (out, tag))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
