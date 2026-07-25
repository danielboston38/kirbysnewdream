# Kirby's New Dream

A custom composite video / USB-C power replacement board for the original Nintendo Entertainment System (NES). Drops in at the original RF module location inside the NES shell, replacing the RF modulator with a clean composite video + USB-C power solution.

## Disclosure

This project's schematic design, debugging, and documentation were developed with the assistance of AI (Claude, by Anthropic). All hardware was hand-assembled, tested, and validated by the author. Use, review, and verify independently before building.

## Status

🟢 First prototype assembled and power-tested successfully (5V confirmed clean on rail, no protection trips). Video output path not yet validated — pending R5 (75Ω) sourcing.

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

- F1 (polyfuse) footprint field in KiCad is mislabeled as a polarized capacitor footprint despite correct value — cosmetic/documentation issue only, does not affect function. Fix planned for v2.
- Video/audio RCA jack mounting holes are slightly asymmetric — cosmetic only, doesn't affect NES shell fit.
- v1 silkscreen doesn't include component value labels or Q1 pin markers (E/C/B) — planned addition for v2 to ease hand-assembly.

## Assembly

<!-- Add step-by-step or reference photos here once you've got a documented build process -->

Refer to BOM.csv for exact part values and footprints. Key notes:
- D1 (zener/TVS): cathode (banded end) toward VBUS/+5V side
- Q1 (2SA1015, PNP): flat side facing viewer, leads down = Emitter-Collector-Base, left to right
- F1 (polyfuse): sits with slight standoff above PCB by design — this is normal for radial-lead parts, not a defect
- USB-C1: GCT USB4970-00-A, SMD receptacle — power-only, no data lines

## License

Licensed under [CERN-OHL-S v2](https://ohwr.org/cern_ohl_s_v2.txt) (strongly reciprocal open hardware license). See [LICENSE](./LICENSE).

## Photos

<!-- Add build photos here -->

## Acknowledgments

<!-- Optional: credit anyone who helped with debugging, Discord community, etc. -->
