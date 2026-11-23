"""Tempo evaluator (post-game): at each planning phase, what saving, levelling and rolling would each have
bought over the next few rounds in gold, board strength and HP, and the rounds where what you did was far
from the best of them.

    python3 -I engine/tempo.py TFTSet19 recordings/<dir>/state.jsonl        # calls only
    python3 -I engine/tempo.py TFTSet19 recordings/<dir>/state.jsonl -v     # every round's options

Accounting: the question is now or later. Levels, units and rolls get bought either way (a roll-down
delayed is still paid for), so the real cost of acting now is the interest given up, and the real cost of
waiting is HP: gold spent counts as kept, interest and HP don't. Rolling
buys copies of units you field (shop odds at your level, pool minus copies out); a hit makes the board
stronger, which raises the chance to win the next rounds. That chance starts from your recent results.
HP lost = expected losses x stage damage. With a fitted fight model (engine/fights.py fit) the starting
chance, the strength slope and the HP per loss come from it instead. Post-game only (docs/POLICY.md).
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fights  # noqa: E402
from econ import damage, hit_chance, income, level_cost, streak_gold, tier_pool  # noqa: E402
from fights import form  # noqa: E402
from lines import strength_fn  # noqa: E402
from reach import OUT_OF_POOL  # noqa: E402
from review import SURVIVORS, hp_rank, lobby_so_far  # noqa: E402
from unlocks import infer_boards, load_set, round_type, stage_key  # noqa: E402

HORIZON = 3            # PvP rounds looked ahead
ROLL_FLOOR = 20        # "roll to 20" keeps 2 interest; the other roll option goes all-in
# ponytail: hand-set until recordings can fit them; FIGHT_SLOPE and the HP per loss are replaced by a fitted
# fight model when data/models/fights_<set>.json exists (engine/fights.py, ML_RESEARCH step 3)
FIGHT_SLOPE = 3.0      # change in log-odds of winning per unit of relative strength gained (+10% -> +0.3)
DEATH_GOLD = 100       # gold-equivalent of the game ending
HP_GOLD = {0: 4, 1: 4, 2: 2, 3: 2}   # gold per HP by losses you can still survive; 1 with 4+
CALL_MARGIN = 10       # gold-equivalent gap before a round is called
CALL_MIN_GOLD = 20     # below this there's little to decide


def hp_price(buffer):
    return HP_GOLD.get(max(buffer, 0), 1)


def pressure(state):
    """How much your HP matters against this lobby: 1 at the bottom of its HP, 0.25 on top (the others go
    out first). 1 when the player list wasn't read."""
    rank = hp_rank(state)
    return 1.0 if not rank or rank[1] < 3 else max(0.25, (rank[0] - 0.5) / (rank[1] - 0.5))


def logit(p):
    return math.log(p / (1 - p))


def upgrades(static, board, owned, level, budget, stage, unlocked):
    """[(unit, P(next star within budget), gold spent on its copies if hit)] for fielded units."""
    units = {u["name"]: u for u in static["units"]}
    odds_row = static["shop_odds_by_level"][min(level, len(static["shop_odds_by_level"])) - 1]
    out = OUT_OF_POOL.get(stage_key(stage)[0], 0.40)
    api = {units[n]["api"] for n in unlocked if n in units}
    held = {}
    for u, c in owned.items():
        cost = units.get(u, {}).get("cost")
        if cost:
            held[cost] = held.get(cost, 0) + c
    res = []
    for b in board:
        u, stars = b["unit"], b.get("stars", 1)
        info, c = units.get(b["unit"]), owned.get(b["unit"], 3 ** (stars - 1))
        if not info or stars >= 3 or info["cost"] > len(odds_row):
            continue
        need = 3 ** stars - c
        if not 0 < need <= 3:
            continue
        cost = info["cost"]
        left, tier_left = round(info["pool"] * (1 - out)) - c, round(tier_pool(static, cost, api) * (1 - out)) - held.get(cost, 0)
        p = hit_chance(need, budget, cost, odds_row[cost - 1], left, tier_left) \
            if odds_row[cost - 1] and left >= need and tier_left > 0 else 0.0
        if p > 0.01:
            res.append((u, p, need * cost))
    return res


