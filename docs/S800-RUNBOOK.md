# S800 fix — what to install, what each run asks, and what would falsify it

Goal: one drop-in extension that gives the two FW400 ports S400 **and** the FW800 port S800,
at the same time. The clamp lives in the FWIM, which asks the PHY what each of its own ports
actually negotiated and clamps each node to the port it arrives on. `FireWire Enabler` is the
only file that changes.

## Install

From `artifacts/`, all MacBinary:

| file | goes to | note |
|---|---|---|
| `FireWire S800 Enabler.bin` | Extensions | start with this one. Reads **2.8.8** in Extensions Manager against stock 2.8.7 |
| the `desc` variant (not shipped; see `--both`) | keep to hand | the other ordering, see run 5 |
| `FWFixCheck.bin` | anywhere | the diagnostic. Writes `FWFixCheck.log` next to itself. |

Names are kept under 22 characters on purpose: HFS caps a filename at 31, the earlier ones ran
to 38, and the Finder truncated away exactly the part that said which build it was. `asc` and
`desc` now sit early enough to survive display truncation as well.

Both Enabler variants expand to a file already named exactly `FireWire Enabler`, so each drops
into Extensions with no rename — which also means they are indistinguishable once expanded.
**Expand one at a time**, and treat the log as the authority: FWFixCheck reads the ordering out
of the resident block, so a mislabelled file cannot mislead you.


Keep the originals. Reverting is: put both stock extensions back. Stock `FireWire Enabler`
md5 is `1a3648314b1a9b9bc9dc76c6b8187aaf`.

## Why there are two variants

Self-IDs are a post-order stream: a node's children immediately precede it, so the tree is
reconstructable from node order plus child counts. What that does **not** pin down is whether
the first child in the stream sits on the lowest or the highest numbered child port. Apple's
`countNodeIDChildren` walks ports ascending, but `buildTopology` matches the built-in hub with
`hubChildRemainder == childrenRemaining`, a countdown, and whether those compose to ascending
or descending turns on exactly when the decrement lands. The explanatory comment reads either
way. Rather than guess, both are built.

**It only matters when two connected ports run at different speeds** — that is, run 5 alone.
Everywhere else the ordering is irrelevant because every node gets the same ceiling. And the
wrong choice fails the way this machine already failed before any of this work: the legacy
device does not mount. Visible, harmless, and fixed by swapping the file.

## Reading FWFixCheck

* **block ABSENT** — the patched Enabler is not resident. Almost certainly the Mac OS ROM's
  own `pciclass,0c0010` parcel bound instead of the extension, the same ambiguity `FWPatchCheck
  v2` hit with the family library. Says nothing about the clamp; the answer is to patch the ROM
  parcel too.
* **block present, `hook calls 0`** — resident but never ran.
* **`mode PER-CONNECTION`** — the per-port map was accepted; each `node N ceiling S___` line is
  what that node was clamped to.
* **`mode GLOBAL FALLBACK`** — the topology was not a plain star centred on this Mac, or the
  PHY was unreadable, so everything got the minimum. Correct and safe, just not fast.

## Run 1 in full — proving the patched Enabler loads and binds

Run 1 is the only run whose job is to validate the *detector* as well as the subject, so it is
done as a before/after pair. Step 0 costs no reboot and is what makes step 3 mean anything.


### Known failure, fixed in v3 — read this if you ran v2

v2 of the Enabler did not load at all. `FireWire Enabler`'s data fork holds two PEF containers,
and CFM locates them through a **`cfrg` (0) resource** in the resource fork carrying each
fragment's `offset` **and `length`**. Growing the OHCIFWIM container without updating its member
left CFM mapping only the original 62096 bytes, so the loader section — moved past that cut —
fell off the end and the fragment silently failed to load. Nothing then claimed the FireWire
controller, its PCI memory space was never enabled, and `FWFixCheck v2` took a Type 1 bus error
on its first MMIO read at `0xF5000000`. The crash was the symptom; the unloadable fragment was
the bug. A byte-for-byte patch never touches `cfrg`; a size change always must.

v3 updates the `cfrg` member length (two bytes) so both containers' declared lengths match their
real extents, and `FWFixCheck v7` now checks the unit table for a bound FWIM **before** going
near MMIO, so this class of failure reports itself instead of crashing.

### Step 0 — the control, on the machine exactly as it stands now

Do this **before touching any extension**, with the stock `FireWire Enabler` still in place.

1. Expand `FWFixCheck.bin` and run it.
2. Expect: **three beeps**, and in the log

   ```
   *** FWIM COUNTER BLOCK NOT FOUND. ***
   ```

3. Rename the log to `FWFixCheck_CONTROL.log` and keep it.

This proves what step 3 otherwise has to assume: the `S8FX` block really is absent when the
patched Enabler is not installed. Without it, "block found" in step 3 could just mean the scan
matches anything.

### Step 1 — install

In the System Folder's Extensions folder, keeping the originals somewhere safe:

1. Replace `FireWire Enabler` with the expansion of `FireWire S800 Enabler.bin`.
3. Check both are enabled in Extensions Manager.

### Step 2 — reboot with the FireWire bus empty

**Unplug everything from all three FireWire ports** before restarting. Run 1 is defined by an
empty bus.

If the machine fails to boot, hold **Shift** to start with extensions off and put the stock
`FireWire Enabler` back. Nothing here touches the ROM, so there is no scarier recovery than that.

