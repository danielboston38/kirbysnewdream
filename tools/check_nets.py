#!/usr/bin/env python3
"""Netlist invariant check for Link to Video.

Run this before generating a fab package. Gerbers carry no net information, so
by the time you have them a wrong net is invisible. This checks the KiCad
sources instead: it exports the schematic netlist, reads the PCB's pad nets,
confirms the two agree, and asserts a set of invariants that encode faults this
board has actually shipped with.

The one that matters most: on the fabbed v1 board (PCBWay, 2026-07-16) Q1's
emitter was on /5V together with J4.3, D1.1 and F1.1. The emitter follower was
clamped to the rail, so Q1 saturated into a grounded collector with nothing
limiting the current. It destroyed transistors on every power-up and cost a
week of bench time. ERC and DRC both passed on that board -- neither one can
see that a net is wrong, only that it is consistent. Hence this file.

    python3 tools/check_nets.py [--sch FILE] [--pcb FILE]

Exit status 0 if every invariant holds, 1 otherwise.

Pointed at the v1 sources it reports, correctly:

    FAIL  Q1.1 is NOT on the +5V rail
          (net '/5V'; rail pads found: ['D1.1', 'F1.1', 'J4.3'])

Note that running it against anything older than v2 will also flag R2 and the
U1 eFuse as missing. Those are v2 additions, not faults.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCH = os.path.join(REPO, "nes_power_video.kicad_sch")
DEFAULT_PCB = os.path.join(REPO, "nes_power_video.kicad_pcb")

KICAD_CLI_CANDIDATES = [
    "kicad-cli",
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
]

# Every power net on the board. Q1's emitter and base must never touch any of
# these. F1/U1 pads are included deliberately: /raw_5v and /fused_5v are just as
# wrong a home for the emitter as /5V itself.
RAIL_PADS = {
    "J4.3", "D1.1", "C1.1", "U1.6", "R1.2", "TP3.1", "J5.3",   # /5V
    "F1.1", "U1.1", "U1.3", "C3.1",                            # /fused_5v
    "F1.2", "USB-C1.A9", "USB-C1.B9",                          # /raw_5v
}


def find_kicad_cli():
    for c in KICAD_CLI_CANDIDATES:
        p = shutil.which(c) if os.path.basename(c) == c else (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def sch_nets(sch_path):
    """{net name: sorted [REF.PAD]} exported from the schematic."""
    cli = find_kicad_cli()
    if not cli:
        return None
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "n.net")
        r = subprocess.run(
            [cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, sch_path],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not os.path.exists(out):
            print("  ! kicad-cli netlist export failed:", r.stderr.strip()[:200])
            return None
        text = open(out).read()

    nets, cur = {}, None
    for line in text[text.index("(nets"):].splitlines():
        t = line.strip()
        m = re.match(r'\(name "([^"]*)"\)', t)
        if m and line.startswith("\t\t\t"):
            cur = m.group(1)
            nets[cur] = []
            continue
        m = re.match(r'\(ref "([^"]+)"\)', t)
        if m and cur is not None:
            nets[cur].append([m.group(1), None])
        m = re.match(r'\(pin "([^"]+)"\)', t)
        if m and cur and nets[cur] and nets[cur][-1][1] is None:
            nets[cur][-1][1] = m.group(1)
    return {k: sorted(f"{r}.{p}" for r, p in v) for k, v in nets.items()}


def pcb_nets(pcb_path):
    """{net name: sorted [REF.PAD]} read straight out of the .kicad_pcb."""
    s = open(pcb_path).read()
    nets, i = {}, 0
    while True:
        i = s.find("\n\t(footprint ", i + 1)
        if i < 0:
            break
        depth = 0
        for k in range(i + 1, len(s)):
            if s[k] == "(":
                depth += 1
            elif s[k] == ")":
                depth -= 1
                if depth == 0:
                    break
        blk = s[i:k + 1]
        ref = re.search(r'\(property "Reference" "([^"]*)"', blk)
        if not ref:
            continue
        ref = ref.group(1)
        for pm in re.finditer(r'\(pad "([^"]+)"', blk):
            d2 = 0
            for kk in range(pm.start(), len(blk)):
                if blk[kk] == "(":
                    d2 += 1
                elif blk[kk] == ")":
                    d2 -= 1
                    if d2 == 0:
                        break
            pad = blk[pm.start():kk + 1]
            n = re.search(r'\(net "([^"]*)"\)', pad)
            if n:
                nets.setdefault(n.group(1), []).append(f"{ref}.{pm.group(1)}")
    return {k: sorted(set(v)) for k, v in nets.items()}


def net_of(nets, pad):
    for name, pads in nets.items():
        if pad in pads:
            return name, set(pads)
    return None, set()


def check(nets, label):
    """Assert the invariants. Returns a list of failure strings."""
    fails = []

    def ok(cond, msg):
        print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
        if not cond:
            fails.append(f"[{label}] {msg}")

    # --- Q1 emitter: the v1 fault ------------------------------------------
    ename, epads = net_of(nets, "Q1.1")
    ok(ename is not None, "Q1.1 (emitter) is connected")
    collision = epads & RAIL_PADS
    ok(not collision,
       f"Q1.1 is NOT on the +5V rail  (net {ename!r}; rail pads found: {sorted(collision) or 'none'})")
    ok(epads == {"Q1.1", "C2.1", "R1.1"},
       f"Q1.1 net is exactly Q1.1 + C2.1 + R1.1  (got {sorted(epads)})")

    # --- Q1 collector and base ---------------------------------------------
    cname, _ = net_of(nets, "Q1.2")
    ok(cname == "GND", f"Q1.2 (collector) is GND  (got {cname!r})")

    bname, bpads = net_of(nets, "Q1.3")
    ok(bpads == {"Q1.3", "R2.2"},
       f"Q1.3 (base) goes only to R2.2  (got {sorted(bpads)})")
    ok(not (bpads & RAIL_PADS), f"Q1.3 is NOT on the +5V rail  (net {bname!r})")

    # --- R2 is in series, not a shunt --------------------------------------
    _, r2a = net_of(nets, "R2.1")
    ok("J4.1" in r2a, f"R2.1 reaches J4.1 (video in)  (got {sorted(r2a)})")
    ok(net_of(nets, "R2.1")[0] != net_of(nets, "R2.2")[0],
       "R2 is in series -- its two pads are on different nets")

    # --- power chain: USB-C -> F1 -> U1 eFuse -> rail -> J4.3 --------------
    rname, rpads = net_of(nets, "J4.3")
    ok({"D1.1", "R1.2", "C1.1", "U1.6"} <= rpads,
       f"J4.3 rail carries D1.1, R1.2, C1.1 and U1.6 (eFuse output)  (net {rname!r})")

    fname, fpads = net_of(nets, "F1.1")
    ok({"U1.1", "U1.3", "C3.1"} <= fpads,
       f"F1.1 feeds the eFuse input U1.1/U1.3 and C3.1  (net {fname!r})")
    ok(fname != rname,
       f"F1 is upstream of the eFuse, not on the rail  ({fname!r} != {rname!r})")

    _, rawpads = net_of(nets, "F1.2")
    ok({"USB-C1.A9", "USB-C1.B9"} <= rawpads,
       f"F1.2 is on USB-C VBUS  (got {sorted(rawpads)})")

    # --- output path --------------------------------------------------------
    _, c2b = net_of(nets, "C2.2")
    ok("R5.1" in c2b, f"C2.2 feeds R5.1  (got {sorted(c2b)})")
    _, r5b = net_of(nets, "R5.2")
    ok("J3.2" in r5b, f"R5.2 reaches the video jack J3.2  (got {sorted(r5b)})")

    # --- USB-C sink ---------------------------------------------------------
    for cc, r in (("USB-C1.A5", "R4.1"), ("USB-C1.B5", "R3.1")):
        _, pads = net_of(nets, cc)
        ok(r in pads, f"{cc} has its 5.1k pulldown ({r})  (got {sorted(pads)})")
    ok(net_of(nets, "USB-C1.A5")[0] != net_of(nets, "USB-C1.B5")[0],
       "CC1 and CC2 are separate nets -- shorting them stops the source enabling VBUS")

    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sch", default=DEFAULT_SCH)
    ap.add_argument("--pcb", default=DEFAULT_PCB)
    args = ap.parse_args()

    failures = []

    print("PCB  (%s)" % os.path.basename(args.pcb))
    pcb = pcb_nets(args.pcb)
    failures += check(pcb, "pcb")

    sch = sch_nets(args.sch)
    if sch is None:
        print("\nSCH  skipped -- kicad-cli not found, checked the PCB only")
    else:
        print("\nSCH  (%s)" % os.path.basename(args.sch))
        failures += check(sch, "sch")

        print("\nSCH vs PCB")
        norm = lambda d: {k: v for k, v in d.items() if not k.startswith("unconnected-")}
        a, b = norm(sch), norm(pcb)
        diff = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
        if diff:
            for k in sorted(diff):
                print(f"  FAIL  {k}\n          sch: {a.get(k)}\n          pcb: {b.get(k)}")
                failures.append(f"[sch/pcb] {k} differs")
        else:
            print(f"  PASS  all {len(a)} nets identical")

    print()
    if failures:
        print("FAILED (%d):" % len(failures))
        for f in failures:
            print("  -", f)
        return 1
    print("All invariants hold. Safe to generate a fab package.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
