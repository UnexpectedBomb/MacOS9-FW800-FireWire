#!/usr/bin/env python3
"""stamp-firewire-support.py — mark a patched FireWire Support as non-stock, in Get Info.

    stamp-firewire-support.py <FireWire Support (fork-ful)> <short> <long/description>

Rewrites BOTH version strings inside the file's own `vers` (1) resource, **in place and at
exactly the same length** (space padded, refused if either will not fit), and bumps the
numeric `minorAndBugRev` to agree with the new short string. Nothing moves, so no resource
offset, no resource map and no fork length changes.

WHERE EACH STRING SHOWS UP ON THE MACHINE
-----------------------------------------
  * SHORT string  -> the version column in **Extensions Manager**. Setting it to "2.8.8"
    makes it immediately obvious the file is not the stock 2.8.7.
  * LONG string   -> the description box in **Apple System Profiler**. That is the place to
    say briefly why this file exists and what it does.

WHY STAMPING IS SAFE HERE, WHEN IT IS FATAL IN A ROM
----------------------------------------------------
There is a hard rule on this project never to stamp `vers` into a patched Mac OS ROM: a
ROM file's resource fork *is the System Enabler's* fork, so a `vers` (1) there is a claim
about the ENABLER, and a mis-versioned enabler leaves enabler-dependent components
uninstalled — "No File System Access modules could be found", then a grey screen.

This file is not a ROM. Its resource fork is its OWN, and it already ships `vers` (1)
("2.8.7") and `vers` (2) ("Mac OS CPU Software 5.9"). Editing its own version string is
exactly what that resource is for. `vers` (2) is left untouched — it describes the wider
software release, not this file.

ON BUMPING THE NUMERIC VERSION
------------------------------
`minorAndBugRev` moves 0x87 -> 0x88 so the numeric version and the displayed string agree;
a file whose string says 2.8.8 while its numeric fields say 2.8.7 is its own kind of trap.
2.8.8 is an INCREASE, so any minimum-version check still passes. The residual risk is a
consumer demanding *exactly* 2.8.7, which would be unusual. `majorRev`, `stage` and
`nonRelRev` are untouched, and `vers` (2) is untouched.
"""
import struct, subprocess, sys, shutil, os


def find_vers1(rf):
    do, mo = struct.unpack('>II', rf[:8])
    tlo = mo + struct.unpack('>H', rf[mo + 24:mo + 26])[0]
    n = struct.unpack('>h', rf[tlo:tlo + 2])[0] + 1
    for i in range(n):
        off = tlo + 2 + i * 8
        if rf[off:off + 4] != b'vers':
            continue
        cnt = struct.unpack('>H', rf[off + 4:off + 6])[0] + 1
        rlo = tlo + struct.unpack('>H', rf[off + 6:off + 8])[0]
        for j in range(cnt):
            ro = rlo + j * 12
            if struct.unpack('>h', rf[ro:ro + 2])[0] != 1:
                continue
            doff = struct.unpack('>I', rf[ro + 4:ro + 8])[0] & 0xFFFFFF
            base = do + doff + 4
            size = struct.unpack('>I', rf[do + doff:do + doff + 4])[0]
            return base, size
    raise SystemExit('no vers (1) resource found')


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    path, new_short, new_long = sys.argv[1], sys.argv[2], sys.argv[3]
    fork = path + '/..namedfork/rsrc'
    rf = open(fork, 'rb').read()

    base, size = find_vers1(rf)
    body = rf[base:base + size]
    p = 6
    sl = body[p]; spos = base + p + 1; short_old = body[p + 1:p + 1 + sl]; p += 1 + sl
    ll = body[p]; lpos = base + p + 1; long_old = body[p + 1:p + 1 + ll]

    print('vers (1) before: short %r (%d)   long %r (%d)'
          % (short_old.decode('mac-roman'), sl, long_old.decode('mac-roman'), ll))

    def fit(text, room, what):
        b = text.encode('mac-roman')
        if len(b) > room:
            raise SystemExit('%s is %d chars but only %d fit without changing the resource '
                             'length. Shorten it.' % (what, len(b), room))
        return b + b' ' * (room - len(b))

    ns = fit(new_short, sl, 'short string')
    nl = fit(new_long, ll, 'description')

    out = bytearray(rf)
    out[spos:spos + sl] = ns
    out[lpos:lpos + ll] = nl
    # keep the numeric minorAndBugRev in step with the displayed short string
    try:
        maj, minbug = new_short.split('.', 1)[0], new_short.split('.')[1:]
        bcd = int(minbug[0]) << 4 | int(minbug[1])
        out[base + 1] = bcd
    except Exception:
        print('  (could not derive a BCD minorAndBugRev from %r - left as-is)' % new_short)

    out = bytes(out)
    assert len(out) == len(rf), 'fork length changed'
    open(fork, 'wb').write(out)
    print('vers (1) after:  short %r   long %r'
          % (ns.decode('mac-roman').rstrip(), nl.decode('mac-roman').rstrip()))
    print('  minorAndBugRev -> 0x%02X ; fork length unchanged (%d bytes)' % (out[base+1], len(out)))


if __name__ == '__main__':
    main()
