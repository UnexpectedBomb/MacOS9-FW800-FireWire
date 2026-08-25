# FireWire 400 for the Power Mac G4 MDD (FireWire 800) under Mac OS 9

On a **Power Mac G4 MDD FW800** (`PowerMac3,6`) running Mac OS 9 via the MacOS9Lives modified ROM, the
two FireWire **400** ports do not work at all. This is a one-byte fix for the `FireWire Support`
extension that makes all three FireWire ports work.

**Status:** FireWire 400 solved and confirmed on hardware — both ports, cold boot and hot-plug, mount
and eject. Everything currently runs at S400; restoring S800 on the FW800 port is in progress
(see `docs/HANDOFF.md`).

## What was wrong

`FWProcessBusReset` in `FWServicesLib` builds the 1394 speed map — a 64×64 byte matrix — **entirely
from the `sp` field of each node's self-ID packet**:

```
speedmap[i][i] = sp_i                              (the diagonal)
speedmap[i][n] = min(sp_i, speedmap[parent][n])    (everything else)
```

**`sp` describes a NODE's capability, not a HOP's.** Two 1394b nodes joined by a *legacy* (1394a
data/strobe) cable each report `sp = 3`, so `min()` yields S800 — but that hop carries only S400. The
packet is transmitted at S800 (OHCI descriptor `spd = 3` on an OHCI 1.1 controller) and simply is not
received. The config-ROM read fails and no device appears.

The MDD FW800's PHY is a **TI TSB81BA3**, a three-port 1394b transceiver: two 6-pin bilingual
connectors plus one 9-pin beta connector, all on one PHY. It reports `PHY_Speed = 7`, so `sp = 3`.

| Connection | Map says | Hop really is | Result |
|---|---|---|---|
| 9-to-9 (beta) | S800 | S800 | mounts |
| 9-to-6 (legacy), **same port** | S800 | S400 | fails |
| 6-to-6 (legacy) | S800 | S400 | fails |
| FW400 MDD, Lucent 1394a PHY (`sp = 2`) | S400 | S400 | mounts |

The hardware knew: the PHY publishes `Max_Legacy_SPD` = S400 whenever a legacy segment exists, and 0
when there is none. The driver never reads it. This is why Apple's OS X family maps the reserved speed
code to "S800 but *unknown*" and then verifies by transfer, and why TI's own errata recommends
determining speeds "by a try-and-see method".

## The fix

One instruction, one byte, in `FWServicesLib` inside the `FireWire Support` extension's resource fork:

```
rlwinm r4,r4,18,30,31   (0x548497BE)  ->  rlwinm r4,r4,18,30,30   (0x548497BC)
```

`sp` 0→S100, 1→S100, 2→S400, 3→S400. Capping the diagonals caps the whole map.

**Monotonic, therefore safe:** every path keeps its speed or gets slower, and slower is always legal on
a faster hop — so it cannot break a configuration that already works.

**Costs:** genuine S200 devices drop to S100 (S200 was effectively never shipped), and the FW800 port is
capped at S400.

## Install

`artifacts/FireWire_Support_S400fix_v3.bin` is MacBinary. Expand it, back up the original
`FireWire Support` from your System Folder's Extensions, drop this one in its place, reboot.

It identifies itself as **version 2.8.8** in Extensions Manager (stock is 2.8.7), and Apple System
Profiler shows *"S400 clamp so the FW400 ports work on FW800 MDD"*.

`artifacts/FireWire_Support_STOCK_2.8.7.bin` is the unmodified stock extension, so you can swap back —
that also switches the FW800 port from S400 to S800 at the cost of the FW400 ports.

### Does this apply to your machine?

The MacOS9Lives "unsupported machines" install CD installs FireWire **2.8.7**, so most FW800 MDD
installs should match. Stock fingerprint:

```
FireWire Support (stock)   data fork 4500      md5 163520614cf13853911c8f6972a7d7e1
                           rsrc fork 253497    md5 a779c606e63c50bb55b845aae17168c0
                           vers (1) 2.8.7
```

If yours differs, patch your own copy rather than using the prebuilt file:

```bash
tools/patch-firewire-support.py "FireWire Support.bin" "FireWire Support patched.bin"
```

It requires the 12-byte signature to occur **exactly once** and refuses otherwise, so a mismatched
build fails loudly rather than silently.

## Tools

| | |
|---|---|
| `patch-firewire-support.py` | the fix — one byte in the extension |
| `stamp-firewire-support.py` | set the `vers` (1) strings so a patched file is identifiable |
| `wrap-macbinary.py` | wrap a fork-ful file into MacBinary II, real resource fork, valid CRC |
| `patch-fwservices-speed.py` | same fix applied to the Mac OS ROM parcel — **not needed**, the extension's copy is what binds |
| `build-firewire-rom.py` | ROM build wrapper for the above, with SysEnabler guards |

## Credit and licence

The defect analysis and patch were produced with Claude (Anthropic). `FireWire Support` is Apple
software; only the tools and documentation here are ours. The patched artifact is a one-byte
modification of the user's own file, provided for people who already have that extension installed.
