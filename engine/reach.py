"""Unlock reachability: chance each unlock happens by a given stage, from one game state.

    python3 -I engine/reach.py TFTSet19 state.json 5-1

Per condition kind:
  shop        units still to find (board_unique, board_stars, unit_state): shop simulation over the
              coming rounds. Two policies: "standard" holds 50 gold and rolls down once on reaching level 8 (the
              usual 4-5 roll-down); "roll_now" rolls down this round (keeping enough to buy), then holds 50.
              Both pay for XP to follow the standard levelling line.
  counter     accumulators: normal approximation from the per-round rate in state["counter_history"].
  streak      Rakan: exact over win/loss sequences from level 8, with p_win (state or 0.5).
  save        Pyke: rounds of saving needed to hold 85 gold.
  action      items, positions, rerolls, trait counts: the player's choice, not chance (p is None).
Extra state keys: "contest" {unit: copies on other boards}, "counter_history" {name: [value per round]},
"p_win" (0-1), "held" {unit: copies owned incl. bench}.
"""
import json
import random
import sys
from math import erf, sqrt
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
from econ import income, tier_pool          # noqa: E402
from unlocks import Board, evaluate, load_set  # noqa: E402

LEVEL_LINE = [("2-1", 4), ("2-5", 5), ("3-2", 6), ("4-1", 7), ("4-5", 8), ("5-5", 9)]
OUT_OF_POOL = {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.30, 5: 0.35, 6: 0.40}   # ponytail: share of each tier on
# other boards by stage; a guess until fitted on recordings
PASSIVE_XP = 2       # XP every player gets each round


def rnum(stage):
    """Planning phases counted from 2-1 (stage 1 ignored: no unlock depends on it)."""
    s, r = map(int, stage.split("-"))
    return (s - 2) * 7 + r


def stage_key_n(stage):
    return int(stage.split("-")[0])


def level_at(stage, now_level):
    return max([now_level] + [lv for st, lv in LEVEL_LINE if rnum(st) <= rnum(stage)])


def stage_of(n):
    return f"{(n - 1) // 7 + 2}-{(n - 1) % 7 + 1}"


def stars(copies):
    return 3 if copies >= 9 else 2 if copies >= 3 else 1 if copies >= 1 else 0


def shop_reach(static, state, caps, held, done, by, trials=400, seed=7, value=None):
    """P(done(copies) by `by`) under both policies, buying wanted units as they show up; with `value`
    (copies -> 0..1), its mean at `by` instead (e.g. the share of wanted units found).

    caps: {unit: most copies worth owning}. held: {unit: copies owned now}. done: copies dict -> bool.
    Each round: free shop, buy, then roll (2 gold) while gold stays above the policy floor.
    """
    # ponytail: bench space, selling and other players' buys during the window are ignored
    units = {u["name"]: u for u in static["units"]}
    rules, odds = static["rules"], static["shop_odds_by_level"]
    unlocked = set(state.get("unlocked", []))
    out_frac = OUT_OF_POOL.get(stage_key_n(state["stage"]), 0.40)
    tiers = {c: tier_pool(static, c, unlocked) * (1 - out_frac) for c in {units[w]["cost"] for w in caps}}
    need = {int(k): v for k, v in rules["xp_to_next_level"].items()}
    buy = rules["buy_xp"]
    start, end = rnum(state["stage"]), rnum(by)
    out, reserve = {}, max(units[w]["cost"] for w in caps)
    rolldown = next((n for n in range(start, end + 1) if level_at(stage_of(n), 1) >= 8), None)
    for policy in ("standard", "roll_now"):
        rng, hits = random.Random(seed), 0
        for _ in range(trials):
            gold, copies = (state.get("gold") or 0), dict(held)
            level, xp = (state.get("level") or 1), (state.get("xp") or [0])[0]
            rem = {w: units[w]["pool"] - state.get("contest", {}).get(w, 0) - held.get(w, 0) for w in caps}
            ok = done(copies)
            for n in range(start, end + 1):
                if ok:
                    break
                if n > start:
                    xp += PASSIVE_XP
                while xp >= need.get(level, 999):
                    xp, level = xp - need[level], level + 1
                while level < level_at(stage_of(n), 1) and gold >= buy["gold"]:   # pay to keep the line
                    gold -= buy["gold"]
                    xp += buy["xp"]
                    while xp >= need.get(level, 999):
                        xp, level = xp - need[level], level + 1
                lvl = level
                # standard line: hold 50, roll down once on reaching level 8 (4-5); roll_now: roll down today
                roll_today = n == start if policy == "roll_now" else n == rolldown
                floor = reserve if roll_today else 50
                while True:
                    for _slot in range(5):
                        cost = rng.choices(range(1, 6), odds[lvl - 1])[0]
                        x = rng.random() * tiers.get(cost, 1)
                        for w in caps:
                            if units[w]["cost"] != cost or rem[w] <= 0:
                                continue
                            x -= rem[w]
                            if x < 0:
                                if copies.get(w, 0) < caps[w] and gold >= cost:
                                    copies[w] = copies.get(w, 0) + 1
                                    rem[w] -= 1
                                    gold -= cost
                                break
                    ok = done(copies)
                    if ok or gold - rules["reroll_gold"] < floor:
                        break
                    gold -= rules["reroll_gold"]
                gold += income(gold, 0, False, rules)
            hits += value(copies) if value else ok
        out[policy] = hits / trials
    return out


