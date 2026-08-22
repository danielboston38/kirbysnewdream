# Kirby's New Dream

A custom composite video / USB-C power replacement board for the original Nintendo Entertainment System (NES). Drops in at the original RF module location inside the NES shell, replacing the RF modulator with a clean composite video + USB-C power solution.

## Disclosure

This project's schematic design, debugging, and documentation were developed with the assistance of AI (Claude, by Anthropic). All hardware was hand-assembled, tested, and validated by the author. Use, review, and verify independently before building.

## Status

🟡 First prototype assembled and power-tested successfully (5V confirmed clean on rail, no protection trips). Video output path **does not work on v1 hardware** — traced to a schematic defect in which Q1's emitter node was shorted to the +5V rail (see Known Issues). Fixed in source; v1 boards need a rework.

<!-- Swap the line above for something like this once video's confirmed:
🟢 Fully validated — power and composite video both confirmed working on hardware.
-->

## Features

- USB-C power input (power only — no data lines)
- Composite video output
- Fits inside the original NES shell at the stock RF module location
- 2-layer PCB, designed in KiCad

## Hardware

- Designed in KiCad (schematic + PCB source included in this repo)
- Fabricated via PCBWay
- See [BOM.csv](./BOM.csv) for full parts list

## Build Notes / Known Issues (v1)

- **Q1 emitter node shorted to +5V (breaks video).** On fabbed v1 boards R1 has both ends on the `/5V` net, so Q1's emitter is clamped to the rail and C2 couples +5V — not video — into R5/J3. Root cause: an R2 (110Ω) was deleted from the schematic on 2026-07-04, and KiCad merged the two leftover collinear wire stubs into one wire, welding the emitter node to `/5V`. Fixed in source as of v1.1. **Rework for an existing board:** cut the trace running from R1's left pad up to the +5V rail (two traces reach that pad, at the D1 and F1 branches), then verify continuity from R1's left pad to Q1's emitter and to C2 pin 1. R1's right pad stays on +5V.
- F1 (polyfuse) footprint field in KiCad is mislabeled as a polarized capacitor footprint despite correct value — cosmetic/documentation issue only, does not affect function. Fix planned for v2.
- Video/audio RCA jack mounting holes are slightly asymmetric — cosmetic only, doesn't affect NES shell fit.
- v1 silkscreen doesn't include component value labels or Q1 pin markers (E/C/B) — planned addition for v2 to ease hand-assembly.

## Assembly

<!-- Add step-by-step or reference photos here once you've got a documented build process -->

Refer to BOM.csv for exact part values and footprints. Key notes:
- D1 (zener/TVS): cathode (banded end) toward VBUS/+5V side
- Q1 (2SA1015, PNP): flat side facing viewer, leads down = Emitter-Collector-Base, left to right
- R1 (300Ω): emitter load for Q1 — one end to +5V, the other to the Q1 emitter / C2 node. Not both ends to +5V.
- F1 (polyfuse): sits with slight standoff above PCB by design — this is normal for radial-lead parts, not a defect
- USB-C1: GCT USB4970-00-A, SMD receptacle — power-only, no data lines

## License

Licensed under [CERN-OHL-S v2](./LICENSE.txt) (strongly reciprocal open hardware license). See [LICENSE](./LICENSE.txt).

## Photos

<!-- Add build photos here -->

## Acknowledgments

<!-- Optional: credit anyone who helped with debugging, Discord community, etc. -->
