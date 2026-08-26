# What the patch is actually worth, measured

LaCie FW800 drive, Power Mac G4 MDD FW800, Mac OS 9.2.2, 2026-08-26. One TI TSB81BA3 drives all
three ports. Raw results in `logs/QuickBench_*.log`. Means are over transfer sizes of 64K and
above, where the bus rather than per-operation overhead dominates.

| configuration | seq read | seq write |
|---|---|---|
| **stock**, beta port, drive alone | **25.22** | **22.17** |
| **patched**, beta port, drive alone | **25.60** | **22.38** |
| patched, FW400 port, drive alone | 23.15 | 20.83 |
| stock, beta port, a legacy device also on the bus | 22.97 | 20.19 |

## The headline correction

**Stock already runs the FW800 port at S800.** Patched against stock on the same port with the
same drive is **+1.5% read and +1.0% write**, which is noise. This project began from the premise
that "the FW800 port works but only at S400". That premise was never measured, and it is wrong.

It survived as long as it did because the first stock measurement was taken with a second,
legacy-speed device also attached, which made stock look like S400. It was not the hop speed. See
below.

The model predicted this outcome and the premise contradicted it: stock reads both nodes' self-ID
`sp` as 3, takes the minimum, and a beta hop physically carries S800, so stock should always have
been S800 there. When a model and an unmeasured assumption disagree, measure.

## So what is the patch worth?

|  | FW400 ports | FW800 port |
|---|---|---|
| stock | **do not enumerate a 1394b device at all** | S800 |
| the earlier one-byte global clamp | work | **S400** |
| this patch | work | S800 |

Against **stock**, the gain is that the two FW400 ports become usable, not throughput. Against the
**previously released fix**, the gain is keeping S800 on the FW800 port instead of trading it
away, worth **+10.6% read and +7.5% write** on that port with this drive.

## S800 versus S400 as hop speeds

Still a real difference, measured on the same drive and controller with only the port changed:
S800 ahead in 39 of 44 individual measurements, **+10.6% sequential read, +7.5% sequential
write**, peak sequential read 26.85 to 30.65 MB/sec.

Modest because the drive is the ceiling, not the bus: it tops out near 30 MB/sec and a FireWire
400 hop already delivers roughly that after SBP-2 overhead. A faster device has more to recover.

## A legacy device on the bus costs everyone about nine percent

Comparing the two stock runs on the beta port, identical but for a second machine attached in
target disk mode at S400: **read ‑8.9%, write ‑8.9%** for the beta device.

The beta hop is unchanged, so this is bus-wide hybrid-mode overhead rather than a speed-map
effect: larger gap counts, different arbitration, border-node latency. Worth knowing if you are
benchmarking, and worth knowing before attributing a slowdown to a driver.

It is also the reason the first stock measurement was misleading, and a reminder that a
comparison is only as good as the variable you actually held still.
