"""Post-game review: tempo notes (gold, levels, HP) plus unlock alerts, as one timeline.

    python3 -I engine/review.py TFTSet19 recordings/<time>/state.jsonl

Tempo rules come from the research report (docs/ROADMAP.md, reports/): placement is driven most by HP
through stages 3-4 and by gold left unspent at death, then by levelling on time. Each note says what
happened and why it cost; thresholds are constants below so they can be tuned against recorded games.
Post-game only: Riot's rules bar showing any of this during a game (docs/POLICY.md).
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alerts import review as unlock_review   # noqa: E402
from econ import damage, level_cost           # noqa: E402
from unlocks import load_set, stage_key, with_prev_boards  # noqa: E402

LINE = [("3-2", 6), ("4-1", 7), ("4-5", 8)]   # standard levelling checkpoints (guide consensus, Set 18)
SURVIVORS = {2: 2, 3: 3, 4: 4, 5: 5, 6: 6}    # ponytail: typical enemy units left after a loss; fit on recordings
DANGER_LOSSES, DANGER_GOLD = 2, 30            # this close to death with this much gold: roll
BLEED_HP, BLEED_GOLD = 60, 50                 # losing HP below this while holding this much
CAP_GOLD = 70                                 # interest stops at 50
LOW_HP_STREAK = 40
REROLL_LINE = 5                               # rerolls over the last 3 phases that mark a reroll comp
LOW_RANK = 2                                  # this close to the bottom of the lobby's HP: the next ones out
SAFE_RANK = 2                                 # top two in the lobby's HP: the others go out first
SLAM_LOSSES = 2                               # lost rounds in a row while holding a buildable pair of components
CDRAGON = Path(__file__).resolve().parent.parent / "data/raw/cdragon"


@lru_cache(maxsize=1)
def recipes():
    """({component names}, {frozenset of two component names: completed item}) from CommunityDragon data;
    empty without it. Recipes are the standard ones, which carry over between sets."""
    try:
        index = json.loads((CDRAGON / "items/index.json").read_text())
        items = json.loads((CDRAGON / "tft_pbe.json").read_text())["items"]
    except (OSError, KeyError, ValueError):
        return set(), {}
    name = {e["api"]: e["name"] for e in index}
    # Spatula and Frying Pan build emblems, which differ per set: left out
    comps = {e["name"] for e in index if e["kind"] == "component"} - {"Spatula", "Frying Pan"}
    out = {}
    for it in items:
        parts = [name.get(c) for c in it.get("composition") or []]
        if it.get("apiName") in name and len(parts) == 2 and all(p in comps for p in parts):
            out.setdefault(frozenset(parts), name[it["apiName"]])
    return comps, out


def slam_notes(states):
    """Components held in pairs that build an item through lost rounds: bench items don't fight."""
    comps, build = recipes()
    notes, said, run, start_hp = [], set(), 0, None
    for s in states:
        held = [i for i in s.get("items_held") or [] if i in comps]
        pair = next(((a, b) for k, a in enumerate(held) for b in held[k + 1:] if frozenset((a, b)) in build), None)
        if pair and s.get("result") == "loss" and s.get("hp") is not None:
            run, start_hp = run + 1, start_hp if run else s["hp"]
        else:
            run, start_hp = 0, None
        stage_n = stage_key(s["stage"])[0]
        if run >= SLAM_LOSSES and f"SLAM{stage_n}" not in said:
            said.add(f"SLAM{stage_n}")
            a, b = pair
            notes.append((s["stage"], "SLAM", f"held {a} and {b} through {run} lost rounds: together they make "
                                              f"{build[frozenset(pair)]}. Items on the bench don't fight; slam it "
                                              f"unless the item your carry wants is a round away."))
    return notes


def hp_rank(s):
    """(your place in the lobby's HP, players still in) from the player list (eliminated players show 0),
    or None when fewer than 5 of the other 7 were read."""
    lobby = s.get("lobby_hp") or {}
    if s.get("hp") is None or len(lobby) < 5:
        return None
    alive = [h for h in lobby.values() if h > 0]
    return 1 + sum(h > s["hp"] for h in alive), 1 + len(alive)


