# Line finder (static filter over Set 19 comps) and the Set 19 board-strength transfer model.
# Needs the private MetaTFT files (data/manual/*metatft*, gitignored); skips without them.
#   python3 -I tests/test_linefinder.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import linefinder as L  # noqa: E402
import power  # noqa: E402
from plans import pbe_comps  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
if not pbe_comps(S) or not power._model(S["set"]):
    print("skip: no MetaTFT PBE data or Set 19 strength model (python3 -I engine/power.py build)")
    sys.exit()

# strength: stars and best-in-slot items add, Riot's cost ordering holds in the kinds
one = [{"unit": "Ziggs", "stars": 1}, {"unit": "Lulu", "stars": 1}]
two = [{"unit": "Ziggs", "stars": 2}, {"unit": "Lulu", "stars": 1}]
assert power.strength(S, two) > power.strength(S, one)
bis = power._model(S["set"])["bis"]["Ziggs"]
assert power.strength(S, [dict(two[0], items=list(bis))] + two[1:]) > power.strength(S, two)
k = power._model(S["set"])["kinds"]
assert k["u:cost4*2"] > k["u:cost3*2"]

# items are sorted into kinds; unknown names reported, not dropped silently
cat = L.catalog(S)
held = L.classify(["B.F. Sword", "Blighting Jewel", "K/DA Emblem", "Nonsense Item"], cat)
assert held["components"] == ["B.F. Sword"] and held["artifacts"] == ["Blighting Jewel"] and held["emblems"] == ["K/DA Emblem"]
assert held["unknown"] == ["Nonsense Item"]
assert len(cat["units"]) == len(S["units"]) and len(cat["augments"]) > 300

# every comp is shown (a board can pivot anywhere); Ziggs + Lulu lead to Hyperpop, which is suggested first;
# a 2-star Ziggs meets the Kobuko condition, shown but not weighted
r = L.find(S, {"units": [{"unit": "Ziggs", "stars": 2}, {"unit": "Lulu", "stars": 1}]})
assert len(r["comps"]) == len(pbe_comps(S))
assert r["suggested"] and r["suggested"][0].startswith("Hyperpop"), r["suggested"]
hk = next(c for c in r["comps"] if c["name"] == "Hyperpop Kobuko")
assert any("Kobuko" in m["why"] for m in hk["conditions_met"]) and hk["gains"]["conditions"] == 0
assert hk["pivot"]["keep"] == ["Ziggs", "Lulu"]
# pivots: a 2-star 2-cost opener doesn't force a reroll line; strong lines that keep part of the board come first
pv = L.find(S, {"units": [{"unit": "Jax", "stars": 2}, {"unit": "Annie", "stars": 2}, {"unit": "Elise", "stars": 1}, {"unit": "Yunara", "stars": 1}]})
by = {c["name"]: c for c in pv["comps"]}
best = by[pv["suggested"][0]]
assert best["adjusted_place"] <= min(c["adjusted_place"] for c in pv["comps"] if c["reachable"]) + 1e-9
assert best["pivot"]["tempo"] and (best["pivot"]["keep"] or best["pivot"]["opener"])      # keeps some units, sells others
everything = L.find(S, {"units": [{"unit": "Ziggs", "stars": 2}], "filters": {"min_fit": 0}})
assert len(everything["comps"]) == len(pbe_comps(S))

# tiers come first (tftflow order), then where your board leads
rank = {t: i for i, (t, _) in enumerate(L.tiers())}
order = [(rank[c["tier"]], -c["odds"]) for c in everything["comps"]]
assert order == sorted(order)

# hard conditions: must include, exclude, archetype
must = L.find(S, {"filters": {"must_units": ["Renata Glasc"]}})["comps"]
assert must and all("Renata Glasc" in c["uses"] or "Renata Glasc" in str(c["openers"]) + str(c["endgame"]) for c in must)
assert not any(c["name"] == "Bodyguard Jax" for c in L.find(S, {"filters": {"exclude_units": ["Renata Glasc"]}})["comps"])
fast9 = L.find(S, {"filters": {"styles": ["fast9"]}})["comps"]
assert fast9 and all(c["archetype"] == "fast9" for c in fast9)

