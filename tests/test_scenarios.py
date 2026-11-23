"""What a pro would expect the line finder to say, on boards anyone could enter. Each check is a judgement call written
down so a change that breaks it is noticed; the measured behaviour across thousands of sampled boards is in
tools/eval_lines.py eval.

    python3 -I tests/test_scenarios.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import linefinder as L  # noqa: E402
from plans import pbe_comps  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
if not pbe_comps(S) or not L.odds_calibration():
    print("skip: needs MetaTFT PBE data and tools/eval_lines.py fit")
    sys.exit()
AP = ["Needlessly Large Rod", "Needlessly Large Rod", "Tear of the Goddess", "Tear of the Goddess"]
AD = ["B.F. Sword", "Sparring Gloves", "Recurve Bow", "B.F. Sword"]


def run(units=(), items=()):
    us = [{"unit": u.split(":")[0], "stars": int(u.split(":")[1]) if ":" in u else 1} for u in units]
    r = L.find(S, {"units": us, "items": list(items)})
    r["by"] = {c["name"]: c for c in r["comps"]}
    r["real"] = [c["name"] for c in r["comps"] if c["reachable"]]
    return r


def top(r):
    return r["suggested"][0]


def shown(r):
    """Suggested lines and the variants listed on their cards (same units, another carry)."""
    return [x for n in r["suggested"] for x in [n] + (r["by"][n].get("variants") or [])]


# openers lead to their comp family
assert top(run(["Ziggs", "Lulu"])).startswith("Hyperpop"), run(["Ziggs", "Lulu"])["suggested"]
# (a short list is padded with a stretch line: K/DA openers also lead to fast-9 Gu Feng on MetaTFT, which is fine)
kda_open = run(["Neeko", "Gragas", "Evelynn"])
assert top(kda_open).startswith("K/DA") and all(n.startswith("K/DA") for n in shown(kda_open) if kda_open["by"][n]["reachable"])
assert top(run(["Olaf", "Annie", "Karthus"])).startswith("Pentakill")
assert top(run(["Kayn", "Illaoi"])).startswith("Gu Feng")

# a 2-star 2-cost is tempo, not a reroll commitment: Renekton 2-star with Zoe and Annie isn't sent to a Renekton reroll
assert "Renekton" not in top(run(["Renekton:2", "Zoe", "Annie"]))
# Jax and Annie 2-stars with Elise and Yunara: the strong line that keeps Elise and Yunara, not the D-tier Annie reroll
assert top(run(["Jax:2", "Annie:2", "Elise", "Yunara"])) != "Swiftstriker Annie"

# a full late board is that comp, and a late board isn't marked down for early tempo (measured on openers only)
kda = run(["Akali (K/DA)", "Ahri", "Leona", "Kai'Sa:2", "Evelynn", "Gragas", "Lillia", "Neeko"], ["Infinity Edge", "Last Whisper"])
assert "K/DA Kai'Sa" in shown(kda) and all(n.startswith("K/DA") for n in shown(kda)), shown(kda)
assert all(c["gains"]["tempo"] == 0 for c in kda["comps"])
assert "Rock Vayne" in shown(run(["Vayne", "Yorick", "Pyke", "Locke", "Swain", "Camille", "Olaf"]))

# many units: only a few lines are realistic, never every comp
many = run(["Ziggs", "Neeko", "Olaf", "Kayn", "Jinx", "Graves", "Yuumi", "Pyke"])
assert len(many["real"]) <= 8 < len(many["comps"]) and len(many["suggested"]) <= L.SUGGESTIONS, len(many["real"])
# adding units of one comp narrows the lines, it doesn't widen them
sizes = [len(run(["Ziggs", "Lulu", "Swain", "Kobuko", "Teemo", "Tristana"][:k])["real"]) for k in (2, 4, 6)]
assert sizes[0] >= sizes[1] >= sizes[2] >= 1, sizes

# a 2-star Baron (7-cost) on a mixed board: the Baron line is offered, first
baron = run(["Mel", "Galio:2", "Shyvana", "Yone:2", "Yasuo", "Locke:2", "Braum", "Baron Nashor:2"])
assert top(baron) == "Prodigy Malzahar", baron["suggested"]

# components steer: AP components fit comps with AP carries better than AD-carry comps, and AD the other way round
_, build = L.recipes()
plans = {p["id"][4:]: p for p in L.pbe_plans(S)}


def carry_kind(r, name):
    return L.main_damage(plans[name], name)


for comps_, want in ((AP, "AP"), (AD, "AD")):
    r = run(items=comps_)
    kinds = {n: carry_kind(r, n) for n in r["by"]}
    mine = [r["by"][n]["gains"]["items"] for n, k in kinds.items() if k == want]
    other = [r["by"][n]["gains"]["items"] for n, k in kinds.items() if k == L.OFF[want]]
    # ahead, not by much: many AP carries' best-in-slot items are hybrid recipes built from AD components
    # (Guinsoo's = Bow + Rod, Jeweled Gauntlet = Gloves + Rod, Shojin = Sword + Tear), and an AP-led comp with an AD
    # second carry (K/DA: Ahri with Kai'Sa) has a home for AD items, so only comps with no carry of that type pay
    assert sum(mine) / len(mine) > sum(other) / len(other) + 0.01, (want, sum(mine) / len(mine), sum(other) / len(other))
# the same opener with AP vs AD components: the AP-carry Pentakill line gains more from the AP set
pk_ap, pk_ad = run(["Olaf", "Annie", "Karthus"], AP), run(["Olaf", "Annie", "Karthus"], AD)
assert pk_ap["by"]["Pentakill Karthus"]["gains"]["items"] > pk_ad["by"]["Pentakill Karthus"]["gains"]["items"]
# a component pair that builds the carry's best-in-slot item is worth more than one that builds nothing
assert run(items=["Recurve Bow", "Needlessly Large Rod"])["by"]["Hyperpop Kobuko Ziggs"]["gains"]["items"] > 0
# availability: Seraphine unlocks only by rerolling before 2-4, so a 5-unit Hyperpop board without her can't go
# Hyperpop Seraphine; a 2-unit opener still can
late_hp = run(["Ziggs", "Lulu", "Swain", "Kobuko", "Teemo"])
assert late_hp["by"]["Hyperpop Seraphine"]["closed"] == ["Seraphine"] and "Hyperpop Seraphine" not in shown(late_hp)
assert not run(["Ziggs", "Lulu"])["by"]["Hyperpop Seraphine"]["closed"]
# a 2-star Ziggs holding an item has Kobuko's unlock ready; going Hyperpop costs gold, staying in it costs less
zig = L.find(S, {"units": [{"unit": "Ziggs", "stars": 2, "items": ["Guinsoo's Rageblade"]}, {"unit": "Lulu", "stars": 1}]})
zb = {c["name"]: c for c in zig["comps"]}
assert any(a["unit"] == "Kobuko" and a["status"] == "ready" for a in zb["Hyperpop Kobuko"]["availability"])
assert zb["Hyperpop Kobuko"]["pivot_cost"]["gold"] < zb["Pentakill Kayle"]["pivot_cost"]["gold"] + 40

# augments: a hero augment is worth most where the hero is the itemised carry, a trait augment where the trait goes deep
tib = L.find(S, {"units": [{"unit": "Annie", "stars": 1}], "augments": ["Tibbers! I Can't See the Stage"]})
tb = {c["name"]: c["gains"]["augments"] for c in tib["comps"]}
assert tb["Ionic Spark Annie"] > tb["Pentakill Karthus"] + 0.3, (tb["Ionic Spark Annie"], tb["Pentakill Karthus"])
pk = {c["name"]: c["gains"]["augments"] for c in L.find(S, {"augments": ["Gathering Storm"]})["comps"]}
assert pk["Pentakill Kayle"] > pk["Slayer Viego"] + 0.2
# special items: an artifact leads to comps that play one of its usual holders (MetaTFT), an emblem to comps that run
# its trait, a radiant to comps whose carry deals its damage type
holders = set(L.meta.artifacts(S["set"])["Lich Bane"]["holders"])
lich = run(items=["Lich Bane"])
assert lich["suggested"] and all(holders & set(lich["by"][n]["units"]) for n in lich["suggested"]), lich["suggested"]
assert lich["by"]["Hyperpop Kobuko"]["gains"]["artifacts"] > lich["by"]["Arcanist Mel"]["gains"]["artifacts"]
for emblem, trait in (("Pentakill Emblem", "Pentakill"), ("K/DA Emblem", "K/DA"), ("Hyperpop Emblem", "Hyperpop")):
    r = run(items=[emblem])
    # at the comp's star levels: K/DA counts stars, so two 2-star K/DA units already run it
    active = lambda n: trait in L.trait_tiers(S, [{"unit": u, "stars": plans[n]["stars"].get(u, 1)} for u in r["by"][n]["units"]])
    assert r["suggested"] and all(active(n) for n in r["suggested"]), (emblem, r["suggested"])
    # and on a mixed board it moves the trait's comps ahead of ones where it would sit dead
kda_e = run(["Gragas", "Neeko", "Jinx", "Shyvana"], ["K/DA Emblem"])
assert top(kda_e).startswith("K/DA") and kda_e["by"]["Gu Feng Xayah Jinx"]["gains"]["emblems"] < 0
for radiant, want in (("Radiant Rabadon's Deathcap", "AP"), ("Radiant Infinity Edge", "AD")):
    r = run(items=[radiant])
    kinds = {n: carry_kind(r, n) for n in r["by"]}
    mine = [r["by"][n]["gains"]["artifacts"] for n, k in kinds.items() if k == want]
    other = [r["by"][n]["gains"]["artifacts"] for n, k in kinds.items() if k == L.OFF[want]]
    assert sum(mine) / len(mine) > sum(other) / len(other), (radiant, sum(mine) / len(mine), sum(other) / len(other))
# a settled board (3-star Kobuko and Ziggs) isn't padded with lines its units rule out: only lines the odds allow or
# that carry its 3-stars (an unitemised 2-star Shyvana is frontline, not a reason to go Frontman Shyvana)
done = run(["Kobuko:3", "Ziggs:3", "Teemo:2", "Lulu:2", "Shyvana:2", "Swain:2", "Tristana"])
best_odds = max(c["odds"] for c in done["comps"])
assert all(done["by"][n]["odds"] >= L.odds_calibration().get("tau_stretch", 0) * best_odds - 1e-4 or done["by"][n]["anchors"]
           for n in done["suggested"]) and all(n.startswith("Hyperpop") for n in done["suggested"]), done["suggested"]
# your carry anchors its lines: a 3-star Vayne on a board of filler still gets Rock Vayne, a 2-star Jinx holding
# Rageblade and Kraken gets a Jinx comp, a 3-star Annie both Annie comps
vay = run(["Vayne:3", "Zac", "Graves", "Lulu", "Shyvana", "Galio"])
assert top(vay) == "Rock Vayne" and vay["by"]["Rock Vayne"]["anchors"][0]["unit"] == "Vayne", vay["suggested"]
jinx = L.find(S, {"units": [{"unit": "Jinx", "stars": 2, "items": ["Guinsoo's Rageblade", "Kraken's Fury"]}] +
                  [{"unit": x, "stars": 1} for x in ("Braum", "Vi", "Zoe", "Galio")]})
assert jinx["suggested"][0] == "Ionic Spark Jinx", jinx["suggested"]
ann = run(["Annie:3", "Tibbers", "Jax", "Vi", "Shyvana", "Graves"])
assert {"Ionic Spark Annie", "Swiftstriker Annie"} <= set(shown(ann)), shown(ann)
# 1-star filler anchors nothing
assert not any(c["anchors"] for c in many["comps"])
# tempo (HP at 4-1, planning / review): with low HP the line that rolls now gains on the one that spikes at 5-2; with
# high HP the greedier line catches up -- Hyperpop Kobuko (rolls 4-1) vs Ionic Spark Jinx (rolls 5-2)
duel = ["Ziggs:2", "Lulu:2", "Kobuko", "Jinx", "Shyvana", "Gwen", "Aurora"]
gap = {}
for hp in (20, 90):
    r = L.find(S, {"units": [{"unit": u.split(":")[0], "stars": int(u.split(":")[1]) if ":" in u else 1} for u in duel], "stage": "4-1", "hp": hp})
    by = {c["name"]: c for c in r["comps"]}
    gap[hp] = by["Ionic Spark Jinx"]["adjusted_place"] - by["Hyperpop Kobuko"]["adjusted_place"]
    assert by["Ionic Spark Jinx"]["tempo_note"]["online"] == "5-2"
assert gap[20] > gap[90] + 0.3, gap
# and two Gu Feng lines from one board swap order: at 20 HP the 4-2 line, at 90 HP the 5-2 fast 9
gf = ["Neeko:2", "Gragas:2", "Evelynn", "Xayah", "Wukong", "Janna", "Leona"]
order = {}
for hp in (20, 90):
    r = L.find(S, {"units": [{"unit": u.split(":")[0], "stars": int(u.split(":")[1]) if ":" in u else 1} for u in gf], "stage": "4-1", "hp": hp})
    by = {c["name"]: c["adjusted_place"] for c in r["comps"]}
    order[hp] = by["Gu Feng Wukong"] < by["Gu Feng Xayah"]
assert order[20] and not order[90], order
print("scenarios ok")