### Step 3 — run FWFixCheck v2 and read the log

Expect **two beeps**. The log lands next to the app (the window's last line says where). Check
the banner says `FWFixCheck v7`, then look for:

```
FWIM block @0x........   port->node ordering: ASCEND
  hook calls 1            clamped last 1     total 1
  PHY reg2 0xE3 (Num_Ports 3)   reg7 0x..   localID 0
  remote nodes 0   mapped to ports 0   global ceiling S400
  port 0: not-connected  - skipped, port registers not read
  port 1: not-connected  - skipped, port registers not read
  port 2: not-connected  - skipped, port registers not read
  *** GLOBAL FALLBACK: everything clamped to S400. ***
  Nothing is attached: ... EXPECTED for run 1.
```

### What each line is actually proving

| line | proves |
|---|---|
| block found | the patched Enabler's code section is resident |
| **`hook calls` > 0** | **the decisive one.** Resident is not the same as bound; a non-zero count proves the *extension's* OHCIFWIM is what the family actually calls, not the ROM's `pciclass,0c0010` parcel |
| `ordering: ASCEND` | the variant you think you installed is the one running |
| `Num_Ports 3`, `localID 0`, three port states | the hook parsed our own self-ID and read the PHY — it did real work, not just increment a counter |
| `clamped last 1` | with an empty bus the only self-ID is ours, and the fallback clamped it |

**Presence of the block is suggestive; `hook calls` is the proof.** The file's own bytes carry
the magic with zeroed counters, so a copy sitting in a disk cache buffer could in principle
match the scan. If two blocks are reported, that is fine and expected — one will read `hook
calls 0` and the other will not.

### If it comes out otherwise

* **Block absent** — the ROM's `pciclass,0c0010` parcel bound instead of the extension. Stop;
  the ROM parcel needs the same patch. Runs 2-5 would prove nothing.
* **Block found, `hook calls 0`** — resident but off the live path. Hot-plug the LaCie, wait a
  few seconds, and re-run: a bus reset must drive the count up. If it stays at 0, self-IDs are
  reaching the family by a path neither hooked call site covers.

### Run 6 — PASSED, 2026-08-27. The last untested case, now measured

LaCie on the FW800 port (9-to-9 beta), **Power Mac G5 in target disk mode on FW400 port 2** via a
9-to-6 cable. Build v006. Log: `logs/FWFixCheck_G5_TDM_v006.log`.

```
  hook calls 3   clamped last 1   total 3
  localID 2   remote nodes 2   mapped to ports 2
  port 0: CHILD  beta         negotiated S800
  port 2: CHILD  legacy(DS)   negotiated S400
  self-ID node 0  its own sp S800  ->  ceiling S800   (the 1394b device)
  self-ID node 1  its own sp S800  ->  ceiling S400   (the 1394b device)
  *** PER-CONNECTION. Each node is clamped to its own port. ***
```

Both G5 volumes and the LaCie mounted together.

**This closes the one gap the README and the announcement had both flagged as inference.** Two
1394b devices, both honestly reporting `sp = 3`, one keeping S800 on a beta hop and the other cut
to S400 on a legacy hop, simultaneously, out of one speed map. It is the configuration stock
cannot handle at all, and until now every two-device run had used the iBook, which is 1394a,
self-limits, and therefore never exercised the clamp (`clamped 0` in every one of them).

**It also re-confirms the ordering the loud way.** With the iBook a backwards port-to-node mapping
was invisible: it reports S400 itself, so nothing broke either way. Here, backwards would have
given the G5 — on a legacy hop, claiming S800 — an S800 ceiling, and it would have failed to
enumerate. It mounted. Ascending confirmed by a test where the wrong answer breaks something.

#### The stock control, run immediately after (log: `logs/FWFixCheck_G5_TDM_stock.log`)

Same two devices, same ports, same cables, stock `FireWire Enabler`. **Neither G5 volume appeared.
The LaCie mounted.**

|  | LaCie, beta hop | G5, legacy hop |
|---|---|---|
| stock | mounts | **absent** |
| v006 | mounts, keeps S800 | **mounts**, clamped to S400 |

The log makes it sharper than a bare absence: `Max_Legacy_SPD 2 (S400)` means the PHY negotiated
with the G5 and knows a legacy segment is present, so the **physical link is up**. The G5 is
missing because the config-ROM read went out at S800 across a hop carrying S400 and was never
answered. The defect is isolated to the speed map, with the hardware demonstrably fine.

That is the complete before and after, on one machine, one pair of devices, one set of cables.

### Re-verification on a fresh OS 9 install, 2026-08-26 (build v005)

New 80 GB disk, clean Mac OS 9 install, MacsBug present. Logs in
`logs/FWFixCheck_freshinstall_*.log`.

| check | configuration | port reading | ceiling | clamped |
|---|---|---|---|---|
| A | nothing attached | all `not-connected` | S400 fallback | 1 (our own self-ID) |
| B | LaCie on port 0, 9-to-9 | `CHILD beta S800` | **S800** | 0 |
| C1 | LaCie on port 1, 6-to-6 | `CHILD legacy(DS) S400` | S400 | 1 |
| C2 | LaCie on port 2, 6-to-6 | `CHILD legacy(DS) S400` | S400 | 1 |

**FW400 port 1 is now verified**, closing the last gap: the goal names two FW400 ports and only
port 2 had previously carried a device.

Two properties observed here for the first time rather than reasoned about:

* **Hot-plug re-enumeration works.** Every earlier run was a cold boot. `hook calls` climbing
  1 -> 5 -> 10 -> 14 across the cable moves shows the hook re-running on each bus reset,
  re-reading the ports and rebuilding the node map against a changed topology.
* **The clamp does not latch.** Check A left the ceiling at S400 with nothing attached, and
  hot-plugging into the beta port then gave `ceiling S800, clamped 0`. It is recomputed from
  scratch every bus reset. See [[feedback_guards_must_not_latch]] for why that matters.

The FWIM block loaded at `0x00CF7628` here against `0x00E792B8` on the old install, which is the
usual per-boot variation and the reason FWFixCheck identifies it by magic rather than address.

#### Cosmetic: the "(the 1394b device)" tag in check A

With nothing attached, the only self-ID is the Mac's own, and the reporter tags it
`(the 1394b device)` because its sp is 3. True, but it reads as though a device were present.
The tag is only meaningful with two devices at different speeds, which is the case it was written
for. Worth qualifying with the local node ID if FWFixCheck is rebuilt for any other reason.

### Reproduced, caught in MacsBug, and what it did to the attribution (2026-08-26)

The hang was **reproduced deliberately** on the fresh install: LaCie on the FW800 port, iBook in
TDM on FW400 port 2, roughly 10 minutes idle. MacsBug caught it:

```
Bus Error at FFC2DE72 _Fix2Frac+0027E
while reading long word from 67076E88 in User data space
CurApName  Finder
```

plus, on starting the log, **`*** MacsBug code has been changed ***`**. That last line is the
important one: MacsBug checksums its own code, so this is genuine **memory corruption**, not a
device going quiet. The `_Fix2Frac+0027E` symbol is noise, MacsBug naming the nearest preceding
symbol it knows; `FFC2DE72` is 68K code in ROM.

⚠ The MacsBug session was then lost to a bad instruction of mine: `f 2800 2400000 'S8FX'`, a
36 MB search run through a debugger whose own code was corrupt. **Record the FWIM block address
from FWFixCheck BEFORE an idle test**, then `dm <address> 80` directly. Failing that, bound the
search: the block has landed between `0x00CF….` and `0x00E7….` on every boot, so
`f C00000 400000 'S8FX'` is enough.

#### A real defect found in this patch as a result

Reviewing against that evidence: `CLAMP` took its buffer length from the parameter block and
looped length/4 times, rewriting any word matching a self-ID packet. The **remote** length is
masked to 2040 by the FWIM inside a 2048-byte buffer, safe. The **local** length was not: it
arrives as `((pFWIMData->0xb9c - 4) & ~7) + 0x10` with no mask, against a buffer only 32 bytes
long before the remote buffer starts.

Fixed in **v006**: the local buffer is no longer clamped in either mode, and `CLAMP` refuses any
buffer over 512 quadlets outright (counted at scratch+0x74) rather than capping and walking. See
the comments at both sites for why refusing beats capping.

#### The v006 re-run does NOT validate the fix

Same configuration, 30 minutes, no hang — but the before and after logs are **identical**, both
reading `hook calls 2, clamped last 0, total 0`. Two things follow, and the second is worth more
than the first:

* **The hook was dormant for the whole idle.** Zero bus resets. Any bus-reset-storm mechanism is
  ruled out, and the hook was not executing when the Finder died.
* **v006's change was inert here.** The local-buffer clamp only runs in global-fallback mode and
  this run was per-connection throughout, so v005 would have behaved identically. The absence of
  a hang says nothing about the fix.

What it does establish is stronger than a passed test. `clamped 0` means that in this exact
configuration the hook rewrites **no self-ID data at all** — both nodes' own sp already matched
their ceilings — so its entire memory footprint is its own 128-byte scratch block. That is very
hard to reconcile with corruption that scribbled MacsBug and handed the Finder a wild pointer.
The same was true on v005 during the run that hung.

Also differed between the two runs: **FW400 port 1 here, port 2 in the hang.** Both read
identically in earlier testing, but it is a real variable alongside "v006" and "intermittent".

#### The control that would settle it

Same configuration with the **stock** `FireWire Enabler` restored, 30+ minutes. That runs fine on
stock: the iBook is 1394a and honestly reports S400, so it enumerates unaided; only the LaCie
loses S800. Hangs on stock and the extension is cleared outright. Survives repeatedly and
suspicion returns here.

### Attempted reproduction on v005 FAILED, twice. Investigation closed as unresolved

| run | build | iBook port | idle | outcome |
|---|---|---|---|---|
| run 5 | v005 | 2 | hours | **hang** |
| deliberate reproduction | v005 | 2 | ~10 min | **hang** |
| control | v006 | 1 | 30 min | clean |
| control | **stock** | 1 | 40 min | clean |
| retry | v005 | 1 | 25 min, plus heavy file copying across all three drives | clean |
| retry | v005 | **2** | 30 min | clean |

Two things died here. The **port-2 correlation** looked perfect for a while (both hangs on port 2,
every clean run on port 1) and there is no port-asymmetric code in the hook to explain it, so it
would have had to be physical. Moving back to port 2 on v005 did not reproduce it. And the
**heavy-I/O attempt** produced nothing: both hangs happened during *idle*, which is the opposite
of a load-related fault and fits a quiet target better.

**Why the investigation stops here.** 55 minutes of clean v005 time across both ports, after two
hangs. If the rate were the ~6/hour the ten-minute reproduction implied, that stretch had about a
0.4% chance of occurring, so the rate is more like <=1/hour and the fast reproduction was luck.
Establishing a baseline at that rate needs several hours; demonstrating a fix reduced it needs
several more. That is the better part of a day of machine time to characterise a fault whose most
likely subject is a clamshell iBook with a dead audio path, a failing screen and a logic board
degrading on several fronts, in a configuration nobody runs.

**Where it leaves the attribution:**

* *Against the patch*: both hangs happened with it installed. Two events.
* *For it, mechanically*: in a measured 30-minute idle in this exact configuration the hook logged
  **zero calls and zero clamps** — dormant, and rewriting nothing outside its own 128-byte scratch
  block. Equally true on v005 when it hung. Getting from that to corrupted MacsBug code and a wild
  pointer in the Finder is very hard.
* *Cause*: genuinely unknown.

**Working position:** treat it as specific to that particular iBook running TDM until shown
otherwise. That machine has no audio at all on speaker or headphones and developed a screen fault
days later, so its logic board is evidently failing on several fronts.

#### The test that could have contradicted that, run 2026-08-27

The gap in the position above was that the **healthy** TDM target had only ever been attached for
minutes at a time, during runs 6 and 6b. So: v006, LaCie on the FW800 port and the Power Mac G5 in
TDM on a FW400 port, the run 6 topology exactly, **left idle for over two hours. No hang.** The run
was still in progress when this was written, so two hours is a floor.

That exonerates the **configuration**, which is the part that was genuinely open: two 1394b devices,
one clamped and one not, one speed map, a TDM target mounted throughout — the same shape as both
hangs, minus the iBook. If the patch or the mixed-speed map were the mechanism, that is where it
should have appeared.

It does not *prove* the attribution. The fault rate was estimated at <=1/hour and the iBook itself
went 55 minutes clean twice, so a clean stretch of this length lowers the probability that the
configuration is at fault without driving it to zero. The honest statement is that the one test
which could have contradicted the working position was run, and did not.

Ongoing exposure comes free from running v006 as the normal configuration, which is more hours
than any deliberate test would buy. If anyone reproduces it, that is better evidence than this one
machine can produce.

## Incident: MDD hung while idle after run 5, 2026-08-26. Unattributed, not recurred

After run 5 (log 08:14) the machine was left idle with the LaCie on the FW800 port and a clamshell
iBook in TDM on FW400 port 2. On returning: desktop icons gone, cursor moving, clicks dead,
nothing touched. No MacsBug installed at the time, so no stack crawl exists. **MacsBug is now
installed; keep it that way.**

### Why it is deliberately absent from the public announcement

Two concrete alternative causes carry hard evidence, against a mechanism for the patch that was
always weak. Publishing an unattributed anomaly beside a fix implies a link the evidence does not
support, which is its own inaccuracy. It stays recorded here in full.

### What the follow-up established

* **System sleep was already set to never.** Display sleep at 20 minutes only, which does not wedge
  a machine, and a bad display wake would have left the icons present.
* **Disk First Aid found "invalid BTree header, 0, 0" on that machine's own boot volume.** Repair
  claimed success and verify failed again every time, which is the known limit of DFA on B-tree
  damage rather than evidence about the drive. The disk was replaced.
* **The iBook has independent hardware faults**: no startup chime at all, on internal speaker and
  on headphones, and a screen fault that appeared days later. Its logic board is degrading.
* **Nothing has recurred** on the replacement disk across the fresh-install checks and a subsequent
  idle period including a display sleep and wake with the LaCie mounted.

### Candidates, best first

1. **A target-disk-mode volume going quiet.** The best fit for the symptom *including the icons*.
   A TDM target is an SBP-2 device backed by a laptop drive that spins down when idle. If the
   Finder touches that mounted volume and the target does not answer, it blocks inside the File
   Manager. Display sleep was on at 20 minutes, so waking the display demands a redraw the blocked
   Finder never performs: icons do not come back, clicks are never processed, and the cursor keeps
   moving because it is drawn by the interrupt handler.
2. **The Finder blocked or dying on the already-damaged boot catalog.** Same shape, different
   volume.
3. **Something FireWire.** Weak. ⚠ But note a correction to the earlier reasoning here: the claim
   that "the hook only runs on a bus reset, and an idle machine generates none" is **not safe with
   a TDM target attached**, because an SBP-2 device that times out can provoke resets. The
   mechanism is weak, not absent.

The patch is excluded as a *direct* cause of the disk corruption on grounds of mechanism: the
damaged volume was on the **internal ATA bus**, and the hook touches only its own 128-byte scratch
block inside the FWIM's code section and self-ID quadlets in FireWire buffers. No path to the File
Manager, to disk drivers, or to ATA. It is *not* excluded as a cause of the hang.

### Why watch 2 was abandoned

The plan was to reproduce it deliberately: new disk, LaCie plus a TDM target, one variable. The
iBook was unusable, and the substitute (the FW400 MDD) **shut itself down about 20 seconds after
power-on with the 6-to-6 cable attached, and booted normally with it removed.** Both ends of a
6-pin link source bus power, so a fault anywhere in that path can trip a supply, and retrying into
an overcurrent is how a bad port becomes a dead one.

The test could only ever have *confirmed* the hypothesis, never refuted it: a desktop drive in the
substitute machine may never spin down at all, so a clean result would have been meaningless. Risk
to a second machine's FireWire hardware against a phrasing improvement in an announcement is not a
trade worth making. **If the community reproduces it, that is better evidence than anything this
one machine could have produced.**

### ⚠ The founding premise was WRONG: stock already ran the FW800 port at S800 (2026-08-26)

This project opened from the statement that on the FW800 MDD "the two FW400 ports are not
recognised at all and the FW800 port works but only at S400". **The second half was never measured
and is false.** Measured at last, mean over transfer sizes >= 64K:

| configuration | seq read | seq write |
|---|---|---|
| stock, beta port, drive alone | 25.22 | 22.17 |
| patched, beta port, drive alone | 25.60 | 22.38 |
| patched, FW400 port, drive alone | 23.15 | 20.83 |
| stock, beta port, a legacy device also on the bus | 22.97 | 20.19 |

Patched against stock on the same port is **+1.5% read, +1.0% write**: nothing. The model always
said so — stock reads both nodes' `sp` as 3, takes the minimum, and a beta hop carries S800 — and
the premise contradicted it. When a model and an unmeasured assumption disagree, measure.

**Why it survived so long.** The first stock measurement was taken with the iBook also attached,
which put stock at 22.97 and made it look like S400. It is not the hop speed: a legacy device
merely being present on the bus costs the beta device **8.9%** in hybrid-mode overhead, larger gap
counts and border-node latency. That accounts for essentially the whole apparent difference. A
comparison is only as good as the variable you actually held still.

**What the patch is therefore worth**, and the README and announcement now say this:

|  | FW400 ports | FW800 port |
|---|---|---|
| stock | do not enumerate a 1394b device at all | S800 |
| the earlier one-byte global clamp | work | S400 |
| this patch | work | S800 |

Against stock the gain is the FW400 ports, not throughput. Against the previously released fix it
is keeping S800 rather than trading it away, worth +10.6% read / +7.5% write on that port. Both
are real; "restores S800" against stock is not, and nearly shipped in the README.

## Results so far

### Run 1 — PASSED, 2026-08-25

```
FWIM block @0x00E744D8   port->node ordering: ASCEND
  hook calls 1   clamped last 1   total 1
  PHY reg2 0xE3 (Num_Ports 3)   reg7 0x20   localID 0
  remote nodes 0   mapped to ports 0   global ceiling S400
  port 0/1/2: not-connected  - skipped, port registers not read
  *** GLOBAL FALLBACK ... EXPECTED for run 1. ***
```

Every line matched the prediction. `hook calls 1` is the one that settles it: the patched
Enabler loaded, bound, and its hook ran during FWIM initialisation, so it is the **extension's**
OHCIFWIM the family calls and not the ROM's `pciclass,0c0010` parcel. `Num_Ports 3` and three
correct port states prove it also read the PHY and parsed our own self-ID.

The one wrong line was `FWIM driver bound: NONE`, which was a defect in v3 of the diagnostic,
not in the fix — see below. Run 1 does not need repeating.

### Run 5 — PASSED, 2026-08-26 (build v005). ORDERING = ASCENDING

LaCie on the FW800 port (9-to-9 beta), clamshell iBook on FW400 port 2.

```
  hook calls 2   clamped last 0   total 0
  localID 2   remote nodes 2   mapped to ports 2
  port 0: CHILD  beta         negotiated S800
  port 2: CHILD  legacy(DS)   negotiated S400
  self-ID node 0  its own sp S800  ->  ceiling S800   (the 1394b device)
  self-ID node 1  its own sp S400  ->  ceiling S400
  *** PER-CONNECTION. Each node is clamped to its own port. ***
```

The node whose own sp is S800 is the LaCie, and it got **ceiling S800**. **The ascending
port->node ordering is correct.** `asc` is the build to keep; the `desc` variant exists only
because Apple's source could not settle this, and it can now be discarded.

Two different link speeds coexist correctly in one speed map, and the star test, the per-port
reads and the node mapping all behaved.

#### What run 5 does NOT prove

`clamped last 0`: nothing needed clamping, because each device's own sp already matched its
port. **Stock would also have produced a correct map here** — the iBook honestly reports sp = 2
and the family's own `min()` handles it. So run 5 establishes the ordering and the absence of a
regression; it is not a demonstration of the fix beating stock.

The configuration that would demonstrate that is a **second 1394b device** on a legacy hop
alongside the LaCie at S800, and there is only one FW800 device here, so it is untestable. What
is proven separately is each half: run 2 keeps S800 on a beta hop, runs 3 and 4 clamp a lying
1394b device on legacy hops where stock fails outright, and run 5 shows per-port ceilings are
assigned correctly and simultaneously. The combined case follows from those components — as an
inference, and any write-up should say so rather than claim it was measured.

#### Still untested: FW400 port 1

Every legacy test so far used port 2. Port 1 has never had a device on it. It is the same PHY and
the same code path, so there is no reason to expect a difference, but the stated goal names *two*
FW400 ports and only one has been exercised. Moving the iBook to port 1 and re-running is a
cheap, honest close-out.

### Run 4 — PASSED, 2026-08-25 (build v005)

LaCie on the Mac's FW800 port via a 9-to-6 cable, 6-pin end in the LaCie's FW400 port.

```
  hook calls 3   clamped last 1   total 3
  remote nodes 1   mapped to ports 1
  port 0: CHILD  legacy(DS)  negotiated S400
  self-ID node 0  its own sp S800  ->  ceiling S400   (the 1394b device)
  *** PER-CONNECTION. Each node is clamped to its own port. ***
  now: reg2 0xE3   reg6 0x50   Max_Legacy_SPD 2 (S400)
```

**The LaCie mounted and worked on this hop**, so the run is closed on both halves: the clamp
computed S400, and the S400 link carries data. A computed ceiling alone would only have been
half the claim.

Three results:

* **`Beta_mode` tracks cable type on the beta port.** Port 0 with a legacy cable reads
  `legacy(DS)`, not `beta`. That was the specific way run 4 could have failed.
* **The clamp caught the lie.** `own sp S800 -> ceiling S400` is the entire fix in one line, in
  the configuration the README records as *failing* on stock.
* **`Max_Legacy_SPD 2` on port 0.** This is the value that was never measured and was flagged
  early as the one thing that could have invalidated the *original* per-bus design. It fires
  correctly. The design has since moved to per-port `Beta_mode`, so reg 6 is no longer
  load-bearing, but the open question is closed.

**The single-device matrix is now complete and correct:**

| cable | port | detected | ceiling | clamped |
|---|---|---|---|---|
| 9-to-9 beta | 0 (beta) | `beta` S800 | S800 | no |
| 6-to-6 legacy | 2 (FW400) | `legacy(DS)` S400 | S400 | yes |
| 9-to-6 legacy | 0 (beta) | `legacy(DS)` S400 | S400 | yes |

Only simultaneity is untested, which is run 5 — and it is the only run whose result depends on
the port->node ordering.

### Reading run 5 in one line

Find the record whose **own sp is S800** — that is the LaCie, the only 1394b device on the bus.

* its ceiling reads **S800** -> ascending is correct, `asc` is the build to keep
* its ceiling reads **S400** -> the ordering is backwards, install `desc` and repeat

Nothing will fail visibly either way, so do not judge run 5 by whether both volumes mount. With
the Mac as root and two children, expect `localID 2`, `remote nodes 2`, `mapped to ports 2`,
`mode PER-CONNECTION`, and two self-ID records, one `own sp S800` and one `own sp S400`.

### Run 3 — PASSED, 2026-08-25 (build v004)

```
  hook calls 7   clamped last 1   total 5
  remote nodes 1   mapped to ports 1
  port 2: CHILD  legacy(DS)  negotiated S400
  node 0 ceiling S400
  *** PER-CONNECTION. Each node is clamped to its own port. ***
```

Cabling was **6-pin to 6-pin**, the Mac's FW400 port to the LaCie's own FW400 port (not the
9-to-6 originally written down). It makes no difference to the result: the Mac's port is 6-pin
either way, so the hop is a legacy DS connection regardless of the far end.

`Beta_mode = 0` correctly read on a FW400 port, the node clamped to S400, and the drive mounted
and benchmarked. The FW400 fix survives being moved into the FWIM.
The PHY's whole-PHY summary agreed independently: `reg6 0x50, Max_Legacy_SPD 2 (S400)`.

`clamped last 1` is worth reading closely: in per-connection mode only remote nodes are touched,
so that one clamp was the LaCie's own self-ID being cut from S800 to S400. **The LaCie reports
sp = 3 even over a 6-to-6 legacy cable** — its PHY claims S800 whichever of its ports you use.
That is the lie the whole fix exists to correct, now measured on this hardware rather than
assumed, and it is why run 4 fails loudly while run 5 would not.

Throughput on this port is the S400 half of the speed comparison — see
`docs-QUICKBENCH-S800-vs-S400.md`.

### ⚠ Run 5's failure signature is NOT what the table above said (corrected)

Working through run 3's result exposed a mistake in the original plan. It said a backwards
port->node ordering would show up as *"the legacy device does not mount"*. With the **iBook** as
the second device, that is wrong, and run 5 would have been unreadable.

A genuine 1394a device reports `sp = 2` in its own self-ID. Our clamp only ever *lowers* sp, and
the family takes the minimum along the path, so:

| ordering | LaCie (sp 3) | iBook (sp 2) | visible symptom |
|---|---|---|---|
| correct | ceiling S800, stays S800 | ceiling S400, already S400 | none — both work, LaCie fast |
| **backwards** | ceiling S400, **clamped down** | ceiling S800, its own sp still limits it to S400 | **none** — both work, LaCie quietly slow |

Nothing fails. The only casualty is the LaCie silently losing S800, and the pre-v005 log could
not say which node was which. The original signature only appears when the legacy-attached device
is *itself* 1394b and honestly claims S800 — which is run 4, the LaCie on a 9-to-6 cable.

**Build v005 fixes this.** For every self-ID packet it records `(phy_ID, that node's own sp, the
ceiling applied)`, so the log names the devices: the node whose own sp is S800 is the LaCie. If
its ceiling reads S400, the ordering is backwards and the `desc` build is the right one.

### Run 2 — PASSED, 2026-08-25 (build v004)

```
FWIM block @0x00E78F08   build v004   port->node ordering: ASCEND
  hook calls 2   clamped last 0   total 0
  PHY reg2 0xE3 (Num_Ports 3)   reg7 0x20   localID 1
  remote nodes 1   mapped to ports 1   global ceiling S400
  port 0: CHILD  beta  negotiated S800
  node 0 ceiling S800
  *** PER-CONNECTION. Each node is clamped to its own port. ***
```

`CHILD` proves the state survives the PHY calls now; `localID 1 == childCount 1` passed the star
test; `node 0 ceiling S800` with `clamped 0` means nothing was clamped and the family may run
S800. The drive then mounted and took a **521 MB disk image in 30 s with no errors**, so the
link is correct and stable under sustained load. That is ~17-18 MB/s, which is *below* S400's
practical ceiling, so it is not yet evidence that S800 is being used — see below.

### Measuring whether S800 is REAL, not just permitted

Run 2's log proves the clamp did not fire. The first data transfer over it — a 521 MB disk image
copied to the LaCie on the FW800 port, 30 s, no errors — proves the link is correct and stable.
It does **not** prove S800 is doing anything: ~17-18 MB/s is about half of S400's practical
ceiling and an unremarkable OS 9 Finder-copy rate. Something above the bus is the limit.

So a single benchmark number cannot answer the question, and neither can a single QuickBench run,
because this drive's own ceiling is unknown. **The evidence is a pair**, and run 3 supplies the
second half for free: one TI TSB81BA3 drives all three ports, so moving the LaCie from port 0 to
a FW400 port changes essentially one variable, beta S800 -> legacy S400.

    on the FW800 port  : QuickBench + the 521 MB copy, settings written down
    run 3, FW400 port  : the same QuickBench settings, the same copy

Markedly slower on the FW400 port means S800 is real and measurable. Identical means the clamp is
correct but S800 buys nothing with this drive — the bottleneck is above the bus, and the fix
removes a cap a faster device could use. Both are results; neither invalidates the fix.

⚠ QuickBench measures the **task-level path only**. That disqualified it on the eSATA driver,
where most Finder writes arrive below task level. Here it is measuring bus speed rather than an
execution-level change, so it is fair — but do not read its write figures as what the Finder does.

### The S400 global fallback is CORRECT, not a limitation — do not "optimise" it

`global ceiling S400` appears in every log even when the only connected port negotiated S800,
because `globalCeil` is seeded at S400 and only ever lowered. This was twice written down here as
needless conservatism to be fixed after run 5. **That was wrong**, and the change was abandoned
during implementation.

The fallback fires exactly when the topology is **not a star** — a hub, a daisy chain. In that
case this PHY can only measure the hops it terminates; everything past the first hop is invisible
to it. Seed the ceiling at S800 and take a true minimum over the connected ports, and:

```
Mac --beta S800--> drive A --legacy cable--> 1394b drive B
```

port 0 reads beta S800, `globalCeil` becomes S800, nothing is clamped, and the family attempts
S800 across a data/strobe hop to B. **That is the original defect, verbatim.**

No topology reconstruction rescues this. A legacy hop between two 1394b nodes is invisible in the
self-ID stream — that is the premise of this whole patch. The information does not exist locally.
Apple's answer is try-and-see step-down, which the OS 9 family does not have.

The cost is real: a genuinely all-beta daisy chain runs at S400. It is indistinguishable from the
case with a hidden legacy hop, and shipping a known path back to the original symptom is not a
trade this project makes. S400 is the right answer.

### Run 2 — attempt 1 FAILED on a bug in the hook, 2026-08-25 (build v003)

```
  hook calls 2   clamped last 2   total 4
  PHY reg2 0xE3 (Num_Ports 3)   reg7 0x20   localID 1
  remote nodes 1   mapped to ports 1   global ceiling S400
  port 0: not-present  beta  negotiated S800
  Child count did not match our own phy_ID; tree not as expected.
  *** GLOBAL FALLBACK: everything clamped to S400. ***
```

`not-present` is state 0, but the code only reaches the register read at state >= 2, so the
state was destroyed between the branch and the log. Cause: **the port state lived in r10 and the
negotiated speed in r12 across `ReadPhyRegister` / `WritePhyRegister`.** On PowerPC r0 and
r3-r12 are volatile and a callee may destroy them; `ReadPhyRegister`'s own prologue does
`mfcr r12`. Both came back as garbage.

Two things worth keeping from this. First, the failure was **safe**: the star test
(`childCount == our phy_ID`) rejected the corrupted topology and degraded to the conservative
global clamp instead of building a wrong per-node map, so the drive still worked, just at S400.
That is the fallback earning its place. Second, nothing about the *design* was disproved — the
PHY was read correctly (`beta`, `negotiated S800` on port 0 is exactly right), only the register
allocation was wrong.

Fixed in build v004: the state moves to r17 and the speed to r18, both non-volatile, and the
frame grows to 128 bytes to save r17-r31. `ppcasm.audit_volatiles()` now decodes every generated
blob and refuses to ship one where a volatile is written, survives a `bl`, and is then read. It
was tested by reintroducing the bug, which it catches.

## The two diagnostic defects found along the way

**v2 crashed** with a Type 1 bus error on its first MMIO read. Cause: the patched Enabler could
not load, because `FireWire Enabler`'s data fork holds two PEF containers and CFM locates them
through a **`cfrg` (0) resource** carrying each fragment's `offset` **and `length`**. Growing
the OHCIFWIM container without updating its member left CFM mapping the original 62096 bytes,
so the loader section fell off the cut end. Nothing claimed the controller, its PCI memory space
was never enabled, and the read faulted. Two bytes. Every earlier patch on this project was
byte-for-byte and never changed a length, so nothing had ever exercised this.

**v3 reported `FWIM driver bound: NONE` on a healthy machine.** The guard looked for a bound
FWIM in the Device Manager unit table. FWRegDump on this same machine reports *"FireWire drivers
bound: 0 of 2 controllers"* with stock extensions and FireWire working perfectly — the FWIM is a
CFM fragment loaded by the FireWire expert and is never a Device Manager unit, so
`GetDriverInformation` cannot see it. v4 uses PCI configuration space instead: command register
bit 1, Memory Space Enable. Config cycles reach the device through the bridge whether or not its
BAR decodes, so that read is always safe, and a clear bit means an MMIO read genuinely would
fault.

## The runs

Delete the old log first and read from the last banner.

| # | Configuration | Question | Confirms | Falsifies |
|---|---|---|---|---|
| 1 | nothing attached | Does the patched Enabler load and bind? | see the full sequence above | block absent → the ROM parcel binds, patch it too |
| 2 | drive on the FW800 port, 9-to-9 | Does S800 survive? | port 0 `beta negotiated S800`, `node 0 ceiling S800`, `clamped 0`, drive mounts | any clamp here means the port read is wrong |
| 3 | drive on a FW400 port | Does the FW400 fix still hold once the clamp lives in the FWIM? | that port `legacy(DS) negotiated S400`, node ceiling S400, drive mounts | drive fails → the FWIM clamp is not equivalent to the family clamp |
| 4 | LaCie on the FW800 port via a **9-to-6 cable**: 9-pin end in the Mac, 6-pin end in the LaCie's FW400 port | Does a legacy hop on the **beta** port get caught? | port 0 `legacy(DS)`, `own sp S800 -> ceiling S400`, drive mounts | port 0 still reads `beta` → `Beta_mode` does not track cable type, and the drive will not mount |
| 5 | **LaCie on the FW800 port AND the clamshell iBook on a FW400 port** (see below) | **The whole point.** Two speeds at once? | `mode PER-CONNECTION`, one node S800 and one S400, both enumerate | the S400 node does not appear → ordering is backwards, swap in the `descend` build and repeat |

### The second device for run 5

The LaCie is the only FW800-capable device here, so the S400 half of run 5 is a **clamshell
iBook (FireWire)** on a 6-to-6 cable into a FW400 port. It is the right shape for this:

* **one FireWire port**, so it is a leaf and the topology stays a plain star. Anything with two
  ports in use would put the code into `GLOBAL FALLBACK` and the run would prove nothing.
* **1394a S400**, so that MDD port should read `legacy(DS) negotiated S400` — exactly the
  discriminator the per-connection clamp turns on.

Three nodes, two connected MDD ports, so `remote nodes 2 / mapped to ports 2` and the star test
passes. Root election does not matter: if a leaf wins root the MDD simply has one parent port and
one child port, which the mapping handles explicitly.

**Target Disk Mode (hold T at startup) is a convenience, not the test.** It gives a volume to copy
files onto, and OS 9 carries the SBP-2 drivers to mount it. But the original
defect was that a config-ROM read at the wrong speed fails and *the device never appears at all*,
so enumeration is itself the discriminator. An iBook booted normally still puts a node on the bus
and still proves the map. If TDM fails, or the iBook's disk has been through a later Mac OS X and
is journaled so OS 9 declines to mount it, that is **not** a run 5 failure — read FWFixCheck's node
table, not the Finder.

Connect both machines with the power off, then boot. That is the normal TDM procedure anyway, and
on 25-year-old 6-pin ports carrying bus power there is no reason to hot-plug.


### Run 4 cabling — no substitute

The Mac's FW800 port is 9-pin, so a legacy hop into it needs a cable that is **9-pin at the Mac
and 6-pin at the device**. A 6-to-6 cannot reach that port at all, and a 9-to-9 negotiates beta
mode and merely repeats run 2. The README records this configuration as already measured here
("9-to-6 (legacy), same port ... fails"), so the cable exists.

The iBook is **not** a substitute for the LaCie in run 4. It is 1394a and honestly reports
sp = 2, so it needs no clamping and would exercise nothing. The LaCie is the right device
precisely because it claims S800 over a legacy hop.

Run 5 is the one the project is for, and it passed: see Results. Runs 2 and 3 are the safety net: they must keep working,
because a build that trades FW400 away for S800 is not a fix.

## What could still bite

* The hook now does up to a dozen bounded PHY accesses per bus reset (50 x 100 us each, worst
  case) and writes PHY register 7 to select port pages, restoring the previous selection
  afterwards. It runs in a FWIM function that already reads the PHY several times, so this is
  established practice there, not a new kind of access — but it is more of it.
* The scratch block lives in the patched code section. Classic Mac OS does not write-protect
  the System heap, so the stores land, but this is the one assumption with no measurement
  behind it. If it were wrong the symptom would be immediate: a crash on the first bus reset.
* Anything deeper than a star (a hub, a daisy chain) deliberately falls back to the global
  minimum rather than guessing. That is a conservative correctness choice, not a bug, and
  `mode GLOBAL FALLBACK` in the log says when it happened.
