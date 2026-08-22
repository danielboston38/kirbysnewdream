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
- Active overcurrent protection — TPS2553 eFuse with a ~1.18 A resistor-programmed limit, soft-start and thermal shutdown, backed by a polyfuse
- Fits inside the original NES shell at the stock RF module location
- 2-layer PCB, designed in KiCad

## Power path

```
USB-C  ──  F1 polyfuse  ──  U1 TPS2553 eFuse  ──  +5V rail  ──  J4.3 → NES
  VBUS      2.0A hold        ~1.18A limit          C1 100µF
            3.8A trip        soft-start            D1 TVS
            (backup)         thermal shutdown
```

F1 alone trips at 3.8 A, which protects nothing on a console that draws
roughly 0.5–0.7 A. U1 is the real protection; F1 stays as a backup in case
the eFuse ever fails short.

The current limit is set by R6 on U1's ILIM pin. The relationship is
**inverse** — a larger resistor gives a *lower* limit:

| R6 | Limit (typ) |
|---|---|
| 15 kΩ | 1700 mA |
| 20 kΩ | 1295 mA |
| **22 kΩ (fitted)** | **~1180 mA** |
| 49.9 kΩ | 520 mA |
| 210 kΩ | 130 mA |

Roughly I_OS(A) ≈ 25.9 / R6(kΩ), valid over TI's recommended 15 kΩ–232 kΩ.

U1's EN (pin 3) is active-high and tied to its own input, so the switch is
always on. FAULT (pin 4) is an open-drain output left unconnected — there is
nothing inside a closed NES shell to indicate to. If you want fault
indication, it can sink 25 mA directly.

A useful side effect: D1 is a unidirectional TVS, so fitting it backwards
puts a forward-biased diode across the 5 V rail. Before U1 that was a near
short relying on a polyfuse taking seconds to react. Now the eFuse current-
limits it at ~1.18 A and thermally shuts down, so the mistake is
self-limiting rather than destructive.

## Hardware

- Designed in KiCad (schematic + PCB source included in this repo)
- Fabricated via PCBWay
- See [BOM.csv](./BOM.csv) for full parts list

## Build Notes / Known Issues (v1)

- **Q1 emitter node shorted to +5V (breaks video).** On fabbed v1 boards R1 has both ends on the `/5V` net, so Q1's emitter is clamped to the rail and C2 couples +5V — not video — into R5/J3. Root cause: an R2 (110Ω) was deleted from the schematic on 2026-07-04, and KiCad merged the two leftover collinear wire stubs into one wire, welding the emitter node to `/5V`. Fixed in source as of v1.1. **Rework for an existing board** (applies to the boards fabbed from the 2026-07-16 gerbers, whose IPC netlist reads `/5V = J4.3, F1.1, R1.1, Q1.1, C2.1, D1.1` and `Net-(C1-Pad1) = R1.2, C1.1`):

That revision has two defects — Q1's emitter is clamped to the rail, *and* C1 only reaches the rail through R1, so the bulk cap decouples nothing. Both are fixed together:

1. **Cut** the 0.8 mm trace leaving R1's left pad toward the **upper left**, about 5–8 mm from the pad. Leave the trace entering that pad from the upper right — that one goes to Q1's emitter and must stay. Two collinear traces (the F1 and D1 branches) overlap along that stretch, so one cut severs both. Do not cut above the point level with D1's cathode, or the rail loses its path to D1 and J4.3.
2. **Jumper** C1's + pad to F1 pad 1 (the pad whose trace runs left toward D1, not the one toward USB-C). This puts R1's right pad on the rail so R1 becomes the emitter pull-up, and connects C1 to the rail properly.
3. **Fit R5 (75Ω)** if not already populated — without it there is no path from C2 to the RCA jack.

Verify with a meter before powering: R1 left pad to D1 cathode must now read **open**; R1 left pad to F1 pad 1 must read **~330Ω** through R1; R1 left pad must still show continuity to Q1's emitter and C2 pin 1. Powered, Q1's emitter should sit near 1.5–3V — a reading of 5V means the cut did not take.
- F1 (polyfuse) footprint field in KiCad is mislabeled as a polarized capacitor footprint despite correct value — cosmetic/documentation issue only, does not affect function. Fix planned for v2.
- Video/audio RCA jack mounting holes are slightly asymmetric — cosmetic only, doesn't affect NES shell fit.
- v1 silkscreen doesn't include component value labels or Q1 pin markers (E/C/B) — planned addition for v2 to ease hand-assembly.
- **D1 does not protect U1.** The fitted TVS is a 1.5KE6.8A: stand-off 5.80 V, breakdown 6.45–7.14 V at 10 mA, clamping 10.5 V at 143 A. The TPS2553's absolute maximum on IN and OUT is 7 V, so the TVS has barely begun conducting by the time the eFuse is already out of spec, and under a real surge it lets the rail reach 10.5 V. D1 protects the console downstream; it will not save U1. Repositioning D1 doesn't help — both U1 pins share the same 7 V rating — and no avalanche TVS clamps below 7 V while standing off USB-C's 5.5 V worst case. Proper protection needs a switch with integrated overvoltage cutoff. Deferred to v2.
- D1's symbol (`Diode:1.5KExxA`) names both pins A1/A2 and draws no cathode — KiCad uses identical pin naming for the unidirectional and bidirectional variants of this part. Polarity comes only from the footprint silkscreen band, which is at the pad-1 (+5 V) end and is correct. Watch this when hand-assembling.

## Assembly

<!-- Add step-by-step or reference photos here once you've got a documented build process -->

Refer to BOM.csv for exact part values and footprints. Key notes:
- D1 (zener/TVS): cathode (banded end) toward VBUS/+5V side
- Q1 (2SA1015, PNP): flat side facing viewer, leads down = Emitter-Collector-Base, left to right
- R1 (300Ω): emitter load for Q1 — one end to +5V, the other to the Q1 emitter / C2 node. Not both ends to +5V.
- F1 (polyfuse): sits with slight standoff above PCB by design — this is normal for radial-lead parts, not a defect
- USB-C1: GCT USB4970-00-A, SMD receptacle — power-only, no data lines
- U1 (TPS2553, SOT-23-6): pin 1 is IN, marked by the dot on the package. Pin order is IN, GND, EN down one side and OUT, ILIM, FAULT up the other. Order the plain TPS2553DBVR — the `-1` suffix is the latch-off variant, which would need a power cycle after every trip instead of retrying automatically.
- C3 (100nF, 0805): TI requires this as close to U1 pin 1 as the layout allows. It sits immediately left of U1.
- R6 (22k, 0805): sets the current limit — see the table above before substituting.

## License

Licensed under [CERN-OHL-S v2](./LICENSE.txt) (strongly reciprocal open hardware license). See [LICENSE](./LICENSE.txt).

## Photos

<!-- Add build photos here -->

## Acknowledgments

<!-- Optional: credit anyone who helped with debugging, Discord community, etc. -->
