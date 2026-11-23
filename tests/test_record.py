# Recorder logic on scripted HUD readings (no capture needed), then a replay through the alerts.
#   python3 -I tests/test_record.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine")]
from alerts import review  # noqa: E402
from record import Recorder, round_type  # noqa: E402
from unlocks import evaluate, load_set  # noqa: E402


def R(t, gold, shop, level=4):
    return {"t": t, "level": level, "xp": None, "gold": gold,
            "shop": [{"slot": i + 1, "unit": u} for i, u in enumerate(shop)], "quality": {"unread": []}}


A = ["Olaf", "Gnar", "Ziggs", "Lux", "Zoe"]
B = ["Varus", "Kayn", "Sett", "Taric", "Elise"]
C = ["Neeko", "Lillia", "Kennen", "Katarina", "Yunara"]
readings = [
    R("1-2", 4, A), R("1-2", 2, B),               # reroll before the 2-4 carousel
    {"t": None},                                   # loading screen: ignored
    R("2-1", 10, B), R("2-1", 8, C),               # reroll
    R("2-1", 7, C[:4] + ["?"]),                    # bought a 1-cost: one slot changes, not a reroll
    R("2-1", 3, C[:4] + ["?"], level=None),        # bought XP; level missed this frame -> carried
    R("2-5", 20, A), R("2-5", 18, B),              # reroll after the carousel
]
rec = Recorder()
done = [s for s in (rec.feed(dict(r), ts) for ts, r in enumerate(readings)) if s]
done.append(rec.close())
assert [s["stage"] for s in done] == ["1-2", "2-1", "2-5"], [s["stage"] for s in done]
R2 = lambda s: {k: s["counters"][k] for k in ("rerolls", "rerolls_before_2_carousel")}  # noqa: E731
assert R2(done[0]) == {"rerolls": 1, "rerolls_before_2_carousel": 1}
assert R2(done[1]) == {"rerolls": 2, "rerolls_before_2_carousel": 2}
assert done[1]["level"] == 4 and done[1]["gold"] == 3
assert R2(done[2]) == {"rerolls": 3, "rerolls_before_2_carousel": 2}

# the log replays straight into review mode: 2 of 4 Seraphine rerolls, then the window closes
timeline = review(load_set("TFTSet19"), done)
got = {(st, u, k) for st, items in timeline for u, k, _ in items}
assert ("2-5", "Seraphine", "DEAD") in got, got

# Purchase bookkeeping
COST = {"Kayn": 1, "Taric": 1, "Lucian": 2, "Camille": 2, "Yone": 4, "Olaf": 1, "Gnar": 1, "Ziggs": 1,
        "Lux": 2, "Zoe": 1, "Varus": 1, "Sett": 1, "Elise": 1}


def shop(*units):
    return [{"slot": i + 1, "unit": u} for i, u in enumerate(units) if u]


def H(gold, *units, t="3-1"):
    return {"t": t, "level": 5, "xp": None, "gold": gold, "shop": shop(*units), "quality": {}}


rec = Recorder(COST)
seq = [H(44, "Kayn", "Lucian", "Camille", "Taric", "Taric"),
       H(43, None, "Lucian", "Camille", "Taric", "Taric"),       # bought Kayn (1)
       H(41, None, "Lucian", "Camille", None, None),               # two Tarics in one frame (1+1)
       H(35, None, None, "Camille", None, None),                   # Lucian (2) + XP (4)
       H(33, "Olaf", "Gnar", "Ziggs", "Lux", "Zoe"),               # reroll: no purchase
       H(32, "Olaf", "Gnar", "Ziggs", "Lux", None),                # Zoe (1)
       H(34, "Olaf", "Gnar", "Ziggs", "Lux", None)]                # sold +2: only Lucian 1-star matches
for i, r in enumerate(seq):
    rec.feed(r, i)
