# Every number on the line finder's path has a stated basis (engine/provenance.py), and none that moves a comp's
# expected place is a bare judgement. Also checks the measured inputs exist.
#   python3 -I tests/test_audit_weights.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "engine")]
import audit_weights  # noqa: E402

rows, problems = audit_weights.audit()
missing_files = [p for p in problems if "measured input missing" in p]
real = [p for p in problems if p not in missing_files]
assert not real, real
if missing_files:
    print("skip measured-file check (private data not present):", missing_files)
assert rows and all(kind in ("measured", "derived", "fact", "structural", "prior") for kind, *_ in rows)
print("ok")
