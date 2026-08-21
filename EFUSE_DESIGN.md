# eFuse Addition — TPS25200

Replaces **F1** (RHEF200 polyfuse) with an active eFuse on the VBUS path.

This branch works off **v1** and is intentionally kept separate from the wider
v2 rework so it can land on its own.

Datasheet referenced throughout: **SLVSCJ0F**, March 2014, revised July 2025.

---

## 1. Why replace F1

F1 is a PTC polyfuse: thermal, seconds-scale response, 2.0A hold / 3.8A trip,
and it cannot tell inrush apart from a genuine short. The TPS25200 replaces it
with a **3.5µs** short-circuit response and adds soft-start, an overvoltage
clamp, and a fault flag — all from one 2mm × 2mm part.

## 2. Part

| | |
|---|---|
| Part number | TPS25200DRVR |
| Package | DRV, 6-pin WSON, 2mm × 2mm, with PowerPAD |
| Pinout | 1 OUT · 2 ILIM · 3 FAULT · 4 EN · 5 GND · 6 IN · PAD |
| Sourcing | LCSC `C128401` |

## 3. Confirmed specifications

| Parameter | Value |
|---|---|
| Operating input | 2.5V – 6.5V |
| Input withstand (abs max) | 20V |
| Abs max on OUT / EN / ILIM / FAULT | **7V** |
| UVLO (IN rising) | 2.35V typ |
| Overvoltage clamp on OUT | 5.25 – 5.55V (5.4V typ) |
| Overvoltage lockout (OVLO) | 6.8 / 7.6 / 8.45V (min/typ/max), 0.6µs response |
| Short-circuit response | 3.5µs |
| On-resistance | 60mΩ typ (up to 99mΩ at 125°C) |
| Continuous load | up to 2.6A |
| Current limit range | 85mA – 2.9A, set by one resistor |
| Soft-start rise time (`tr`) | 2.05ms typ, 3.2ms max |
| Turn-on time (`ton`) | 5.12ms typ, 7.3ms max |
| Output discharge when disabled | 480 – 625Ω |
| Reverse current blocking | **only while disabled** |
| Thermal shutdown | OTSD1 135°C (in current limit), OTSD2 155°C, 20°C hysteresis |
| UL 2367 recognized | File 169910, R_ILIM ≥ 33kΩ |

> Two corrections to earlier working assumptions: the recommended R_ILIM range
> is **33kΩ**–1100kΩ, not 36kΩ. And the part **does** have reverse-current
> blocking, but only while disabled — it does not block reverse current while
> enabled. Not relevant to this build (the stock NES PSU is removed), but worth
> recording accurately.

## 4. Fault behavior — auto-retry, not latch-off

**This is the finding that matters most.** The TPS25200 does not latch off.

On overcurrent it enters **constant-current mode** — it holds output current at
`IOS` and lets the output voltage droop rather than disconnecting. Power
dissipation then heats the die, and:

- **OTSD1** turns the switch off above 135°C *while in current limit*
- **OTSD2** turns it off above 155°C regardless
- Either way it restarts after cooling ~20°C, and **cycles on/off until the
  fault is removed**

### What this means for the chassis short

Good news first: constant-current mode is exactly what stops the OC trips. The
eFuse caps the current the battery pack ever sees at `IOS`, so the pack's own
overcurrent protection never sees the transient that was tripping it.

But be clear about what that is — **it masks the symptom, it does not fix the
fault.** A sustained short will make the part thermally cycle, and the NES 5V
rail will droop or drop out during each event, which can reset the console.

**The Kapton/mylar insulation fix and the flush lead trim are still required.**
The eFuse is defense-in-depth, not a substitute.

Worth wiring `FAULT` to something visible for exactly this reason — see §7.

## 5. Setting the current limit

### Equation 1, verbatim from the datasheet

```
IOS_max (mA) = 96754 / R_ILIM^0.985  + 30
IOS_nom (mA) = 98322 / R_ILIM^1.003
IOS_min (mA) = 97399 / R_ILIM^1.015  - 30
```

with `R_ILIM` in kΩ, valid for **33kΩ ≤ R_ILIM ≤ 1100kΩ**, 1% resistors.

### Equation 2 — solving for a minimum threshold

```
R_ILIM (kΩ) = ( 97399 / (IOS_min + 30) ) ^ (1/1.015)
```

Verified against the datasheet's own worked example: a 2100mA minimum gives
43.22kΩ, matching §8.2.2.4 exactly.

### Selection table (E96 1% values)

| R_ILIM | IOS min | IOS nom | IOS max |
|---:|---:|---:|---:|
| 43.2k | 2101 mA | 2250 mA | 2400 mA |
| 45.3k | 2001 mA | 2146 mA | 2292 mA |
| 49.9k | 1811 mA | 1947 mA | 2086 mA |
| 53.6k | 1682 mA | 1813 mA | 1946 mA |
| **59.0k** | **1523 mA** | **1646 mA** | **1773 mA** |
| 64.9k | 1380 mA | 1496 mA | 1617 mA |
| 73.2k | 1218 mA | 1326 mA | 1440 mA |
| 86.6k | 1022 mA | 1120 mA | 1225 mA |