# an artifact counts once, on its best MetaTFT holder in the comp, at the measured usual-holder premium; a comp with
# none of its usual holders gets the measured cost instead; its item condition then adds nothing more
jewel = {c["name"]: c for c in L.find(S, {"items": ["Blighting Jewel"], "filters": {"min_fit": 0}})["comps"]}
jax = jewel["Bodyguard Jax"]
art = next(n for n in jax["item_notes"] if n["item"] == "Blighting Jewel")
prem = L.measured_items()
assert art["holder"] == "Renata Glasc" and (not prem or abs(art["places"] + prem["artifact_fit"][0]) < 1e-3)
holders = set(L.meta.artifacts(S["set"])["Blighting Jewel"]["holders"])
off = next(c for c in jewel.values() if not holders & set(c["units"]))
assert not prem or next(n for n in off["item_notes"] if n["item"] == "Blighting Jewel")["places"] == -prem["artifact_misfit"][0]
assert all(m["places"] == 0 for m in jax["conditions_met"] if "Blighting" in m["why"])

# conditions move the expected place in the right direction and the tier follows it
plain = {c["name"]: c for c in L.find(S, {"filters": {"min_fit": 0}})["comps"]}
assert all(c["adjusted_place"] == c["avg_place"] for c in plain.values())
assert jax["adjusted_place"] < plain["Bodyguard Jax"]["adjusted_place"]
assert L.tier_of(3.0) == "OP" and L.tier_of(4.9) == "C"

# unlock conditions read as words
assert "a 2★ Annie holding an item" in L.describe({"unit_state": {"units": ["Annie"], "stars": 2, "items": 1}})
# team builder input: items on units count as held; bench units count for fit but not for the board's strength
tb = L.find(S, {"units": [{"unit": "Ziggs", "stars": 2, "items": ["Guinsoo's Rageblade"]}, {"unit": "Lulu", "stars": 1},
                          {"unit": "Teemo", "stars": 1, "bench": True}]})
hyper = next(c for c in tb["comps"] if c["name"] == "Hyperpop Kobuko")
assert any(n["item"] == "Guinsoo's Rageblade" and n["holder"] == "Ziggs" for n in hyper["item_notes"])
assert "Teemo" in hyper["uses"] and tb["your_board"]["level"] == 2
assert cat["trait_info"] and cat["recipes"]["Archangel's Staff"] == sorted(["Needlessly Large Rod", "Tear of the Goddess"])

# the page's script parses (node, if installed)
import re, shutil, subprocess, tempfile  # noqa: E401,E402
if shutil.which("node"):
    html = (ROOT / "tools" / "line_finder.html").read_text()
    js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "innerHTML" not in js                        # DOM methods only: names can't inject markup
# unlock conditions: every condition kind reads as words (no raw keys like "window:" or "n=")
for u in S["unlocks"]:
    text = L.describe(u["when"])
    assert text and "=" not in text and "_" not in text and ":" not in text, (u["unit"], text)

# win chance vs the typical board: stars and items raise it; a random pile of 1-stars is below par
import augvalue  # noqa: E402
weak = [{"unit": n, "stars": 1, "items": []} for n in ["Jax", "Annie", "Renekton", "Zoe", "Elise", "Yunara", "Kobuko"]]
strong = [{"unit": "Ziggs", "stars": 2, "items": ["Guinsoo's Rageblade"]}, {"unit": "Lulu", "stars": 2, "items": []},
          {"unit": "Swain", "stars": 1, "items": []}, {"unit": "Teemo", "stars": 1, "items": []}]
assert power.win_chance(S, weak) < 0.4 < 0.5 < power.win_chance(S, strong)
# stars: fights scale with HP x damage (x1.8 each per star), so a lone 3-star dominates a typical 1-unit board
solo = [power.win_chance(S, [{"unit": "Renekton", "stars": s, "items": []}]) for s in (1, 2, 3)]
# (a lone 1-star 2-cost is a bit above the typical level-4 slot, often a 1-cost: ~0.65 on the final-fight scale)
assert solo[0] < 0.75 and solo[1] - solo[0] > 0.2 and solo[2] > 0.95, solo
# expensive units hit harder (damage x cost^gamma, fitted): a 2-star 4-cost out-fights a 2-star 1-cost; the
# breakdown's parts say where a board stands, and items count against the typical board's
duo = [power.win_chance(S, [{"unit": u, "stars": 2, "items": []}]) for u in ("Yone", "Kayn")]
assert duo[0] > duo[1], duo
bd = power.fight_breakdown(S, strong)
assert set(bd["parts"]) == {"units", "items", "traits"} and bd["items"] == 1 and bd["typical_items"] > 0, bd
# vs the lobby at a round: the same board fades as the lobby levels and items up (MetaTFT levelling, Set 18 items)
if power._model(S["set"]).get("fight", {}).get("rounds"):
    lv8 = [{"unit": u, "stars": s, "items": []} for u, s in (("Mel", 1), ("Galio", 2), ("Shyvana", 1), ("Yone", 2), ("Yasuo", 1),
                                                           ("Locke", 2), ("Braum", 1), ("Baron Nashor", 2))]
    wins = [power.vs_lobby(S, lv8, r)["win"] for r in L.ROUNDS]
    assert all(a >= b for a, b in zip(wins, wins[1:])) and wins[0] > 0.8 > 0.5 > wins[-1], wins
    res = L.find(S, {"units": lv8, "stage": "4-2"})
    assert res["your_board"]["stage"] == "4-2" and res["your_board"]["typical_level"] > 6, res["your_board"]
    try:
        L.find(S, {"units": lv8, "stage": "9-9"})
        raise AssertionError("bad stage accepted")
    except ValueError:
        pass
