#!/usr/bin/env python3
"""patch-fwservices-speed.py — clamp OS 9's FireWire speed map to S400.

    patch-fwservices-speed.py <FWServicesLib.pef> <out.pef>

WHAT IT CHANGES, AND WHY
------------------------
`FWProcessBusReset` in FWServicesLib builds the 1394 speed map — a 64x64 byte matrix —
*entirely* from the `sp` field of each node's self-ID packet, with the standard
min-along-the-path recursion:

    speedmap[i][i] = sp_i                                   (the diagonal)
    speedmap[i][n] = min(sp_i, speedmap[parent][n])         (everything else)
    speedmap[n][i] = same                                   (the transpose, 64 stride)

The bug is that **`sp` describes a NODE's capability, not a HOP's.** Two 1394b nodes
joined by a *legacy* (1394a data/strobe) cable each report `sp = 3`, so min() yields 3
= S800 — but that hop can only carry S400. The only place the truth exists is the PHY's
per-port `Negotiated_speed` register, which 1394a-era code never reads because in 1394a
a node's capability *was* its hops' capability.

On a Power Mac G4 MDD FW800 (TI TSB81BA3, a 1394b PHY reporting PHY_Speed = 7 -> sp = 3)
the result is measured and stark:

    9-to-9 beta cable   -> map says S800, hop really is S800 -> device mounts
    6-to-6 legacy cable -> map says S800, hop is S400        -> transmit fails, no device
    9-to-6 legacy cable -> same failure on the *same* port that works with 9-to-9
    FW400 MDD (Lucent 1394a PHY, PHY_Speed = 2 -> sp = 2)    -> map says S400 -> works

This is exactly why Apple's OS X family maps the reserved code to "S800 but UNKNOWN" and
then verifies by transfer (`IOFireWireController.cpp`), and why TI's own TSB81BA3 errata
says to determine speeds "by a try-and-see method" rather than trusting a computed value.
FireWire 2.8.x trusts it.

THE PATCH — one instruction, one byte, length-preserving
-------------------------------------------------------
At the diagonal write, the 2-bit `sp` extraction becomes a 1-bit extraction:

    rlwinm r4, r4, 18, 30, 31     ->     rlwinm r4, r4, 18, 30, 30
    0x548497BE                           0x548497BC

    sp = 0 (S100) -> 0  S100
    sp = 1 (S200) -> 0  S100      <- the only cost; see below
    sp = 2 (S400) -> 2  S400
    sp = 3 (rsvd) -> 2  S400      <- the fix

Because every other entry is a min() against the diagonals, capping the diagonals caps
the whole map. The instruction keeps its length and encoding class, so nothing moves and
no offset changes.

WHY THIS IS SAFE
----------------
The patch is **monotonic**: every path either keeps its speed or gets slower, and a
slower transmission is always legal on a faster hop. So it *cannot* break a
configuration that already works — the beta port keeps working, just at S400.

COSTS, STATED PLAINLY
---------------------
  * Genuine S200 devices drop to S100. S200 was essentially never shipped in products;
    this is a throughput nicety, not a correctness issue.
  * The FW800 port is capped at S400. Restoring S800 needs per-hop data from the PHY's
    `Negotiated_speed` register, which lives in the FWIM, not here — a separate and much
    larger job. This patch buys three working ports at a uniform S400.

NOT PATCHED, DELIBERATELY
-------------------------
A second site (`FWProcessSelfIDs`, PEF offset ~0x11DE8) ORs `sp << 30` into the oMPR and
iMPR data-rate field of the IEC 61883 plug control registers. `sp = 3` is reserved there
too, so it is also wrong — but it affects only isochronous plug advertisement, not
asynchronous transfers or mounting a disk. Left alone so this build changes exactly ONE
thing and a hardware result cannot be ambiguous.
"""
import sys, os

# lwz r4,0(r8) ; rlwinm r4,r4,18,30,31 ; stb r4,8(r24)
SIG      = bytes.fromhex('80 88 00 00 54 84 97 be 98 98 00 08')
SIG_DONE = bytes.fromhex('80 88 00 00 54 84 97 bc 98 98 00 08')
PATCH_AT = 7          # index within SIG of the byte to change
OLD, NEW = 0xBE, 0xBC


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit('refusing to patch in place: give a distinct output path')

    d = open(src, 'rb').read()
    if d[:4] != b'Joy!':
        raise SystemExit('%s is not a PEF (no Joy! magic)' % src)

    done = d.count(SIG_DONE)
    n    = d.count(SIG)
    if n == 0 and done == 1:
        print('already patched (%s) -- copying through unchanged' % src)
        open(dst, 'wb').write(d)
        return
    if n != 1:
        raise SystemExit('expected exactly 1 occurrence of the speed-map signature, '
                         'found %d (and %d already-patched). This is not a FireWire '
                         '2.8.x FWServicesLib, or its code differs -- refusing to guess.'
                         % (n, done))

    at = d.index(SIG) + PATCH_AT
    if d[at] != OLD:
        raise SystemExit('byte at 0x%X is 0x%02X, expected 0x%02X' % (at, d[at], OLD))

    out = bytearray(d)
    out[at] = NEW
    out = bytes(out)

    # verify, rather than trust
    assert len(out) == len(d), 'length changed'
    assert sum(a != b for a, b in zip(out, d)) == 1, 'more than one byte changed'
    assert out.count(SIG_DONE) == 1 and out.count(SIG) == 0, 'signature not updated'

    open(dst, 'wb').write(out)
    print('patched 1 byte at 0x%X: 0x%02X -> 0x%02X  (rlwinm r4,r4,18,30,31 -> ...,30,30)'
          % (at, OLD, NEW))
    print('  speed map diagonal now caps at S400; every other entry is a min() of those.')
    print('  %s -> %s (%d bytes, unchanged length)' % (src, dst, len(out)))


if __name__ == '__main__':
    main()
