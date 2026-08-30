# Pre-fab Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A distributable Claude Code plugin whose CLI refuses to produce a fab package from a board that has not passed verification.

**Architecture:** One CLI entry point (`prefab_gate.py`) over a small package of single-responsibility modules. A single `kicad-cli pcb drc` invocation yields violations, unconnected items and schematic parity together; a pure `classify()` function turns that JSON into a verdict; export only runs when the verdict is clean, builds into a temp directory, and renames on success.

**Tech Stack:** Python 3.10+, standard library only. `kicad-cli` (KiCad 8+) as an external dependency. Tests via `python3 -m unittest` — no pytest, no pip install.

**Spec:** `docs/superpowers/specs/2026-08-29-prefab-gate-design.md`

## Global Constraints

- **Python 3.10+, standard library only.** No pip installs, no third-party imports, in the plugin or its tests. Matches kicad-happy's hard requirement so the plugin runs anywhere with a Python interpreter.
- **`kicad-cli` is required, never optional.** Missing or incapable → exit `3` with a message naming what is missing.
- **Capability is feature-probed, not version-parsed.** `kicad-cli pcb drc --help` must advertise `--format`, `--schematic-parity` and `--refill-zones`.
- **Exit codes:** `0` clean · `2` blocked by findings · `3` environment problem.
- **Unrecognised parity descriptions block**, naming the exact unmatched string.
- **No files on a blocking verdict.** Not even a partial directory.
- **Export is atomic:** build in a temp directory, `os.replace` into place on success.
- **Build location:** `prefab-gate/` at the repo root. Extraction into its own publishable repo is a mechanical `git init` of that directory and is deliberately not part of this plan.

## File Structure

| File | Responsibility |
|---|---|
| `prefab-gate/scripts/prefab_gate.py` | CLI: argument parsing, subcommand dispatch, exit codes |
| `prefab-gate/scripts/gate/model.py` | `Finding` and `Verdict` dataclasses |
| `prefab-gate/scripts/gate/classify.py` | Pure DRC-JSON → `Verdict`. No I/O |
| `prefab-gate/scripts/gate/kicad.py` | Locate `kicad-cli`, probe capability, run DRC |
| `prefab-gate/scripts/gate/report.py` | Human-readable and JSON renderings of a `Verdict` |
| `prefab-gate/scripts/gate/manifest.py` | Hashing and manifest construction |
| `prefab-gate/scripts/gate/export.py` | Atomic package export |
| `prefab-gate/skills/prefab-gate/SKILL.md` | When to reach for the gate, how to read a verdict |
| `prefab-gate/plugin.json` | Marketplace metadata |
| `prefab-gate/tests/` | Unit tests, one module per source module |

`classify.py` is deliberately pure: it takes parsed JSON and returns a verdict, touching no filesystem and no subprocess. That is what makes the policy testable without KiCad installed.

---

### Task 1: Finding and Verdict model

**Files:**
- Create: `prefab-gate/scripts/gate/__init__.py` (empty)
- Create: `prefab-gate/scripts/gate/model.py`
- Test: `prefab-gate/tests/test_model.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Finding(kind, type, description, severity, items, blocking, reason)` frozen dataclass; `Verdict(blocking, cosmetic)` with `.passed` property returning `bool`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from gate.model import Finding, Verdict


def finding(blocking=True):
    return Finding(kind="violation", type="clearance", description="Clearance violation",
                   severity="error", items=("Track F.Cu", "Pad U1.2"),
                   blocking=blocking, reason="severity is error")


