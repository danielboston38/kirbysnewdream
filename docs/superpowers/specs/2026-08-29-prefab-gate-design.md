# Pre-fab gate — design

**Date:** 2026-08-29
**Status:** approved for planning
**Author:** Mark (with Claude Opus 5)

## Problem

Nothing in the current toolchain can stop a bad fab package from shipping.

On 2026-08-28 this project's board had `/AUDIO_OUT` shorted to the GND pour — a
stale zone fill left behind when J2 was rotated — and `tools/check_nets.py`
passed clean, because it only compares net *membership* between schematic and
PCB and cannot see copper geometry at all. KiCad keeps serving the previously
serialised fill polygon until something refills it.

kicad-happy cannot catch this either, and not by oversight: it invokes
`kicad-cli` in zero Python files, by design ("KiCad not required at runtime").
That means it can only read serialised fills, never recompute them.

A second class of fault was found on 2026-08-29 while designing this gate:
running DRC with `--schematic-parity` — a flag nothing in this repo had ever
passed — reported 30 parity issues, including a `dnp` attribute on both RCA
jacks that the schematic did not share.

That one is instructive, because the flag was not a mistake. It was set
deliberately, when the plan was to have PCBWay assemble the SMD parts only and
leave the through-hole jacks unfitted. The plan later changed; the PCB kept the
flag and the schematic never had it. Nobody typed anything wrong — a decision
was reversed and only one side of the design heard about it.

This is the failure mode parity checking actually defends against: not typos,
but **drift between two representations of the same intent**. It is also why a
DNP mismatch blocks rather than warns. The gate cannot know which side is
right — only that the two disagree about whether a part gets fitted, which is
not a question to resolve at the assembler.

## What this is

A distributable Claude Code plugin providing one CLI that refuses to produce a
fab package from a board that has not passed verification.

The gate **owns the export**. Verification and packaging are one operation, so
the check cannot be skipped and a stale package is structurally impossible —
the gerbers are always produced from the state that just passed.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Audience | Distributable plugin | The gap is in kicad-happy generally, not just this board |
| Enforcement | Gate owns the export | Un-skippable; removes staleness as a category |
| DRC policy | Respect KiCad's own severities | No second config language; honours a decision already made in the GUI |
| Parity policy | Split by sub-type | A footprint mismatch can ruin a board; a missing MPN field cannot |
| Output | Gerbers + drill + BOM + CPL | Matches the existing `pcbway_production/<timestamp>/` layout |
| Zone fills | Refill and save the board | Fixes the stale fill at source; board and package always agree |
| Shape | One CLI, subcommands | Matches "gate owns export" without inventing a hash protocol |

## Structure

```
prefab-gate/
├── plugin.json                     marketplace metadata
├── skills/prefab-gate/SKILL.md     when to use it, how to read a verdict
├── scripts/prefab_gate.py          the gate
└── tests/                          unit + fixture boards
```

Internally split into small units, each independently testable: `locate_cli`,
`run_drc`, `classify`, `export_package`, `report`.

## CLI

```
prefab_gate.py check   <board.kicad_pcb>   verify only, produces no files
prefab_gate.py package <board.kicad_pcb>   check then export — the un-skippable path
```

A standalone `export` subcommand was considered and dropped: an export that
could run without a check would reintroduce exactly the skip this gate exists to
prevent, and one that re-runs the check itself is just `package` under another
name.

Flags:

| Flag | Meaning |
|---|---|
| `--out <dir>` | package destination, default `fab/` |
| `--json` | machine-readable verdict on stdout in addition to the report |
| `--strict` | treat cosmetic findings as blocking too — for a final pre-order run |

Exit codes: `0` clean · `2` blocked by findings · `3` environment problem.

## Data flow (`package`)

1. Locate `kicad-cli`: `$KICAD_CLI`, then `PATH`, then platform-standard paths.
2. One DRC invocation:
   `--format json --severity-all --schematic-parity --refill-zones --save-board`
   This yields violations, unconnected items and parity together, and leaves the
   board's zones correctly filled.
3. Classify every finding as blocking or cosmetic.
4. On any blocking finding: print the report, exit `2`, **produce no files**. A
   half-written package directory is its own hazard.
5. Otherwise export gerbers, drill, BOM and CPL into `<out>/<timestamp>/`,
   building in a temp directory and renaming on success so failure never leaves
   something that looks shippable.
6. Write `manifest.json` beside the package.

## Classification

**DRC violations** — `error` blocks, `warning` is cosmetic, exclusions are
counted and otherwise ignored. **Unconnected items** always block.

**Schematic parity** — the JSON `type` field is *not* sufficient.
`footprint_symbol_mismatch` covers both "doesn't match footprint given by
symbol" (structural) and "'Exclude from bill of materials' settings differ"
(metadata). Classification therefore matches on description text, which is
fragile across KiCad versions, so:

**Any parity description the classifier does not recognise blocks**, naming the
exact unmatched string. A gate that fails open on an unfamiliar message is not a
gate.

| Class | Findings |
|---|---|
| Blocking | footprint doesn't match symbol; footprint missing/extra; net mismatch; **DNP differs** |
| Cosmetic | missing symbol field; exclude-from-BOM differs |

## manifest.json

Written beside every package. Records `kicad-cli` version, the board's SHA-256
at export time, the complete verdict including every cosmetic finding waved
through, and a checksum per exported file.

This answers, months later: what exactly was sent, from which board state, and
what did the gate knowingly allow past? Re-hashing the board says immediately
whether the package still corresponds to it.

## Error handling

- `kicad-cli` missing or too old → exit `3` with platform-specific install
  hints. This plugin *requires* KiCad, the opposite of kicad-happy's premise, so
  the failure must be loud rather than a silent degrade.
- Capability is feature-probed rather than version-parsed: the gate runs
  `kicad-cli pcb drc --help` once and requires `--format`, `--schematic-parity`
  and `--refill-zones` to be present. This avoids pinning a version number that
  would be wrong on distro builds and nightlies, and it fails with a message
  naming the missing flag.
- `--exit-code-violations` is deliberately not used; the gate parses the JSON and
  applies its own policy.
- `--save-board` mutates the board, so the gate hashes it before and after and
  states plainly when the refill changed it — the git diff should be expected,
  not mysterious.

## Testing

Unit tests drive `classify` with synthetic DRC JSON: every severity, both parity
classes, and an unrecognised description that must block.

Integration tests use fixture boards — one deliberately broken that must fail,
one clean that must produce a complete package with a valid manifest.

**Acceptance test.** `nes_power_video.kicad_pcb` at commit `c37b56b` must yield
exactly:

```
BLOCK  courtyards_overlap               TP1/J3     (error)
BLOCK  footprint_symbol_mismatch        J5         (footprint id mismatch)
pass   silk_edge_clearance        x4               (warning)
pass   silk_overlap               x2               (warning)
pass   footprint_symbol_field_mismatch x23         (metadata)
pass   exclude-from-BOM differs   x4    TP1-TP4    (metadata)
```

Two blockers, twenty-nine passed with a note. Any other verdict means the gate
is wrong.

## Out of scope

- Fab-house profiles (JLCPCB vs PCBWay drill formats, CPL column names). Deferred
  until the core gate is proven; this is where such tools accrete per-vendor
  breakage.
- Exported drill/copper diffing against the board. Made redundant by the gate
  owning the export.
- Replacing `tools/check_nets.py`. Its design-intent invariants are complementary
  and stay as they are.
