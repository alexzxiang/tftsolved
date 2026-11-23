"""Augment value from real games: the Kaggle "Team Fight Tactics matches" dataset (teckmengwong, CC0; Riot API data,
patches 12.12-12.23 = Sets 7 and 8, Master-Challenger, NA / EUW / KR / OCE). One row per player: placement, the
three augments in pick order (2-1, 3-2, 4-2), final traits and units with stars and items.

What it measures (least squares of placement, so each augment is judged with the player's other two augments held
fixed; 95% intervals from the residual spread). Every player takes one augment per round, so round effects alone
aren't identified: each kind is measured against a COMBAT augment taken in the same round, tiers against silver.
  kind x round x tier   what an augment of each kind is worth when taken at 2-1 / 3-2 / 4-2, and per tier
  fit                   trait augments: is the trait deep (2nd tier or higher), light (1st tier) or off on the final
                        board? hero augments: is the hero the carry (2+ items), fielded without items, or not fielded?
                        econ: did the player end on a level-9+ board? reroll: did they end with a 3-star unit?
                        (the comp-conditional value no public site publishes; it is still selection-biased: players
                        who abandon an augment's trait were often losing already)
Results go to data/models/augment_kaggle.json for tools/calibrate.py augments.

    python3 -I tools/kaggle_augments.py            # needs data/raw/kaggle_tft/extracted/*.csv (unzipped download)
"""
import csv
import glob
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "raw" / "kaggle_tft" / "extracted"
OUT = ROOT / "data" / "models" / "augment_kaggle.json"
ROUNDS = ("2-1", "3-2", "4-2")
FAST9_UNITS = 9
ECON = re.compile(r"\bgold\b|\bXP\b|interest|experience|\blevel", re.I)
ITEMS = re.compile(r"\bitems?\b|component|anvil|forge", re.I)
REROLL = re.compile(r"reroll|refresh", re.I)


def cdragon():
    f = ROOT / "data" / "raw" / "cdragon" / "tft_pbe.json"
    return {i["apiName"]: i for i in json.loads(f.read_text())["items"] if i.get("apiName")} if f.exists() else {}


def tier_of(api, info):
    """silver / gold / prismatic from the name or icon (I / II / III, 1 / 2 / 3), else None."""
    name = (info or {}).get("name") or ""
    m = re.search(r"\b(I{1,3})\+?$", name)
    if m:
        return ("silver", "gold", "prismatic")[len(m.group(1)) - 1]
    icon = ((info or {}).get("icon") or "").lower()
    m = re.search(r"(?:-|_)?(i{1,3}|[123])(?:-|_)?(?:plus)?\.tex$", icon)
    if m:
        g = m.group(1)
        return ("silver", "gold", "prismatic")[(len(g) if g.startswith("i") else int(g)) - 1]
    m = re.search(r"(\d)(?:Plus)?$", api)
    return ("silver", "gold", "prismatic")[int(m.group(1)) - 1] if m and m.group(1) in "123" else None


def kind_of(api, info, units, traits):
    """(kind, referenced unit or trait): hero / trait / econ / items / reroll / combat."""
    short = re.sub(r"^TFT\d+_Augment_", "", api)
    unit = next((u for u in sorted(units, key=len, reverse=True) if short.startswith(u)), None)
    if unit and re.search(r"(Support|Carry)", short) or (unit and not re.search(r"(Trait|Emblem|Crest|Crown|Heart|Soul)", short)
                                                       and api.startswith("TFT8")):
        return "hero", unit
    trait = next((t for t in sorted(traits, key=len, reverse=True) if t.lower() in short.lower()), None)
    if trait and re.search(r"(Trait|Emblem|Crest|Crown|Heart|Soul|Spirit|Essence)", short):
        return "trait", trait
    desc = (info or {}).get("desc") or ""
    if REROLL.search(desc):
        return "reroll", None
    if ITEMS.search(desc):
        return "items", None
    if ECON.search(desc):
        return "econ", None
    return "combat", None