class TestVerdict(unittest.TestCase):
    def test_verdict_with_no_blocking_findings_has_passed_true(self):
        self.assertTrue(Verdict(blocking=[], cosmetic=[finding(False)]).passed)

    def test_verdict_with_a_blocking_finding_has_passed_false(self):
        self.assertFalse(Verdict(blocking=[finding()], cosmetic=[]).passed)

    def test_finding_is_hashable_so_verdicts_can_be_deduplicated(self):
        self.assertEqual(len({finding(), finding()}), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest discover -s ../tests -t . -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Value types for gate verdicts."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    kind: str          # "violation" | "unconnected" | "parity"
    type: str          # kicad-cli's machine-readable type, "" when absent
    description: str
    severity: str      # "error" | "warning" | "exclusion" | ""
    items: tuple       # tuple[str, ...] of affected item descriptions
    blocking: bool
    reason: str        # why the gate placed it in this class


@dataclass
class Verdict:
    blocking: list = field(default_factory=list)
    cosmetic: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blocking
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest discover -s ../tests -t . -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/__init__.py prefab-gate/scripts/gate/model.py prefab-gate/tests/test_model.py
git commit -m "feat(prefab-gate): add Finding and Verdict model"
```

---

### Task 2: Classify DRC violations and unconnected items

**Files:**
- Create: `prefab-gate/scripts/gate/classify.py`
- Test: `prefab-gate/tests/test_classify_drc.py`

**Interfaces:**
- Consumes: `Finding`, `Verdict` from Task 1
- Produces: `classify(drc: dict, strict: bool = False) -> Verdict`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from gate.classify import classify


def drc(violations=(), unconnected=(), parity=()):
    return {"violations": list(violations), "unconnected_items": list(unconnected),
            "schematic_parity": list(parity)}


def violation(severity, type_="clearance"):
    return {"type": type_, "description": f"{type_} problem", "severity": severity,
            "items": [{"description": "Pad U1.2"}]}


class TestClassifyViolations(unittest.TestCase):
    def test_error_severity_blocks(self):
        v = classify(drc(violations=[violation("error")]))
        self.assertEqual(len(v.blocking), 1)
        self.assertFalse(v.passed)

    def test_warning_severity_is_cosmetic(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)

    def test_exclusion_severity_is_neither_blocking_nor_cosmetic(self):
        v = classify(drc(violations=[violation("exclusion")]))
        self.assertEqual((len(v.blocking), len(v.cosmetic)), (0, 0))

    def test_unconnected_items_always_block(self):
        v = classify(drc(unconnected=[{"description": "Net /5V", "items": []}]))
        self.assertEqual(len(v.blocking), 1)

    def test_strict_mode_promotes_cosmetic_to_blocking(self):
        v = classify(drc(violations=[violation("warning", "silk_overlap")]), strict=True)
        self.assertEqual(len(v.blocking), 1)
        self.assertEqual(len(v.cosmetic), 0)

    def test_finding_records_affected_items(self):
        v = classify(drc(violations=[violation("error")]))
        self.assertEqual(v.blocking[0].items, ("Pad U1.2",))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_classify_drc -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate.classify'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Turn parsed kicad-cli DRC JSON into a Verdict.

Pure: no filesystem, no subprocess. That is what makes the policy testable
without KiCad installed.
"""
from gate.model import Finding, Verdict


def _items(entry):
    return tuple(i.get("description", "") for i in entry.get("items", []))


def classify(drc: dict, strict: bool = False) -> Verdict:
    verdict = Verdict()

    def place(finding):
        if finding.blocking or strict:
            verdict.blocking.append(
                finding if finding.blocking
                else Finding(**{**finding.__dict__, "blocking": True,
                                "reason": finding.reason + " (promoted by --strict)"}))
        else:
            verdict.cosmetic.append(finding)

    for v in drc.get("violations", []):
        severity = v.get("severity", "")
        if severity == "exclusion":
            continue          # user excluded it in the GUI; counted, not judged
        place(Finding(kind="violation", type=v.get("type", ""),
                      description=v.get("description", ""), severity=severity,
                      items=_items(v), blocking=(severity == "error"),
                      reason=f"DRC severity is {severity or 'unset'}"))

    for u in drc.get("unconnected_items", []):
        place(Finding(kind="unconnected", type=u.get("type", "unconnected"),
                      description=u.get("description", ""), severity="error",
                      items=_items(u), blocking=True,
                      reason="unconnected items always block"))

    return verdict
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_classify_drc -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/classify.py prefab-gate/tests/test_classify_drc.py
git commit -m "feat(prefab-gate): classify DRC violations by KiCad severity"
```

---

### Task 3: Classify schematic parity, blocking on anything unrecognised

**Files:**
- Modify: `prefab-gate/scripts/gate/classify.py`
- Test: `prefab-gate/tests/test_classify_parity.py`

**Interfaces:**
- Consumes: `classify()` from Task 2
- Produces: same signature; adds `BLOCKING_PARITY`, `COSMETIC_PARITY` module constants (tuples of substrings)

The `type` field is *not* sufficient here. `footprint_symbol_mismatch` covers both "doesn't match footprint given by symbol" (structural) and "'Exclude from bill of materials' settings differ" (metadata). Matching is on description substrings, and anything unmatched blocks.

Real descriptions observed on a KiCad 10 board, use these verbatim in tests:

- `Missing symbol field 'Manufacturer' in footprint`
- `Footprint attributes don't match symbol: 'Do not populate' settings differ`
- `Footprint attributes don't match symbol: 'Exclude from bill of materials' settings differ`
- `PinHeader_1x03_P2.54mm_Vertical doesn't match footprint given by symbol (Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical)`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from gate.classify import classify


def parity(description, type_="footprint_symbol_mismatch"):
    return {"type": type_, "description": description, "severity": "warning",
            "items": [{"description": "Footprint J5"}]}


def drc(parity_entries):
    return {"violations": [], "unconnected_items": [], "schematic_parity": list(parity_entries)}


class TestClassifyParity(unittest.TestCase):
    def test_footprint_mismatch_blocks(self):
        v = classify(drc([parity(
            "PinHeader_1x03_P2.54mm_Vertical doesn't match footprint given by symbol "
            "(Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical)")]))
        self.assertEqual(len(v.blocking), 1)

    def test_dnp_mismatch_blocks(self):
        v = classify(drc([parity(
            "Footprint attributes don't match symbol: 'Do not populate' settings differ")]))
        self.assertEqual(len(v.blocking), 1)

    def test_missing_symbol_field_is_cosmetic(self):
        v = classify(drc([parity("Missing symbol field 'Manufacturer' in footprint",
                                 "footprint_symbol_field_mismatch")]))
        self.assertEqual(len(v.cosmetic), 1)
        self.assertTrue(v.passed)

    def test_exclude_from_bom_is_cosmetic(self):
        v = classify(drc([parity(
            "Footprint attributes don't match symbol: "
            "'Exclude from bill of materials' settings differ")]))
        self.assertEqual(len(v.cosmetic), 1)

    def test_unrecognised_description_blocks(self):
        v = classify(drc([parity("Some future KiCad wording nobody has seen")]))
        self.assertEqual(len(v.blocking), 1)

    def test_unrecognised_description_names_the_string_it_did_not_match(self):
        v = classify(drc([parity("Some future KiCad wording nobody has seen")]))
        self.assertIn("Some future KiCad wording nobody has seen", v.blocking[0].reason)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_classify_parity -v`
Expected: FAIL — parity entries are currently ignored, so every test reports 0 findings

- [ ] **Step 3: Write minimal implementation**

Add to `classify.py`, above `classify()`:

```python
# Parity descriptions are matched by substring because kicad-cli's `type` field
# is too coarse: footprint_symbol_mismatch covers both a genuine footprint
# mismatch and a trivial exclude-from-BOM difference.
BLOCKING_PARITY = (
    "doesn't match footprint given by symbol",
    "'Do not populate' settings differ",
    "not found in schematic",
    "not found on PCB",
    "net mismatch",
)
COSMETIC_PARITY = (
    "Missing symbol field",
    "'Exclude from bill of materials' settings differ",
)
```

and inside `classify()`, before `return verdict`:

```python
    for p in drc.get("schematic_parity", []):
        description = p.get("description", "")
        if any(s in description for s in BLOCKING_PARITY):
            blocking, reason = True, "structural parity mismatch"
        elif any(s in description for s in COSMETIC_PARITY):
            blocking, reason = False, "metadata-only parity mismatch"
        else:
            blocking = True
            reason = ("unrecognised parity description, blocking by default: "
                      f"{description!r}")
        place(Finding(kind="parity", type=p.get("type", ""), description=description,
                      severity=p.get("severity", "warning"), items=_items(p),
                      blocking=blocking, reason=reason))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest discover -s ../tests -t . -v`
Expected: all 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/classify.py prefab-gate/tests/test_classify_parity.py
git commit -m "feat(prefab-gate): classify parity findings, block on unrecognised wording"
```

---

### Task 4: Locate kicad-cli and probe its capability

**Files:**
- Create: `prefab-gate/scripts/gate/kicad.py`
- Test: `prefab-gate/tests/test_kicad_locate.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class KicadUnavailable(Exception)`; `locate_cli(env=None, which=shutil.which, exists=os.path.exists) -> str`; `probe_capability(cli, runner=subprocess.run) -> None` raising `KicadUnavailable`

Injected `which`/`exists`/`runner` keep the tests free of a real KiCad install.

- [ ] **Step 1: Write the failing test**

```python
import unittest
from gate.kicad import locate_cli, probe_capability, KicadUnavailable

HELP = ("Usage: pcb drc [--help] [--output OUTPUT_FILE] [--format FORMAT] "
        "[--schematic-parity] [--severity-all] [--refill-zones] INPUT_FILE")


class Result:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


class TestLocate(unittest.TestCase):
    def test_env_var_wins(self):
        found = locate_cli(env={"KICAD_CLI": "/custom/kicad-cli"},
                           which=lambda n: None, exists=lambda p: True)
        self.assertEqual(found, "/custom/kicad-cli")

    def test_falls_back_to_path(self):
        found = locate_cli(env={}, which=lambda n: "/usr/bin/kicad-cli",
                           exists=lambda p: False)
        self.assertEqual(found, "/usr/bin/kicad-cli")

    def test_raises_when_absent_everywhere(self):
        with self.assertRaises(KicadUnavailable) as ctx:
            locate_cli(env={}, which=lambda n: None, exists=lambda p: False)
        self.assertIn("kicad-cli", str(ctx.exception))

    def test_env_var_pointing_at_nothing_is_an_error(self):
        with self.assertRaises(KicadUnavailable):
            locate_cli(env={"KICAD_CLI": "/nope"}, which=lambda n: None,
                       exists=lambda p: False)


class TestProbe(unittest.TestCase):
    def test_accepts_a_capable_cli(self):
        probe_capability("kicad-cli", runner=lambda *a, **k: Result(HELP))

    def test_rejects_and_names_the_missing_flag(self):
        stripped = HELP.replace("[--schematic-parity] ", "")
        with self.assertRaises(KicadUnavailable) as ctx:
            probe_capability("kicad-cli", runner=lambda *a, **k: Result(stripped))
        self.assertIn("--schematic-parity", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_kicad_locate -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate.kicad'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Locating and driving kicad-cli."""
import os
import shutil
import subprocess

REQUIRED_FLAGS = ("--format", "--schematic-parity", "--refill-zones")

# Checked in order, after $KICAD_CLI and $PATH.
FALLBACK_PATHS = (
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
)


class KicadUnavailable(Exception):
    """kicad-cli is missing, or too old to do what the gate needs."""


def locate_cli(env=None, which=shutil.which, exists=os.path.exists) -> str:
    env = os.environ if env is None else env
    override = env.get("KICAD_CLI")
    if override:
        if exists(override):
            return override
        raise KicadUnavailable(f"KICAD_CLI is set to {override!r}, which does not exist")
    found = which("kicad-cli")
    if found:
        return found
    for candidate in FALLBACK_PATHS:
        if exists(candidate):
            return candidate
    raise KicadUnavailable(
        "kicad-cli not found. Install KiCad 8 or newer, then either put kicad-cli on "
        "your PATH or set KICAD_CLI to its full path.\n"
        "  macOS:   /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli\n"
        "  Linux:   apt install kicad  (or the KiCad AppImage)\n"
        "  Windows: C:\\Program Files\\KiCad\\<version>\\bin\\kicad-cli.exe")


def probe_capability(cli: str, runner=subprocess.run) -> None:
    result = runner([cli, "pcb", "drc", "--help"], capture_output=True, text=True)
    help_text = getattr(result, "stdout", "") or ""
    missing = [f for f in REQUIRED_FLAGS if f not in help_text]
    if missing:
        raise KicadUnavailable(
            f"{cli} does not support {', '.join(missing)}. The gate needs KiCad 8 or "
            "newer; upgrade KiCad or point KICAD_CLI at a newer install.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_kicad_locate -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/kicad.py prefab-gate/tests/test_kicad_locate.py
git commit -m "feat(prefab-gate): locate kicad-cli and feature-probe its DRC flags"
```

---

### Task 5: Run DRC and parse its JSON

**Files:**
- Modify: `prefab-gate/scripts/gate/kicad.py`
- Test: `prefab-gate/tests/test_kicad_drc.py`

**Interfaces:**
- Consumes: `KicadUnavailable` from Task 4
- Produces: `run_drc(cli: str, board: str, runner=subprocess.run) -> dict`

`--exit-code-violations` is deliberately not passed: the gate applies its own policy, so a non-zero exit would only obscure a successful run that found problems.

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import tempfile
import unittest
from gate.kicad import run_drc, KicadUnavailable


class TestRunDrc(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def runner(self, payload=None, returncode=0):
        def _run(cmd, **kwargs):
            self.calls.append(cmd)
            out = cmd[cmd.index("-o") + 1]
            with open(out, "w") as fh:
                json.dump(payload if payload is not None
                          else {"violations": [], "unconnected_items": [],
                                "schematic_parity": []}, fh)

            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = returncode, "", ""
            return r
        return _run

    def test_returns_parsed_json(self):
        drc = run_drc("kicad-cli", "board.kicad_pcb", runner=self.runner())
        self.assertEqual(drc["violations"], [])

    def test_passes_the_flags_the_gate_depends_on(self):
        run_drc("kicad-cli", "board.kicad_pcb", runner=self.runner())
        cmd = " ".join(self.calls[0])
        for flag in ("--format json", "--severity-all", "--schematic-parity",
                     "--refill-zones", "--save-board"):
            self.assertIn(flag, cmd)

    def test_raises_when_kicad_cli_fails(self):
        def failing(cmd, **kwargs):
            class R:
                pass
            r = R()
            r.returncode, r.stdout, r.stderr = 1, "", "boom"
            return r
        with self.assertRaises(KicadUnavailable):
            run_drc("kicad-cli", "board.kicad_pcb", runner=failing)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_kicad_drc -v`
Expected: FAIL with `ImportError: cannot import name 'run_drc'`

- [ ] **Step 3: Write minimal implementation**

Append to `kicad.py`:

```python
import json
import tempfile


def run_drc(cli: str, board: str, runner=subprocess.run) -> dict:
    """One DRC pass: violations, unconnected items and parity together.

    --refill-zones --save-board is intentional. A stale zone fill is the fault
    this gate exists to catch, and refilling without saving would leave the
    board on disk disagreeing with the package just exported from it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "drc.json")
        result = runner([cli, "pcb", "drc", "--format", "json", "--severity-all",
                         "--schematic-parity", "--refill-zones", "--save-board",
                         "-o", out, board],
                        capture_output=True, text=True)
        if getattr(result, "returncode", 0) != 0:
            raise KicadUnavailable(
                f"kicad-cli DRC failed (exit {result.returncode}): "
                f"{(getattr(result, 'stderr', '') or '').strip()}")
        with open(out) as fh:
            return json.load(fh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_kicad_drc -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/kicad.py prefab-gate/tests/test_kicad_drc.py
git commit -m "feat(prefab-gate): run DRC with parity and zone refill, parse JSON"
```

---

### Task 6: Render the verdict

**Files:**
- Create: `prefab-gate/scripts/gate/report.py`
- Test: `prefab-gate/tests/test_report.py`

**Interfaces:**
- Consumes: `Verdict`, `Finding` from Task 1
- Produces: `render_text(verdict) -> str`; `render_json(verdict) -> str`

The report is a first-class output, not a debug aid: a blocked run must say what blocked it and where, without the user opening KiCad.

- [ ] **Step 1: Write the failing test**

```python
import json
import unittest
from gate.model import Finding, Verdict
from gate.report import render_text, render_json


def f(blocking, description="Courtyards overlap", items=("Footprint TP1", "Footprint J3")):
    return Finding(kind="violation", type="courtyards_overlap", description=description,
                   severity="error" if blocking else "warning", items=items,
                   blocking=blocking, reason="DRC severity is error")


class TestRenderText(unittest.TestCase):
    def test_blocked_report_names_the_blocking_finding_and_its_items(self):
        text = render_text(Verdict(blocking=[f(True)], cosmetic=[]))
        self.assertIn("BLOCKED", text)
        self.assertIn("Courtyards overlap", text)
        self.assertIn("Footprint TP1", text)

    def test_clean_report_says_so_and_counts_what_it_waved_through(self):
        text = render_text(Verdict(blocking=[], cosmetic=[f(False), f(False)]))
        self.assertIn("PASSED", text)
        self.assertIn("2", text)

    def test_cosmetic_findings_are_listed_not_just_counted(self):
        text = render_text(Verdict(blocking=[], cosmetic=[f(False, "Silkscreen clipped")]))
        self.assertIn("Silkscreen clipped", text)


class TestRenderJson(unittest.TestCase):
    def test_json_is_machine_readable_and_carries_both_classes(self):
        data = json.loads(render_json(Verdict(blocking=[f(True)], cosmetic=[f(False)])))
        self.assertIs(data["passed"], False)
        self.assertEqual(len(data["blocking"]), 1)
        self.assertEqual(len(data["cosmetic"]), 1)
        self.assertEqual(data["blocking"][0]["type"], "courtyards_overlap")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_report -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate.report'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Human and machine renderings of a verdict."""
import json
from dataclasses import asdict


def _line(finding):
    where = f"  [{', '.join(finding.items)}]" if finding.items else ""
    return (f"  {finding.type or finding.kind:32} {finding.description}{where}\n"
            f"      {finding.reason}")


def render_text(verdict) -> str:
    out = []
    if verdict.passed:
        out.append(f"PASSED — nothing blocking. {len(verdict.cosmetic)} cosmetic "
                   f"finding(s) waved through.")
    else:
        out.append(f"BLOCKED — {len(verdict.blocking)} blocking finding(s). "
                   "No files were produced.")
        out.append("")
        out.append("Blocking:")
        out.extend(_line(f) for f in verdict.blocking)
    if verdict.cosmetic:
        out.append("")
        out.append(f"Cosmetic ({len(verdict.cosmetic)}):")
        out.extend(_line(f) for f in verdict.cosmetic)
    return "\n".join(out)


def render_json(verdict) -> str:
    return json.dumps({
        "passed": verdict.passed,
        "blocking": [asdict(f) for f in verdict.blocking],
        "cosmetic": [asdict(f) for f in verdict.cosmetic],
    }, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_report -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/report.py prefab-gate/tests/test_report.py
git commit -m "feat(prefab-gate): render verdicts as text and JSON"
```

---

### Task 7: Build the manifest

**Files:**
- Create: `prefab-gate/scripts/gate/manifest.py`
- Test: `prefab-gate/tests/test_manifest.py`

**Interfaces:**
- Consumes: `Verdict` from Task 1
- Produces: `sha256(path) -> str`; `build_manifest(board, cli_version, verdict, files) -> dict`

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest
from gate.model import Finding, Verdict
from gate.manifest import sha256, build_manifest


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.board = os.path.join(self.tmp.name, "b.kicad_pcb")
        with open(self.board, "w") as fh:
            fh.write("(kicad_pcb)")
        self.addCleanup(self.tmp.cleanup)

    def test_sha256_is_stable_and_content_dependent(self):
        first = sha256(self.board)
        self.assertEqual(first, sha256(self.board))
        with open(self.board, "a") as fh:
            fh.write(" ")
        self.assertNotEqual(first, sha256(self.board))

    def test_manifest_records_board_hash_and_cli_version(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [])
        self.assertEqual(m["board"]["sha256"], sha256(self.board))
        self.assertEqual(m["kicad_cli_version"], "10.0.5")

    def test_manifest_records_every_cosmetic_finding_it_let_past(self):
        waved = Finding(kind="violation", type="silk_overlap", description="Silk",
                        severity="warning", items=(), blocking=False, reason="warning")
        m = build_manifest(self.board, "10.0.5", Verdict(cosmetic=[waved]), [])
        self.assertEqual(len(m["verdict"]["cosmetic"]), 1)
        self.assertEqual(m["verdict"]["cosmetic"][0]["type"], "silk_overlap")

    def test_manifest_checksums_each_exported_file(self):
        m = build_manifest(self.board, "10.0.5", Verdict(), [self.board])
        self.assertEqual(m["files"][0]["sha256"], sha256(self.board))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_manifest -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The package receipt.

Answers, months later: what was sent, from which board state, and what did the
gate knowingly allow past?
"""
import hashlib
import os
from dataclasses import asdict
from datetime import datetime, timezone


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(board: str, cli_version: str, verdict, files) -> dict:
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "kicad_cli_version": cli_version,
        "board": {"path": os.path.basename(board), "sha256": sha256(board)},
        "verdict": {
            "passed": verdict.passed,
            "blocking": [asdict(f) for f in verdict.blocking],
            "cosmetic": [asdict(f) for f in verdict.cosmetic],
        },
        "files": [{"name": os.path.basename(p), "sha256": sha256(p)} for p in sorted(files)],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_manifest -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/manifest.py prefab-gate/tests/test_manifest.py
git commit -m "feat(prefab-gate): build a package manifest with hashes and waived findings"
```

---

### Task 8: Export the package atomically

**Files:**
- Create: `prefab-gate/scripts/gate/export.py`
- Test: `prefab-gate/tests/test_export.py`

**Interfaces:**
- Consumes: `KicadUnavailable` from Task 4
- Produces: `schematic_for(board) -> str`; `export_package(cli, board, out_dir, runner=subprocess.run) -> str` returning the final package directory path

Four kicad-cli invocations: `pcb export gerbers --board-plot-params` (honours the board's own layer setup), `pcb export drill`, `pcb export pos --format csv`, and `sch export bom` against the sibling schematic — the BOM comes from the schematic because that is where sourcing fields live.

- [ ] **Step 1: Write the failing test**

```python
import os
import tempfile
import unittest
from gate.export import export_package, schematic_for


class TestSchematicFor(unittest.TestCase):
    def test_swaps_the_extension(self):
        self.assertEqual(schematic_for("/p/board.kicad_pcb"), "/p/board.kicad_sch")


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = os.path.join(self.tmp.name, "b.kicad_pcb")
        for path in (self.board, os.path.join(self.tmp.name, "b.kicad_sch")):
            with open(path, "w") as fh:
                fh.write("x")
        self.calls = []

    def runner(self, fail_on=None):
        def _run(cmd, **kwargs):
            self.calls.append(cmd)
            class R:
                pass
            r = R()
            r.returncode = 1 if fail_on and fail_on in " ".join(cmd) else 0
            r.stdout = r.stderr = ""
            if r.returncode == 0 and "-o" in cmd:
                target = cmd[cmd.index("-o") + 1]
                if target.endswith(".csv"):
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    open(target, "w").close()
                else:
                    os.makedirs(target, exist_ok=True)
                    open(os.path.join(target, "plot.gbr"), "w").close()
            return r
        return _run

    def test_produces_a_timestamped_directory(self):
        out = os.path.join(self.tmp.name, "fab")
        package = export_package("kicad-cli", self.board, out, runner=self.runner())
        self.assertTrue(os.path.isdir(package))
        self.assertTrue(package.startswith(out))

    def test_runs_gerbers_drill_pos_and_bom(self):
        export_package("kicad-cli", self.board, os.path.join(self.tmp.name, "fab"),
                       runner=self.runner())
        joined = [" ".join(c) for c in self.calls]
        self.assertTrue(any("export gerbers" in c for c in joined))
        self.assertTrue(any("export drill" in c for c in joined))
        self.assertTrue(any("export pos" in c for c in joined))
        self.assertTrue(any("sch export bom" in c for c in joined))

    def test_a_failure_leaves_no_package_behind(self):
        out = os.path.join(self.tmp.name, "fab")
        with self.assertRaises(Exception):
            export_package("kicad-cli", self.board, out, runner=self.runner(fail_on="drill"))
        self.assertEqual([] if not os.path.isdir(out) else os.listdir(out), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_export -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gate.export'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Atomic fab-package export.

Built in a temp directory and moved into place only on success, so a failure
never leaves something that looks shippable.
"""
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

from gate.kicad import KicadUnavailable


def schematic_for(board: str) -> str:
    return os.path.splitext(board)[0] + ".kicad_sch"


def _run(runner, cmd):
    result = runner(cmd, capture_output=True, text=True)
    if getattr(result, "returncode", 0) != 0:
        raise KicadUnavailable(
            f"{' '.join(cmd[1:4])} failed (exit {result.returncode}): "
            f"{(getattr(result, 'stderr', '') or '').strip()}")


def export_package(cli: str, board: str, out_dir: str, runner=subprocess.run) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    final = os.path.join(out_dir, stamp)
    staging = tempfile.mkdtemp(prefix=".prefab-gate-")
    try:
        _run(runner, [cli, "pcb", "export", "gerbers", "--board-plot-params",
                      "-o", os.path.join(staging, "gerbers"), board])
        _run(runner, [cli, "pcb", "export", "drill", "--format", "excellon",
                      "--excellon-units", "mm", "--generate-map",
                      "-o", os.path.join(staging, "drill"), board])
        _run(runner, [cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                      "--side", "both", "-o", os.path.join(staging, "cpl.csv"), board])
        _run(runner, [cli, "sch", "export", "bom", "--group-by", "",
                      "--fields", "Reference,Value,Footprint,Manufacturer,MPN,LCSC,Datasheet",
                      "-o", os.path.join(staging, "bom.csv"), schematic_for(board)])
        os.makedirs(out_dir, exist_ok=True)
        shutil.move(staging, final)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_export -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/gate/export.py prefab-gate/tests/test_export.py
git commit -m "feat(prefab-gate): export gerbers, drill, CPL and BOM atomically"
```

---

### Task 9: Wire the CLI

**Files:**
- Create: `prefab-gate/scripts/prefab_gate.py`
- Test: `prefab-gate/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces: `main(argv, deps=None) -> int`. `deps` is a dict overriding `locate_cli`, `probe_capability`, `run_drc`, `export_package`, `cli_version` for tests

- [ ] **Step 1: Write the failing test**

```python
import io
import unittest
from contextlib import redirect_stdout
from prefab_gate import main

CLEAN = {"violations": [], "unconnected_items": [], "schematic_parity": []}
BLOCKED = {"violations": [{"type": "courtyards_overlap", "description": "Courtyards overlap",
                           "severity": "error", "items": [{"description": "Footprint TP1"}]}],
           "unconnected_items": [], "schematic_parity": []}


def deps(drc, exported=None, record=None):
    def export(*args, **kwargs):
        if record is not None:
            record.append(args)
        return "/fab/2026-01-01-00-00-00"
    return {"locate_cli": lambda: "kicad-cli", "probe_capability": lambda cli: None,
            "run_drc": lambda cli, board: drc, "export_package": export,
            "cli_version": lambda cli: "10.0.5"}


class TestCli(unittest.TestCase):
    def test_check_on_a_clean_board_exits_zero(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=deps(CLEAN))
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out.getvalue())

    def test_check_on_a_blocked_board_exits_two(self):
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=deps(BLOCKED))
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out.getvalue())

    def test_package_does_not_export_when_blocked(self):
        record = []
        with redirect_stdout(io.StringIO()):
            code = main(["package", "b.kicad_pcb"], deps=deps(BLOCKED, record=record))
        self.assertEqual(code, 2)
        self.assertEqual(record, [])

    def test_package_exports_when_clean(self):
        record = []
        with redirect_stdout(io.StringIO()) as out:
            code = main(["package", "b.kicad_pcb"], deps=deps(CLEAN, record=record))
        self.assertEqual(code, 0)
        self.assertEqual(len(record), 1)
        self.assertIn("2026-01-01-00-00-00", out.getvalue())

    def test_missing_kicad_cli_exits_three(self):
        from gate.kicad import KicadUnavailable

        def boom():
            raise KicadUnavailable("kicad-cli not found")
        d = deps(CLEAN)
        d["locate_cli"] = boom
        with redirect_stdout(io.StringIO()) as out:
            code = main(["check", "b.kicad_pcb"], deps=d)
        self.assertEqual(code, 3)
        self.assertIn("kicad-cli not found", out.getvalue())

    def test_json_flag_emits_machine_readable_output(self):
        import json
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb", "--json"], deps=deps(CLEAN))
        self.assertIs(json.loads(out.getvalue().split("\n\n")[-1])["passed"], True)

    def test_says_so_when_the_refill_modified_the_board(self):
        d = deps(CLEAN)
        hashes = iter(["before", "after"])
        d["board_hash"] = lambda path: next(hashes)
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=d)
        self.assertIn("zone fills", out.getvalue())

    def test_stays_quiet_when_the_board_was_already_filled(self):
        d = deps(CLEAN)
        d["board_hash"] = lambda path: "same"
        with redirect_stdout(io.StringIO()) as out:
            main(["check", "b.kicad_pcb"], deps=d)
        self.assertNotIn("zone fills", out.getvalue())