# tempo: winning more fights is worth gold-equivalent (streak gold + HP), losing them costs it
assert augvalue.tempo_gold(0.8) > 0 > augvalue.tempo_gold(0.2)

# augments: a hero augment for a comp's carry beats one for a unit the comp doesn't play; an econ augment suits a
# fast-9 comp better than a reroll comp; a reroll augment the other way round
import augments as A  # noqa: E402
from plans import pbe_plans  # noqa: E402
cat_a = A.catalog(S["set"])
plans = {p["id"][4:]: p for p in pbe_plans(S)}
comps = {c["name"]: c for c in pbe_comps(S)}
hero = next(a for a, i in L.meta.augments(S["set"]).items() if i.get("hero_unit"))
hunit = L.meta.augments(S["set"])[hero]["hero_unit"]
withh = next((c for c in comps.values() if hunit in plans[c["name"]]["carries"]), None)
without = next(c for c in comps.values() if hunit not in c["units"])
if withh:
    v1 = augvalue.value(S, withh, plans[withh["name"]], L.archetype(S, plans[withh["name"]], withh), hero, cat_a)[0]
    v2 = augvalue.value(S, without, plans[without["name"]], L.archetype(S, plans[without["name"]], without), hero, cat_a)[0]
    assert v1 < 0 < v2, (hero, v1, v2)
f9 = next(c for c in comps.values() if c["style"] == "Fast 9")
rr = next(c for c in comps.values() if c["style"].startswith("lvl"))
econ = next(a for a, i in L.meta.augments(S["set"]).items() if i.get("category") == "econ_xp")
rer = next(a for a, i in L.meta.augments(S["set"]).items() if i.get("category") == "reroll")
val = lambda c, a: augvalue.value(S, c, plans[c["name"]], L.archetype(S, plans[c["name"]], c), a, cat_a)[0]   # noqa: E731
assert val(rr, rer) < val(f9, rer)

# stage boards: hexes on the 4x7 grid, no two units on one hex, a final tab last
for c in L.find(S, {"filters": {"min_fit": 0}})["comps"][:10]:
    assert c["stages"] and c["stages"][-1]["key"] == "final"
    for st in c["stages"]:
        hexes = [u["hex"] for u in st["units"]]
        assert all(0 <= h < 28 for h in hexes) and len(set(hexes)) == len(hexes), (c["name"], st["key"])
# data-backed calibrations are in the model (tools/calibrate.py via power.py build)
m19 = power._model(S["set"])
assert m19.get("par") and all(str(L) in m19["par"] for L in (4, 5, 6, 7, 8, 9)), m19.get("par")
ft = m19.get("finetune")
assert ft and ft["held_out"]["mae"] < ft["held_out"]["prior_mae"], ft        # applied only when held-out comps improve

# where your units lead: a probability over comps; Ziggs + Lulu lead to Hyperpop more than to an unrelated comp
odds = L.line_odds(S, {"Ziggs": 2, "Lulu": 1}, pbe_comps(S), L.meta.details(S["set"]))
assert abs(sum(odds.values()) - 1) < 1e-6
hyper_odds = max(v for n, v in odds.items() if n.startswith("Hyperpop"))
assert hyper_odds > odds.get("Slayer Viego", 0)
# expected LP follows the placement distribution: all-1st is +40, all-8th is -40
assert L.expected_lp({"placements": [1, 0, 0, 0, 0, 0, 0, 0]}) == 40 and L.expected_lp({"placements": [0] * 7 + [1]}) == -40
# comp item value: an item whose boards sit below the comp's average item is worth something, capped
# measured item premiums (tools/calibrate.py items): artifacts beat normal items, a best-in-slot item beats a non-BIS one
if prem:
    assert prem["artifact_fit"][2] < 0 < prem["artifact_misfit"][1] and prem["bis"][2] < 0     # whole intervals
    assert prem["radiant_fit"][0] < prem["radiant_ontype"][0] < prem["radiant_misfit"][0]             # radiants pay where wanted
    assert prem["emblem_used"][0] < prem["emblem_activates"][0] < prem["emblem_dead"][0]             # emblems in the comp's trait
