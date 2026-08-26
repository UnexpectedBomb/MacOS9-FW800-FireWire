# FireWire S800 for the Power Mac G4 MDD (FW800) under Mac OS 9

Restores all three FireWire ports on a Power Mac G4 MDD FW800 (PowerMac3,6) running Mac OS 9.2.2:
the two FW400 ports at S400, and the FW800 port at S800, at the same time. The whole fix is one
patched extension. `FireWire Support` stays stock.

Stock behaviour on this machine is that the two FW400 ports do not enumerate a device at all, and
the FW800 port runs at S400.

## The defect, in Apple's own words

`FWServicesLib` builds the IEEE 1394 speed map from the `sp` field of each node's self-ID packet.
`sp` is two bits, and the value 3 is **reserved** in 1394a. 1394b uses it to mean "S400 or better,
ask the PHY". It does not mean S800.

Apple's own `IOFireWireController::buildTopology` says exactly that:

```c
speedCode = (id0 & kFWSelfID0SP) >> kFWSelfID0SPPhase;
if( speedCode == kFWSpeedReserved )
    speedCode = kFWSpeed800MBit | kFWSpeedUnknownMask;   // we don't know how fast it is
```

and then verifies by transfer: on a failed config-ROM read it calls `setNodeSpeed(node, local,
current - 1)` and retries, down to S100. TI's TSB81BA3 errata recommends the same try-and-see
approach.

Mac OS 9's family has no step-down. It stores `sp` verbatim and treats 3 as S800. So two 1394b
nodes joined by a **legacy** (1394a data/strobe) cable both claim S800 on a hop that physically
carries S400, the transmit is never received, and the device simply never appears. That is the
dead-FW400-ports bug.

## The fix

OS 9 cannot try-and-see without a rewrite, but the FWIM owns the PHY, and the PHY knows. So the
FWIM (`FireWire Enabler`, the OHCIFWIM container) is hooked immediately before it hands the
self-IDs up to `FWProcessSelfIDs`. For each of its own ports it reads page 0 registers 8, 9 and 11
(Connected, Negotiated_speed, Beta_mode), maps each node to the port it arrives on, and clamps
that node's self-ID `sp` to what its own hop can actually carry. The family's existing
min-propagation then produces a correct map with no change to `FireWire Support` at all.

The local node's own `sp` is deliberately left at S800. That is what allows one speed map to give
S800 to a beta neighbour and S400 to a legacy one simultaneously.

Fail-safe throughout. PHY register 2 is a liveness oracle, and an unreadable PHY, an unexpected
port count, or any topology that is not a plain star centred on this Mac all fall back to a
conservative S400 rather than risking the original symptom.

## Results

Measured on the target machine, Mac OS 9.2.2, one LaCie FW800 drive and a clamshell iBook
(FireWire) in Target Disk Mode.

| run | configuration | result |
|---|---|---|
| 1 | nothing attached | extension loads and binds, hook runs |
| 2 | drive on the FW800 port, 9-to-9 | `beta S800`, ceiling S800, not clamped, mounts |
| 3 | drive on a FW400 port, 6-to-6 | `legacy(DS) S400`, clamped, mounts |
| 4 | drive on the FW800 port, 9-to-6 | `legacy(DS) S400`, clamped, mounts |
| 5 | drive on FW800 + iBook on FW400 | S800 and S400 in one map, both work |

Throughput, same drive and controller with only the port changed, so the single variable is the
hop speed. S800 was faster in 39 of 44 QuickBench measurements. Averaged over transfer sizes of
64K and above: sequential read +10.6%, sequential write +7.5%, random read +10.6%, random write
+6.4%. Peak sequential read went from 26.85 to 30.65 MB/sec. The gain is modest because the drive
peaks near 30 MB/sec and a FireWire 400 hop already delivers roughly 30 MB/sec after SBP-2
overhead. A faster device has more headroom to recover. Details in
`docs-QUICKBENCH-S800-vs-S400.md`.

## Install

Both files go in the System Folder's Extensions folder. Keep the originals.

