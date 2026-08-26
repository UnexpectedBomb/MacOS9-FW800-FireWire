# SUPERSEDED: the one-byte global clamp

> **This describes the first fix, which is no longer what ships.** It clamped the whole speed map
> to S400 with one byte in `FireWire Support`, which recovered the two FW400 ports at the cost of
> the FW800 port's S800. The shipping fix moves the clamp into the FWIM and makes it
> per-connection, so all three ports run at their proper speeds. See `README.md`.
>
> Kept because the defect analysis below is still correct and is why the current fix works, and
> because the `Max_Legacy_SPD` measurements are the original hardware evidence.

## The defect

`FWProcessBusReset` in `FWServicesLib` builds the 1394 speed map — a 64×64 byte matrix — **entirely
from the `sp` field of each node's self-ID packet**:

```
0x8000ffb4  rlwinm r4,r4,18,30,31   ; r4 = sp (IEEE bits 15:14)
0x8000ffb8  stb    r4, 8(r24)       ; speedmap[i][i] = raw sp
0x80010014  stbu   r5, 1(r7)        ; speedmap[i][n] = min(sp_i, speedmap[parent][n])
0x80010018  stbu   r5, 0x40(r8)     ; transpose, 64-byte stride
```

**`sp` is a NODE capability, not a HOP capability.** Two 1394b nodes joined by a *legacy* (1394a
data/strobe) cable each report `sp = 3`, so min() yields S800 — but that hop carries only S400. OHCI
descriptor `spd = 3` is S800 on an OHCI 1.1 controller, so the packet really goes out at S800 and is
simply not received. The config-ROM read fails and no device appears.

Measured on this machine (TI TSB81BA3, `PHY_Speed = 7` → `sp = 3`):

| Connection | Map says | Hop really is | Result |
|---|---|---|---|
| 9-to-9 (beta) | S800 | S800 | mounts |
| 9-to-6 (legacy), same port | S800 | S400 | fails |
| 6-to-6 (legacy) | S800 | S400 | fails |
| FW400 MDD, Lucent 1394a PHY (`sp = 2`) | S400 | S400 | mounts |

### The hardware knew the answer

`Max_Legacy_SPD` in PHY base register 6 — TI's `Max_legacy_path_speed`, "a new CFR addition in IEEE
Std 1394b-2002", the maximum speed usable across a path containing legacy segments:

| FWPhyDump run | reg 6 | Max_Legacy_SPD |
|---|---|---|
| A — idle | `0x10` | 0 |
| **B — drive on a FW400 port** | **`0x50`** | **2 = S400** |
| D — drive on the FW800 port | `0x10` | 0 |

The PHY computed **S400** and published it, only when a legacy segment existed. The speed map ignores
it. Two independent PHY registers agree the hop is S400 (`Negotiated_speed` and `Max_Legacy_SPD`)
while the map says S800.

This is why Apple's OS X family maps the reserved code to "S800 but *unknown*" and then verifies by
transfer (`IOFireWireController.cpp`), and why TI's errata recommends determining speeds "by a
try-and-see method". FireWire 2.8.x trusts the computed value.

## The fix

`rlwinm r4,r4,18,30,31` → `rlwinm r4,r4,18,30,30`. One byte: `0xBE` → `0xBC`.

`sp` 0→S100, 1→S100, 2→S400, 3→S400. Capping the diagonals caps the whole map, since every other
entry is a min() of them.

**Monotonic, therefore safe:** every path keeps its speed or gets slower, and slower is always legal
on a faster hop. It cannot break a configuration that already works.

**Costs:** genuine S200 devices drop to S100 (S200 was effectively never shipped). The FW800 port caps
at S400 — real S800 needs per-hop speed from the PHY, which lives in the FWIM, not here.

## Build

```bash
./build-firewire-rom.py <your fork-ful Mac OS ROM> fw1 FW800_FireWireFix_fw1.hqx
```

The base must be **fork-ful** — rehydrate one with `usb2-ehci/scripts/rehydrate-rom-fork.py <data>
<._sidecar> <out>` if you only have a data fork and an AppleDouble sidecar.

Guards: fork-ful base required; SysEnabler size preserved; `SysEnabler.rdump` byte-identical; the
parcel must differ by exactly one byte; the rebuilt ROM must dump back cleanly. Nothing is ever
stamped into the resource fork — a `vers` (1) there mis-versions the System Enabler and the ROM boots
to a grey screen.

## Install and test

1. **Back up the current `Mac OS ROM`** from the System Folder. Without a valid one the machine cannot
   boot OS 9, so keep a copy reachable from OS X or another volume.
2. Expand the `.hqx` and put the result in the System Folder as `Mac OS ROM`.
3. Reboot **with the drive on a FW400 port**, cold.

| Result | Meaning |
|---|---|
| Drive mounts on a FW400 port | **Confirmed.** Goal 1 achieved — all three ports usable |
| Still doesn't mount | Hypothesis wrong or incomplete. Swap the ROM back; nothing lost |
| Beta port stops working | Unexpected — the patch is meant to be monotonic. Report it; something is mis-modelled |

Then re-run **FWPhyDump** and **FWOHCIDump** in both configurations to capture the post-patch state.

Recovery is just replacing a file — the ROM is a System Folder file, not firmware.

## v2, later

Clamp the map to `Max_Legacy_SPD` when nonzero — the vendor-intended field for exactly this — which
would preserve S800 on beta-only buses while capping mixed ones. Needs the FWIM, since the family
never touches the PHY. TI's errata warns early-production parts miscompute that field; ours is
`83_13_04`, a good revision.