def counter_reach(cond, state, by):
    hist = state.get("counter_history", {}).get(cond["name"])
    if not hist or len(hist) < 2:
        return None, "needs per-round history of this counter"
    deltas = [b - a for a, b in zip(hist, hist[1:])][-4:]
    mu, sd = mean(deltas), max(pstdev(deltas), 0.25 * mean(deltas) + 1e-9)
    k = rnum(by) - rnum(state["stage"]) + 1
    left = cond["n"] - hist[-1]
    if left <= 0:
        return 1.0, "already met"
    if k <= 0:
        return 0.0, f"deadline passed ({left} left)"
    if mu <= 0:      # unchanged readings: the tracker may simply not have been re-read, so don't call it dead
        return None, f"no change seen in recent rounds ({left} left; tracker may not be on screen)"
    z = (left - k * mu) / (sqrt(k) * sd)
    return 0.5 * (1 - erf(z / sqrt(2))), f"{left} left at ~{mu:.0f}/round over {k} rounds (if the gate holds)"


def streak_reach(cond, state, by):
    """Exact P(win streak >= win or loss streak >= loss) within the rounds after reaching level 8."""
    p = state.get("p_win", 0.5)
    first = max(rnum(state["stage"]), next(rnum(st) for st, lv in LEVEL_LINE if lv >= 8)
                if (state.get("level") or 1) < 8 else rnum(state["stage"]))
    s = state.get("streak") or {}
    dist = {(s.get("type"), (s.get("n") or 0)) if (state.get("level") or 1) >= 8 else (None, 0): 1.0}
    hit = 0.0
    for _ in range(first, rnum(by) + 1):
        nxt = {}
        for (t, n), pr in dist.items():
            for res, q in (("win", p), ("loss", 1 - p)):
                key = (res, n + 1 if t == res else 1)
                if key[1] >= cond[res]:
                    hit += pr * q
                else:
                    nxt[key] = nxt.get(key, 0) + pr * q
        dist = nxt
    return hit, f"p_win {p:.2f} per round from level 8"


