# v2 Design Notes

Working notes for the v2 revision. Captures the intermittent overcurrent
investigation and the changes it implies. Items marked **PENDING** still need
datasheet numbers or bench confirmation.

---

## 1. Intermittent overcurrent trips — root cause

**Symptom:** battery pack intermittently reported overcurrent when powering the
board. Went away entirely when the board was isolated from the NES with a cloth.

**Conclusion:** mechanical short between the board and the RF shield can, not a
circuit design fault.

The cloth test is the key evidence — adding clearance resolved it, which points
at contact rather than anything in the power path.

Contributing factors from the layout:

- The GND pour is on `B.Cu` only and extends to within ~0.1–0.5mm of the board
  outline on all sides. The entire underside is effectively ground-adjacent
  copper.
- Nearly every part is through-hole, so the underside carries exposed solder
  joints, and several are **not** GND: F1's VBUS-side leg (`/raw_5v`), the
  CC-side legs of R3/R4, the `/5V` leg of C1/C2/D1, and Q1's leads. Solder mask
  does not cover solder joints.

A tall or blobby joint on any of those nets making intermittent contact with the
shield can produces exactly the observed behavior.

### Fix (v2)

- [ ] Trim all through-hole leads flush on the bottom side; reflow any tall or
      blobby joints, especially near the board edges.
