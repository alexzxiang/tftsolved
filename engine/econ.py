"""Shop odds and gold/HP arithmetic. Pure functions over a static-data dict from tools/build_static.py.

    hit_chance(...)   P(buy N more copies of one unit within a gold budget)
    gold_for(...)     smallest budget that reaches a target probability
    level_cost(...)   gold to buy the next level
    income(...), damage(...), losses_to_death(...)
"""
from math import ceil, comb

SHOP_SLOTS = 5


def tier_pool(static, cost, unlocked=(), out=0):
    """Copies of `cost` units this player can be shown: base units plus their own unlocks, minus `out`
    (copies of that cost sitting on any board or bench, including theirs)."""
    return sum(u["pool"] for u in static["units"]
               if u["cost"] == cost and (not u["unlockable"] or u["api"] in unlocked)) - out


def hit_chance(need, gold, cost, odds, copies_left, tier_left, reroll=2, pay_for_units=True):
    """P(buying `need` more copies of one unit with at most `gold`, rolling fresh shops).

    odds: chance a slot is this unit's cost tier at the player's level (shop_odds_by_level[level-1][cost-1]).
    copies_left / tier_left: copies of the unit / of its whole tier still in the pool.
    pay_for_units=False counts reroll gold only, as most community calculators do.
    """
    # ponytail: the 5 slots are treated as independent draws (binomial); the real shop draws without
    # replacement, which tests/test_econ.py shows changes results by under 2 points.
    if need <= 0:
        return 1.0
    price = cost if pay_for_units else 0
    states, hit = {(0, gold): 1.0}, 0.0
    while states:
        nxt = {}
        for (got, g), pr in states.items():
            if g < reroll:
                continue                                  # out of gold: a miss
            g -= reroll
            k, r = copies_left - got, tier_left - got
            p = odds * k / r if r > 0 else 0.0
            for j in range(SHOP_SLOTS + 1):
                pj = comb(SHOP_SLOTS, j) * p ** j * (1 - p) ** (SHOP_SLOTS - j)
                if pj == 0:
                    continue
                buy = min(j, need - got, g // price if price else need)
                if got + buy >= need:
                    hit += pr * pj
                else:
                    key = (got + buy, g - buy * price)
                    nxt[key] = nxt.get(key, 0.0) + pr * pj
        states = nxt
    return hit


def gold_for(prob, max_gold=200, **kw):
    """Smallest even gold budget whose hit_chance reaches `prob`, or None within max_gold."""
    for g in range(0, max_gold + 1, 2):
        if hit_chance(gold=g, **kw) >= prob:
            return g
    return None


def level_cost(level, xp, rules):
    """Gold to buy enough XP for the next level (XP comes in 4-XP purchases)."""
    missing = rules["xp_to_next_level"][str(level)] - xp
    per = rules["buy_xp"]
    return ceil(max(missing, 0) / per["xp"]) * per["gold"]


def streak_gold(streak, rules):
    n = min(abs(streak), max(map(int, rules["streak_gold"])))
    return rules["streak_gold"].get(str(n), 0)


def income(gold, streak, won, rules):
    """Gold gained at the start of next round. streak: +n wins / -n losses including this round."""
    i = rules["interest"]
    return (rules["base_income"] + min(gold // i["per_gold"], i["cap"]) + streak_gold(streak, rules)
            + (rules["pvp_win_gold"] if won else 0))


def damage(stage, survivors, rules):
    """HP lost on a loss: stage base + 1 per surviving enemy unit."""
    return rules["stage_damage"][str(min(stage, 8))] + survivors * rules["damage_per_surviving_unit"]


def losses_to_death(hp, stage, survivors, rules):
    """How many more losses at this stage (to boards leaving `survivors` alive) the player can take."""
    return ceil(hp / damage(stage, survivors, rules)) - 1