# every weight that moves a comp's expected place is measured: tempo from MetaTFT openers, tiers from MetaTFT letters
assert L.tiers()[0][0] == "OP"
# expected place stays in 1-8 however much help piles up
assert 1 < L.adjust(3.0, 5.0) < 3.0 and L.adjust(3.0, -50) == 8.0
# augment values are on the measured scale (tools/calibrate.py augments, archived tactics.tools outcomes)
cal = augvalue.calibration()
if cal.get("bounds"):
    assert 0.3 < cal["scale"] < 1.5 and cal["round_step"]["econ"] > 0 > cal["round_step"]["combat"]
    for c in L.find(S, {"filters": {"min_fit": 0}})["comps"][:8]:
        for a in c["best_augments"]:
            assert a["places"] <= 0.6, a                  # no augment beyond what measured picks ever moved
    hyper_c = comps["Hyperpop Kobuko"]
    econ_aug = next(a for a, i in L.meta.augments(S["set"]).items() if i.get("category") == "econ_gold")
    e21 = augvalue.value(S, hyper_c, plans[hyper_c["name"]], "reroll", econ_aug, cat_a, round_idx=0)[0]
    e42 = augvalue.value(S, hyper_c, plans[hyper_c["name"]], "reroll", econ_aug, cat_a, round_idx=2)[0]
    assert e42 > e21                                     # econ taken at 4-2 is worth less than at 2-1 (measured)
# measured augment effects (tools/kaggle_augments.py, 40k Master+ games): off-plan picks cost more than on-plan ones
if augvalue.measured():
    eff = augvalue.measured()
    for r in ("2-1", "3-2"):
        assert eff[f"trait@{r}|off"][0] > eff[f"trait@{r}|deep"][0]   # a trait augment pays when the trait goes deep
        assert eff[f"trait@{r}|light"][0] > eff[f"trait@{r}|deep"][0]   # splashing it doesn't
        assert eff[f"reroll@{r}|off"][0] > eff[f"reroll@{r}|on"][0]
    assert eff["hero@4-2|off"][0] > eff["hero@4-2|carry"][0] + 0.3   # a late hero augment you don't field is costly
    assert eff["hero@3-2|other"][0] > eff["hero@3-2|carry"][0] + 0.2  # and fielding the hero isn't enough: carry it
    trait_aug = next(a for a, i in L.meta.augments(S["set"]).items() if i.get("trait") == "Hyperpop") if any(
        i.get("trait") == "Hyperpop" for i in L.meta.augments(S["set"]).values()) else None
    if trait_aug:
        on = augvalue.value(S, comps["Hyperpop Kobuko"], plans["Hyperpop Kobuko"], "reroll", trait_aug, cat_a, round_idx=1)[0]
        off = augvalue.value(S, comps["Slayer Viego"], plans["Slayer Viego"], "reroll", trait_aug, cat_a, round_idx=1)[0]
        assert off > on

# --- checks from the 2026-11-22 data and feature pass -------------------------------------------------------------
# board strength is on the final-fight scale (fitted on 1st vs 2nd: the last combat is between those two boards)
fight = power._model(S["set"])["fight"]
assert fight.get("label", "").startswith("1st vs 2nd") and fight["loglik"] > fight["same_round_loglik_refit"], fight.get("label")  # final fights: a cleaner label
kda8 = ["Akali (K/DA)", "Ahri", "Leona", "Kai'Sa", "Evelynn", "Gragas", "Lillia", "Neeko"]
one, two = (power.win_chance(S, [{"unit": u, "stars": st, "items": []} for u in kda8]) for st in (1, 2))
assert one < 0.05 < 0.1 < two, (one, two)             # a full board a star up is a different board
# Set 19 trait weights stay on Set 18's scale (the fine-tune once divided by a tiny slope and spread them 4x wider)
final = [power.rest_parts(power._model(S["set"]), S, [(b["unit"], b.get("stars", 1), b.get("items", [])) for b in c["board"]])["traits"]
         for c in pbe_comps(S) if c.get("source") != "lolchess" and c.get("board")]