def reach(static, state, by, only=None):
    """Rows per unlock (checker fields + kind, p, why). only: optional set of unit names to score."""
    b = Board(static, state)
    rows = {r["unit"]: r for r in evaluate(static, state)}
    units = {u["name"]: u for u in static["units"]}
    unlocked = set(state.get("unlocked", [])) | {u for u in b.fielded if u in rows}
    out = []
    for u in static["unlocks"]:
        if only is not None and u["unit"] not in only:
            continue
        r = dict(rows[u["unit"]], kind=None, p=None, why="")
        if r["status"] in ("UNLOCKED", "BLOCKED", "DEAD", "READY") or not u.get("when"):
            r["p"] = {"READY": 1.0, "UNLOCKED": 1.0, "BLOCKED": 0.0, "DEAD": 0.0}.get(r["status"])
            out.append(r)
            continue
        lvl_ok = not u.get("min_level") or level_at(by, (state.get("level") or 1)) >= u["min_level"]
        if not lvl_ok or r["status"] == "NEEDS_LEVEL":
            r.update(kind="level", p=float(lvl_ok),
                     why=f"standard line reaches level {u['min_level']} {'by' if lvl_ok else 'after'} {by}")
            out.append(r)
            continue
        held = {n: state.get("held", {}).get(n, 3 ** (x.get("stars", 1) - 1)) for n, x in b.fielded.items()}
        shoppable = lambda n: (n not in rows or n in unlocked) and units[n]["cost"] <= 5  # noqa: E731
        (kind, a), = u["when"].items()
        if kind in ("board_unique", "board_stars"):
            pool = [n for n, x in units.items() if any(t in x["traits"] for t in a["traits"])
                    and (shoppable(n) or n in b.fielded)]
            if kind == "board_unique":
                caps = {n: 1 for n in pool}
                done = lambda c, pool=pool, n_=a["n"]: sum(c.get(x, 0) >= 1 for x in pool) >= n_  # noqa: E731
            else:
                caps = {n: 9 if units[n]["cost"] <= 2 else 3 for n in pool}   # 3-star only for cheap units
                done = lambda c, pool=pool, n_=a["n"]: sum(stars(c.get(x, 0)) for x in pool) >= n_  # noqa: E731
            best = sum(min(3 if caps[n] == 9 else 2, 3) if caps[n] > 1 else 1 for n in pool)
            if best < a["n"]:
                r.update(kind="shop", p=0.0, why=f"at most {best} of {a['n']} with today's unlocks")
            else:
                r.update(kind="shop", p=shop_reach(static, state, {n: caps[n] for n in pool if shoppable(n)},
                                                   held, done, by),
                         why=f"{r['value'] or 0}/{a['n']} now; {sum(map(shoppable, pool))} shoppable units")
        elif kind == "unit_state":
            need = 3 ** (a["stars"] - 1)
            names = [n for n in a["units"] if shoppable(n)]
            best = None
            for name in names:
                pr = shop_reach(static, state, {name: need}, held,
                                lambda c, name=name: c.get(name, 0) >= need, by)
                if best is None or pr["roll_now"] > best[1]["roll_now"]:
                    best = (name, pr)
            if best:
                extra = f" plus {a['items']} item(s)" if a.get("items") else ""
                r.update(kind="shop", p=best[1],
                         why=f"{max(need - held.get(best[0], 0), 0)} more {best[0]}{extra}")
            else:
                r.update(kind="shop", p=0.0, why=f"{' / '.join(a['units'])} not unlocked yet")
        elif kind == "counter":
            p, why = counter_reach(a, state, by)
            r.update(kind="counter", p=p, why=why)
        elif kind == "all_of" and all("counter" in w for w in a):
            parts = [counter_reach(w["counter"], state, by) for w in a]
            ps = [p for p, _ in parts]
            r.update(kind="counter", p=None if None in ps else min(ps), why="; ".join(w for _, w in parts))
        elif kind == "streak":
            p, why = streak_reach(a, state, by)
            r.update(kind="streak", p=p, why=why)
        elif kind == "gold_end_combat":
            g, n = (state.get("gold") or 0), 0
            while g < a["n"] and n < 30:
                g += income(g, 0, False, static["rules"])
                n += 1
            ok = rnum(state["stage"]) + n <= rnum(by)
            r.update(kind="save", p=1.0 if ok else 0.0, why=f"{n} rounds of saving (no spending) to hold {a['n']}")
        else:
            r.update(kind="action", why="your choice (items, positions, rerolls or traits), not shop luck")
        out.append(r)
    return out


def fmt_p(p):
    if p is None:
        return "  -  "
    if isinstance(p, dict):
        return f"{p['standard']:4.0%} / {p['roll_now']:4.0%}"
    return f"{p:4.0%}"


if __name__ == "__main__":
    static, state, by = load_set(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), sys.argv[3]
    print(f"{'unlock':<22}{'status':<12}{'kind':<8}{'P by ' + by:<16}why   (shop: standard line / roll down now)")
    for r in reach(static, state, by):
        print(f"{r['unit']:<22}{r['status']:<12}{r['kind'] or '':<8}{fmt_p(r['p']):<16}{r['why'] or r['detail']}")