def rows():
    """Deduplicated player rows: (placement, [3 augments], {trait: tier}, {unit: stars}, {unit: n items}, set)."""
    csv.field_size_limit(10 ** 9)
    seen = set()
    for f in sorted(glob.glob(str(DATA / "*.csv"))):
        with open(f, newline="") as fh:
            r = csv.reader(fh)
            h = next(r)
            ia = [h.index(c) for c in ("augment0", "augment1", "augment2")]
            ip, im = h.index("placement"), h.index("match_id")
            tcols = [(i, c.split("_", 1)[1]) for i, c in enumerate(h) if re.match(r"^Set\d+_", c)]
            ucols = [(i, c.split("_", 1)[1]) for i, c in enumerate(h) if re.match(r"^TFT\d+_[A-Za-z]+$", c)]
            icols = [(i, c.split("_")[1]) for i, c in enumerate(h) if re.match(r"^TFT\d+_.*_item\d$", c)]
            setn = "8" if any(c.startswith("Set8") for c in h) else "7"
            for row in r:
                key = (row[im], row[ip])
                if key in seen or not row[ip]:
                    continue
                seen.add(key)
                traits = {t: float(row[i]) for i, t in tcols if row[i] not in ("", "0", "0.0")}
                units = {u: float(row[i]) for i, u in ucols if row[i] not in ("", "0", "0.0")}
                items = Counter(u for i, u in icols if row[i] not in ("", "None"))
                yield int(float(row[ip])), [row[i] for i in ia], traits, units, items, setn


def ols(X, y, names):
    k = len(names)
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for x, t in zip(X, y):
        nz = [(i, v) for i, v in x.items()]
        for i, vi in nz:
            b[i] += vi * t
            for j, vj in nz:
                A[i][j] += vi * vj
    for i in range(k):
        A[i][i] += 1e-6
    inv = [[float(i == j) for j in range(k)] for i in range(k)]
    M = [row[:] for row in A]
    for i in range(k):                                         # Gauss-Jordan for coefficients and their variances
        piv = max(range(i, k), key=lambda r: abs(M[r][i]))
        M[i], M[piv], inv[i], inv[piv] = M[piv], M[i], inv[piv], inv[i]
        p = M[i][i]
        M[i] = [v / p for v in M[i]]
        inv[i] = [v / p for v in inv[i]]
        for r in range(k):
            if r != i and M[r][i]:
                f = M[r][i]
                M[r] = [a - f * c for a, c in zip(M[r], M[i])]
                inv[r] = [a - f * c for a, c in zip(inv[r], inv[i])]
    beta = [sum(inv[i][j] * b[j] for j in range(k)) for i in range(k)]
    sse = sum((t - sum(beta[i] * v for i, v in x.items())) ** 2 for x, t in zip(X, y))
    s2 = sse / max(1, len(y) - k)
    return {n: (beta[i], 1.96 * math.sqrt(max(0.0, s2 * inv[i][i]))) for i, n in enumerate(names)}


