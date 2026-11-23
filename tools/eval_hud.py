"""HUD reader vs hand-read truth: per field, how often the reader is right, wrong, silent where the screen
showed a value (missed), or reads a value the screen didn't show (phantom). Truth: one JSON line per frame
(t = the frame's time in rows.jsonl.gz; fields as read off the screen, null where not shown), made by
reading zoomed crops of sampled frames without looking at the reader's output.

    python3 -I tools/eval_hud.py data/raw/labels/hud/<game>.jsonl recordings/<dir> [-v]
"""
import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "capture")]
from hud import counter_targets, read  # noqa: E402
from record import same_name  # noqa: E402
from unlocks import load_set  # noqa: E402

SCALARS = (("stage", "t"), ("level", "level"), ("xp", "xp"), ("gold", "gold"), ("streak", "streak_n"), ("hp", "hp"))


def outcome(truth, got):
    if truth is None:
        return "phantom" if got is not None else None
    return "missed" if got is None else "right" if got == truth else "wrong"


def compare(label, r):
    """[(field, outcome, detail)] for one frame: scalars, then per trait / shop slot / lobby player."""
    out = []
    for f, k in SCALARS:
        got = r.get(k)
        got = list(got) if isinstance(got, tuple) else got
        if f == "streak" and label.get("streak") == 0 and got is None:
            got = 0                                    # no streak shows as 0 or nothing: both mean none
        o = outcome(label.get(f), got)
        if o:
            out.append((f, o, f"{label.get(f)} read {got}"))
    mine = {x["name"]: x for x in r.get("traits") or []}
    for x in label.get("traits") or []:
        g = mine.pop(x["name"], None)
        o = "missed" if g is None else "right" if g["count"] == x["count"] and not g.get("count_is_lower_bound") \
            else "unsure" if g["count"] is None or g.get("count_is_lower_bound") else "wrong"
        out.append(("trait", o, f"{x['name']} {x['count']} read {g and g['count']}"))
    out += [("trait", "phantom", f"{n} {g['count']} not on screen") for n, g in mine.items()
            if label.get("traits")]                     # only where the panel was readable at all
    if label.get("shop") is not None:
        shop = {s["slot"]: s["unit"] for s in r.get("shop") or []}
        for k, unit in enumerate(label["shop"], 1):
            o = outcome(unit, shop.get(k))
            if o:
                out.append(("shop", o, f"slot {k} {unit} read {shop.get(k)}"))
    lob = dict(r.get("lobby") or {})
    for name, hp in (label.get("lobby") or {}).items():
        n = next((m for m in lob if same_name(name, [m])), None)
        got = lob.pop(n) if n else None
        out.append(("lobby", outcome(hp, got), f"{name} {hp} read {got}"))
    return out


def evaluate(static, labels, rows_path):
    want = {lab["t"]: lab for lab in labels}
    targets, transform, rows = counter_targets(static["unlocks"]), None, []
    with gzip.open(rows_path, "rt") as f:
        for line in f:
            d = json.loads(line)
            r = read(d["rows"], static["units"], static["traits"], targets=targets, transform=transform)
            transform = r["quality"]["transform"] or transform
            if d["t"] in want:
                rows += [(want[d["t"]], o) for o in compare(want[d["t"]], r)]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels", type=Path)
    ap.add_argument("recording", type=Path)
    ap.add_argument("--set", default="TFTSet19")
    ap.add_argument("-v", action="store_true", help="list every miss")
    a = ap.parse_args()
    labels = [json.loads(x) for x in a.labels.read_text().splitlines() if x.strip()]
    res = evaluate(load_set(a.set), labels, a.recording / "rows.jsonl.gz")
    by = {}
    for _, (f, o, _) in res:
        by.setdefault(f, Counter())[o] += 1
    print(f"{len(labels)} frames; per field: right / shown on screen (wrong, missed, unsure = trait named but its count "
          f"unread or only a lower bound), phantom reads")
    for f, c in by.items():
        shown = c["right"] + c["wrong"] + c["missed"] + c["unsure"]
        print(f"  {f:7} {c['right']:3}/{shown:<3} {100 * c['right'] / shown if shown else 0:5.1f}%  "
              f"(wrong {c['wrong']}, missed {c['missed']}" + (f", unsure {c['unsure']}" if c["unsure"] else "")
              + f"), phantom {c['phantom']}")
    if a.v:
        for lab, (f, o, detail) in res:
            if o != "right":
                print(f"  {lab['frame']} {lab.get('stage')} {f} {o}: {detail}")


if __name__ == "__main__":
    main()