def evaluate(static, pre, rules, strength):
    """Options at one planning phase. pre: gold, level, xp, hp, stage, streak, p0, board, owned, unlocked, and
    optionally fight = (strength slope, strength scale, HP per loss) from a fitted fight model."""
    g, lvl, stage = pre["gold"], pre["level"], pre["stage"]
    board = [(b["unit"], b.get("stars", 1), None) for b in pre["board"]]
    s0 = strength(board)
    bench = [u for u in pre["owned"] if u not in {b[0] for b in board}]
    slope, scale, dmg = pre.get("fight") or \
        (FIGHT_SLOPE, max(abs(s0), 1.0), damage(stage_key(stage)[0], SURVIVORS.get(stage_key(stage)[0], 6), rules))
    buffer = math.ceil(pre["hp"] / dmg) - 1
    xp_cost = level_cost(lvl, pre["xp"], rules) if lvl < 10 else None
    plans = [("save", 0, None)]
    if xp_cost is not None and g >= xp_cost:
        plans.append(("level", xp_cost, None))
    for name, xp in (("", 0), ("level+", xp_cost)):
        if xp is None or g < xp:
            continue
        for floor in (ROLL_FLOOR, 0):
            if g - xp - floor >= 6:
                plans.append((f"{name}roll to {floor}", xp, floor))
    out = []
    for name, xp, floor in plans:
        level = lvl + (1 if xp else 0)
        budget = g - xp - floor if floor is not None else 0
        gain = spend = 0.0
        if xp:              # the new slot takes your best benched unit, else a 1-star of the likeliest cost
            row = static["shop_odds_by_level"][min(level, len(static["shop_odds_by_level"])) - 1]
            cost = max(range(len(row)), key=lambda k: row[k]) + 1
            pool = [(u, 3 if c >= 9 else 2 if c >= 3 else 1) for u, c in pre["owned"].items() if u in bench] or \
                [(u["name"], 1) for u in static["units"] if u["cost"] == cost and not u.get("unlockable")]
            gains = [strength(board + [(u, st, None)]) - s0 for u, st in pool]
            gain += max(gains) if pool and pool[0][0] in bench else sum(gains) / max(len(gains), 1)
        if budget:
            for u, p, cost in upgrades(static, pre["board"], pre["owned"], level, budget, stage, pre["unlocked"]):
                up = [(x, s + 1 if x == u else s, i) for x, s, i in board]
                gain += p * (strength(up) - s0)
                spend += p * cost
        if spend > budget:                                 # copies of several targets compete for one budget
            gain, spend = gain * budget / spend, budget
        p = 1 / (1 + math.exp(-(logit(pre["p0"]) + slope * max(gain, 0) / scale)))
        q = 1 - p
        hp_lost = min(pre["hp"], HORIZON * q * dmg)
        p_death = sum(math.comb(HORIZON, k) * q ** k * p ** (HORIZON - k) for k in range(buffer + 1, HORIZON + 1))
        bank = g - xp - budget
        streak = pre["streak"]
        keep = p if streak > 0 else q if streak < 0 else 0     # chance the current streak goes on
        for _ in range(HORIZON):
            bank += income(bank, 0, False, rules) + keep * streak_gold(streak + (1 if streak > 0 else -1), rules) \
                + p * rules["pvp_win_gold"]
        worth = bank + xp + budget                         # spent now = bought later anyway: only interest differs
        out.append({"option": name, "fees": round(budget - spend, 1), "gain": round(gain, 2), "p_win": round(p, 2),
                    "hp_lost": round(hp_lost, 1), "p_death": round(p_death, 3), "gold_end": round(worth, 1),
                    "value": round(worth - pre["pressure"] * (hp_price(buffer) * hp_lost + DEATH_GOLD * p_death), 1)})
    return out


def natural_xp(level, xp, rules):
    """Level and XP after the free 2 XP at a round start."""
    xp += 2
    need = rules["xp_to_next_level"][str(level)]
    return (level + 1, xp - need) if xp >= need else (level, xp)


def total_xp(level, xp, rules):
    return sum(rules["xp_to_next_level"][str(k)] for k in range(1, level)) + xp


def what_you_did(pre, s, rules, rerolls):
    """'save' / 'level' / 'roll to N' / 'level+roll to N' from the round's level, gold and reroll count."""
    bought = total_xp(s["level"], (s.get("xp") or [0])[0], rules) - total_xp(pre["level"], pre["xp"], rules)
    rolled = rerolls * 2 >= 6 or pre["gold"] - s["gold"] - max(bought, 0) >= 20
    if not rolled:
        return "level" if bought >= 4 else "save"
    floor = ROLL_FLOOR if s["gold"] >= ROLL_FLOOR - 4 else 0
    return f"{'level+' if bought >= 4 else ''}roll to {floor}"


