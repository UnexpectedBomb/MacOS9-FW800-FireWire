"""ppcasm.py — a deliberately tiny two-pass PowerPC assembler.

Only the instruction forms the FireWire Enabler patch needs are implemented. Every
encoder is checked against a real instruction taken from the Apple binaries in
`selftest()`, so a typo in a bit field fails here rather than on the target machine.

Usage:
    a = Asm(base_va)            # base_va = the address the first word will live at
    a.label('top'); a.mflr(0); a.b('top')
    blob = a.assemble()
"""
import struct


def _d(op, rt, ra, d):
    return (op << 26) | (rt << 21) | (ra << 16) | (d & 0xFFFF)


def _x(op, rs, ra, rb, xo, rc=0):
    return (op << 26) | (rs << 21) | (ra << 16) | (rb << 11) | (xo << 1) | rc


def _m(op, rs, ra, sh, mb, me, rc=0):
    return (op << 26) | (rs << 21) | (ra << 16) | (sh << 11) | (mb << 6) | (me << 1) | rc


# BO/BI pairs for the cr0 conditions used here
_COND = {'eq': (12, 2), 'ne': (4, 2), 'lt': (12, 0), 'ge': (4, 0),
         'gt': (12, 1), 'le': (4, 1), 'dnz': (16, 0)}


class Asm:
    def __init__(self, base_va):
        self.base = base_va
        self.words = []          # int, or ('b', kind, arg, label)
        self.labels = {}

    # ---- bookkeeping -------------------------------------------------
    def _emit(self, w):
        self.words.append(w)

    def label(self, name):
        if name in self.labels:
            raise ValueError('duplicate label %r' % name)
        self.labels[name] = self.base + 4 * len(self.words)

    def here(self):
        return self.base + 4 * len(self.words)

    def raw(self, w):
        self._emit(w)

    def blob(self, b):
        if len(b) % 4:
            raise ValueError('blob must be a multiple of 4 bytes')
        for i in range(0, len(b), 4):
            self._emit(struct.unpack('>I', b[i:i + 4])[0])

    # ---- instructions ------------------------------------------------
    def _base(self, ra):
        # RA=0 in a D-form load/store means the literal address zero, not r0. Nothing
        # here ever wants absolute addressing, and getting it by accident is a wild
        # store into low memory, so refuse it outright.
        if ra == 0:
            raise ValueError('load/store with RA=0 addresses absolute zero, not r0')
        return ra

    def lwz(self, rt, d, ra):    self._emit(_d(32, rt, self._base(ra), d))
    def lwzu(self, rt, d, ra):   self._emit(_d(33, rt, self._base(ra), d))
    def stw(self, rs, d, ra):    self._emit(_d(36, rs, self._base(ra), d))
    def stwu(self, rs, d, ra):   self._emit(_d(37, rs, self._base(ra), d))
    def addi(self, rt, ra, d):
        # In D-form, RA=0 means the literal zero, NOT r0. `addi rD,r0,v` is `li`,
        # so silently accepting ra=0 here turns an intended increment of r0 into a
        # load-immediate. Say `li` when that is what you mean.
        if ra == 0:
            raise ValueError('addi with RA=0 is li -- use li() if that is intended')
        self._emit(_d(14, rt, ra, d))
    def addis(self, rt, ra, d):  self._emit(_d(15, rt, ra, d))
    def ori(self, ra, rs, u):    self._emit(_d(24, rs, ra, u))
    def li(self, rt, v):         self._emit(_d(14, rt, 0, v))
    def lis(self, rt, v):        self._emit(_d(15, rt, 0, v))
    def mr(self, rt, rs):        self._emit(_x(31, rs, rt, rs, 444))
    def not_(self, ra, rs):      self._emit(_x(31, rs, ra, rs, 124))
    def sub(self, rt, ra, rb):   # rt = ra - rb, i.e. subf rt,rb,ra
        self._emit((31 << 26) | (rt << 21) | (rb << 16) | (ra << 11) | (40 << 1))
    def add(self, rt, ra, rb):   self._emit((31 << 26) | (rt << 21) | (ra << 16) | (rb << 11) | (266 << 1))
    def cmpwi(self, ra, v):      self._emit((11 << 26) | (ra << 16) | (v & 0xFFFF))
    def cmpw(self, ra, rb):      self._emit((31 << 26) | (ra << 16) | (rb << 11))
    def rlwinm(self, ra, rs, sh, mb, me): self._emit(_m(21, rs, ra, sh, mb, me))
    def rlwimi(self, ra, rs, sh, mb, me): self._emit(_m(20, rs, ra, sh, mb, me))
    def lmw(self, rt, d, ra):    self._emit(_d(46, rt, self._base(ra), d))
    def stmw(self, rs, d, ra):   self._emit(_d(47, rs, self._base(ra), d))
    def or_(self, ra, rs, rb):   self._emit(_x(31, rs, ra, rb, 444))
    def mflr(self, rt):          self._emit((31 << 26) | (rt << 21) | (256 << 11) | (339 << 1))
    def mtlr(self, rs):          self._emit((31 << 26) | (rs << 21) | (256 << 11) | (467 << 1))
    def mtctr(self, rs):         self._emit((31 << 26) | (rs << 21) | (288 << 11) | (467 << 1))
    def blr(self):               self._emit(0x4E800020)

    def b(self, target, lk=0):   self._emit(('br', target, lk))
    def bl(self, target):        self.b(target, 1)
    def bc(self, cond, target):  self._emit(('bc', target, cond))

    # ---- resolve -----------------------------------------------------
    def assemble(self):
        out = bytearray()
        for i, w in enumerate(self.words):
            va = self.base + 4 * i
            if isinstance(w, int):
                enc = w
            elif w[0] == 'br':
                tgt = self.labels.get(w[1], w[1]) if isinstance(w[1], str) else w[1]
                disp = tgt - va
                if not (-0x2000000 <= disp < 0x2000000):
                    raise ValueError('branch out of range at 0x%x' % va)
                enc = (18 << 26) | (disp & 0x03FFFFFC) | w[2]
            elif w[0] == 'bc':
                tgt = self.labels.get(w[1], w[1]) if isinstance(w[1], str) else w[1]
                disp = tgt - va
                if not (-0x8000 <= disp < 0x8000):
                    raise ValueError('conditional branch out of range at 0x%x' % va)
                bo, bi = _COND[w[2]]
                enc = (16 << 26) | (bo << 21) | (bi << 16) | (disp & 0xFFFC)
            else:
                raise ValueError(w)
            out += struct.pack('>I', enc)
        return bytes(out)