```

The `deps()` helper above must also supply `"board_hash": lambda path: "same"` by
default, so tests that do not care about refilling stay quiet.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd prefab-gate/scripts && python3 -m unittest tests.test_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prefab_gate'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Pre-fab gate: no fab package without a passing check."""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate.classify import classify                      # noqa: E402
from gate.export import export_package                  # noqa: E402
from gate.kicad import KicadUnavailable, locate_cli, probe_capability, run_drc  # noqa: E402
from gate.manifest import build_manifest, sha256        # noqa: E402
from gate.report import render_json, render_text        # noqa: E402


def _cli_version(cli):
    result = subprocess.run([cli, "version"], capture_output=True, text=True)
    return (result.stdout or "").strip()


DEFAULT_DEPS = {"locate_cli": locate_cli, "probe_capability": probe_capability,
                "run_drc": run_drc, "export_package": export_package,
                "cli_version": _cli_version, "board_hash": sha256}


def main(argv=None, deps=None) -> int:
    d = dict(DEFAULT_DEPS)
    d.update(deps or {})

    parser = argparse.ArgumentParser(prog="prefab_gate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "package"):
        p = sub.add_parser(name)
        p.add_argument("board")
        p.add_argument("--out", default="fab")
        p.add_argument("--json", action="store_true")
        p.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    try:
        cli = d["locate_cli"]()
        d["probe_capability"](cli)
        # --refill-zones --save-board can rewrite the board. Hash it either side so
        # the resulting git diff is expected rather than mysterious.
        before = d["board_hash"](args.board)
        drc = d["run_drc"](cli, args.board)
        if d["board_hash"](args.board) != before:
            print(f"Note: refilling updated the zone fills in {args.board} — "
                  "the board file has been modified and should be committed.\n")
    except KicadUnavailable as exc:
        print(str(exc))
        return 3

    verdict = classify(drc, strict=args.strict)
    print(render_text(verdict))

    code = 0 if verdict.passed else 2
    if verdict.passed and args.command == "package":
        try:
            package = d["export_package"](cli, args.board, args.out)
        except KicadUnavailable as exc:
            print(str(exc))
            return 3
        files = [os.path.join(root, f) for root, _, fs in os.walk(package) for f in fs]
        manifest = build_manifest(args.board, d["cli_version"](cli), verdict, files)
        with open(os.path.join(package, "manifest.json"), "w") as fh:
            json.dump(manifest, fh, indent=2)
        print(f"\nPackage written to {package}")

    if args.json:
        print()
        print(render_json(verdict))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd prefab-gate/scripts && python3 -m unittest discover -s ../tests -t . -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/scripts/prefab_gate.py prefab-gate/tests/test_cli.py
git commit -m "feat(prefab-gate): wire check and package subcommands"
```