mt = sum(final) / len(final)
assert (sum((x - mt) ** 2 for x in final) / len(final)) ** 0.5 < 1.2   # Set 18's top-2 boards: sd 0.74
# default comparison: the lobby at the round boards are usually your size; tiny and 10-unit boards keep the size par
assert L.usual_round(S["set"], 8) in ("4-5", "5-1") and L.usual_round(S["set"], 2) is None and L.usual_round(S["set"], 10) is None
lvl8 = L.find(S, {"units": [{"unit": u, "stars": 1} for u in kda8]})["your_board"]
assert lvl8["stage_auto"] and lvl8["stage"] == L.usual_round(S["set"], 8) and lvl8["win_size"] is not None
# no HP entered: the tempo term is zero (the board score's link to MetaTFT round win rates was measured flat)
assert all(c["gains"]["tempo"] == 0 for c in L.find(S, {"units": [{"unit": u, "stars": 2} for u in kda8[:4]]})["comps"])
# input at the trust boundary: wrong shapes are a ValueError (a 400), unknown units are reported, stars clamp to 1-4
for bad in ([], None, {"units": "Ziggs"}, {"items": "Infinity Edge"}, {"stage": {"Hyperpop Kobuko": "l7"}}, {"hp": 0}, {"hp": 101},
            {"hp": "50"}, {"hp": True},
            {"units": [{"unit": "Ziggs", "stars": "2"}]}, {"filters": {"sort": "nope"}}):
    try:
        L.find(S, bad)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
odd = L.find(S, {"units": [{"unit": "Nobody", "stars": 1}, {"unit": "Ziggs", "stars": 9}]})
assert odd["unknown_units"] == ["Nobody"] and odd["your_board"]["level"] == 1
# filters: MetaTFT's style label decides the archetype; the damage filter goes by the main damage carry's role
# (tank-role carries skipped), so the AD and AP lists split the comps with no overlap
ad = {c["name"] for c in L.find(S, {"filters": {"damage": "AD"}})["comps"]}
ap = {c["name"] for c in L.find(S, {"filters": {"damage": "AP"}})["comps"]}
assert not ad & ap and len(ad | ap) == len(pbe_comps(S)), (ad & ap, len(ad | ap))
assert {"Ionic Spark Annie", "Hyperpop Kobuko"} <= ap and {"Juggernaut Yorick", "Gu Feng Wukong", "Rock Vayne"} <= ad
assert all(c["style"] == "Fast 9" for c in L.find(S, {"filters": {"styles": ["fast9"]}})["comps"])
# trait-granted items (Gu Feng's Scrolls) never take a best-in-slot slot: no component builds them
gfx = plans["Gu Feng Xayah"]
assert not any(i.startswith("Scroll") for _, i in L.bis_slots(gfx, None, L.meta.units(S["set"]), list(gfx["items"])))
# MetaTFT's doubled-item rows ("2nd Gargoyle Stoneplate") fold into the item
assert not any(i.startswith("2nd ") for u in L.meta.units(S["set"]).values() for i in u["item_play"])
# --- tempo: the HP chain (engine/survival.py) -------------------------------------------------------------------
import json  # noqa: E402
import survival  # noqa: E402
fitd = json.loads((ROOT / "data" / "models" / "survival_TFTSet19.json").read_text())
assert 0 < fitd["sigma"] < 2.5 and fitd["max_place_error"] < 0.05, fitd["sigma"]     # interior ML fit; anchored to MetaTFT
assert all(abs(fitd["knockouts"]["chain"][s_] - fitd["knockouts"]["set18"][s_]) < 0.06 for s_ in ("4", "5", "6"))
for comp in ("Hyperpop Kobuko", "Gu Feng Xayah", "Prodigy Malzahar"):
    sh = [survival.scenario(S["set"], comp, "4-1", hp)["places"] for hp in (20, 50, 90)]
    assert sh[0] > sh[1] > sh[2], (comp, sh)                                         # more HP, better place
    typ = survival.scenario(S["set"], comp, "4-1", 50)["typical_hp"]
    assert abs(survival.scenario(S["set"], comp, "4-1", int(typ))["places"]) < 0.35    # a typical player: ~no shift
# lines that spike late (roll-down at 5-1 or later) lean on HP more than lines that roll by 4-1
_, _, rolls, _, _ = survival.anchored(S["set"])
sens = {c: survival.scenario(S["set"], c, "4-1", 25)["places"] - survival.scenario(S["set"], c, "4-1", 95)["places"] for c in rolls if rolls[c]}
late = [v for c, v in sens.items() if survival._rnd(rolls[c]) >= (5, 1)]
early = [v for c, v in sens.items() if survival._rnd(rolls[c]) <= (4, 1)]
assert sum(late) / len(late) > sum(early) / len(early), (sum(late) / len(late), sum(early) / len(early))
# top-4 share follows average place across MetaTFT comps (for comps without their own placements)
assert 0.6 < L.top4_line()(3.0) < 0.8 and L.top4_line()(3.0) > L.top4_line()(5.0)
print("ok")