def main():
    cd = cdragon()
    data = list(rows())
    units = {u for _, _, _, us, _, _ in data for u in us}
    traits = {t for _, _, ts, _, _, _ in data for t in ts}
    tagged = {}
    for _, augs, *_ in data:
        for a in augs:
            if a and a not in tagged:
                tagged[a] = (*kind_of(a, cd.get(a), units, traits), tier_of(a, cd.get(a)))
    print(f"{len(data)} players ({len(data) // 8} games), {len(tagged)} augments; kinds "
          f"{dict(Counter(k for k, _, _ in tagged.values()))}; tiers {dict(Counter(t for *_, t in tagged.values()))}")
    # features: kind x round, tier, and fit for trait / hero augments; placement centred on 4.5
    names, idx = [], {}

    def col(n):
        if n not in idx:
            idx[n] = len(names)
            names.append(n)
        return idx[n]

    X, y = [], []
    marg = defaultdict(lambda: [0.0, 0])
    rates = defaultdict(lambda: [0, 0, 0])
    for place, augs, ts, us, items, _ in data:
        x = defaultdict(float)
        x[col("intercept")] = 1.0
        # the plans' end states for EVERY player, so econ / reroll "on" measure the augment's extra, not survival
        x[col("board:9+ units")] = 1.0 if len(us) >= FAST9_UNITS else 0.0
        x[col("board:3-star unit")] = 1.0 if any(v >= 3 for v in us.values()) else 0.0
        for r, a in enumerate(augs):
            if not a or a not in tagged:
                continue
            kind, ref, tier = tagged[a]
            fit = None
            if kind == "trait":
                fit = "deep" if ts.get(ref, 0) >= 2 else "light" if ts.get(ref, 0) > 0 else "off"
            elif kind == "hero":
                fit = "carry" if items.get(ref, 0) >= 2 else "other" if ref in us else "off"
            elif kind == "econ":                                # on plan: ended on a level-9+ board (9+ units)
                fit = "on" if len(us) >= FAST9_UNITS else "off"
            elif kind == "reroll":                              # on plan: ended with a 3-star unit
                fit = "on" if any(v >= 3 for v in us.values()) else "off"
            key = f"{kind}@{ROUNDS[r]}" + (f"|{fit}" if fit else "")
            if kind != "combat":                                # reference: a combat augment in the same round
                x[col(key)] += 1
            if tier and tier != "silver":                       # reference: silver
                x[col(f"tier:{tier}")] += 1
            m = marg[(kind, ROUNDS[r], fit)]
            m[0] += place
            m[1] += 1
            rt = rates[(kind, ROUNDS[r])]                      # how often takers reach each plan's end state
            rt[0] += len(us) >= FAST9_UNITS
            rt[1] += any(v >= 3 for v in us.values())
            rt[2] += 1
        if x:
            X.append(dict(x))
            y.append(place - 4.5)
    fit = ols(X, y, names)
    out = {"source": "Kaggle teckmengwong/team-fight-tactics-matches (CC0), patches 12.12-12.23, Sets 7-8, Master+",
           "players": len(data), "effects": {}, "marginal": {}}
    print("\neffect on placement vs a combat augment in the same round (tiers vs silver); - = better, 95% interval:")
    for n in sorted(names, key=lambda n: (n.split("@")[0], n)):
        b, ci = fit[n]
        out["effects"][n] = [round(b, 3), round(ci, 3)]
        print(f"  {n:26} {b:+.3f} ± {ci:.3f}")
    for (k, r, f), (s, c) in sorted(marg.items(), key=lambda x: (x[0][0], x[0][1], str(x[0][2]))):
        out["marginal"][f"{k}@{r}" + (f"|{f}" if f else "")] = [round(s / c, 3), c]
    # mediation: the end-state controls block the econ / reroll mechanism (reaching 9, hitting a 3-star), so add it
    # back as (how much more often takers reach it than combat takers in the same round) x (what reaching it is worth)
    b9, b3 = fit["board:9+ units"][0], fit["board:3-star unit"][0]
    out["indirect"] = {}
    print("\nindirect effect through the plan's end state (vs combat takers in the same round):")
    for kind, b, i in (("econ", b9, 0), ("reroll", b3, 1)):
        for r in ROUNDS:
            k, c = rates[(kind, r)], rates[("combat", r)]
            if k[2] and c[2]:
                dp = k[i] / k[2] - c[i] / c[2]
                out["indirect"][f"{kind}@{r}"] = [round(dp * b, 3), round(dp, 4)]
                print(f"  {kind}@{r}: {'9+ units' if i == 0 else '3-star'} rate {k[i] / k[2]:.1%} vs combat {c[i] / c[2]:.1%}"
                      f" -> {dp * b:+.3f} places")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
