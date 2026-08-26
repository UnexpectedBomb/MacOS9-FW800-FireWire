# The iMic FW800 ROM is stock 10.2.1 plus one bootinfo line

Analysed 2026-08-25, entirely on the Mac, no hardware runs.

Source: this machine's own FW800 MDD ROM, backed up from the System Folder
(data fork 2,796,822 + AppleDouble resource fork 616,301).

| | md5 | data fork |
|---|---|---|
| stock MDD 10.2.1 (`mdd-original-rom/`) | `48fd7a428aaebeaec2dea347795a4910` | 2,796,822 |
| FW800 (iMic/nanopico) | `9dfbd3d5e43706ae44dfde03dd4ad6a0` | 2,796,822 |

## What differs

Same length. 9,508 differing bytes, **all** between `0x20` and `0x37bb` — entirely inside the
`<CHRP-BOOT>` Open Firmware bootinfo script. Bytes `0x37bc`..EOF (**2,782,554 bytes, 99.5% of the
file** — every parcel, the 4 MB PPC ROM, the 3 MB 68K ROM, the NanoKernel) are **byte-identical**.

The substantive change is one line, and `tbxi` exposes it as one line of `Bootscript`:

```
<COMPATIBLE>
MacRISC MacRISC2 MacRISC3 MacRISC4     <- stock says only "MacRISC"
</COMPATIBLE>
```

That is the whole reason OF 4.6.0 on the FW800 rejects a stock ROM as a valid `tbxi`: an
architecture-compatibility declaration, nothing more. The rest of the diff is the script text
shifting inside its fixed-size region (it grew 0x8a bytes), consuming trailing `FFFF` filler.

## It is a sound base for injection

- **Fork-ful**: `tbxi dump` yields the real **185,240-byte SysEnabler**, so both of
  `build-rom-hqx.py`'s guards are satisfied. Rehydrate the fork first with
  `usb2-ehci/scripts/rehydrate-rom-fork.py <data> <._sidecar> <out>`.
- **Clean tbxi round-trip**: dump -> build -> dump gives an IDENTICAL `SysEnabler`,
  `SysEnabler.rdump`, `Bootscript`, and an identical parcel tree (`diff -rq Parcels.src` is silent).
- The packed `Parcels` blob drifts by exactly **64 bytes from `0x1a9`** — real crc32 fields become
  `0x99999999` placeholders. **The stock MDD ROM round-trips with the identical 64-byte drift at the
  identical offset**, so this is inherent to tbxi, not to this ROM. Every USB2/eSATA ROM shipped so
  far was built through this path and boots.

## Consequence: invert the enhanced-ROM plan

Do **not** rebase the validated USB2/eSATA work onto an unfamiliar ROM. Take the already-hardened
mass-storage ROM and apply iMic's one-line `<COMPATIBLE>` edit to its `Bootscript`. The two edits
touch **disjoint regions** of the file — iMic's in the bootinfo header, ours in the parcels — so they
cannot interact. That removes the base-ROM risk Stage 0 existed to measure.

⚠ Still unverified on hardware: that a ROM carrying **both** edits actually boots the FW800 MDD.
That is now the single Stage-0 question, and it is one reboot.