owned = {o["unit"]: (o["copies"], o["stars"]) for o in rec.cur["owned"]}
assert owned == {"Kayn": (1, 1), "Taric": (2, 1), "Zoe": (1, 1)}, owned
assert rec.counters["rerolls"] == 1 and rec.unattributed == 0
rec.feed(H(32, "Olaf", "Gnar", "Ziggs", "Lux", None), 9)          # spent 2, nothing missing: not a buy
rec.feed(H(33, "Olaf", "Gnar", "Ziggs", "Lux", None), 10)         # +1: Kayn, Taric or Zoe? ambiguous
assert rec.unattributed == 1 and sum(c for c, _ in owned.values()) == 4

# The shop leaving the screen (combat camera, closed shop) or gold going unread books nothing; cards
# vanishing together are booked only as far as the gold drop pays for them (real-VOD bug: 4 false "buys")
rec = Recorder(COST)
for i, r in enumerate([H(30, "Kayn", "Lucian", "Camille", "Taric", "Zoe"), H(30), H(None), H(30),
                       H(None, None, "Lucian", None, None, None), H(None, None, "Lucian", None, None, None)]):
    rec.feed(r, i)
assert rec.close()["owned"] == [], rec.cur["owned"]
rec = Recorder(COST)
for i, r in enumerate([H(30, "Kayn", "Lucian", "Camille", "Taric", "Zoe"),
                       H(29, None, "Lucian", None, None, None), H(29, None, "Lucian", None, None, None)]):
    rec.feed(r, i)                                       # 4 cards gone, 1 gold spent: only Kayn (first, 1 gold)
assert [o["unit"] for o in rec.close()["owned"]] == ["Kayn"], rec.cur["owned"]

# A card name missing for one reading (OCR blip) is not a buy; missing with no gold spent is dropped
rec = Recorder(COST)
for i, r in enumerate([H(30, "Kayn", "Lucian", "Camille", "Taric", "Zoe"),
                       H(30, "Kayn", None, "Camille", "Taric", "Zoe"),            # blip
                       H(30, "Kayn", "Lucian", "Camille", "Taric", "Zoe")] +
                      [H(30, "Kayn", "Lucian", "Camille", None, "Zoe")] * 7):     # unread for long, never paid
    rec.feed(r, i)
assert rec.close()["owned"] == [], rec.cur["owned"]

# A backward stage reading (4-5 read as 4-4) doesn't open a new round; a sustained one (a rewind) does
rec = Recorder({})
for i, t_ in enumerate(["4-4", "4-5", "4-4", "4-5", "4-6"]):
    rec.feed({"t": t_, "level": 8, "gold": 10, "shop": [], "quality": {}}, i)
rec.close()
assert [s["stage"] for s in rec.phases] == ["4-4", "4-5", "4-6"], [s["stage"] for s in rec.phases]
rec = Recorder({})                                  # a real rewind replays 4-4: it replaces, never duplicates
for i, t_ in enumerate(["4-4"] * 3 + ["4-5"] * 3 + ["4-4"] * 6 + ["4-5"] * 3 + ["4-6"]):
    rec.feed({"t": t_, "level": 8, "gold": 10, "shop": [], "quality": {}}, i)
rec.close()
assert [s["stage"] for s in rec.phases] == ["4-4", "4-5", "4-6"], [s["stage"] for s in rec.phases]
assert rec.phases[0]["ts"] >= 6                                      # the replayed copy was kept

# Facts derived when a round ends, checked through the unlock checker itself
S19 = load_set("TFTSet19")
assert [round_type(s) for s in ("1-1", "1-3", "2-1", "2-4", "2-7", "5-5")] == \
    ["carousel", "pve", "pvp", "carousel", "pve", "pvp"]
ROCK = [{"name": "Rock", "count": 3, "active": True}]
GU = [{"name": "Gu Feng", "count": 1, "active": False}]


def P(t, hp, level, gold, traits=(), shop=()):
    return {"t": t, "level": level, "xp": None, "gold": gold, "hp": hp, "streak_n": None,
            "traits": list(traits), "shop": [{"slot": i + 1, "unit": u} for i, u in enumerate(shop)], "quality": {}}


