# HANDOFF — where S800 stands

FireWire 400 is **done**. What remains is restoring **S800** on the FW800 port *without* losing the
FW400 ports. Goal, in the user's words: **one extension that fixes all three ports at their proper
speeds.**

## Why the current fix costs S800

The S400 clamp is global — it caps the speed-map diagonal for every node, so the beta hop runs at S400
even though it negotiated S800. The clamp is deliberate and monotonic; it is a trade, not a speed fix.

## The design that gets S800 back

Clamp per-connection instead of globally: **`min(requested, Negotiated_speed of the connected port)`**.

* beta port only connected → S800 ✓
* a legacy port connected → S400 ✓
* both → S400 everywhere (conservative, safe) ✓

That needs the PHY's per-port `Negotiated_speed`, which only the **FWIM** can read. The FWIM is the
**`FireWire Enabler`** extension. If the clamp lives there, `FireWire Support` reverts to **stock** and
the deliverable is a single patched extension — exactly the stated goal.

`Max_Legacy_SPD` (PHY base register 6) is an equally good discriminator and is already proven:
**0 on beta-only, 2 = S400 when a legacy segment exists** (measured across three runs, see `logs/`).

## Where the RE got to

**The FWIM binary to patch is `FireWire Enabler`, NOT the ROM parcel.**

* `FireWire Enabler` — type `ndrv`, creator `fw  `, **data fork 116960 bytes** = the PEF, containing
  **both** `OHCIFWIM` and `LynxFWIM`; resource fork 946. md5 `1a3648314b1a9b9bc9dc76c6b8187aaf`.
* the Mac OS ROM parcel `pciclass,0c0010-2.8.7d6.pef` is **61952 bytes**, OHCI-only.
* ⇒ **different builds.** Analysis done on the ROM parcel does not carry over by offset; redo it on the
  Enabler. (Which of the two actually binds is still unproven — the shared 2.8.7 version does not
  discriminate. Settle it with a system-heap signature scan once a target instruction exists, the same
  way `FWPatchCheck` settled it for `FWServicesLib`.)

**Established:**

* the async command object's speed field is **offset 0x94**; `FWSetAsynchCommandSpeed` writes it and
  ORs 0x10 into flags at 0x78 ("client set it explicitly"). ~8 other `FWServicesLib` sites write 0x94 —
  the per-command default, which is what the current clamp caps.
* the FWIM's OHCI register base is **ctx+0xDC** (97 loads in the ROM parcel), confirmed by
  `CheckFWIMPersonality` comparing it against `0xF5000000`.
* the FWIM is an **ndrv** — it does *not* import `FWInstallNewFWIM` and exports only `DoDriverIO` +
  `TheDriverDescription`. So the family reaches it via **`DoDriverIO` csCode dispatch**, and the
  async-transmit path is a case inside that. **Finding that dispatch is the next step.**
  `pef2elf` labels only import symbols, so locate `DoDriverIO` from the PEF loader header's
  `main` (section + offset), not by name.

**Ruled out — do not re-tread:**

* the FWIM does **not** read the family's command speed at 0x94 (both 0x94 accesses in the ROM parcel
  are its own context fields, alongside 0xbc8/0xbcc/0xbdc/0xbf5).
* the `0x180`–`0x198` displacements near r2 `0x1000` are a **DMA-program struct**, not OHCI registers.
* there is **no** `rlwimi`/`rlwinm` at bits 13:15, so the async header's `spd` (IEEE 18:16) is not
  written with a bitfield insert. 17 `slwi <<16` candidates exist and encoding scans cannot pick one.
* a **family-only** scheme using self-ID port fields ("clamp unless the peer is on port 0, the 9-pin
  connector") is **wrong**: the 9-to-6 cable is a legacy hop *on port 0*, and that case is measured. It
  is also board-specific.

## Tooling traps that already cost time

* **r2 parses these files as PEF** (`format pef`, `bintype cfm`) and maps code at vaddr 0, so
  **file offset = r2 address + 0x80**. Reconcile the two spaces explicitly before quoting any offset.
* Retro68 headers are **Latin-1** — grep them with `LC_ALL=C grep -a` or matches vanish.
* `Microseconds()` is declared in `Timer.h`, not `OSUtils.h`.
* **Never scan for an instruction encoding without reading the surrounding sequence.** It produced two
  false alarms here: a "sp == 3 check" that was a child-port counter, and a "speed map" that was the
  IEC 61883 plug control registers.
* **Every diagnostic must write a log file** — do not make the operator photograph a window.

## Open, unrelated

* **Sleep/wake is broken on this machine independently of FireWire** — confirmed with no FireWire device
  ever attached. Not our defect; secondary, to be looked at after the ports.
* The **enhanced ROM** (USB2 + eSATA + FireWire for the FW800 MDD) is now unblocked. FireWire is an
  *extension* component, so it does not complicate the ROM at all.

## Not yet done

* The repo has **not been pushed** to GitHub — that needs explicit permission each time.
* Consider a forum write-up (macos9lives / 68kmla). House style: ~400–500 words, no em-dashes, and mark
  which parts were written with Claude.
