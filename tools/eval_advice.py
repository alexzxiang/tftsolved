"""How often the advisor (engine/advise.py) agrees with what the recorded player did, against simple baselines.
Recorded games are strong players' VODs, so agreement measures "plays like a strong player", not optimal
play; it catches advice that is plainly off.
  buys:     of the cards the purchase ledger saw bought from this round's shops, the share the advisor said
            to buy (recall), and the share of its picks that were bought (precision). Baselines: buy only
            units you already own copies of ("pairs"), and a random card ("random" = bought / offered).
  line:     from stage 3, how often the top line's trait is one the game ended on (an active trait with 3+
            units in the last 3 panels read). Baseline: your biggest active trait at the time.
  augments: the best-fitting card is the one taken, where the pick is known (random = 1 in 3).

    python3 -I tools/eval_advice.py [recordings/<dir> ...]     # default: every recorded game, each once
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from advise import advise  # noqa: E402
from fights import games  # noqa: E402
from plans import build_plans  # noqa: E402
from unlocks import load_set, stage_key  # noqa: E402


def bought(prev, s):
    """Units whose copies the ledger saw rise this round."""
    a = {o["unit"]: o["copies"] for o in prev.get("owned", [])}
    return {o["unit"] for o in s.get("owned", []) if o["copies"] > a.get(o["unit"], 0)}


def top_trait(s):
    act = [x for x in s.get("traits", []) if x.get("active") and not x.get("carried")]
    return max(act, key=lambda x: x.get("count") or 0)["name"] if act else None


def score(static, states):
    adv = {r["stage"]: r for r in advise(static, states)}
    plans = build_plans(static)
    # the main traits of the last 3 rounds whose panel was read (one read can be partial: a collapsed panel)
    read = [s for s in states if any(not x.get("carried") for x in s.get("traits", []))][-3:]
    final = {x["name"] for s in read for x in s["traits"] if x.get("active") and (x.get("count") or 0) >= 3}
    c = Counter()
    for prev, s in zip(states, states[1:]):
        r = adv.get(s["stage"])
        if not r:
            continue
        offered = set(s.get("shop_seen") or [])
        got = bought(prev, s) & offered
        rec = {u for u, _, _ in r["buy"]}
        pairs = {o["unit"] for o in prev.get("owned", [])} & offered
        c["bought"] += len(got)
        c["offered"] += len(offered)
        for name, picks in (("advisor", rec), ("pairs", pairs)):
            c[f"{name} hits"] += len(got & picks)
            c[f"{name} picks"] += len(picks)
        if stage_key(s["stage"]) >= (3, 1) and r["lines"]:
            top = next(p for p in plans if p["id"] == r["lines"][0][0])["trait"]
            c["line rounds"] += 1
            c["line hits"] += top in final
            c["now hits"] += top_trait(prev) in final
        if r["augment"] and r["augment"]["picked"]:
            c["augments"] += 1
            c["augment hits"] += r["augment"]["best"] == r["augment"]["picked"]
    return c, final


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def main():
    static = load_set("TFTSet19")
    dirs = [Path(d) for d in sys.argv[1:]] or sorted(d for d in (ROOT / "recordings").iterdir() if d.is_dir())
    total = Counter()
    for name, states in games(dirs).items():
        c, final = score(static, states)
        total += c
        print(f"{name}: ended on {', '.join(sorted(final))}; bought {c['bought']} of {c['offered']} cards offered")
    t = total
    print(f"buys      advisor: recall {pct(t['advisor hits'], t['bought'])}, precision {pct(t['advisor hits'], t['advisor picks'])}"
          f" ({t['advisor picks']} picks) | pairs-only: recall {pct(t['pairs hits'], t['bought'])}, precision "
          f"{pct(t['pairs hits'], t['pairs picks'])} | random card: precision {pct(t['bought'], t['offered'])}")
    print(f"line      top line on the final trait in {pct(t['line hits'], t['line rounds'])} of {t['line rounds']} rounds "
          f"from 3-1 | biggest active trait: {pct(t['now hits'], t['line rounds'])}")
    print(f"augments  best fit taken {t['augment hits']} of {t['augments']} known picks (random: 1 in 3)")


if __name__ == "__main__":
    main()