| file | note |
|---|---|
| `FireWire Support` | must be **stock**. If a previous global-clamp build is installed, put the stock one back first, or it masks everything. |
| `FireWire Enabler` | the patched build. Reads **2.8.8** in Extensions Manager against a stock 2.8.7. |

`FWFixCheck` is a read-only diagnostic. It scans the System heap for the hook's counter block and
reports what the hook decided: per-port state, beta flag and negotiated speed, each node's own
`sp` against the ceiling applied to it, and whether `FireWire Support` really is stock.

## Limitations, stated plainly

* **Only a plain star centred on this Mac gets per-connection speeds.** Behind a hub or a daisy
  chain, everything is capped at S400. This is correct rather than conservative: the PHY can only
  measure the hops it terminates, a legacy hop deeper in the tree is invisible in the self-ID
  stream, and assuming S800 there would reproduce the original defect. See the warning in
  `tools/patch-firewire-enabler.py`.
* **One FW800 device was available for testing.** Runs 2 through 4 prove each half separately, and
  run 5 proves per-port ceilings are assigned correctly and simultaneously. The specific case of a
  second 1394b device on a legacy hop alongside an S800 device follows from those as an inference,
  not as a measurement.
* **FW400 port 1 has not been tested.** All legacy testing used port 2. Same PHY, same code path.
* **Sleep and wake are broken on this machine independently of FireWire**, confirmed with no
  FireWire device ever attached. Not addressed here.

## Building

```bash
python3 tools/patch-firewire-enabler.py "FireWire Enabler" out/
python3 tools/wrap-macbinary.py "out/ascend/FireWire Enabler" "FireWire S800 Enabler.bin"
```

Give it **your machine's own** `FireWire Enabler`, transferred with its resource fork intact. The
patcher refuses to touch a file whose `vers` is not 2.8.7, so it cannot silently patch a build it
was not derived from.

What it does: grows the OHCIFWIM container's code section, appends the hook, redirects the two
`bl` instructions that call `FWProcessSelfIDs`, updates the container length in the **`cfrg`**
resource, and stamps `vers` (1) to 2.8.8. Two bytes change inside the original code, everything
else is appended, and the data and loader sections come through byte-identical.

### Files

| path | purpose |
|---|---|
| `artifacts/FireWire S800 Enabler.bin` | the patched extension, MacBinary. Expands to a file already named `FireWire Enabler`. |
| `artifacts/FireWire_Support_STOCK_2.8.7.bin` | stock `FireWire Support`, to revert to. |
| `artifacts/FWFixCheck.bin` | the diagnostic. |
| `artifacts/FireWire_Support_S400fix_v3.bin` | **superseded.** The earlier global S400 clamp. Installing it now would mask the current fix. Kept only because it was previously released. |
| `tools/patch-firewire-enabler.py` | the patcher. All the reasoning is in its docstring and comments. |
| `tools/ppcasm.py` | a small PowerPC assembler whose encoders are each checked against a real instruction from the Apple binaries. It refuses `addi` with `RA=0`, a load or store based on `r0`, and any volatile register held across a `bl`. Each of those caught a real bug here. |
| `tools/versstamp.py` | the `vers` (1) rewrite, shared with `stamp-firewire-support.py`. |
| `tools/fw-fixcheck/` | diagnostic source, for the Retro68 PowerPC toolchain. |
| `docs/S800-RUNBOOK.md` | every hardware run, what it asked, what would have falsified it, and the three bugs found on the way. |
| `docs/QUICKBENCH-S800-vs-S400.md` | the throughput comparison and why it is only about ten percent. |
| `docs/SUPERSEDED-one-byte-fix.md` | the earlier global clamp and the original defect analysis. |
| `logs/` | raw diagnostic output from every run quoted above. |

## Credit

Reverse engineering, the patch, the diagnostics and the documentation were produced with
substantial help from Claude (Anthropic), working from Apple's published IOFireWireFamily source,
the TI TSB81BA3 datasheet, and disassembly of the shipping OS 9 binaries. All hardware testing was
run on a real Power Mac G4 MDD FW800.
