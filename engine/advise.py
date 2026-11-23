"""Per-round advice from what the screen showed (post-game only, docs/POLICY.md): the line to aim for and how
contested it is by the boards you scouted, which shop cards to buy for it, what your held components should
become, and which augment fit. tools/eval_advice.py scores it against what the player actually did.

    python3 -I engine/advise.py TFTSet19 recordings/<dir>/state.jsonl

What it can see: your trait panel, the shop (every card offered in the round), the purchase ledger (copies
bought), held components, augment offers, and other players' trait panels while you scout them. What it
can't: units on other boards except through their panels, star levels except through the ledger, and which
items suit a Set 19 champion (best-in-slot tables come from Riot match data after launch).
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_model  # noqa: E402
from augments import catalog, review_offers  # noqa: E402
from plans import build_plans, focus, match  # noqa: E402
from reach import shop_reach  # noqa: E402
from review import recipes  # noqa: E402
from unlocks import infer_board, infer_boards, load_set, stage_key  # noqa: E402

SCOUT_ROUNDS = 6       # a scouted board still counts this many rounds later (comps change slowly)
COPIES_PER_BOARD = 3   # ponytail: copies of a unit on a scouted board (a 2-star) from stage 3; 1 before
FALLBACK_PLACE = 5.0   # placement when a line isn't reached (as plans.py); fit on recordings
LINE_CANDIDATES = 6    # best-fitting plans priced per round (a shop simulation each, ~0.2 s)
LATE_MIN_FIT = 0.5     # ponytail: from stage 4 a line needs half its core held (strong players don't pivot
                       # late to a 40% line; the reach simulation ignores the weak boards in between)
FINAL_LEVEL = {"Fast 9": 9, "Fast 8": 8, "Standard": 8}    # MetaTFT styles; "lvl N" = reroll at N
MIN_HOLDER_PLAY = 0.001  # artifact holders under 0.1% of a unit's games are noise (one Katarina: avg place 1.00)
MAX_ARTIFACT_GAIN = 1.0  # places one artifact can be worth to a line
ROOT = Path(__file__).resolve().parent.parent


def artifacts(set_name):
    """MetaTFT artifact stats (private file, gitignored): {name: {"change": places, "holders": {unit: change}}}."""
    f = ROOT / "data" / "manual" / f"{set_name}.metatft_artifacts.json"
    if not f.exists():
        return {}
    return {a["name"]: {"change": a["place_change"], "holders": {h["unit"]: h["place_change"] for h in a["holders"]
                                                                 if h["play_rate"] >= MIN_HOLDER_PLAY}}
            for a in json.loads(f.read_text())["artifacts"]}


def line_units(plan):
    return set(plan["core"]) | set(plan.get("flex", [])) | set(plan.get("carries", [])) if plan else set()


def artifact_gain(art, units):
    """(places an artifact is worth on its best holder among `units`, that holder): MetaTFT's best holders."""
    best = min(((c, u) for u, c in art["holders"].items() if u in units), default=(0.0, None))
    return min(MAX_ARTIFACT_GAIN, max(0.0, -best[0])), best[1]


def held_items(state):
    """Items you hold: the bench, and items read under your units' health bars."""
    return set(state.get("items_held") or []) | {i for u in state.get("units") or [] for i in u.get("items") or []}
BUY_AT = 2.0           # buy score from which a card is worth buying (scored against strong players' buys)


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def lobby_boards(static, states, i):
    """Other players' boards scouted in the last SCOUT_ROUNDS rounds up to round i, the newest reading of
    each (alike = half their trait names shared): [(stage, panel, inferred units)]."""
    seen = []
    for s in reversed(states[max(0, i - SCOUT_ROUNDS + 1):i + 1]):
        for panel in s.get("scouted") or []:
            names = {x["name"] for x in panel}
            if any(jaccard(names, {x["name"] for x in p}) >= 0.5 for _, p, _ in seen):
                continue
            board, _ = infer_board(static, {"traits": panel, "level": s.get("level") or 8, "unlocked": []})
            seen.append((s["stage"], panel, [u["unit"] for u in board or []]))
    return seen