def lobby_so_far(states):
    """Each round's lobby HP with players unread that round at their last reading: HP only falls, so the
    gap is filled with an upper bound (you never look safer than you were)."""
    known = {}
    for s in states:
        known.update(s.get("lobby_hp") or {})
        yield dict(s, lobby_hp=dict(known))


def nth(k):
    return f"{k}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(k, 'th')}"


def losses_left(hp, stage, rules):
    s = stage_key(stage)[0]
    return (hp - 1) // damage(s, SURVIVORS.get(s, 6), rules)


def tempo(static, states):
    rules, notes, said = static["rules"], [], set()

    def note(stage, kind, msg, key=None):
        k = key or kind
        if k not in said:
            said.add(k)
            notes.append((stage, kind, msg))

    lost_run = 0
    states = list(lobby_so_far(states))
    for i, s in enumerate(states):
        st, lvl, gold, hp = s["stage"], s.get("level"), s.get("gold"), s.get("hp")
        prev = states[i - 1] if i else {}
        if None not in (hp, prev.get("hp")):
            lost_run = lost_run + 1 if hp < prev["hp"] else 0
        rerolls = s.get("counters", {}).get("rerolls", 0) - (states[max(0, i - 3)].get("counters", {}).get("rerolls", 0))
        stage_n = stage_key(st)[0]

        for cp, target in LINE:
            if stage_key(st) >= stage_key(cp) and None not in (lvl, gold) and lvl < target and rerolls < REROLL_LINE:
                cost = level_cost(lvl, (s.get("xp") or [0])[0], rules)
                if gold >= cost:
                    note(st, "LEVEL", f"level {lvl} at {st} with {gold} gold; the usual line is {target} by {cp} "
                                      f"({cost} gold away). Late levels mean worse odds and weaker boards in stage 4.",
                         key=f"LEVEL{cp}")
        rank = hp_rank(s)
        where = f" ({nth(rank[0])} of {rank[1]} in HP)" if rank else ""
        if rank and stage_n >= 3 and rank[1] >= 5 and rank[0] > rank[1] - LOW_RANK:     # top 4 still open
            others = sorted(h for h in s["lobby_hp"].values() if h > 0)
            note(st, "LOW", f"{nth(rank[0])} of {rank[1]} in HP at {st} ({hp}; the lobby's middle is "
                            f"{others[len(others) // 2]}): the bottom two go out first, so this is the moment to "
                            f"stabilise, not to save.")
        if None not in (hp, gold) and stage_n >= 3:
            k = losses_left(hp, st, rules)
            if k <= DANGER_LOSSES and gold >= DANGER_GOLD and not (rank and rank[0] <= SAFE_RANK):
                risk = "the next loss likely ends your game" if k == 0 else f"about {k} more loss(es) end your game"
                note(st, "SPEND", f"at {hp} HP{where} {risk}, with {gold} gold banked. Saved gold is worth nothing "
                                  f"once you're out: roll here.", key=f"SPEND{stage_n}")
                said.add(f"STREAK{stage_n}")                  # same point; don't repeat it
            if lost_run >= 2 and hp < BLEED_HP and gold >= BLEED_GOLD:
                note(st, "BLEED", f"lost HP {lost_run} rounds running, down to {hp}{where}, while holding {gold} gold. "
                                  f"Top-4 finishers keep their HP through stages 3-4; spend to stabilise.",
                     key=f"BLEED{stage_n}")
            if lost_run >= 2 and hp < LOW_HP_STREAK:
                note(st, "STREAK", f"still losing under {LOW_HP_STREAK} HP ({hp}). A loss streak pays off only "
                                   f"with HP to spare; stop it here.", key=f"STREAK{stage_n}")
        # banking past 50 to buy a level within the next few rounds (fast 9) is a plan, not waste
        soon = [x.get("level") or 0 for x in states[i + 1:i + 4]]
        if gold is not None and gold >= CAP_GOLD and not (lvl and soon and max(soon) > lvl):
            note(st, "CAP", f"{gold} gold at {st}: interest stops at 50, so {gold - 50} gold was earning nothing.")

    last = states[-1] if states else {}
    if None not in (last.get("hp"), last.get("gold")) and last["gold"] >= 10 \
            and losses_left(last["hp"], last["stage"], rules) == 0 \
            and f"SPEND{stage_key(last['stage'])[0]}" not in said and (hp_rank(last) or (0,))[0] != 1:
        notes.append((last["stage"], "OUT", f"last seen at {last['hp']} HP holding {last['gold']} gold: "
                                            f"if that was your exit, the gold should have been on the board."))
    return notes


