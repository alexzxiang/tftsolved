# 06 — Data Pipeline

What data the engine needs, where it comes from, and how it is refreshed.

## Sources

| Data | Source | Notes |
|---|---|---|
| Units, costs, traits, breakpoints, items, recipes, augments, ability values | CommunityDragon `raw.communitydragon.org/<patch or pbe>/cdragon/tft/en_us.json` | No key needed. PBE path has Set 19 now. Riot's Data Dragon lags and omits detail |
| Icons for template matching | CommunityDragon game assets | Paths are in the JSON |
| Unlock conditions and thresholds | Tooltip strings in the CommunityDragon JSON + in-game check | Hand-encoded into `unlocks.yaml` |
| Shop odds per level, pool sizes, XP table | Patch notes / in-game; community wikis | Small constants file per patch |
| Match outcomes | Riot `tft-match-v1` | End-of-game only: placement, level, last round, gold left, final units with stars and items, traits, augments |
| High-rank player list | Riot `tft-league-v1` (Challenger/GM/Master) | Seeds the crawler |
| Round-by-round data | **Own recordings only** | Riot's API has none; other sites' round data comes from their own apps and is not public |
| Meta priors before live data | PBE content creators, site tier lists (manual) | For hand-written plans only |

Do not scrape stats sites for bulk data. They have no public APIs and it adds a fragile dependency.

Note: the sandbox used to prepare these docs could not reach CommunityDragon, so the PBE JSON has not been inspected directly. First step on a normal machine: download it and extract the unlock strings and numeric variables.

## Static data build

`build_static.py <patch>` produces `data/<patch>/`:

- `units.json`: id, name, cost, traits, role, unlockable flag
- `traits.json`: breakpoints, members, counting rule (units vs. star levels for K/DA)
- `items.json`, `augments.json`
- `shop.json`: odds by level, pool sizes, XP table, special-pool units
- `unlocks.yaml`: hand-maintained (see `03`)
- `templates/`: icons

Loader tests: every name in `unlocks.yaml` and in plan files resolves; breakpoints monotone; counts match the known totals (94 units, 36 unlockables for 19.1).

## Match crawler

Riot API key tiers: development keys expire daily and are heavily rate-limited; a personal key is suitable for a personal project. Production keys require an approved product, which this is not.

Loop:

1. Pull Master+ ladders per region.
2. For each player, list recent match IDs; dedupe.
3. Fetch matches for the current patch only; store raw JSON (one row per match) and a flattened participant table.
4. Respect rate limits with a token bucket; resume from a cursor.

Volume: a few thousand matches (8 participants each) per patch is enough for plan clustering; 20–50k for item and augment conditioning. Store in SQLite or Parquet.

**Policy note on augments.** Riot's rules bar published tools from showing augment win rates or average placements. Using augment–board associations privately inside the engine is a different thing from publishing them, but keep these tables out of anything shared.

## Archetype mining

1. Represent each final board as a bag of units weighted by cost and stars, plus active trait tiers.
2. Cluster (HDBSCAN or agglomerative on Jaccard/cosine distance). Target 40–80 clusters at ≥ 0.5% play rate.
3. Per cluster: core units (present in > 70%), flex slots, carry units (most items), item sets per carry, level distribution, placement distribution.
4. Tag required unlocks: any unlockable in the core. Record how often the cluster appears *with* vs. *without* each unlockable, and the placement difference. That difference is the payoff of the unlock for that plan.
5. Conditioning: placement by carry-item match and by augment category, with shrinkage toward the cluster mean for small samples.
6. Emit plan files (see `04`), keeping stable IDs across patches by matching clusters on core units.

What end-of-game data cannot give:

- When units were unlocked or bought. Only that they were on the final board.
- Early and mid boards. Players who placed 7th–8th died early; their final boards are a rough proxy for mid-game boards of that line, biased toward failure.
- Why a line failed.

So unlock timing, accumulator rates, and early-board quality come from own recordings.

## Own-game recordings

Every game the tool watches is logged in the schema from `05`. From these:

- Accumulator rate priors per unlock (progress per combat vs. board composition).
- Unlock round distributions for calibration.
- Round win/loss vs. board features for the strength model.
- Labelled crops for the unit classifier.
- Review-mode test cases.

Recording VODs of strong players and running the capture pipeline over them is a way to get more round-by-round data without playing. It is slower and needs a spectator-view layout, so treat it as optional.

## Cold start at Set 19 launch

There is no ranked data until 2026-12-01, and the first week's data reflects players still learning the set.

- Weeks −2 to 0 (PBE): structural plans, hand priors, rules file, capture assets. PBE matches are not a reliable API data source; rely on own PBE recordings.
- Week 1: crawl daily; clusters unstable; keep structural plans and blend in data with low weight.
- Week 2+: data-driven plans dominate. Treat each placement estimate as a posterior: prior from structure, updated by observed matches, with the prior worth ~200 games.

## Per-patch refresh

Patches land roughly every two weeks; B-patches in between.

1. Rebuild static data; diff against previous patch; flag changed unlock strings automatically.
2. Update `unlocks.yaml` thresholds from the diff.
3. Restart the crawl for the new patch; carry over plan priors, discounted.
4. Re-run loader tests and the Set 16 regression set.
5. Spot-check capture on one game (HUD changes are rare but happen).

## Storage layout

```
data/
  19.1/ units.json traits.json items.json augments.json shop.json unlocks.yaml templates/
  plans/19.1/*.yaml
matches/19.1/raw.parquet participants.parquet
recordings/<game-id>/state.jsonl frames/
models/strength/ unit-classifier/
```
