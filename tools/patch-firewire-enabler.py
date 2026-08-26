#!/usr/bin/env python3
"""patch-firewire-enabler.py — restore S800 by moving the speed clamp into the FWIM.

    patch-firewire-enabler.py <FireWire Enabler (fork-ful)> <out dir>

WHY THIS EXISTS
---------------
The shipped FW400 fix clamps the family's speed map to S400 for *every* node, by one
byte in `FireWire Support`'s `FWServicesLib`. That is monotonic: it buys the two FW400
ports at the cost of the FW800 port's S800. This patch replaces it, so `FireWire
Support` goes back to STOCK and the whole fix lives in one extension.

THE DEFECT, IN APPLE'S OWN WORDS
--------------------------------
`IOFireWireController::buildTopology` (IOFireWireFamily, Mac OS X) reads the same
self-ID field OS 9 does and says:

    speedCode = (id0 & kFWSelfID0SP) >> kFWSelfID0SPPhase;
    if( speedCode == kFWSpeedReserved )
        speedCode = kFWSpeed800MBit | kFWSpeedUnknownMask;  // we don't know how fast it is

`sp == 3` is *not* "S800". Per 1394a it is reserved, and 1394b uses it to mean "S400 or
better, ask the PHY". OS X then does try-and-see: on a failed transaction it steps the
node's speed down and retries. OS 9's `FWServicesLib` has no step-down; it stores `sp`
verbatim, so two 1394b nodes joined by a legacy cable both claim S800 on a hop that
physically carries S400, and the transfer fails. That is the FW400-ports bug.

WHAT THIS PATCH DOES
--------------------
OS 9 cannot try-and-see without a rewrite, but the FWIM *owns the PHY*, and the PHY
knows. TSB81BA3 base register 6 carries `Max_Legacy_SPD`: measured 0 with only the beta
port connected and 2 (S400) whenever a legacy segment exists (three runs, see `logs/`).

So: hook the FWIM immediately before it hands the self-IDs up to the family, read the
PHY, and if a legacy segment exists clamp the self-ID `sp` fields down to what that
segment can actually carry. The family's own min-propagation then produces the right
map with no family patch at all.

    beta port only        -> Max_Legacy_SPD 0 -> no clamp   -> S800
    any legacy segment    -> Max_Legacy_SPD 2 -> clamp to 2 -> S400 everywhere
    PHY unreadable        -> clamp to S400 (fail safe, never fail open)

WHERE IT HOOKS
--------------
`FireWire Enabler`'s data fork is TWO PEF containers: LynxFWIM at 0x0 and OHCIFWIM at
0xd650. Only the second is touched. OHCIFWIM imports `FWServicesLib.FWProcessSelfIDs`
and calls it from exactly two sites, both of which are hooked:

    0x7004  HandleSelfIDInterrupt   r30 = pFWIMData
    0x2d88  SelfIDDeferredTask      r31 = pFWIMData

BOTH matter. The parameter block carries *two* self-ID buffers, and the family reads
both: `params+0x28/0x2c` is the DMA copy of the remote nodes' self-IDs, and
`params+0x30/0x34` is the LOCAL node's own self-ID. Clamping only the first would leave
the host still claiming S800 - a silent half-fix. The family also validates each
packet against its inverse quadlet (`nor r3,r8,r8; cmplw r7,r3` at FWProcessSelfIDs+0xe8),
so the clamp rewrites the inverse alongside the packet.

Room for the new code is made by growing OHCIFWIM's code section and moving the two
sections after it; every PEF offset that changes lives in the section table, and
relocations are section-relative, so nothing else needs rewriting.
"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppcasm import Asm, selftest, audit_volatiles                                    # noqa: E402
import versstamp                                                    # noqa: E402

C2_AT          = 0xD650      # OHCIFWIM container start in the data fork
C2_CODE_SIZE   = 56216       # its code section, unpatched
READPHY        = 0x0B2C      # ReadPhyRegister(r3 = OHCI base, r4 = reg) -> r3
WRITEPHY       = 0x0D0C      # WritePhyRegister(r3 = OHCI base, r4 = reg, r5 = value)
GLUE_FPSI      = 0xD62C      # cross-TOC glue for FWServicesLib.FWProcessSelfIDs
OHCI_BASE_OFF  = 0xDC        # pFWIMData->ohciRegisterBase
SITES = {0x7004: 30, 0x2D88: 31}   # call site -> register holding pFWIMData
STOCK_SHORT, PATCHED_SHORT = '2.8.7', '2.8.8'
BUILD = 5                    # in-band build number: the 'v00N' magic and Get Info
BL_TO_GLUE = {0x7004: 0x48006629, 0x2D88: 0x4800A8A5}


ORDER_ASCEND, ORDER_DESCEND = 0, 1

# Self-ID packet 0 port status, from IOFireWireController.h. Note 3 = child and
# 2 = parent, which is the opposite way round from the obvious guess.
ST_NOTPRESENT, ST_NOTCONNECTED, ST_PARENT, ST_CHILD = 0, 1, 2, 3

# Scratch block word offsets.
NCALLS, PHY2, GCEIL, MODE, TOTAL, LENB, LAST = 8, 12, 16, 20, 24, 28, 32
LOCALID, NREMOTE, NTABLE, PORT0, REG7, TABLE = 36, 40, 44, 48, 60, 0x44
NODES, NODEN = 0x60, 0x70          # (phy_ID<<16)|(own sp<<8)|applied ceiling


def build_blob(base, order):
    """Assemble the scratch block, the two stubs, the hook and the clamp.

    `order` decides how the local PHY's child ports map to node IDs. Self-IDs are a
    post-order stream, so a node's children immediately precede it and the tree is
    reconstructable from (order, child counts) alone — but whether the FIRST child in
    the stream sits on the LOWEST or the HIGHEST numbered child port is not something
    Apple's source settles. `countNodeIDChildren` walks ports ascending, while
    `buildTopology` identifies the hub with `hubChildRemainder == childrenRemaining`,
    a countdown; whether those compose to ascending or descending turns on exactly when
    the decrement lands, and the explanatory comment reads either way. So both variants
    are built and the machine decides. It only matters when two connected ports run at
    DIFFERENT speeds, and the wrong choice fails the way this machine already failed
    before any of this work: the legacy device does not mount. Visible, harmless,
    reversible by swapping the file.
    """
    a = Asm(base)

    # ---- scratch. Pre-initialised in the file so FWFixCheck finds the block as soon as
    # the extension is resident; non-zero counters then prove the hook ran.
    a.label('SCRATCH')
    a.blob(b'S8FX' + ('v%03d' % BUILD).encode())   # +0x00 magic, +0x04 build
    a.blob(b'\0' * 56)                             # +0x08..+0x3f counters
    a.blob(b'ENDS')                                # +0x40 tail marker
    a.blob(b'\0' * 16)                             # +0x44 node -> speed table
    a.blob(struct.pack('>I', order))               # +0x54 which ordering this build uses
    a.blob(b'\0' * 8)                              # +0x58 spare
    a.blob(b'\0' * 16)                             # +0x60 per-node record, 4 entries
    a.blob(b'\0' * 16)                             # +0x70 record count, then spare

    # ---- one stub per call site, to normalise pFWIMData into r11
    for site, reg in sorted(SITES.items()):
        a.label('STUB_%X' % site)
        a.mr(11, reg)
        a.b('HOOK')

    # ---- the hook. r3 = &params, r11 = pFWIMData, LR = the original call site.
    a.label('HOOK')
    a.mflr(0)
    a.stw(0, 8, 1)                                 # our LR into the caller's linkage
    a.stwu(1, -128, 1)
    a.stmw(17, 68, 1)                              # r17..r31
    a.mr(31, 3)
    a.mr(30, 11)
    a.lwz(29, OHCI_BASE_OFF, 30)                   # OHCI register base
    a.bl('LPC')
    a.label('LPC')
    a.mflr(28)
    a.addi(28, 28, a.labels['SCRATCH'] - a.labels['LPC'])

    a.lwz(9, NCALLS, 28)
    a.addi(9, 9, 1)
    a.stw(9, NCALLS, 28)

    # Defaults are the fail-safe ones: clamp everything to S400 and stay in global mode,
    # which is precisely the behaviour already proven to fix the FW400 ports.
    # globalCeil: the ceiling used when the per-connection map cannot be trusted.
    # ⚠ DO NOT "fix" this by seeding it at S800 and taking a true minimum over the
    # connected ports. It looks like needless conservatism and is not. The fallback
    # fires precisely when the topology is NOT a star -- a hub, a daisy chain -- and
    # in that case this PHY can only measure the hops it terminates. Everything past
    # the first hop is invisible. Seed it at S800 and
    #
    #     Mac --beta S800--> drive A --legacy cable--> 1394b drive B
    #
    # leaves globalCeil at S800, clamps nothing, and the family attempts S800 across
    # a data/strobe hop to B. That is the original defect, verbatim. Self-IDs cannot
    # reveal that hop -- a legacy link between two 1394b nodes being invisible in the
    # self-ID stream is the premise of this entire patch -- so no amount of topology
    # reconstruction helps. Apple's answer is try-and-see step-down, which the OS 9
    # family does not have. S400 is the correct answer here, not merely the safe one.
    a.li(27, 2)                                    # globalCeil
    a.li(26, 0)                                    # tableCount
    a.li(25, 0)                                    # childCount
    a.li(23, -1)                                   # localID
    a.li(20, -1)                                   # saved reg 7 = not read
    a.li(9, 0)
    a.stw(9, MODE, 28)
    a.stw(9, LAST, 28)
    a.stw(9, NODEN, 28)
    a.li(9, -1)
    for k in range(3):
        a.stw(9, PORT0 + 4 * k, 28)
    a.stw(9, REG7, 28)
    a.stw(9, LOCALID, 28)

    a.lwz(9, 0x2C, 31)                             # remote self-ID bytes
    a.stw(9, LENB, 28)
    a.rlwinm(24, 9, 29, 3, 31)                     # remoteCount = bytes / 8 (q,~q pairs)
    a.stw(24, NREMOTE, 28)

    # ---- PHY register 2 is the liveness oracle AND carries Num_Ports
    a.mr(3, 29)
    a.li(4, 2)
    a.bl(READPHY)
    a.stw(3, PHY2, 28)
    a.cmpwi(3, 0)
    a.bc('eq', 'LDECIDE')
    a.rlwinm(21, 3, 0, 27, 31)                     # numPorts = reg2 & 0x1f
    a.cmpwi(21, 0)
    a.bc('eq', 'LDECIDE')
    a.cmpwi(21, 3)
    a.bc('gt', 'LDECIDE')                          # >3 ports cannot be described by
                                                   # self-ID packet 0; Apple bails too

    # ---- our own self-ID gives our phy_ID and our three port states
    a.lwz(5, 0x30, 31)                             # bufferA = the local node's self-ID
    a.lwz(6, 0x34, 31)
    a.cmpwi(6, 4)
    a.bc('lt', 'LDECIDE')
    a.lwz(22, 0, 5)
    a.rlwinm(9, 22, 2, 30, 31)                     # self-ID identifier, bits 31:30
    a.cmpwi(9, 2)
    a.bc('ne', 'LDECIDE')
    a.rlwinm(9, 22, 9, 31, 31)                     # bit 23: extended packet?
    a.cmpwi(9, 0)
    a.bc('ne', 'LDECIDE')
    a.rlwinm(23, 22, 8, 26, 31)                    # localID = (q >> 24) & 0x3f
    a.stw(23, LOCALID, 28)
    a.rlwinm(22, 22, 30, 26, 31)                   # p0,p1,p2 packed into bits 5..0

    a.mr(3, 29)                                    # remember the page/port selection
    a.li(4, 7)
    a.bl(READPHY)
    a.mr(20, 3)
    a.stw(20, REG7, 28)

    # ---- per-port pass
    a.li(19, 0)
    a.label('LPORT')
    # r17 (state) and r18 (speed) MUST be non-volatile: ReadPhyRegister and
    # WritePhyRegister are called below and r0/r3-r12 do not survive that.
    # ReadPhyRegister's own prologue does `mfcr r12`, so r12 in particular is gone.
    a.rlwinm(17, 22, 28, 30, 31)                   # state of this port
    a.rlwinm(22, 22, 2, 26, 31)                    # shift the next port's state up
    a.rlwinm(9, 17, 16, 0, 15)                     # log the state even for a port we are
    a.ori(9, 9, 0x00F0)                            # about to skip: 0xf0 = registers unread
    a.rlwinm(8, 19, 2, 0, 29)
    a.add(8, 8, 28)
    a.stw(9, PORT0, 8)
    a.cmpwi(17, ST_PARENT)
    a.bc('lt', 'LPNEXT')                           # not present / not connected

    a.mr(3, 29)                                    # select page 0, this port
    a.li(4, 7)
    a.mr(5, 19)
    a.bl(WRITEPHY)
    a.mr(3, 29)                                    # a full PHY round trip doubles as the
    a.li(4, 2)                                     # settle delay and as a liveness check
    a.bl(READPHY)
    a.cmpwi(3, 0)
    a.bc('eq', 'LPNEXT')

    a.mr(3, 29)
    a.li(4, 8)
    a.bl(READPHY)
    a.rlwinm(9, 3, 30, 31, 31)                     # reg 8 bit 5 = Connected
    a.cmpwi(9, 0)
    a.bc('eq', 'LPNEXT')

    a.mr(3, 29)
    a.li(4, 9)
    a.bl(READPHY)
    a.rlwinm(18, 3, 27, 29, 31)                    # reg 9 bits 0-2 = Negotiated_speed

    a.mr(3, 29)
    a.li(4, 11)
    a.bl(READPHY)
    a.rlwinm(11, 3, 29, 31, 31)                    # reg 11 bit 4 = Beta_mode
    a.cmpwi(11, 0)
    a.bc('ne', 'LPCAP')
    a.cmpwi(18, 2)                                 # a data/strobe hop cannot exceed S400
    a.bc('le', 'LPCAP')
    a.li(18, 2)
    a.label('LPCAP')
    a.cmpwi(18, 3)
    a.bc('le', 'LPMIN')
    a.li(18, 3)
    a.label('LPMIN')
    a.cmpw(18, 27)
    a.bc('ge', 'LPREC')
    a.mr(27, 18)                                   # globalCeil = min over connected ports
    a.label('LPREC')
    a.rlwinm(9, 17, 16, 0, 15)                     # log (state<<16)|(beta<<8)|spd
    a.rlwinm(0, 11, 8, 0, 23)
    a.or_(9, 9, 0)
    a.or_(9, 9, 18)
    a.rlwinm(8, 19, 2, 0, 29)                      # r8, not r0: a D-form base of r0
    a.add(8, 8, 28)                                # means absolute zero, not register 0
    a.stw(9, PORT0, 8)

    a.cmpwi(26, 4)                                 # table full (impossible at <= 3 ports)
    a.bc('ge', 'LPNEXT')
    a.cmpwi(17, ST_CHILD)
    a.bc('ne', 'LPPAR')
    a.rlwinm(9, 25, 16, 0, 15)                     # child: remember its child index
    a.addi(25, 25, 1)
    a.b('LPPUT')
    a.label('LPPAR')
    a.lis(9, 0x0001)                               # parent: flag it, resolved below
    a.ori(9, 9, 0x0100)
    a.label('LPPUT')
    a.or_(9, 9, 18)
    a.rlwinm(8, 26, 2, 0, 29)
    a.add(8, 8, 28)
    a.stw(9, TABLE, 8)
    a.addi(26, 26, 1)
    a.label('LPNEXT')
    a.addi(19, 19, 1)
    a.cmpw(19, 21)
    a.bc('lt', 'LPORT')

    a.cmpwi(20, 0)                                 # put the page/port selection back
    a.bc('lt', 'LDECIDE')
    a.mr(3, 29)
    a.li(4, 7)
    a.mr(5, 20)
    a.bl(WRITEPHY)

    # ---- is this a plain star centred on us, with every neighbour a leaf?
    a.label('LDECIDE')
    a.stw(27, GCEIL, 28)
    a.stw(26, NTABLE, 28)
    a.cmpwi(26, 0)
    a.bc('eq', 'LCLAMP')
    a.cmpw(25, 23)                                 # our child count must equal our phy_ID
    a.bc('ne', 'LCLAMP')
    a.cmpw(26, 24)                                 # every remote node must sit on a port
    a.bc('ne', 'LCLAMP')

    # ---- resolve each table entry to a node ID
    a.li(8, 0)                                     # r8, not r0: `addi r0,r0,1` is `li r0,1`
    a.label('LRES')
    a.cmpw(8, 26)
    a.bc('ge', 'LRESDONE')
    a.rlwinm(10, 8, 2, 0, 29)
    a.add(10, 10, 28)
    a.lwz(9, TABLE, 10)
    a.rlwinm(12, 9, 0, 24, 31)                     # spd
    a.rlwinm(11, 9, 24, 28, 31)                    # parent flag
    a.rlwinm(9, 9, 16, 24, 31)                     # child index
    a.cmpwi(11, 0)
    a.bc('eq', 'LRESCHILD')
    a.mr(9, 24)                                    # the parent is the root: node N-1
    a.b('LRESPUT')
    a.label('LRESCHILD')
    if order == ORDER_DESCEND:
        a.sub(9, 25, 9)                            # mirror: childCount - 1 - index
        a.addi(9, 9, -1)
    a.label('LRESPUT')
    a.rlwinm(9, 9, 8, 0, 23)
    a.or_(9, 9, 12)
    a.stw(9, TABLE, 10)
    a.addi(8, 8, 1)
    a.b('LRES')
    a.label('LRESDONE')
    a.li(9, 1)
    a.stw(9, MODE, 28)                             # per-connection

    # ---- clamp. Remote nodes only: leaving our own sp at S800 is exactly what lets
    # the family's min-propagation give S800 to a beta neighbour and S400 to a legacy
    # one in the same speed map.
    a.label('LCLAMP')
    a.lwz(5, 0x28, 31)
    a.lwz(6, 0x2C, 31)
    a.bl('CLAMP')
    a.stw(3, LAST, 28)
    a.lwz(9, TOTAL, 28)
    a.add(9, 9, 3)
    a.stw(9, TOTAL, 28)
    a.lwz(9, MODE, 28)
    a.cmpwi(9, 0)
    a.bc('ne', 'LCALL')
    a.lwz(5, 0x30, 31)                             # the global fallback also clamps our
    a.lwz(6, 0x34, 31)                             # own self-ID, matching the proven fix
    a.bl('CLAMP')
    a.lwz(9, LAST, 28)                             # count it too, or the fallback path
    a.add(9, 9, 3)                                 # under-reports and reads as "did nothing"
    a.stw(9, LAST, 28)
    a.lwz(9, TOTAL, 28)
    a.add(9, 9, 3)
    a.stw(9, TOTAL, 28)

    a.label('LCALL')
    a.mr(3, 31)
    a.bl(GLUE_FPSI)
    a.lwz(2, 20, 1)                                # the glue saved our TOC here
    a.lwz(11, 0, 1)                                # back chain = the caller's frame
    a.stw(2, 20, 11)                               # its own `lwz r2,0x14(r1)` needs this
    a.lmw(17, 68, 1)
    a.addi(1, 1, 128)
    a.lwz(0, 8, 1)
    a.mtlr(0)
    a.blr()

    # ---- CLAMP(r5 = quadlets, r6 = bytes) -> r3 = packets clamped.
    # Leaf. Reads r26 (table entries), r27 (global ceiling), r28 (scratch).
    a.label('CLAMP')
    a.li(3, 0)
    a.cmpwi(6, 4)
    a.bc('lt', 'CEND')
    a.rlwinm(7, 6, 30, 2, 31)
    a.cmpwi(7, 0)
    a.bc('eq', 'CEND')
    a.mtctr(7)
    a.add(4, 5, 6)
    a.addi(4, 4, -4)                               # address of the last quadlet
    a.addi(5, 5, -4)
    a.label('CLOOP')
    a.lwzu(11, 4, 5)
    a.rlwinm(9, 11, 2, 30, 31)                     # self-ID identifier, bits 31:30
    a.cmpwi(9, 2)
    a.bc('ne', 'CNEXT')
    a.rlwinm(9, 11, 9, 31, 31)                     # bit 23: extended packet, carries no sp
    a.cmpwi(9, 0)
    a.bc('ne', 'CNEXT')
    a.mr(12, 27)                                   # ceiling defaults to the global one
    a.lwz(0, MODE, 28)
    a.cmpwi(0, 0)
    a.bc('eq', 'CHAVE')
    a.rlwinm(10, 11, 8, 26, 31)                    # this packet's phy_ID
    a.li(6, 0)                                     # r6 is dead after `add r4,r5,r6`
    a.label('CFIND')
    a.cmpw(6, 26)
    a.bc('ge', 'CHAVE')                            # unmapped node keeps the global ceiling
    a.rlwinm(9, 6, 2, 0, 29)
    a.add(9, 9, 28)
    a.lwz(9, TABLE, 9)
    a.addi(6, 6, 1)
    a.rlwinm(8, 9, 24, 26, 31)
    a.cmpw(8, 10)
    a.bc('ne', 'CFIND')
    a.rlwinm(12, 9, 0, 30, 31)
    a.label('CHAVE')
    a.rlwinm(9, 11, 18, 30, 31)                    # sp

    # Record (phy_ID, this node's OWN sp, the ceiling we applied) for every self-ID
    # packet, clamped or not. Without this, run 5 is unreadable: a genuine 1394a
    # device reports sp=2 itself, so if the port->node ordering were backwards it
    # would still work -- the family takes min(sp, ceiling) and the device's own sp
    # already limits it. The only casualty would be the 1394b drive silently losing
    # S800, with nothing in the log to say which node was which. The sp column names
    # them: sp 3 is the beta drive, sp 2 the legacy one.
    a.lwz(10, NODEN, 28)
    a.cmpwi(10, 4)
    a.bc('ge', 'CREC')
    a.rlwinm(8, 11, 8, 26, 31)                     # phy_ID
    a.rlwinm(8, 8, 16, 0, 15)
    a.rlwinm(7, 9, 8, 0, 23)                       # own sp
    a.or_(8, 8, 7)
    a.or_(8, 8, 12)                                # applied ceiling
    a.rlwinm(7, 10, 2, 0, 29)
    a.add(7, 7, 28)
    a.stw(8, NODES, 7)
    a.addi(10, 10, 1)
    a.stw(10, NODEN, 28)
    a.label('CREC')

    a.cmpw(9, 12)
    a.bc('le', 'CNEXT')
    a.mr(7, 11)                                    # keep the original for the inverse test
    a.rlwimi(11, 12, 14, 16, 17)                   # sp := ceiling
    a.stw(11, 0, 5)
    a.addi(3, 3, 1)
    a.cmpw(5, 4)
    a.bc('eq', 'CNEXT')                            # last quadlet: no inverse to fix
    a.lwz(10, 4, 5)
    a.not_(0, 7)
    a.cmpw(10, 0)
    a.bc('ne', 'CNEXT')                            # not a matching inverse: leave it
    a.not_(0, 11)
    a.stw(0, 4, 5)
    a.label('CNEXT')
    a.bc('dnz', 'CLOOP')
    a.label('CEND')
    a.blr()

    blob = a.assemble()
    if len(blob) % 4:
        raise SystemExit('blob not word aligned')
    warnings = audit_volatiles(blob, a.labels)
    if warnings:
        for w in warnings:
            print('  VOLATILE-AUDIT: ' + w)
        raise SystemExit('volatile registers do not survive a bl; fix before shipping')
    return blob, a.labels



def patch_cfrg(rsrc, container_off, new_len):
    """Update the OHCIFWIM container's length in the `cfrg` resource.

    `FireWire Enabler` holds two PEF containers in one data fork, and the Code Fragment
    Manager finds them through a `cfrg` (0) resource in the resource fork: one member per
    fragment, each carrying `where`, `offset` and **`length`**. Grow a container without
    updating its member and CFM maps only the old number of bytes, the loader section
    falls off the cut end, and the fragment silently fails to load -- which on this
    machine means nothing claims the FireWire controller at all.

    A byte-for-byte patch never touches this. A size change always must.

    Layout per Inside Macintosh (CFragResource / CFragResourceMember): a 32-byte header
    ending in memberCount, then members of `memberSize` bytes each, with `offset` and
    `length` at +0x18 and +0x1c from the member start.
    """
    do, mo, dl, ml = struct.unpack('>IIII', rsrc[:16])
    out = bytearray(rsrc)
    off, found = do, 0
    while off < do + dl:
        ln = struct.unpack('>I', rsrc[off:off + 4])[0]
        body_at = off + 4
        if ln >= 32 and rsrc[body_at + 32: body_at + 36] == b'pwpc':
            count = struct.unpack('>H', rsrc[body_at + 30: body_at + 32])[0]
            m = body_at + 32
            for _ in range(count):
                arch = rsrc[m:m + 4]
                moff, mlen = struct.unpack('>II', rsrc[m + 0x18: m + 0x20])
                msize = struct.unpack('>H', rsrc[m + 0x28: m + 0x2A])[0]
                if arch != b'pwpc' or msize < 44:
                    raise SystemExit('cfrg member %d looks wrong: arch %r size %d'
                                     % (_, arch, msize))
                if moff == container_off:
                    if mlen == 0:
                        raise SystemExit('cfrg member for 0x%X is kCFragGoesToEOF; '
                                         'growing it needs no length edit, but this '
                                         'build did not expect that. Refusing.'
                                         % container_off)
                    struct.pack_into('>I', out, m + 0x1C, new_len)
                    found += 1
                m += msize
        off = (off + 4 + ln + 3) & ~3
    if found != 1:
        raise SystemExit('expected exactly 1 cfrg member at container offset 0x%X, '
                         'found %d' % (container_off, found))
    return bytes(out)


def sections(c):
    n = struct.unpack('>H', c[32:34])[0]
    return [list(struct.unpack('>iIIIIIBBBB', c[40 + 28 * i: 68 + 28 * i])) for i in range(n)]


def put_sections(c, secs):
    c = bytearray(c)
    for i, s in enumerate(secs):
        struct.pack_into('>iIIIIIBBBB', c, 40 + 28 * i, *s)
    return bytes(c)


def finder_info(path):
    out = subprocess.run(['xattr', '-px', 'com.apple.FinderInfo', path],
                         capture_output=True, text=True, check=True).stdout
    return bytes(int(x, 16) for x in out.split())


def main():
    selftest()
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, outdir = sys.argv[1], sys.argv[2]

    data = open(src, 'rb').read()
    rsrc = open(src + '/..namedfork/rsrc', 'rb').read()
    fi = finder_info(src)
    if fi[0:8] != b'ndrvfw  ':
        raise SystemExit('type/creator is %r, expected %r -- is this really the '
                         'FireWire Enabler?' % (fi[0:8], b'ndrvfw  '))

    c1, c2 = data[:C2_AT], data[C2_AT:]
    if c2[:8] != b'Joy!peff' or c1[:8] != b'Joy!peff':
        raise SystemExit('expected two PEF containers, second at 0x%X' % C2_AT)
    if b'OHCIFWIM' not in c2 or b'LynxFWIM' not in c1:
        raise SystemExit('containers are not (LynxFWIM, OHCIFWIM) as expected')

    secs = sections(c2)
    code, dat, ldr = secs
    if code[6] != 0 or code[2] != code[3] != code[4] != C2_CODE_SIZE or code[5] != 0x80:
        raise SystemExit('OHCIFWIM code section is not the expected %d bytes at 0x80: %r'
                         % (C2_CODE_SIZE, code))
    for site, want in BL_TO_GLUE.items():
        got = struct.unpack('>I', c2[0x80 + site: 0x84 + site])[0]
        if got == want:
            continue
        raise SystemExit('call site 0x%X holds 0x%08X, expected 0x%08X (bl to the '
                         'FWProcessSelfIDs glue). Refusing to patch an unrecognised '
                         'build.' % (site, got, want))

    os.makedirs(outdir, exist_ok=True)
    for order, tag, abbr in ((ORDER_ASCEND, 'ascend', 'asc'),
                             (ORDER_DESCEND, 'descend', 'desc')):
        blob, labels = build_blob(C2_CODE_SIZE, order)
        new_code_size = C2_CODE_SIZE + len(blob)

        body = bytearray(c2[0x80:0x80 + C2_CODE_SIZE])
        for site in sorted(SITES):
            disp = labels['STUB_%X' % site] - site
            struct.pack_into('>I', body, site, (18 << 26) | (disp & 0x03FFFFFC) | 1)
        body += blob

        align = lambda v, n=16: (v + n - 1) & ~(n - 1)
        orig = sections(c2)
        code, dat, ldr = sections(c2)
        dat_off = align(0x80 + new_code_size)
        ldr_off = align(dat_off + dat[4])
        code[2] = code[3] = code[4] = new_code_size
        dat[5], ldr[5] = dat_off, ldr_off

        out = bytearray(put_sections(c2, [code, dat, ldr])[:0x80])
        out += body
        out += b'\0' * (dat_off - len(out))
        out += c2[orig[1][5]: orig[1][5] + orig[1][4]]        # data section, verbatim
        out += b'\0' * (ldr_off - len(out))
        out += c2[orig[2][5]: orig[2][5] + orig[2][4]]        # loader section, verbatim
        out = bytes(out)

        assert out[orig[1][5] if False else dat_off:dat_off + orig[1][4]] == \
            c2[orig[1][5]:orig[1][5] + orig[1][4]], 'data section not carried verbatim'
        changed = sum(a != b for a, b in
                      zip(c2[0x80:0x80 + C2_CODE_SIZE], out[0x80:0x80 + C2_CODE_SIZE]))
        assert changed == 4, 'expected 4 changed bytes in the original code, got %d' % changed

        new_data = c1 + out
        new_rsrc = patch_cfrg(rsrc, C2_AT, len(out))
        new_rsrc = versstamp.stamp(
            new_rsrc, PATCHED_SHORT,
            '%s - S800 per-conn clamp v%d, %s' % (PATCHED_SHORT, BUILD, abbr),
            expect_short=STOCK_SHORT)
        vdir = os.path.join(outdir, tag)
        os.makedirs(vdir, exist_ok=True)
        dst = os.path.join(vdir, 'FireWire Enabler')
        with open(dst, 'wb') as f:
            f.write(new_data)
        with open(dst + '/..namedfork/rsrc', 'wb') as f:
            f.write(new_rsrc)
        subprocess.run(['xattr', '-wx', 'com.apple.FinderInfo',
                        ' '.join('%02x' % b for b in fi), dst], check=True)

        print('%s  [%s ordering]' % (dst, tag))
        print('    OHCIFWIM code %d -> %d bytes (+%d);  data fork %d -> %d;  rsrc %d carried'
              % (C2_CODE_SIZE, new_code_size, len(blob), len(data), len(new_data), len(rsrc)))
        print('    cfrg member for container 0x%X: length -> %d bytes' % (C2_AT, len(out)))
        print('    vers (1) stamped %s -> %s (build v%03d)'
              % (STOCK_SHORT, PATCHED_SHORT, BUILD))
        print('    ' + '  '.join('%s@0x%X' % (n, labels[n])
                                 for n in ('SCRATCH', 'HOOK', 'CLAMP')))
        print('    call sites ' + '  '.join('0x%X->0x%X' % (st, labels['STUB_%X' % st])
                                            for st in sorted(SITES)))


if __name__ == '__main__':
    main()