def lines(static, state, plans, contested, k=3, arts=None):
    """[(plan, fit, reach, contested share of its core, expected place)], best first. reach: the share of
    the comp's core you can expect to hold by its deadline: core units held now plus those the shop
    simulation (reach.shop_reach: your level, gold, the odds by level, the pool minus copies on scouted
    boards) finds, by the time its players reach its final level on MetaTFT (fast 9 ~5-2, rerolls when
    they roll; else 4-5), at least 3 rounds from now. A share, not P(all of it): with every core unit
    required, every comp read ~0% in stage 3 and the ranking was noise. Expected place = reach x the
    comp's placement + the rest x FALLBACK_PLACE, minus what artifacts you hold are worth on the comp's units
    (MetaTFT's best holders: Lich Bane on Ziggs -1.22 places). Focused comps (plans.py --focus) come first."""
    held = [arts[i] for i in held_items(state) if i in (arts or {})]
    chosen = {p["id"] for p in focus(static) or []}
    stage_n = stage_key(state["stage"])[0]
    copies = {u: n * (COPIES_PER_BOARD if stage_n >= 3 else 1) for u, n in contested.items()}
    n = list(stage_key(state["stage"]))
    n[1] += 3
    if n[1] > 7:
        n = [n[0] + 1, n[1] - 7]
    soon = f"{n[0]}-{n[1]}"
    floor = LATE_MIN_FIT if stage_n >= 4 else 0
    out = []
    cands = [x for x in match(static, state, plans) if "avg_place" in x[0] and x[1] > floor]
    for p, fit in cands[:LINE_CANDIDATES]:
        style = p.get("style") or ""
        final = FINAL_LEVEL.get(style) or (int(style.split()[-1]) if style.split()[-1:] and style.split()[-1].isdigit() else 8)
        by = max((p.get("level_by") or {}).get(final) or "4-5", soon, key=stage_key)
        have = {o["unit"] for o in state.get("owned", [])} | {u["unit"] for u in state.get("board") or []}
        need = [u for u in p["core"] if u not in have]
        found = shop_reach(static, dict(state, contest=copies), {u: 1 for u in need}, {}, lambda c: False, by,
                           trials=150, value=lambda c: sum(1 for u in need if c.get(u)) / len(need)
                           )["standard"] if need else 0.0
        reach_p = (len(p["core"]) - len(need) + found * len(need)) / len(p["core"])
        share = sum(1 for u in p["core"] if contested.get(u)) / len(p["core"])
        place = reach_p * p["avg_place"] + (1 - reach_p) * FALLBACK_PLACE \
            - sum(artifact_gain(a, line_units(p))[0] for a in held)
        out.append((p, fit, reach_p, share, place - (10 if p["id"] in chosen else 0)))
    return sorted(out, key=lambda x: x[4])[:k]