rec = Recorder({}, {u["unit"] for u in S19["unlocks"]})
game = [P("4-5", 70, 8, 40, ROCK), P("4-6", 70, 8, 44, ROCK), P("4-7", 60, 8, 48), P("5-1", 60, 8, 50, GU),
        P("5-2", 50, 8, 52, GU), P("5-3", 40, 8, 86, GU, shop=["Janna"]), P("5-5", 40, 8, 60)]
states = [s for s in (rec.feed(dict(r), i) for i, r in enumerate(game)) if s] + [rec.close()]
by = {s["stage"]: s for s in states}
assert [by[s].get("result") for s in ("4-6", "4-7", "5-1", "5-2", "5-3")] == ["win", "loss", None, "loss", "loss"]
# ^ each is the previous round's combat: 4-6's loss shows at 4-7; the 4-7 PvE round neither counts nor breaks it
assert by["5-3"]["streak_l8"] == {"type": "loss", "n": 3}
assert by["4-7"]["counters"]["rock_combats"] == 2                        # 4-5 and 4-6 had Rock active
assert by["5-3"]["counters"]["xayah_interest"] == 5 + 5 + 5              # 50, 52, 86 gold with Gu Feng fielded
assert by["5-3"]["gold_end_combat"] == 86 and "Janna" in by["5-3"]["unlocked"]
st = dict(by["5-3"], board=None)
status = {r["unit"]: r["status"] for r in evaluate(S19, st)}
assert status["Rakan"] == "READY" and status["Pyke"] == "READY" and status["Janna"] == "UNLOCKED", status
assert status["Vayne"] == "PROGRESS"                                       # 2 of 3 Rock combats

# real-VOD fixes: HP is the round's most common reading, bounded per round; stale rules get flagged
rec = Recorder({}, {"Galio"})
rec.gates = {"Galio": 7}
for i, (stage, hp) in enumerate([("3-1", 93), ("3-1", 93), ("3-1", 9), ("3-2", 3), ("3-3", 90), ("3-3", 90)]):
    rec.feed({"t": stage, "level": 5, "gold": 10, "hp": hp, "shop": [{"slot": 1, "unit": "Galio"}], "quality": {}}, i)
st = rec.close()
hps = [s["hp"] for s in rec.phases]
assert hps == [93, 93, 90], hps                     # 9 outvoted; 3 is a 90-point drop in one round: rejected
assert st["rule_conflicts"] == ["Galio in shop at level 5 (rule says level 7+)"]
# augment choice: every card seen is kept (rerolls), the last three are the final offer
rec = Recorder({})
for i, cards in enumerate([["Missed Connections", "Rolling For Days", "Focused Fire"],
                           ["Missed Connections", "Rolling For Days", None],
                           ["Missed Connections", "Crit Rune+", "Dummify"]]):
    rec.feed({"t": "3-2", "level": 6, "gold": 30, "shop": [], "quality": {},
              "augments": [c and {"name": c, "desc": ""} for c in cards]}, i)
a = rec.close()["augment_offers"][0]
assert a["stage"] == "3-2" and a["final"] == ["Missed Connections", "Crit Rune+", "Dummify"], a
assert set(a["offered"]) == {"Missed Connections", "Rolling For Days", "Focused Fire", "Crit Rune+", "Dummify"}
# a round's items are the consensus of its readings: one misread frame doesn't count, flicker units drop
from record import consensus_units  # noqa: E402
U = lambda x, y, *items: {"x": x, "y": y, "w": 0.03, "h": 0.004, "items": [[i, 0.9] for i in items]}   # noqa: E731
reads = [[U(0.45, 0.30, "Choreographer Emblem", "Warmog's Armor", "Protector's Vow")],
         [U(0.451, 0.301, "Choreographer Emblem", "Warmog's Armor", "Beach Pop Emblem")],
         [U(0.45, 0.30, "Choreographer Emblem", "Warmog's Armor", "Protector's Vow")],
         [U(0.45, 0.30, "Choreographer Emblem", "Warmog's Armor", "Protector's Vow"), U(0.7, 0.6)]]
c = consensus_units(reads)
assert len(c) == 1 and c[0]["items"] == ["Choreographer Emblem", "Warmog's Armor", "Protector's Vow"], c

