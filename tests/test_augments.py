# Augment tags, archetypes and fit; offer review on a recorded augment round.
#   python3 -I tests/test_augments.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import augments as A  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
CAT = A.catalog("TFTSet19")

# cards never seen before are tagged from their on-screen text (two real VOD cards)
assert A.tags("Punch Line", "Gain a Sett. Your strongest Sett becomes an Attack Fighter", S)[:2] == (["hero"], "Sett")
assert A.tags("Rolling For Days", "Gain 10 free Shop rerolls.", S)[0] == ["reroll"]
assert A.tags("X", "Gain an Artifact Anvil. After you open it, gain a Component Anvil.", S)[0][0] == "artifact_radiant"
if not CAT:                                                       # data/manual/augments.json: kept private
    print("ok (keyword tagging); skip: catalog checks need data/manual/augments.json")
    sys.exit()
# the catalog wins over keywords, primary category first
assert A.tags("Money Monsoon", "", S, CAT)[0][0] == "econ_gold"

reroll = {"id": "r", "trait": "Hyperpop", "core": ["Kobuko", "Ziggs"], "carries": ["Kobuko"], "roll_level": 5}
fast9 = {"id": "f", "trait": "Jazz", "core": ["Smeech", "Bard", "Galio"], "carries": ["Smeech"], "level": 9}
fast8 = {"id": "s", "trait": "Ionic Spark", "core": ["Jinx", "Gwen"], "carries": ["Jinx"], "level": 9}
assert [A.archetype(p, S) for p in (reroll, fast9, fast8)] == ["reroll", "fast9", "fast8"]   # Smeech: level-9 gate
fit = lambda p, name, desc="": A.fit(S, p, *A.tags(name, desc, S, CAT))          # noqa: E731
assert fit(reroll, "Rolling For Days") > fit(fast9, "Rolling For Days")          # rerolls suit reroll lines
assert fit(fast9, "Money Monsoon") > fit(reroll, "Money Monsoon")                # pure gold suits fast 9
assert fit(reroll, "Punch Line", "Your strongest Sett becomes") == 0             # hero augment off-plan
assert fit({**fast8, "core": ["Sett", "Jinx"], "carries": ["Sett"]}, "Punch Line", "Your strongest Sett") == 1.5

# offer review: final cards ranked for the line, rerolled cards listed
state = {"augment_offers": [{"stage": "4-2", "final": ["Soul Awakening", "Nesting Anvils+", "Giant and Mighty"],
                             "offered": ["Money Monsoon", "Nesting Anvils+", "Invested++", "Soul Awakening",
                                         "Giant and Mighty"], "desc": {}}]}
r = A.review_offers(S, state, [fast8], CAT)[0]
assert r["cards"][0]["name"] == "Nesting Anvils+" and r["rerolled_away"] == ["Money Monsoon", "Invested++"], r
print("ok")
