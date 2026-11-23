# How well does board inference (trait panel + bars + emblems + ledger + last round) name the fielded units?
# Scored against boards you labelled in tools/label_units.py (fully labelled rounds only, carousels skipped), and
# separately on rounds whose labels explain the trait panel (at most one unread emblem): elsewhere the labels
# miss units the crops didn't catch, so the guess is marked wrong for finding them.
#   python3 -I tools/eval_boards.py [-v]
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "capture"), str(ROOT / "engine")]
import label_units as L  # noqa: E402
from unlocks import infer_boards, load_set  # noqa: E402


def evaluate(verbose=False):
    static = load_set(L.SET)
    if not L.META.exists():
        sys.exit("no labelled crops yet: tools/label_units.py prepare + serve")
    m, lab = json.loads(L.META.read_text()), L.labels()
    short = {r["round"]: sum(b - a for a, b in r.get("short", {}).values()) for r in L.check(m, lab, static)}
    score = {"all": [0] * 3, "consistent": [0] * 3}       # true pos, false pos, false neg, then exact per board
    for rec in sorted({r["rec"] for r in m["rounds"].values()}):
        f = Path(rec) / "state.replay.jsonl"
        states = list(map(json.loads, open(f if f.exists() else Path(rec) / "state.jsonl")))
        tag = Path(rec).name
        for s, (b, _) in zip(states, infer_boards(static, states)):
            rk = f"{tag}/{s['stage']}"
            if rk not in m["rounds"] or s["stage"].endswith("-4"):
                continue
            names = [lab.get(c["id"]) for c in m["crops"].values() if c["round"] == rk and not c["bench"]]
            if not names or None in names:
                continue
            truth = {x for x in names if x != "__skip__"}
            guess = {u["unit"] for u in b or []}
            for k in ("all", "consistent") if short.get(rk, 9) <= 1 else ("all",):
                score[k].append(guess == truth)
                for i, x in enumerate((guess & truth, guess - truth, truth - guess)):
                    score[k][i] += len(x)
            if verbose:
                print(f"  {tag[:16]} {s['stage']}: missed {sorted(truth - guess)} extra {sorted(guess - truth)}")
    for k, (tp, fp, fn, *ex) in score.items():
        print(f"{k:10} {len(ex):2} labelled boards: precision {tp / max(1, tp + fp):.0%}, "
              f"recall {tp / max(1, tp + fn):.0%}, exact {sum(ex)}/{len(ex)}")


if __name__ == "__main__":
    evaluate("-v" in sys.argv)