---

### Task 10: Package as a plugin and verify against the real board

**Files:**
- Create: `prefab-gate/plugin.json`
- Create: `prefab-gate/skills/prefab-gate/SKILL.md`
- Create: `prefab-gate/README.md`

**Interfaces:**
- Consumes: the CLI from Task 9
- Produces: an installable plugin directory

- [ ] **Step 1: Write plugin.json**

```json
{
  "name": "prefab-gate",
  "version": "0.1.0",
  "description": "Refuses to produce a KiCad fab package from a board that has not passed verification. Runs DRC with zone refill and schematic parity, classifies findings as blocking or cosmetic, and exports gerbers, drill, CPL and BOM only when nothing blocks.",
  "license": "MIT",
  "keywords": ["kicad", "pcb", "drc", "fabrication", "gerber", "hardware"]
}
```

- [ ] **Step 2: Write SKILL.md**

```markdown
---
name: prefab-gate
description: Use before ordering any KiCad PCB - verifies a board with DRC, zone refill and schematic parity, and refuses to export a fab package if anything blocking is found. Triggers on "order this board", "generate gerbers", "fab package", "is this ready to fab", "send to JLCPCB/PCBWay".
---

# Pre-fab gate

Never hand-generate gerbers. Run:

    python3 scripts/prefab_gate.py package <board.kicad_pcb>

Exit codes: `0` clean and packaged · `2` blocked, no files written · `3` kicad-cli missing or too old.

Use `check` instead of `package` to verify without producing files.

## Reading a verdict

Blocking findings stop the export. Cosmetic ones are listed, waved through, and
recorded in the package manifest so you can see later what shipped despite them.

An **unrecognised parity description always blocks** — if you see one, it means
KiCad reworded a message and the classifier needs the new string added. Do not
work around it by exporting by hand.

## What it does not do

It does not replace design review. It checks that the board you have is
internally consistent and manufacturable, not that it is the board you meant.
```