CHECKPOINTS = ("3-2", "4-1", "4-5")


def plan_notes(static, states):
    """At each checkpoint, the plan the board fits best (if any fits 40%+) and what blocks its unlocks."""
    if not (static["traits"] and "kind" in static["traits"][0]):
        return []
    from plans import build_plans, match
    from unlocks import evaluate
    from plans import focus
    chosen = focus(static)                       # focused comps: report progress toward them, not best fit
    plans, out, last = chosen or build_plans(static), [], None
    for cp in CHECKPOINTS:
        s = next((x for x in states if stage_key(x["stage"]) >= stage_key(cp)), None)
        if not s:
            continue
        if chosen:
            p, fit = match(static, s, plans)[0]
        else:                                    # same ranking as line selection: fit and placement
            from lines import anchors
            top = anchors(static, s, k=1)
            if not top:
                continue
            p = top[0]
            fit = dict((q["id"], f) for q, f in match(static, s, [p]))[p["id"]]
        if chosen:
            fit = max(fit, 0.4)                  # always report a chosen comp, even when far off
        if fit < 0.4 or p["id"] == last:
            continue
        last = p["id"]
        st = {r["unit"]: r for r in evaluate(static, s) if r["unit"] in p["unlocks"]}
        block = [f"{n} {r['status'].lower()} ({r['detail']})" for n, r in st.items() if r["status"] not in ("READY", "UNLOCKED")]
        kind = f"PBE avg place {p['avg_place']:.2f}" if "avg_place" in p else "structural plan"
        out.append((s["stage"], "PLAN", f"board fits {p['id']} ({fit:.0%}, {kind})"
                    + (f"; its unlocks: {'; '.join(block)}" if block else "; its unlocks are done")))
    return out


def line_notes(static, states):
    """At checkpoints with known owned units: the board that kept the line, when it differs from the
    strongest one (post-game only)."""
    from lines import best_board
    out = []
    for cp in CHECKPOINTS:
        s = next((x for x in states if stage_key(x["stage"]) >= stage_key(cp)), None)
        if not s or len(s.get("owned") or []) < 3:
            continue
        r = best_board(static, s)
        if r and r["anchors"] and r["why"] != "the strongest board already keeps your line":
            out.append((s["stage"], "LINE", f"toward {', '.join(r['anchors'][:2])}: {r['why']}"))
    return out


def review(static, states, deadline="5-1"):
    states = with_prev_boards(static, states)          # sorted, each round inferring from the one before
    from tempo import tempo_calls                       # (imports this module)
    calls = [(st, "TEMPO", call) for st, _, _, call in tempo_calls(static, states) if call]
    called = {c[0] for c in calls}                      # the numbered call replaces the rule of thumb there
    rows = [r for r in tempo(static, states) if not (r[1] in ("SPEND", "BLEED") and r[0] in called)] + calls
    rows += plan_notes(static, states) + line_notes(static, states) + slam_notes(states)
    for stage, items in unlock_review(static, states, deadline):
        rows += [(stage, kind, f"{unit}: {msg}") for unit, kind, msg in items]
    return sorted(rows, key=lambda r: stage_key(r[0]))


if __name__ == "__main__":
    log = [json.loads(x) for x in Path(sys.argv[2]).read_text().splitlines() if x.strip()]
    for stage, kind, msg in review(load_set(sys.argv[1]), log):
        print(f"{stage:<6}{kind:<10}{msg}")
