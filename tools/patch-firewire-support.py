#!/usr/bin/env python3
"""patch-firewire-support.py — apply the S400 speed-map clamp to a FireWire Support extension.

    patch-firewire-support.py <FireWire Support (MacBinary .bin)> <out.bin>

WHY THIS EXISTS
---------------
`FWServicesLib` is resident TWICE on an OS 9 machine: once as a parcel in the Mac OS ROM,
and once as an `nlib` resource (id -21140, ~148 KB) in the resource fork of the on-disk
`FireWire Support` extension. Patching only the ROM copy achieved nothing —
`FWPatchCheck v2` scanned the System heap after booting the patched ROM and found
**UNPATCHED 1, PATCHED 0**, so the resident copy is not the one that was patched.

Two explanations remain: the extension's copy is the one that binds, or the patched ROM
was not actually the one installed. Patching this copy as well removes the ambiguity
instead of diagnosing it — whichever binds, the clamp is present.

WHAT IT CHANGES
---------------
The same single byte as `patch-fwservices-speed.py`, found by the same 12-byte signature:

    lwz r4,0(r8) ; rlwinm r4,r4,18,30,31 ; stb r4,8(r24)
    80 88 00 00    54 84 97 be             98 98 00 08
                            ^^ -> bc

`sp` 0->S100, 1->S100, 2->S400, 3->S400. See patch-fwservices-speed.py for the full
reasoning: `sp` is a NODE capability, not a HOP capability, so two 1394b nodes joined by
a legacy cable both claim S800 on a hop that carries S400.

The signature is searched for across the WHOLE FILE rather than by parsing the resource
map, because the edit does not change any length — so no offset, resource map or
MacBinary header field needs rewriting. Exactly one occurrence is required; anything else
is refused rather than guessed at.

⚠ Give it YOUR machine's own `FireWire Support`, transferred as MacBinary so the resource
fork survives. Do not substitute a copy from an installer image: if your system carries a
different FireWire version, patching the wrong file would downgrade it.
"""
import sys, os

SIG      = bytes.fromhex('80 88 00 00 54 84 97 be 98 98 00 08')
SIG_DONE = bytes.fromhex('80 88 00 00 54 84 97 bc 98 98 00 08')
PATCH_AT = 7
OLD, NEW = 0xBE, 0xBC


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit('refusing to patch in place: give a distinct output path')

    d = open(src, 'rb').read()
    done, n = d.count(SIG_DONE), d.count(SIG)

    if n == 0 and done == 1:
        print('already patched -- copying through unchanged')
        open(dst, 'wb').write(d)
        return
    if n != 1:
        raise SystemExit('expected exactly 1 occurrence of the speed-map signature, found '
                         '%d (and %d already patched). Is this really a FireWire Support '
                         'extension carrying FireWire 2.8.x, transferred as MacBinary so '
                         'the resource fork is present? Refusing to guess.' % (n, done))

    at = d.index(SIG) + PATCH_AT
    if d[at] != OLD:
        raise SystemExit('byte at 0x%X is 0x%02X, expected 0x%02X' % (at, d[at], OLD))

    out = bytearray(d)
    out[at] = NEW
    out = bytes(out)

    assert len(out) == len(d), 'length changed'
    assert sum(a != b for a, b in zip(out, d)) == 1, 'more than one byte changed'
    assert out.count(SIG_DONE) == 1 and out.count(SIG) == 0, 'signature not updated'

    open(dst, 'wb').write(out)
    print('patched 1 byte at 0x%X: 0x%02X -> 0x%02X' % (at, OLD, NEW))
    print('  rlwinm r4,r4,18,30,31 -> rlwinm r4,r4,18,30,30  (speed map caps at S400)')
    print('  %s -> %s (%d bytes, unchanged length)' % (src, dst, len(out)))
    print('\nInstall: replace the FireWire Support extension in the System Folder with this,')
    print('keeping a backup of the original, then reboot and re-run FWPatchCheck.')


if __name__ == '__main__':
    main()