- [ ] Add a permanent insulating layer between the board and the shield can
      (Kapton or thin mylar cut to the can's inner profile). Do not rely on the
      cloth.
- [ ] Confirm which net was shorting: with the board seated in its installed
      position, check continuity from the shield can to GND, `/raw_5v`, `/5V`,
      CC1, and CC2, flexing gently to catch the intermittent.
- [ ] If it is consistently the same joint, relocate that pad away from the
      board edge.

The NES stock power supply is **removed** from this build, so reverse-current
backfeed from a second live source is not a concern.

---

## 2. CC circuit — verified correct, no change needed

Traced against the **PCB** netlist (`nes_power_video.kicad_pcb`), which is what
was actually fabricated:

| USB-C1 pin | Net | Path |
|---|---|---|
| CC1 (A5) | `Net-(USB-C1-CC1)` | → R4 → GND |
| CC2 (B5) | `Net-(USB-C1-CC2)` | → R3 → GND |
| VBUS (A9/B9) | `/raw_5v` | → F1 → `/5V` rail |

Each CC line has its own independent 5.1kΩ pulldown to GND. This is the correct
topology for a passive Type-C sink advertising default current.

**No PD negotiation happens on this board and none is needed.** There is no CC
receiver, no PD PHY, and no data lines — the board presents Rd and the source
applies 5V via the mandatory legacy fallback path. There is no handshake that
can fail, which is why PD was ruled out as a cause of the OC trips.

> `BOM.csv` previously had the R3/R4 CC assignments swapped. Corrected — R3 is
> the **CC2** pulldown, R4 is the **CC1** pulldown. Functionally irrelevant
> (both 5.1kΩ) but the documentation now matches the board.

---

## 3. Planned v2 change — replace F1 with an eFuse

F1 (RHEF200 polyfuse) is slow (thermal, seconds-scale), loose (2.0A hold /
3.8A trip) and cannot distinguish inrush from a genuine short. Replacing it
with an active eFuse gives fast overcurrent shutoff **and** soft-start from a
single part — the soft-start also removes inrush into C1 (100µF) as a variable.

### Candidate: TI TPS25200 (TPS25200DRVR)

Purpose-built 5V eFuse rather than a wide-input part adapted down.

| Parameter | Value |
|---|---|
| Current limit | Adjustable 85mA–2.9A via single resistor to GND |
| `R_ILIM` range | 36kΩ – 1100kΩ, 1% |
| Continuous load | ~2.5A |
| On-resistance | 60mΩ internal FET |
| Soft-start | Yes, integrated |
| Overvoltage clamp | Yes |
| Package | DRV, 6-pin WSON with thermal pad |
| Pinout | EN / ILIM / OUT / IN / GND / FAULT |
| Sourcing | LCSC `C128401`, in stock, ~$0.14 |

Reverse-current blocking is **not** required for this build (stock PSU removed).
If that ever changes, TI's TPS25947 family is the equivalent part with true
reverse-current blocking.

### PENDING — confirm from datasheet before committing

- [ ] Exact `R_ILIM` equation, and the resistor value for the chosen trip point
- [ ] **Fault response: latch-off vs auto-retry.** Matters here — auto-retry
      would chatter during an intermittent chassis short, latch-off would stay
      down until power-cycled
- [ ] Overvoltage clamp threshold
- [ ] Required input/output capacitors
- [ ] Target current limit — measure actual NES 5V rail draw first, then set the
      limit above measured peak with margin

### Layout implications

- The DRV package is leadless with a thermal pad. The board's only copper pour
  is on `B.Cu`; `F.Cu` has no pour at all. The eFuse goes top-side near USB-C1,
  so its thermal pad needs stitching vias down to the bottom GND pour.
- Leadless means no iron rework. Fine for assembled boards, but a bad unit is
  not fixable at the bench.
- Space is not a constraint. F1 sits at (35.5, 24.9) with 10.1mm to R4, 13.7mm
  to C1 and 14.1mm to USB-C1 on a 60 × 59.7mm board with only 13 parts.

---

## 4. Assembly readiness (PCBWay turnkey)

Assembly is planned at PCBWay rather than by hand. Blockers found:

- [ ] **`pcbway_production/` exports are stale.** Newest set is dated
      2026-07-16 and predates the RCA jack change. The exported CPL lists J2/J3
      as footprint `nes connector` at (72.45, −37.05) and (73.0, −65.0); the
      current PCB has `nes1:PJRAN1X1U03X` at (70.05, 42.23) and (69.05, 68.63).
      C2 also moved, and F1's footprint changed. **Re-export before ordering.**
- [ ] **MPN column is empty for every part** in both the exported BOM and CPL.
      Turnkey assembly needs real manufacturer part numbers. The passives are
      listed as "MOGAOPI" (an assortment brand) with no MPN — PCBWay cannot
      source these. Either supply real MPNs or explicitly authorize house
      substitutes with tolerance, voltage rating and package specified.
- [ ] **USB-C1 part/footprint mismatch.** `BOM.csv` specifies GCT USB4970-00-A,
      but the PCB footprint is
      `USB_C_Receptacle_GCT_USB4125-xx-x-0190_6P_TopMnt_Horizontal` — a
      different GCT series. v1 was hand-assembled successfully so they may be
      pad-compatible, but confirm before letting PCBWay source to the BOM MPN.
- [ ] Consider converting R1/R3/R4/R5 to 0805. 12 of 13 parts are currently
      through-hole and PCBWay hand-solders those per joint; SMT setup is being
      paid for regardless once USB-C1 and the eFuse are on the board.

---

## 5. Repo / file issues to clean up

- [ ] **Schematic does not match the PCB.** Commit `abaffb6` ("Changing to
      proper RCA jacks") modified `nes_power_video.kicad_pcb` but never touched
      `nes_power_video.kicad_sch`. The schematic also disagrees with the PCB on
      the CC circuit: in the schematic CC1 is floating, CC2 sits on the fused
      `raw_5v` node, R3 is between VBUS and GND, and R4 has a dangling leg. The
      **PCB is correct**; the schematic is stale. Re-sync it in KiCad before
      doing any v2 schematic work, or v2 will be built on a file that
      misrepresents the board.
- [ ] KiCad lock files and autosaves are tracked in git and should not be:
      `~nes_power_video.kicad_pcb.lck`, `~nes_power_video.kicad_pro.lck`,
      `~nes_power_video.kicad_sch.lck`, `_autosave-nes_power_video.kicad_pcb`,
      `_autosave-nes_power_video.kicad_sch`, `pcbway_production/.DS_Store`.
      Stale `.lck` files on a fresh clone can make KiCad think the project is
      open elsewhere. Add to `.gitignore` and `git rm --cached`.
- [ ] Resolved since v1: F1's footprint field is now correct
      (`Fuse:Fuse_Bourns_MF-RG300`) in both the schematic and the PCB. The
      README known-issues entry for it is out of date.