# which augment was taken: the one final card that later shows in the Augments panel (OCR slips allowed)
from record import picked  # noqa: E402
final = ["Patience Is A Virtue", "Expedition", "Silver Destiny"]
assert picked(final, ["Silver Destlny", "Bundle o' Shrooms"]) == "Silver Destiny"   # granted augments don't count
assert picked(final, []) is None and picked(final, ["Expedition", "Silver Destiny"]) is None

# the HUD streak must follow the streak rule: robinsongz's "6" read as "9" (3-1, 3-2) is dropped, the true
# value kept; PvE rounds leave it alone; a round with no allowed reading is unread and the next one catches up
rec = Recorder({})
seq = [("2-6", [4, 5]), ("2-7", [5, 5]), ("3-1", [5, 5, 9, 9, 6, 9]), ("3-2", [9, 9, 6, 7, 9]),
       ("3-3", [9, 9]), ("3-4", []), ("3-5", [8, 9]), ("3-6", [9, 10])]
i = 0                                               # joined at 2-6: its last reading starts the streak
for stage, reads in seq:
    for k in reads or [None]:
        rec.feed({"t": stage, "level": 7, "gold": 10, "streak_n": k, "shop": [], "quality": {}}, i)
        i += 1
rec.close()
got = {s["stage"]: s["streak_n"] for s in rec.phases}
assert got["3-1"] == 6 and got["3-2"] == 7 and got["2-7"] == 5, got
assert got["3-3"] is None and got["3-4"] is None and got["3-5"] == 9 and got["3-6"] == 10, got   # 3-3's 8 never read

# trait panel: readings that caught a sliver of the panel (an overlay over it) don't push real traits out
rec = Recorder({})
full = [{"name": "Beach Pop", "count": 7, "active": True}, {"name": "Arcanist", "count": 2, "active": True},
        {"name": "Juggernaut", "count": 2, "active": True}]
for i in range(30):
    rec.feed({"t": "4-6", "level": 8, "gold": 10, "shop": [], "quality": {},
              "traits": full if i < 8 else [{"name": "Beach Pop", "count": 1, "active": False}]}, i)
names = {x["name"]: x["count"] for x in rec.close()["traits"]}
assert names.get("Arcanist") == 2 and names.get("Juggernaut") == 2 and names.get("Beach Pop") == 7, names

# the panel collapsed in combat ("+9": only two inactive traits listed) keeps last round's hidden traits
# (marked carried); scouting another board hides our HUD bar, and its trait panel isn't ours
T = lambda *xs: [{"name": n, "count": c, "active": a} for n, c, a in xs]   # noqa: E731
rec = Recorder({})
mine = T(("Beach Pop", 7, True), ("Arcanist", 2, True), ("Jazz", 1, False), ("Collab", 1, False))
i = 0
for stage, level, traits, hidden, n in [("4-5", 8, mine, 0, 5), ("4-6", 8, T(("Jazz", 1, False), ("Collab", 1, False)), 9, 20),
                                        ("4-6", None, T(("Synthwave", 1, True), ("K/DA", 13, True)), 0, 10), ("4-7", 8, mine, 0, 3)]:
    for _ in range(n):
        rec.feed({"t": stage, "level": level, "gold": level and 50, "shop": [], "quality": {}, "traits": traits,
                  "traits_hidden": hidden}, i)
        i += 1
rec.close()
p46 = {x["name"]: (x["count"], bool(x.get("carried"))) for x in rec.phases[1]["traits"]}
assert p46 == {"Beach Pop": (7, True), "Arcanist": (2, True), "Jazz": (1, False), "Collab": (1, False)}, p46

# star badges: a unit's stars are its most common reading over the round
SU = lambda x, s: {"x": x, "y": 0.3, "w": 0.03, "h": 0.004, "items": [], "stars": s}   # noqa: E731
assert [u["stars"] for u in consensus_units([[SU(0.4, 2), SU(0.5, 1)], [SU(0.4, 2), SU(0.5, 1)], [SU(0.4, 1), SU(0.5, 1)]])] == [2, 1]
print("ok")
