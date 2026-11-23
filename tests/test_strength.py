# Board strength: features, synergy prior, a quick fit on the cached lobbies, constrained synergy search.
#   python3 -I tests/test_strength.py      (full held-out evaluation: python3 -I engine/strength.py fit)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from strength import QUALITY, features, fit, load_lobbies, pairs, search  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
cost = {u["name"]: u["cost"] for u in S["units"]}

# Pentakill 7: tiers 3/5/7 -> 1+2+3 = 6, plus Juggernaut 2 (Olaf, Yorick) -> 1
penta = [{"unit": u} for u in ("Gnar", "Olaf", "Karthus", "Viego", "Yorick", "Kayle", "Mordekaiser")]
f = features(S, penta)
assert f["synergy"] == 7 and f["units"] == 7, f
assert features(S, [{"unit": "Miss Fortune"}, {"unit": "Zeri"}])["synergy"] == 0      # solo traits aren't synergy
assert features(S, [{"unit": "Xayah", "stars": 2, "items": 3}])["carry_quality"] == 3 / 3 * 2 * 4 / 5

# Quick fit on the cached lobbies orders pairs at least as well as gold value alone
lob = load_lobbies()
if lob:
    w, g = fit(lob, QUALITY, iters=300), fit(lob, ["gold_value"], iters=300)
    acc = lambda wt, ks: sum(sum(wt[k] * v for k, v in zip(ks, d)) > 0 for _, r in lob for d, _ in pairs(r, ks)) / \
        sum(1 for _, r in lob for _ in pairs(r, ks))   # noqa: E731
    assert acc(w, QUALITY) >= acc(g, ["gold_value"]) - 0.01, (acc(w, QUALITY), acc(g, ["gold_value"]))

# Search: within budget, level gates respected, never both Akalis
for sc, board, traits, need in search(S, 8, None, restarts=8):
    assert len(board) == 8 and sum(cost[u] for u in board) <= 24, board
    assert "Smeech" not in board and not {"Akali (K/DA)", "Akali (True Damage)"} <= set(board)
    syn = features(S, [{"unit": u} for u in board])["synergy"]
    assert syn >= 3, (syn, board)                    # some trait at tier 2+ (score scale depends on weights used)
print("ok")
