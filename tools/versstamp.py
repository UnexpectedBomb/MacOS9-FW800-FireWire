"""versstamp.py — rewrite a file's own `vers` (1) strings in place, same length.

Extracted from stamp-firewire-support.py so the patcher and the standalone stamper
share ONE implementation of the resource-fork walk. Both strings are rewritten at
exactly their existing length (space padded, refused if the new text will not fit),
so no resource offset, no resource map and no fork length changes.

WHERE EACH STRING SHOWS UP ON THE MACHINE
  * SHORT -> the version column in Extensions Manager. "2.8.8" against a stock
    "2.8.7" makes a patched file obvious at a glance.
  * LONG  -> the description box in Apple System Profiler; say what the file is.

WHY THIS IS SAFE HERE AND FATAL IN A ROM
There is a hard rule on this project never to stamp `vers` into a patched Mac OS
ROM: a ROM file's resource fork *is the System Enabler's*, so a `vers` (1) there is
a claim about the ENABLER, and a mis-versioned enabler leaves components
uninstalled and ends at a grey screen. An extension's resource fork is its own, and
already ships `vers` (1); editing it is what that resource is for. `vers` (2)
describes the wider software release and is left alone.
"""
import struct


def find_vers1(rf):
    """Return (offset of the vers(1) body, its length) inside the resource fork."""
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
            return do + doff + 4, struct.unpack('>I', rf[do + doff:do + doff + 4])[0]
    raise SystemExit('no vers (1) resource found')


def stamp(rf, new_short, new_long, expect_short=None):
    """Return the resource fork with vers(1) rewritten. Length never changes."""
    base, size = find_vers1(rf)
    body = rf[base:base + size]
    p = 6
    sl = body[p]; spos = base + p + 1; old_short = body[p + 1:p + 1 + sl]; p += 1 + sl
    ll = body[p]; lpos = base + p + 1

    if expect_short is not None and old_short.decode('mac-roman') != expect_short:
        raise SystemExit('vers (1) short string is %r, expected %r. Refusing to stamp a '
                         'file that is not the version this patch was built against.'
                         % (old_short.decode('mac-roman'), expect_short))

    def fit(text, room, what):
        b = text.encode('mac-roman')
        if len(b) > room:
            raise SystemExit('%s is %d chars but only %d fit without changing the '
                             'resource length. Shorten it.' % (what, len(b), room))
        return b + b' ' * (room - len(b))

    out = bytearray(rf)
    out[spos:spos + sl] = fit(new_short, sl, 'short string')
    out[lpos:lpos + ll] = fit(new_long, ll, 'description')

    # Keep the numeric minorAndBugRev in step with the displayed string: a file whose
    # string says 2.8.8 while its numeric fields say 2.8.7 is its own kind of trap.
    parts = new_short.split('.')
    if len(parts) >= 3 and all(x.isdigit() and int(x) < 10 for x in parts[1:3]):
        out[base + 1] = (int(parts[1]) << 4) | int(parts[2])

    out = bytes(out)
    assert len(out) == len(rf), 'resource fork length changed'
    return out