def tempo_calls(static, states):
    """[(stage, what you did, options, call or None)] for each PvP planning phase with known gold."""
    rules, strength = static["rules"], strength_fn(static)
    boards = [s.get("board") or b for s, (b, _) in zip(states, infer_boards(static, states))]   # exact when known
    lobby = list(lobby_so_far(states))
    model = fights.load(static["set"])
    spots = fights.spots(static, states) if model else None
    out = []
    for i in range(1, len(states)):
        prev, s = states[i - 1], states[i]
        if round_type(s["stage"]) != "pvp" or stage_key(s["stage"])[0] < 2 or not boards[i - 1] or \
                None in (prev.get("gold"), prev.get("level"), prev.get("xp"), s.get("gold"), s.get("level"), s.get("hp")):
            continue
        st = s.get("streak") or {}
        streak = (st.get("n") or 0) * (1 if st.get("type") == "win" else -1 if st.get("type") == "loss" else 0)
        level, xp = natural_xp(prev["level"], prev["xp"][0], static["rules"])
        pre = {"stage": s["stage"], "level": level, "xp": xp, "hp": s["hp"], "streak": streak, "p0": form(states, i),
               "gold": prev["gold"] + income(prev["gold"], streak, s.get("result") == "win", rules),
               "board": boards[i - 1], "unlocked": s.get("unlocked", []), "pressure": pressure(lobby[i]),
               "owned": {o["unit"]: o["copies"] for o in prev.get("owned", [])}}
        if model:                       # the spot before you acted: last round's board, this round's lobby
            n = stage_key(s["stage"])[0]
            norm = model["norm"].get(str(n))
            pre["p0"] = fights.predict(model, pre["p0"], level, spots[i][2], spots[i - 1][3], n)
            pre["fight"] = (model["w"]["strength"], max(abs(norm), 1.0) if norm is not None else 1.0,
                            fights.hp_loss(model, n, rules))
        opts = evaluate(static, pre, rules, strength)
        rr = (s.get("counters") or {}).get("rerolls", 0) - (prev.get("counters") or {}).get("rerolls", 0)
        did = what_you_did(pre, s, rules, rr)
        # calls compare rolling and saving under the level choice you made: what a level buys beyond its slot
        # (better odds for higher costs, the next unit's traits) isn't modelled, so levelling isn't judged here
        same = [o for o in opts if o["option"].startswith("level") == did.startswith("level")]
        best = max(same, key=lambda o: o["value"]) if same else None
        mine = next((o for o in opts if o["option"] == did), None)
        call = None
        if mine and pre["gold"] >= CALL_MIN_GOLD and best["value"] - mine["value"] >= CALL_MARGIN:
            call = (f"you went '{did}' with {pre['gold']} gold at {s['hp']} HP: est. {mine['hp_lost']:.0f} HP lost over "
                    f"the next {HORIZON} rounds ({mine['p_death']:.0%} chance they end your game). '{best['option']}' "
                    f"est. {best['hp_lost']:.0f} HP ({best['p_death']:.0%}), "
                    + (f"giving up {cost:.0f} gold of interest." if (cost := mine["gold_end"] - best["gold_end"]) > 0
                       else f"and {-cost:.0f} more gold."))
        out.append((s["stage"], did, opts, call))
    return out


if __name__ == "__main__":
    static = load_set(sys.argv[1])
    states = [json.loads(x) for x in Path(sys.argv[2]).read_text().splitlines() if x.strip()]
    for stage, did, opts, call in tempo_calls(static, states):
        if "-v" in sys.argv:
            print(f"{stage}  you: {did}")
            for o in sorted(opts, key=lambda o: -o["value"]):
                print(f"    {o['option']:17} value {o['value']:7.1f}  win {o['p_win']:.0%}  HP -{o['hp_lost']:4.1f}  "
                      f"death {o['p_death']:4.0%}  gold+assets {o['gold_end']:5.1f}  fees {o['fees']:4.1f}")
        if call:
            print(f"{stage:<6}TEMPO     {call}")