### Suggested starting point: 59.0kΩ

Gives 1523mA worst-case minimum — comfortably above the NES load plus inrush —
while holding the worst-case maximum to 1773mA, which stays under the rating of
a typical 2A USB source so the eFuse trips before the upstream supply does.

**Pending:** measure the actual NES 5V rail draw and confirm. Set the limit
above measured peak with margin. Note the datasheet's warning that programming
the limit too low prevents start-up into a heavy capacitive load — C1 is 100µF.

## 6. Soft-start solves the inrush question

Rise time is 2.05ms typ. Charging C1 (100µF) over that ramp draws:

```
I = C · dV/dt = 100µF × 5V / 2.05ms ≈ 244mA
```

against an essentially unlimited peak today, where the only impedance between
VBUS and C1 is the polyfuse's cold resistance. 244mA is far below any sensible
`IOS` setting, so start-up into C1 is not at risk, and inrush is eliminated as
a contributing cause of the OC trips.

## 7. Schematic changes

```
USB-C1 VBUS ──┬── IN ──[ TPS25200 ]── OUT ── /5V rail (C1, C2, D1, Q1, R1)
              │        EN  ILIM  FAULT  GND+PAD
              │
            C_IN 0.1µF
              │
             GND
```

- **Remove F1**, or keep its footprint as DNP for fallback.
- **IN** ← `/raw_5v` from USB-C1 VBUS. **OUT** → the `/5V` rail.
- **GND and PowerPAD both to GND.** The PAD is internally connected to GND and
  must also be connected externally.
- **EN — do not tie directly to IN.** EN's absolute maximum is 7V while IN
  withstands 20V, so a direct tie would destroy the pin under exactly the
  overvoltage fault the part exists to survive. The datasheet (§7.3.1) is
  explicit: tie EN to IN through a **300kΩ** pull-up. An internal zener clamps
  EN at ~6.4V typ and the 300kΩ limits the current into it.
- **ILIM** → `R_ILIM` to GND. Keep the trace as short as possible; parasitics
  degrade current-limit accuracy.
- **FAULT** is active-low open-drain with an 8ms deglitch, and can sink 25mA.
  Pull it up to **OUT, not IN** — OUT is clamped to ≤5.55V, safely inside
  FAULT's 7V limit, whereas IN can reach 20V and would exceed it.

## 8. Layout requirements

- **Thermal pad needs stitching vias.** The board's only copper pour is on
  `B.Cu`; `F.Cu` has none. The eFuse sits top-side, so its PowerPAD needs vias
  down to the bottom GND pour to shed heat.
- Place `C_IN` (0.1µF ceramic) as close to the IN pin as physically possible.
- Keep the `R_ILIM` trace short.
- Space is not a constraint: F1 currently sits at (35.5, 24.9) with 10.1mm to
  R4, 13.7mm to C1 and 14.1mm to USB-C1, on a 60 × 59.7mm board with 13 parts.
  The replacement is 2mm × 2mm.
- Leadless package — no iron rework. Fine for PCBWay assembly, but a bad unit
  is not repairable at the bench.

## 9. BOM rows to add

Kept here rather than edited into `BOM.csv` directly, so this branch does not
collide with the BOM corrections pending in PR #1. Merge these in once that
lands.

| Ref | Description | Value | Package | Mfr | MPN | Qty | Notes |
|---|---|---|---|---|---|---|---|
| U1 | 5V eFuse, adjustable current limit | — | WSON-6 (DRV) 2×2mm | TI | TPS25200DRVR | 1 | LCSC C128401. Replaces F1 |
| R6 | Current-limit set resistor | 59.0kΩ 1% | SMD | — | — | 1 | Pending measured NES draw. See §5 |
| R7 | EN pull-up | 300kΩ | SMD | — | — | 1 | IN→EN. Do **not** tie EN to IN directly |
| R8 | FAULT pull-up | 100kΩ | SMD | — | — | 1 | Pull up to **OUT**, not IN |
| C3 | Input bypass | 0.1µF ceramic | SMD | — | — | 1 | As close to IN as possible |
| F1 | PTC polyfuse | — | — | — | — | — | **Removed**, superseded by U1 |

Optional fault indicator: LED plus ~1kΩ in series from OUT to FAULT gives ~3mA,
well inside FAULT's 25mA sink rating, and replaces R8. Given how long the
intermittent short took to find, a visible fault light is worth the two parts.

## 10. Open items

- [ ] Measure NES 5V rail draw, then finalize `R_ILIM` (§5)
- [ ] Decide on the FAULT indicator LED vs a plain pull-up and test point
- [ ] Create or source the KiCad symbol and footprint for the DRV package
- [ ] **Re-sync the schematic before doing this work.** `nes_power_video.kicad_sch`
      is stale against the PCB — it disagrees on the CC circuit, and commit
      `abaffb6` changed the RCA jacks in the PCB without touching the schematic.
      The PCB is the correct file.
- [ ] Still required regardless of this change: insulate the board from the RF
      shield can and trim the through-hole leads flush (§4)
