"""Audit the line finder's numbers: every module-level constant in the audited modules must have a stated basis in
engine/provenance.py, and none that moves a comp's expected place may be a bare judgement ('prior').

    python3 -I tools/audit_weights.py            # table of constants by basis, then any problems
"""
import ast
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from provenance import MEASURED_FILES, P  # noqa: E402

MODULES = ("linefinder", "augvalue", "power", "survival")


def constants(module):
    tree = ast.parse((ROOT / "engine" / f"{module}.py").read_text())
    out = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            names = [t] if isinstance(t, ast.Name) else list(t.elts) if isinstance(t, ast.Tuple) else []
            out += [n.id for n in names if isinstance(n, ast.Name) and n.id.isupper() and not n.id.startswith("_")]
    return out


def audit():
    problems, rows = [], []
    for m in MODULES:
        for c in constants(m):
            key = f"{m}.{c}"
            if key not in P:
                problems.append(f"{key}: no stated basis in engine/provenance.py")
                continue
            kind, moves, why = P[key]
            rows.append((kind, moves, key, why))
            if moves and kind not in ("measured", "derived", "fact", "structural"):
                problems.append(f"{key}: moves the expected place but is a {kind}")
    for f in MEASURED_FILES:
        if not (ROOT / f).exists():
            problems.append(f"{f}: measured input missing (run its script)")
    return rows, problems


def main():
    rows, problems = audit()
    for kind, moves, key, why in sorted(rows):
        print(f"{kind:10} {'MOVES PLACE' if moves else '           '} {key:28} {why}")
    print("\nby basis:", dict(Counter(k for k, *_ in rows)))
    print("measured inputs read at run time:")
    for f, why in MEASURED_FILES.items():
        print(f"  {'ok ' if (ROOT / f).exists() else 'MISSING'} {f}: {why}")
    print("\nproblems:" if problems else "\nno problems: every number that moves an expected place is measured or derived from a measurement")
    for p in problems:
        print("  " + p)
    return problems


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
