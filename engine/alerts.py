"""Unlock alerts for review mode: Free, Start now, Closing, Dead.

    python3 -I engine/alerts.py TFTSet19 game.jsonl [deadline]     # one state per line, oldest first

Only unlocks that fit the board (share a trait with a fielded or benched unit), are listed in
state["targets"], or have a stage-2 window (Seraphine) are considered. Closing and no-path Dead alerts
are limited to targets and counters, so chase unlocks you aren't pursuing stay quiet. Each alert is reported when it first appears or
changes type, not every round. Deadline (default 5-1) is the stage reachability is measured against.

Extra state keys: "bench" (units like "board"), "item_bench" (list of item or component names).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reach import reach                       # noqa: E402
from unlocks import Board, load_set, stage_key, with_prev_boards  # noqa: E402

CLOSING_BELOW = 0.5     # in-progress unlock under this chance by the deadline
ROLL_GAIN = 0.25        # roll-now beats standard line by this much -> worth flagging


def relevant(static, state, b):
    owned = list(b.fielded) + list(b.bench)
    traits = {t for n in owned for t in b.units.get(n, {}).get("traits", [])}
    traits |= {x["name"] for x in state.get("traits", []) if x.get("count")}   # HUD trait panel
    out = set(state.get("targets", []))
    for u in static["unlocks"]:
        when = u.get("when") or {}
        if "window" in when or traits & set(b.units.get(u["unit"], {}).get("traits", [])):
            out.add(u["unit"])
    return out


def free_action(u, r, state, b):
    """One cheap action that completes the condition, or None."""
    (kind, a), = u["when"].items()
    items = state.get("item_bench", [])
    if kind == "items_on" and r["value"] == a["n"] - 1 and items:
        holder = max((n for n in b.fielded if b.has_trait(n, a["traits"])),
                     key=lambda n: len(b.fielded[n].get("items") or []), default=None)
        return f"put one more item on {holder}" if holder else None
    if kind == "unit_state" and items and a.get("items"):
        for n in a["units"]:
            x = b.fielded.get(n)
            if x and x.get("items") is not None and x.get("stars", 1) >= a["stars"] and len(x["items"]) == a["items"] - 1:
                return f"put an item on {n}"
    if kind == "window" and r["status"] == "PROGRESS" and (state.get("gold") or 0) >= 2 * (a["n"] - r["value"]):
        return f"reroll {a['n'] - r['value']} more times before {a['deadline']} ({2 * (a['n'] - r['value'])} gold)"
    if kind in ("front_rows_max", "beach_pop_hex_each_cost") and r["status"] == "LOCKED":
        return "reposition for one combat (pick a round you can afford to lose)"
    return None


def alerts(static, state, deadline="5-1"):
    if stage_key(state["stage"]) >= stage_key(deadline):     # past the deadline: look to the end of the game
        deadline = "7-1"
    if not state.get("targets") and static["traits"] and "kind" in static["traits"][0]:
        from plans import targets                       # no targets set: use the plans the board fits
        state = dict(state, targets=targets(static, state))
    b = Board(static, state)
    rules = {u["unit"]: u for u in static["unlocks"]}
    rows = reach(static, state, deadline, only=relevant(static, state, b))
    bench = b.bench
    out = []
    for r in rows:
        u, name = rules[r["unit"]], r["unit"]
        when = u.get("when") or {}
        if r["status"] in ("UNLOCKED", "READY") or not when:
            continue
        if r["status"] in ("DEAD", "BLOCKED"):
            out.append((name, "DEAD", r["detail"]))
            continue
        act = free_action(u, r, state, b)
        if act:
            out.append((name, "FREE", act))
            continue
        gate = (when.get("counter") or {}).get("requires_unit")
        if gate and gate not in b.fielded and gate in bench:
            out.append((name, "START NOW", f"field {gate} from your bench: its counter only runs while fielded"))
            continue
        p = r["p"]
        if isinstance(p, dict) and p["roll_now"] - p["standard"] >= ROLL_GAIN and name in state.get("targets", []):
            out.append((name, "START NOW", f"rolling down now: {p['standard']:.0%} -> {p['roll_now']:.0%} by {deadline}"))
            continue
        best = max(p.values()) if isinstance(p, dict) else p
        if r["kind"] in ("level", "save"):
            continue                                    # only late for this deadline, not lost
        if r["kind"] != "counter" and name not in state.get("targets", []):
            continue                                    # chance alerts only for chosen targets and counters
        if best is not None and best == 0 and r["status"] != "LOCKED":
            # off pace, not dead: DEAD is reserved for closed windows and exclusive unlocks taken
            out.append((name, "OFF PACE", f"under 1% by {deadline}: {r['why']}"))
        elif best is not None and best < CLOSING_BELOW and r["status"] == "PROGRESS":
            pct = f"{best:.0%}" if best >= 0.01 else "<1%"
            out.append((name, "CLOSING", f"{pct} by {deadline}: {r['why']}"))
    return out


def review(static, states, deadline="5-1"):
    """[(stage, [(unit, type, message)])] with each alert reported once per type change."""
    last, timeline, hist = {}, [], {}
    for st in with_prev_boards(static, states):         # stage order; boards inferred with continuity
        for k, v in (st.get("counters") or {}).items():       # per-round history drives Closing alerts
            hist.setdefault(k, []).append(v)
        st = dict(st, counter_history={k: list(v) for k, v in hist.items()} | st.get("counter_history", {}))
        new = [a for a in alerts(static, st, deadline) if last.get(a[0]) != a[1]]
        for a in new:
            last[a[0]] = a[1]
        if new:
            timeline.append((st["stage"], new))
    return timeline


if __name__ == "__main__":
    states = [json.loads(line) for line in Path(sys.argv[2]).read_text().splitlines() if line.strip()]
    for stage, items in review(load_set(sys.argv[1]), states, *(sys.argv[3:4] or [])):
        for unit, kind, msg in items:
            print(f"{stage:<6}{kind:<11}{unit:<22}{msg}")