- [ ] **Step 3: Run the full unit suite**

Run: `cd prefab-gate/scripts && python3 -m unittest discover -s ../tests -t . -v`
Expected: all tests PASS

- [ ] **Step 4: Run against the real board and check the acceptance verdict**

Run: `cd prefab-gate/scripts && python3 prefab_gate.py check ../../nes_power_video.kicad_pcb`

Expected — exit code `2`, and exactly these two blocking findings:

```
BLOCK  courtyards_overlap         Footprint TP1, Footprint J3
BLOCK  footprint_symbol_mismatch  Footprint J5
```

with 29 cosmetic: 4 `silk_edge_clearance`, 2 `silk_overlap`, 23 `footprint_symbol_field_mismatch`, and 4 exclude-from-BOM differences on TP1–TP4.

**If the verdict differs, the gate is wrong — stop and investigate before adjusting the expectation.** The counts come from a real DRC run on this board at commit `c37b56b`.

- [ ] **Step 5: Commit**

```bash
git add prefab-gate/plugin.json prefab-gate/skills prefab-gate/README.md
git commit -m "feat(prefab-gate): package as an installable plugin"
```

---

## Notes for the executor

- `sys.path` juggling in `prefab_gate.py` is deliberate: the plugin has to run as a bare script with no installation step, so `gate/` is imported relative to the script's own directory.
- Tests run from `prefab-gate/scripts` so that `gate` and `prefab_gate` are both importable without packaging.
- Do not add pytest. `unittest` is in the standard library; the plugin's whole distribution story depends on having no dependencies.