def buys(static, state, board, plan, contested):
    """Cards offered this round, scored for your board and line: [(unit, score, reasons)], best first.
    What strong players buy (ledger, 2 recorded games): copies of units they hold (toward 2-star), and first
    copies that add to their active traits (early boards; 4-5 costs from stage 4 for the final board) more
    than units from a stored comp list."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    owned = {o["unit"]: o["copies"] for o in state.get("owned", [])}
    fielded = {u["unit"] for u in board or []}
    core, flex = set(plan["core"]) if plan else set(), set(plan.get("flex", [])) if plan else set()
    carries, stage_n = set(plan["carries"]) if plan else set(), stage_key(state["stage"])[0]
    panel = {x["name"] for x in state.get("traits", []) if x.get("active")}
    traits = {u["name"]: set(u["traits"]) for u in static["units"]}
    level = state.get("level") or 0
    early = {u for lv, us in ((plan or {}).get("early") or {}).items() if lv in (level, level + 1) for u in us}
    out = []
    for u in state.get("shop_seen") or [x["unit"] for x in state.get("shop", [])]:
        if u not in cost:
            continue
        c = owned.get(u, 0) or (1 if u in fielded else 0)
        shared = len(traits[u] & panel)
        score, why = 0.0, []
        if c in (1, 2):
            score, why = score + 2, why + [f"{c} cop{'y' if c == 1 else 'ies'}: toward 2-star"]
        elif 3 <= c < 9 and (u in carries or u in core or (plan or {}).get("roll_level")):
            score, why = score + 1.5, why + [f"{c} copies: toward 3-star"]
        if u in core:
            score, why = score + 2, why + ["core of the line"]
        elif u in flex:
            score, why = score + 1, why + ["flex slot of the line"]
        if u in early and u not in core:
            score, why = score + 1, why + ["on the line's early board"]
        if not c and shared:
            late = stage_n >= 4 and cost[u] >= 4
            score, why = score + shared + (1 if late else 0), why + [f"adds to {shared} active trait(s)"
                                                                     + (", a late-game cost" if late else "")]
        if contested.get(u):
            score, why = score - 0.5 * contested[u], why + [f"on {contested[u]} scouted board(s)"]
        if stage_n >= 4 and not c and not shared and u not in core | flex:
            score, why = score - 1, why + ["fits nothing you play, late"]
        out.append((u, round(score, 2), why))
    return sorted(out, key=lambda x: -x[1])


def item_choice(state, plan, arts):
    """The round's item choice ranked for the line: [(card, places it's worth, why)]. Artifacts by their best
    holder among the line's units (else their average effect); then items MetaTFT lists on the line's
    carries, and components that make one with a component you hold; the rest are unranked."""
    listed = {it: c for c in (plan or {}).get("carries", []) for it in (plan.get("items") or {}).get(c, [])}
    comps, build = recipes()
    held = [i for i in held_items(state) if i in comps]
    out = []
    for card in state.get("item_offer") or []:
        makes = next(((build[frozenset((card, h))], h) for h in held if build.get(frozenset((card, h))) in listed), None)
        if card in comps and makes:
            out.append((card, 0.0, f"with your {makes[1]} makes {makes[0]}, listed for {listed[makes[0]]}"))
            continue
        if card in arts:
            gain, holder = artifact_gain(arts[card], line_units(plan))
            out.append((card, round(gain, 2), f"on {holder}: {-gain:+.2f} places" if holder else
                        f"no best holder in your line (avg {arts[card]['change']:+.2f})"))
        elif card in listed:
            out.append((card, 0.0, f"listed for {listed[card]}"))
        else:
            out.append((card, -1.0, ""))
    return sorted(out, key=lambda x: (-x[1], x[2] == ""))


def items(state, plan, bis):
    """Completed items your held components make: [(item, component, component, note)], those a carry of
    the line uses first: the items MetaTFT lists on the comp's carries, else Riot match data's best-in-slot."""
    comps, build = recipes()
    held = [i for i in state.get("items_held") or [] if i in comps]
    want = {}
    for carry in (plan or {}).get("carries", []):
        for it in (plan.get("items") or {}).get(carry) or bis.get(carry, ()):
            want.setdefault(it, carry)
    out = []
    for k, a in enumerate(held):
        for b in held[k + 1:]:
            it = build.get(frozenset((a, b)))
            if it:
                out.append((it, a, b, f"for {want[it]}" if it in want else ""))
    return sorted(out, key=lambda x: not x[3])


def advise(static, states):
    """Per round: {"stage", "lines", "lobby", "buy", "skip", "items", "augment"}. Each round is judged from
    the spot before you acted in it: last round's panel, board and copies owned, this round's shops."""
    plans, cat, arts = build_plans(static), catalog(static["set"]), artifacts(static["set"])
    n = int(static["set"].replace("TFTSet", "")) if static["set"].replace("TFTSet", "").isdigit() else None
    model = board_model.load(n) if n else None
    bis = (model or {}).get("bis") or {}
    boards = [s.get("board") or b for s, (b, _) in zip(states, infer_boards(static, states))]
    picks = {a["stage"]: a for a in states[-1].get("augment_offers") or []} if states else {}   # picks show late
    out = []
    for i, s in enumerate(states):
        if stage_key(s["stage"]) < (2, 1) or not i:
            continue
        prev = states[i - 1]
        pre = dict(s, owned=prev.get("owned", []), traits=prev.get("traits", []), board=boards[i - 1])
        lobby = lobby_boards(static, states, i)
        contested = Counter(u for _, _, units in lobby for u in units)
        ranked = lines(static, pre, plans, contested, arts=arts)
        plan = ranked[0][0] if ranked else None
        scored = buys(static, pre, boards[i - 1], plan, contested)
        aug = None
        if s["stage"] in picks and plan:
            r = review_offers(static, {"augment_offers": [picks[s["stage"]]]}, [p for p, *_ in ranked[:2]], cat)[0]
            aug = {"best": r["cards"][0]["name"] if r["cards"] else None, "picked": r["picked"],
                   "cards": [(c["name"], c["fit"]) for c in r["cards"]]}
        out.append({"stage": s["stage"], "lines": [(p["id"], fit, rp, share, pl) for p, fit, rp, share, pl in ranked],
                    "lobby": [(st, [x["name"] for x in panel if x.get("active")][:3], units) for st, panel, units in lobby],
                    "buy": [x for x in scored if x[1] >= BUY_AT], "skip": [x for x in scored if x[1] < BUY_AT],
                    "items": items(s, plan, bis), "augment": aug, "item_choice": item_choice(s, plan, arts)})
    return out


def main():
    static = load_set(sys.argv[1])
    states = [json.loads(x) for x in Path(sys.argv[2]).read_text().splitlines() if x.strip()]
    for r in advise(static, states):
        line = ", ".join(f"{pid} (fit {fit:.0%}, reach {rp:.0%}, exp. place {pl:.1f}"
                         + (f", {share:.0%} contested)" if share else ")") for pid, fit, rp, share, pl in r["lines"][:2])
        print(f"{r['stage']:5} line: {line or '-'}")
        if r["buy"] or r["skip"]:
            print("      buy: " + (", ".join(f"{u} ({'; '.join(w)})" for u, _, w in r["buy"]) or "nothing")
                  + "   skip: " + ", ".join(u for u, _, _ in r["skip"]))
        for it, a, b, note in r["items"][:2]:
            print(f"      items: {a} + {b} = {it}" + (f" ({note})" if note else ""))
        if r["item_choice"]:
            best = r["item_choice"][0]
            print("      item choice: " + (f"{best[0]} ({best[2]})" if best[2] else "no pick for this line") + "; offered "
                  + ", ".join(c for c, _, _ in r["item_choice"]))
        if r["augment"]:
            a = r["augment"]
            print(f"      augment: best fit {a['best']}" + (f"; you took {a['picked']}" if a["picked"] else ""))
        for st, top, units in r["lobby"]:
            if st == r["stage"]:
                print(f"      scouted: a board with {', '.join(top)} ({', '.join(units[:5])}...)")


if __name__ == "__main__":
    main()
