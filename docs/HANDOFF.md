# HANDOFF: resolved

The S800 work this document used to describe is **done**. All three FireWire ports run at their
proper speeds from a single patched extension, `FireWire Enabler`.

See `../README.md` for what shipped and `S800-RUNBOOK.md` for every hardware run, what each one
asked, what would have falsified it, and the three bugs found along the way.

The design question this file left open, whether the first child in a self-ID stream sits on the
lowest or the highest numbered child port, was not answerable from Apple's source. Both variants
were built and the hardware settled it: **ascending**.
