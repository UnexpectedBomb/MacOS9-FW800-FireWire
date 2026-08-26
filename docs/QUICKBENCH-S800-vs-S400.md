# Does S800 actually buy anything? QuickBench, same drive, same controller

LaCie FW800 drive, 2026-08-25, build v004 ascend. One TI TSB81BA3 drives all three ports, so
moving the drive from port 0 (beta) to a FW400 port changes essentially one variable: the hop
goes S800 to S400. Raw results in `logs/QuickBench_LaCie_FW*_QB_Results.log`.

| Xfer | Seq Read S800 / S400 | Seq Write S800 / S400 | Rnd Read | Rnd Write |
|---|---|---|---|---|
| 16K | 17.92 / 16.25 **+10.3%** | 7.15 / 6.98 +2.4% | 17.85 / 16.30 +9.5% | 2.40 / 6.80 *(outlier)* |
| 32K | 23.74 / 21.13 **+12.4%** | 11.38 / 11.03 +3.2% | 23.61 / 21.05 +12.2% | 11.55 / 10.68 +8.2% |
| 64K | 18.79 / 21.33 *(dip)* | 16.59 / 15.37 **+8.0%** | 28.06 / 24.52 +14.5% | 16.38 / 15.59 +5.1% |
| 128K | 18.03 / 17.34 +4.0% | 20.99 / 19.45 **+7.9%** | 20.61 / 17.97 +14.7% | 20.93 / 19.68 +6.4% |
| 256K | 30.62 / 23.90 **+28.1%** | 23.54 / 21.82 **+7.9%** | 13.23 / 12.70 +4.2% | 23.31 / 21.87 +6.6% |
| 512K | 29.91 / 26.33 **+13.6%** | 24.98 / 23.37 **+6.9%** | 17.75 / 15.81 +12.3% | 24.97 / 23.33 +7.0% |
| 1M | 30.65 / 26.85 **+14.2%** | 25.81 / 24.11 **+7.0%** | 21.92 / 20.80 +5.4% | 25.69 / 24.12 +6.5% |

**Mean over >= 64K:** seq read +10.6%, seq write +7.5%, random read +10.6%, random write +6.4%.
**S800 is faster in 39 of 44 individual measurements.**

## Why this is a real effect and not noise

Sequential write at the five largest sizes reads +8.0, +7.9, +7.9, +6.9, +7.0%. Five consecutive
independent measurements landing within a point of each other is systematic. The three
disagreements are explainable: the 1K and 2K sizes are dominated by per-operation latency rather
than the bus, and the 16K random-write figure of 2.40 MB/s sits below the 8K figure of 4.22 in
the *same* run, so it is a hiccup in that one measurement, not a port effect. The 64K sequential
read dip appears in **both** runs, so it is a property of the drive or its bridge.

## Why the Finder copy saw nothing

521 MB in 30 s is ~17-18 MB/s. Both ports benchmark **above** that for sequential writes
(25.8 and 24.1 MB/s), so the Finder's copy path is the limiter and the bus is not being asked for
its full rate. A 7% difference would also be ~2 s out of 30, at the edge of stopwatch resolution.
The copy proves correctness under sustained load; it was never able to resolve the speeds.

## Why only ~10% and not ~2x

The drive is the ceiling, not the bus. It peaks near 30 MB/s, and a FireWire 400 hop delivers
roughly 30-35 MB/s in practice after SBP-2 overhead — so S400 was only just constraining it.

The gain is probably not raw bandwidth at all. SBP-2 is request/response with a limited number of
outstanding transactions, and S800 halves the wire time of every packet, which shortens the
round trip and lifts throughput even when the link is nowhere near saturated. That would explain
a consistent single-digit gain at every transfer size rather than a cliff at some threshold.
*That is an interpretation of the numbers, not something these runs measured.*

## What this means for the fix

S800 is doing real work, and this drive shows the smallest gain it ever will: it is the
bottleneck. A faster device — an SSD in an FW800 enclosure, or a modern bridge — has headroom
this one does not, and the removed cap is worth more there. The fix is not a placebo, and it is
also not a doubling on this hardware. Both halves of that should go in any write-up.
