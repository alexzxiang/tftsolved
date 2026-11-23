# Board strength, line selection, and where learning fits

Status 2026-11-19. Companion to `ROADMAP.md`; numbers are held-out by lobby on 506 crawled Set 18 Master+ lobbies.

## What makes a board strong, and how each part is learned

| Ingredient | Representation | Learned from | Status |
|---|---|---|---|
| Unit quality (same cost is not same power) | value per unit per star (`u:Ahri*2`) | crawled final boards, per set | built (`engine/board_model.py`) |
| Trait synergy, per tier step | value per trait tier, cumulative (`t:Spellweaver:3` = what the 3rd tier adds) | same | built |
| Items: how much a unit needs them, and BIS vs random | per unit: value of items on it (`it:`), and of its best-in-slot items (`bis:`); BIS = most common items on that unit in top-4 boards | same (item names are in match data) | built |
| Board size, raw gold | `units`, `gold`, `carry` (itemized starred carry) | same | built |
| Ability interactions (unit x unit) | pairwise interaction terms | needs tens of thousands of boards | later: factorization machine or tree ranker (LambdaMART) |
| Augments | none: not in Riot's match data | own recordings; the player's focus choices | via focus list |
| Positioning | none | board detector (M9) | later |

Model: listwise ranking of each lobby's whole finishing order (Plackett-Luce likelihood) on sparse features, Adagrad SGD; linear and readable. It replaced pairwise Bradley-Terry (same features), which it matches or beats on every held-out measure at a quarter of the training time. Models are compared on **same-round** pairs first, then **gold-matched** pairs (board gold values within 10%: no credit for "the more expensive board won"), all pairs last.

| Model | All pairs | Same-round pairs |
|---|---|---|
| gold value only | 74.8% | 56% |
| generic build quality | 79.3% | 57% |
| + one weight per trait | 81.6% | - |
| per unit-star + trait tiers + items/BIS + gold/carry (Bradley-Terry, 506 lobbies) | 82.4% | 60% |
| **same features, Plackett-Luce (562 lobbies; gold-matched 76.0%)** | **83.0%** | **60.8%** |

Same-round pairs (boards alive at the same moment) are the honest test of fight strength and stay near 60%: final boards also encode survival time. Telling the model during training how long each player survived (a per-round or per-stage term, dropped when scoring) made every measure worse (same-round 59.8%), and scoring never-seen unit-stars at their kind's average changed nothing, so neither is in. Round-by-round HP changes from recordings are the fix.

### Launch day and patches: priors

Weights start at, and are pulled back toward, an older model, with the weight of about 100 lobbies (`PRIOR_LOBBIES`): a patch moves them as far as its own lobbies show, further the more lobbies it has.

- **Same set, new patch** (`fit 19 --since PATCH_DATE --prior 19`): each feature starts at the last patch's weight. `--since` is required so the old model's lobbies aren't counted twice.
- **New set** (`fit 19 --prior 18`): no unit or trait name carries over, so each feature starts at the older set's average for its kind: a 4-cost 2-star, a trait's 2nd tier, items on a unit, best-in-slot items, plus board size, gold and carry as they are. The model file keeps these averages (`kinds`).

Backtest on Set 18 in time order: a model on the oldest 300 lobbies is the prior, a few newer lobbies train the new model, the newest 162 are the test (same-round / gold-matched / all pairs):

| New lobbies | No prior | Kinds prior (as on launch day) | Same-set prior (as on a patch) |
|---|---|---|---|
| 25 | 56.5 / 59.3 / 71.6% | 60.8 / 71.9 / 81.0% | 61.0 / 71.5 / 80.7% |
| 50 | 56.2 / 64.6 / 76.4% | 59.8 / 72.4 / 81.2% | 61.2 / 74.7 / 81.8% |
| 100 | 61.5 / 70.7 / 80.1% | 61.5 / 74.9 / 82.6% | 62.2 / 76.9 / 82.8% |

More lobbies still help (no prior, 5-fold): 506 lobbies 82.4% all pairs; 962: 83.6% (gold-matched 76.9%); 1,162: 83.8% (77.1%); 1,962: 84.1% (77.2%). Same-round stays at 59-61% throughout: final boards can't say much more about who wins at one moment, which is what round-by-round recordings are for. At 1,162 lobbies, shrinkage from 0.001 to 0.1 and 20 vs 40 epochs are all within noise, so the defaults stay.

With a prior, 25 lobbies rank about as well as 300 without one (that model: 60.5 / 76.7 / 82.1%). Prior strengths of 25-200 lobbies all helped; 100 was best on all pairs and close to best on gold-matched, and same-round moved within noise (about ±2 points on ~400 pairs). Limits: this is one set without a known patch boundary inside it (the API reports no patch version), so it shows the value of a starting point when data is thin, not how far Set 18's kinds of weight transfer to Set 19.

## Strong comps should pull the algorithm, conditionally

- **Comp priors:** PBE/live comp averages (MetaTFT, private) attach placement to plans; plans rank by expected placement = P(reach) x plan placement + rest x fallback.
- **Conditions we can't observe** (augments, item components held, fast-9 vs reroll): the **focus list**. The player picks comps before the game (`plans.py --suggest`, `--focus`); alerts, targets and review follow them. Static pre-game plans are allowed in game under Riot's rules.
- **Conditions we can observe later:** items held (item bench vision), level and gold (HUD), unlocks (checker). Plan reach already conditions on gold, level, pool and unlocks.

## Early and mid game: lines, not boards

A line is a path: early board -> mid board -> capped plan. Built in `engine/lines.py` (items 1-3); item 4 needs data:

1. **Endgame anchors:** focused plans (or top expected-placement plans).
2. **Candidate boards now:** from owned units (purchase ledger + trait panel), enumerate boards of the current level; score = board model strength now + lambda(HP) x sum over anchors of how much the board keeps that anchor reachable (shared units, shared traits, unlock progress it feeds: Rock fielded -> Vayne). This is `docs/04` PlayNow with the learned model in place of the hand weights.
3. **Transition graph between plans:** edge weight = shared core units + shared item holders + shared unlock prerequisites; used to suggest pivots that keep items and units.
4. **Early-board data:** MetaTFT/tftflow show early boards per comp (manual, private); own recordings give the real thing once games are recorded.

## Learning techniques, in order of payoff

1. **Supervised ranking (now):** the sparse listwise model above; retrain per set and per patch from the crawler, starting from the previous model.
2. **Interactions (more data):** factorization machine over unit and trait features, or a tree ranker; later a set model (unit embeddings + attention) when boards number in the hundreds of thousands.
3. **Fight outcomes (recordings):** round win/loss from HP changes gives same-moment labels; train the fight model on those, using the board model as features.
4. **Decision policies (last):** roll / level / spend / pivot as a policy over the economy simulator (`engine/reach.py` shops) with the fight model as the environment's combat step. Search (expectimax over the next few rounds) before reinforcement learning; RL only once the simulator is trustworthy, because a policy is only as good as its simulator. Riot's own agents used a learned fight predictor for the same reason.