def selftest():
    """Every expectation below is a real instruction lifted from Apple's binaries."""
    a = Asm(0x80000000)
    a.mflr(0)                              # 0x8000ff14 in the OS 9 FireWire binaries
    a.mtlr(0)                              # 0x8000cb4
    a.mtctr(5)                             # 0x8000ffe8
    a.rlwinm(4, 4, 18, 30, 31)             # 0x8000ffb4  the speed-map extract
    a.lwz(4, 0, 8)                         # 0x8000ffb0
    a.stw(2, 0x14, 1)                      # 0x8000d630  the CFM glue's TOC save
    a.stwu(1, -0xA0, 1)                    # 0x80011bf0
    a.mr(30, 3)                            # 0x80002d10
    a.not_(3, 8)                           # 0x80011cc4  nor r3,r8,r8
    a.addi(9, 27, 0xC)                     # 0x8000ff8c  addi r9,r27,0xc
    a.cmpwi(3, 0)                          # 0x80002cdc
    a.sub(8, 8, 8)                         # 0x8000000c, same source
    a.stmw(24, -0x20, 1)                   # 0x80002d04
    a.lmw(26, -0x18, 1)                    # 0x80000b9c
    a.blr()                                # 0x80002cc0
    got = a.assemble().hex()
    want = ('7c0802a6' '7c0803a6' '7ca903a6' '548497be' '80880000' '90410014'
            '9421ff60' '7c7e1b78' '7d0340f8' '393b000c' '2c030000'
            '7d084050' 'bf01ffe0' 'bb41ffe8' '4e800020')
    assert got == want, 'ppcasm selftest FAILED\n got %s\nwant %s' % (got, want)

    b = Asm(0x1000)                        # branch/condition forms
    b.label('top')
    b.bc('dnz', 'top')
    b.bl(0x800)
    b.bc('eq', 'end')
    b.label('end')
    assert b.assemble().hex() == '420000004bfff7fd41820004', b.assemble().hex()
    return True


