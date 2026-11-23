"""Line selection: the board to field from your own units that stays strong now AND keeps your chosen
endgame comps (and their unlocks) on track. Post-game/review use: shown live it would be game-state advice.

    python3 -I engine/lines.py TFTSet19 state.json        # best line-keeping board vs strongest-now board
    python3 -I engine/lines.py TFTSet19 --graph           # pivot map: comps sharing units/unlocks with your focus

Score of a board = strength now + lambda(HP) * (line keeping + unlock progress)   (docs/04 PlayNow)
  strength now:  the set's learned board model (engine/board_model.py) if trained, else cost/stars plus
                 learned trait values (PBE-derived for Set 19 until our own crawl)
  line keeping:  per anchor comp, share of its core units on board + progress of its main trait
  unlock progress: anchors' unlocks evaluated on this board; counters whose gate the board satisfies
  lambda(HP):    future weighs less as HP falls (at 20 HP the present dominates)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from plans import build_plans, focus, match  # noqa: E402
from strength import features  # noqa: E402
from unlocks import evaluate, load_set  # noqa: E402

LINE_WEIGHT, UNLOCK_WEIGHT, GATE_BONUS = 1.5, 1.0, 0.5    # ponytail: hand-set, tune on recordings


def strength_fn(static):
    """board [(unit, stars, items|None)] -> strength now (bigger is better; only differences matter)."""
    n = int(static["set"].replace("TFTSet", "")) if static["set"].replace("TFTSet", "").isdigit() else None
    if n is not None:
        import board_model
        m = board_model.load(n)
        if m:
            # in calibrated log-odds of winning (the model's fitted temperature), so the hand-set line weights
            # below keep their meaning when the model is refitted (tools/calibrate.py)
            t = m.get("temperature", 1.0)
            return lambda board: t * board_model.score(m, static, [(u, s, i or []) for u, s, i in board])
    tw = None
    for p in (ROOT / "data" / f"trait_weights_{static['set']}.json",
              ROOT / "data" / "manual" / f"{static['set']}.metatft_trait_weights.json"):
        if p.exists():
            tw = json.loads(p.read_text())
            break

    def generic(board):
        f = features(static, [{"unit": u, "stars": s} for u, s, _ in board])
        traits = sum(tw.get(k[2:], 0) * v for k, v in f.items() if k.startswith("T:")) if tw else 0.05 * f["synergy"]
        return 0.28 * f["gold_value"] + 0.2 * f["carry_stars"] + traits
    return generic


def anchors(static, state, k=3):
    """The comps to steer toward: the player's focus, else well-fitting plans ranked by a cheap expected
    placement (fit x plan placement + rest x 5.0; plans without placement count as 5.0)."""
    if focus(static):
        return focus(static)
    cands = [(p, fit) for p, fit in match(static, state, build_plans(static))[:10] if fit > 0]
    cands.sort(key=lambda x: x[1] * x[0].get("avg_place", 5.0) + (1 - x[1]) * 5.0)
    return [p for p, _ in cands[:k]]


def owned_units(state):
    """[(unit, stars, items|None)]: purchase ledger plus any known board/bench (best copy per unit)."""
    best = {}
    for o in state.get("owned", []):
        best[o["unit"]] = (o["unit"], o["stars"], None)
    for u in state.get("board", []) or []:
        cur = best.get(u["unit"])
        if not cur or u.get("stars", 1) >= cur[1]:
            best[u["unit"]] = (u["unit"], u.get("stars", 1), u.get("items"))
    return list(best.values())


def line_value(static, state, board, anchor_plans):
    """(line keeping, unlock progress) for this board toward the anchors."""
    names = {u for u, _, _ in board}
    f = features(static, [{"unit": u, "stars": s} for u, s, _ in board])
    keep = 0.0
    for p in anchor_plans:
        core = len(names & set(p["core"])) / len(p["core"])
        depth = f.get(f"T:{p['trait']}", 0)
        keep += 0.7 * core + 0.3 * depth
    wanted = {u for p in anchor_plans for u in p["unlocks"]}
    rows = evaluate(static, dict(state, board=[{"unit": u, "stars": s, "items": i} for u, s, i in board],
                                 owned=None, traits=None))
    rules = {u["unit"]: u for u in static["unlocks"]}
    prog = 0.0
    for r in rows:
        if r["unit"] not in wanted or r["status"] in ("UNLOCKED", "BLOCKED", "DEAD"):
            continue
        if r["status"] in ("READY", "NEEDS_LEVEL"):
            prog += 1.0
        elif r["status"] == "PROGRESS" and r.get("target") and isinstance(r.get("value"), (int, float)):
            prog += min(1.0, r["value"] / r["target"])
        gate = ((rules[r["unit"]].get("when") or {}).get("counter") or {})
        if gate.get("requires_unit") in names or (gate.get("requires_trait") and f.get(f"T:{gate['requires_trait']}")):
            prog += GATE_BONUS                       # this board keeps the counter running
    return keep / max(len(anchor_plans), 1), prog / max(len(wanted), 1)


def best_board(static, state, anchor_plans=None, size=None):
    """{"board", "strength", "keep", "unlocks", "score"} for the best line-keeping board, and the same for
    the strongest-now board ("alt"). Greedy fill, then 1-for-1 swaps until no swap helps."""
    pool = owned_units(state)
    size = min(size or state.get("level") or 8, len(pool))
    anchor_plans = anchor_plans if anchor_plans is not None else anchors(static, state)
    strength = strength_fn(static)
    lam = max(0.2, min(1.0, (state.get("hp") or 100) / 100))

    def parts(b):
        s = strength(b)
        keep, unl = line_value(static, state, b, anchor_plans) if anchor_plans else (0.0, 0.0)
        return {"strength": s, "keep": keep, "unlocks": unl,
                "score": s + lam * (LINE_WEIGHT * keep + UNLOCK_WEIGHT * unl)}

    def climb(key):
        board = []
        for _ in range(size):                                        # greedy fill
            board.append(max((u for u in pool if u not in board), key=lambda u: parts(board + [u])[key]))
        improved = True
        while improved:                                              # swaps
            improved = False
            cur = parts(board)[key]
            for i in range(len(board)):
                for u in pool:
                    if u in board:
                        continue
                    nb = board[:i] + [u] + board[i + 1:]
                    if parts(nb)[key] > cur + 1e-9:
                        board, cur, improved = nb, parts(nb)[key], True
        return dict(parts(board), board=board)

    if size == 0:
        return None
    best, alt = climb("score"), climb("strength")
    best["alt"], best["anchors"], best["lambda"] = alt, [p["id"] for p in anchor_plans], lam
    best["why"] = explain(best, alt)
    return best


def explain(best, alt):
    """Doc 01 style trade-off: what the line board fields instead of the strongest board, and what it buys."""
    a, b = {u for u, _, _ in best["board"]}, {u for u, _, _ in alt["board"]}
    if a == b:
        return "the strongest board already keeps your line"
    ds, dk, du = best["strength"] - alt["strength"], best["keep"] - alt["keep"], best["unlocks"] - alt["unlocks"]
    return (f"field {', '.join(sorted(a - b))} over {', '.join(sorted(b - a))}: "
            f"{ds:+.2f} strength now, {dk:+.0%} line keeping, {du:+.2f} unlock progress")


def pivots(static, plan, plans, k=3):
    """Comps sharing the most core units / unlocks with `plan`: pivots that keep units and progress."""
    out, real = [], any("avg_place" in q for q in plans)
    for q in plans:
        if q["id"] == plan["id"] or q["trait"] == plan["trait"] or (real and "avg_place" not in q):
            continue                       # same main trait = a variant, not a pivot; prefer real comps
        shared = set(plan["core"]) & set(q["core"])
        unl = set(plan["unlocks"]) & set(q["unlocks"])
        if shared or unl:
            out.append((len(shared) + len(unl), q, sorted(shared), sorted(unl)))
    # a placement point better than 5.0 counts like one more shared unit: don't pivot into a weak comp
    return sorted(out, key=lambda x: -(x[0] + 5.0 - x[1].get("avg_place", 5.0)))[:k]


if __name__ == "__main__":
    static = load_set(sys.argv[1])
    if sys.argv[2:3] == ["--graph"]:
        plans = build_plans(static)
        for p in focus(static) or [p for p in plans if "avg_place" in p][:5] or plans[:5]:
            print(f"{p['id']}")
            for n, q, shared, unl in pivots(static, p, plans):
                place = f" (PBE {q['avg_place']:.2f})" if "avg_place" in q else ""
                print(f"   -> {q['id']}{place}: shares {', '.join(shared) or '-'}" + (f"; unlocks {', '.join(unl)}" if unl else ""))
        sys.exit()
    state = json.loads(Path(sys.argv[2]).read_text())
    r = best_board(static, state)
    if not r:
        sys.exit("no owned units in this state")
    fmt = lambda b: ", ".join(f"{u}{'*' * s}" for u, s, _ in b)   # noqa: E731
    print(f"anchors: {', '.join(r['anchors']) or '-'}   (lambda {r['lambda']:.2f} from HP)")
    print(f"line board:      {fmt(r['board'])}\n   strength {r['strength']:.2f}  keep {r['keep']:.0%}  unlocks {r['unlocks']:.2f}")
    print(f"strongest board: {fmt(r['alt']['board'])}\n   strength {r['alt']['strength']:.2f}  keep {r['alt']['keep']:.0%}  unlocks {r['alt']['unlocks']:.2f}")
    print("why:", r["why"])