if __name__ == '__main__':
    selftest()
    print('ppcasm selftest OK')


# --------------------------------------------------------------------------
# Volatile-register audit
#
# On PowerPC r0 and r3-r12 are VOLATILE: a called routine may destroy them.
# Holding a value in one across a `bl` is the classic hand-assembly bug, and it
# cost a hardware run here -- the FireWire port state lived in r10 and the
# negotiated speed in r12 across ReadPhyRegister, whose own prologue does
# `mfcr r12`. The values came back as garbage, the topology test rejected them,
# and the fix silently degraded to its conservative fallback.
#
# This decodes the assembled words and reports any volatile that is written,
# then survives a `bl`, then is read before being rewritten. Control flow is
# ignored, so a branch can produce a false positive; every hit still deserves an
# explanation before it is dismissed.
# --------------------------------------------------------------------------

_VOLATILE = {0} | set(range(3, 13))


def _defs_uses(w):
    """(defs, uses, is_call) for the instruction forms this assembler emits."""
    op, rt, ra, rb = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    if op == 18:
        return (set(), set(), bool(w & 1))
    if op == 16:
        return (set(), set(), False)
    if op in (32, 33, 34, 40, 46):                       # lwz lwzu lbz lhz lmw
        return ({rt}, {ra}, False)
    if op in (36, 37, 38, 44, 47):                       # stw stwu stb sth stmw
        return (set(), {rt, ra}, False)
    if op in (14, 15):                                   # addi addis (RA=0 is literal)
        return ({rt}, ({ra} if ra else set()), False)
    if op == 24:                                         # ori rA,rS,imm
        return ({ra}, {rt}, False)
    if op in (10, 11):                                   # cmplwi cmpwi
        return (set(), {ra}, False)
    if op == 21:                                         # rlwinm rA,rS
        return ({ra}, {rt}, False)
    if op == 20:                                         # rlwimi rA,rS  (reads rA too)
        return ({ra}, {rt, ra}, False)
    if op == 31:
        xo = (w >> 1) & 0x3FF
        if xo in (444, 124):                             # or / nor  rA,rS,rB
            return ({ra}, {rt, rb}, False)
        if xo in (266, 40):                              # add / subf rT,rA,rB
            return ({rt}, {ra, rb}, False)
        if xo in (0, 32):                                # cmpw / cmplw
            return (set(), {ra, rb}, False)
        if xo == 339:                                    # mfspr
            return ({rt}, set(), False)
        if xo == 467:                                    # mtspr
            return (set(), {rt}, False)
    return (set(), set(), False)


def audit_volatiles(blob, labels=None):
    """Return a list of human-readable warnings; empty means clean."""
    words = [struct.unpack('>I', blob[i:i + 4])[0] for i in range(0, len(blob), 4)]
    names = {}
    if labels:
        base = min(labels.values()) if labels else 0
        for k, v in labels.items():
            names[(v - base) // 4] = k
    warn = []
    live = {}                     # volatile reg -> index where it was last written
    crossed = set()               # volatiles that have survived a call since
    for i, w in enumerate(words):
        op = w >> 26
        defs, uses, is_call = _defs_uses(w)
        for r in uses & _VOLATILE:
            if r in crossed:
                where = names.get(max([k for k in names if k <= i], default=None), '?')
                warn.append('r%-2d written at +0x%X, read at +0x%X after a bl '
                            '(near %s) -- volatile, the call may have destroyed it'
                            % (r, live.get(r, 0) * 4, i * 4, where))
                crossed.discard(r)
        for r in defs & _VOLATILE:
            live[r] = i
            crossed.discard(r)
        if is_call:
            crossed |= {r for r in live if r not in (3,)}
            live[3] = i           # r3 comes back as the return value
            crossed.discard(3)
        # After an unconditional transfer nothing falls through, so whatever follows
        # is only reachable by branch and none of this state carries into it. Without
        # this the scan walks off the end of one routine into the next and reports the
        # next routine's parameters as stale.
        if (op_of(w) == 18 and not (w & 1)) or w == 0x4E800020:
            live, crossed = {}, set()
    return warn


def op_of(w):
    return w >> 26
