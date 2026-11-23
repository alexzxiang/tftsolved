# What machine learning and RL can do for the solver

Status 2026-11-19. Research note for after parsing is solid. Companion to [STRENGTH.md](STRENGTH.md) (current board model), [ROADMAP.md](ROADMAP.md) and [POLICY.md](POLICY.md) (no live advice: anything learned is shown before or after a game).

## Bottom line

1. **Data volume and label quality beat model choice.** Our learning curve still rises by about 0.8 points per 100 lobbies, and every published game-ML result that beat linear baselines had 10^4 to 10^5+ games. The Riot API can supply that volume. Crawl it before changing the model class.
2. **Our main modelling error is confounding, not capacity.** Final boards encode how long a player survived. Gold value alone ranks 74.8% of pairs; same-round pairs, the honest test, sit at 60%. Select models on same-round accuracy, and get round-level labels from recordings.
3. **Three cheap, stdlib-only upgrades come first:** a Plackett–Luce (listwise) loss, priors from the previous patch with shrinkage toward cost and trait groups, and descriptive "what strong players do here" norms from recorded and VOD games for the post-game review.
4. **Don't build RL self-play.** There is no Set 19 combat simulator. Riot's own TFT agents replaced fight simulation with a learned predictor. Under Riot's rules a policy's output could only be shown after the game anyway.

## What has been done for TFT and auto-battlers

| Work | What it is | Lesson for us |
|---|---|---|
| Riot, GDC 2023, ["Machine Learning: Simulating Teamfight"](https://www.gdcvault.com/play/1028851/Machine-Learning-Simulating-Teamfight) (Ran Cao) | Riot trained RL agents on a lightweight copy of TFT that **predicts fight outcomes with a neural network instead of simulating them**, and used it to test design changes cheaply. The public page gives no architecture or accuracy figures. | Even Riot, with the source code, didn't simulate combat for RL. A learned fight predictor is the right environment step (ROADMAP "Learning techniques" item 4 already assumes this). |
| [silverlight6/TFTMuZeroAgent](https://github.com/silverlight6/TFTMuZeroAgent) | Community MuZero-style project on a hand-built **Set 4** simulator (shop, pool, combat, items), packaged as PettingZoo/Gymnasium environments with separate positioning and item-assignment envs. 735 commits; the README reports no results and no compute figures. | Years of simulator work, frozen to one set, with no published strength result. A single person can't keep a simulator current with a set that changes every 4 months and is patched every 2 weeks. |
| [tacticians-academy/teamfight-simulator](https://github.com/tacticians-academy/teamfight-simulator) | TypeScript fight simulator for Set 6.5. The README says values are partly approximated and lists unimplemented engine features. | Combat simulators exist but lag sets and are approximate. Not a usable Set 19 environment. |
| [TFT Set 13 placement project](https://wihi1131.github.io/Machine-Learning-Project/Conclusions) | ~1,500 Challenger games, trait-count features. Logistic regression 71%, SVM 72%, random forest ~70% on top-4 classification; exact placement is much harder. The degree-2 kernel suggests trait pairs matter. | A useful baseline: per-player top-4 classification from traits alone reaches ~70%. Our pairwise 82.4% measures something different (and is inflated by survival). |
| [Hearthstone Battlegrounds MCTS assistant](https://easychair.org/publications/paper/Kftf) (EPiC 2022) | MCTS over shop and battle with a learned simulation; reports fewer lost turns than experienced players on a small test set. | Search plus a learned evaluator works in an auto-battler at small scale. |
| [Świechowski et al., MCTS + supervised nets in Hearthstone](https://arxiv.org/abs/1808.04794) | Small networks trained to score positions, used inside MCTS: higher win rate at lower compute. | Train the value model first; search is a cheap layer on top. |

**Analogs worth copying**

- **MTG draft.** [Ward et al.](https://arxiv.org/abs/2009.00655) (100k+ Draftsim drafts): a neural net predicts human picks best, Naive Bayes and an expert-tuned heuristic come next, simple heuristics last. [Rigaux & Kashima, CoG 2026](https://arxiv.org/abs/2607.04782): contextual card embeddings beat **linear baselines** at predicting deck strength, on large-scale draft data. Both results need volume. At our size, linear models are the right default.
- **MOBA draft.** [DraftRec](https://arxiv.org/abs/2204.12750): a hierarchical transformer trained on about 280k LoL and 50k Dota 2 matches does both pick recommendation and win prediction. That is the same "set of picks → outcome" problem as a TFT board, at 100x our data.
- **AlphaStar** ([DeepMind blog](https://deepmind.google/discover/blog/alphastar-grandmaster-level-in-starcraft-ii-using-multi-agent-reinforcement-learning/)): imitation of human replays alone beat 84% of active players. League RL with exploiter agents was needed to get past that. Lesson: imitation is the cheap first 80%.
- **OpenAI Five** ([arXiv 1912.06680](https://arxiv.org/abs/1912.06680)): 10 months of training on a game that kept changing, made possible by continual-training tools. Lesson: carry a model across patches instead of retraining from zero.
- **Pluribus** ([Meta AI](https://ai.meta.com/blog/pluribus-first-ai-to-beat-pros-in-6-player-poker/)): action and information abstraction, a self-play blueprint, and depth-limited search at play time. Trained on one 64-core CPU server in about 8 days for under $150. Lesson: abstraction makes search affordable without GPUs. For us that means bucketing boards into comps and actions into coarse econ choices.
- **Legends of Runeterra** ([Anyscale write-up](https://www.anyscale.com/blog/riot-games-and-deep-reinforcement-learning-in-gaming)): Riot's RL self-play there is a balance-testing tool for designers, not a player coach.

**Bias in TFT stats.** Community analysts name survivorship bias as the main trap: final-board stats flatter late-game units and items ([elbroc](https://elbroc.substack.com/p/5-biases-that-stop-you-from-mastering-tft-stats-analysis-e1242ef92911)). Their fixes are to compare like with like (same cost, same augment tier) and to measure what changes when a factor is removed. [TFTable's "Necessity"](https://tftable.cc/blog/introducing-tftable) measures how much a unit's placement drops when an item is missing, as an alternative to raw placement delta. Our board model has the same bias.

## Techniques for our setting

Cost is on this Mac's CPU. The repo is stdlib-only today (no numpy, LightGBM or torch installed). "Have it?" refers to data.

| Technique | Data needed | Have it? | Cost | Value for us | Main risk |
|---|---|---|---|---|---|
| **Plackett–Luce listwise loss** (replace pairwise BT in `board_model.train`) | Full lobby orderings | Yes (Riot API) | Same as now; ~30 lines, stdlib | Medium: proper likelihood of the whole order, calibrated P(1st), P(top 4) and expected placement for `plans.py` | Small accuracy gain; still survival-confounded |
| **Shrinkage / hierarchical priors** (L2 toward previous-patch weights; new unit-stars toward a cost×star prior; traits toward a tier prior) | Previous patch's model plus few new lobbies | Yes from Set 18; per-patch after 12-02 | Trivial (change the `l2*w` term) | **High** on launch day and after each patch, when data is thin | Prior from the old set is wrong when a unit is reworked: decay it by patch distance |
| **Empirical-Bayes shrinkage of rates** (comp avg place, augment and item stats by sample size) | Counts with each average | Partly (MetaTFT pick rates; own crawl later) | Trivial | Medium: stops 30-game comps topping `plans.py` | None worth noting |
| **More crawl volume per patch** | Riot API, ~45 min per 2,000 games on a personal key | Yes | Hours of wall clock; pure-Python training gets slow above ~5k lobbies | **High**: the learning curve hasn't flattened | Rate limits; only Master+ biases toward expert play |
| **GBDT ranker** (LightGBM `rank_xendcg` / lambdarank, `group` = lobby) | 5k+ lobbies for interactions to pay | After crawling | Minutes; first non-stdlib dependency | Medium: finds unit×unit and unit×item interactions the linear model can't | Opaque; overfits on 500 lobbies. Use as a challenger, keep the linear model for explanations |
| **Factorization machine / unit embeddings** | 10k+ lobbies | After crawling | Minutes in numpy | Medium: pairwise synergies with few parameters; embeddings carry over to reworked units | Same as GBDT |
| **Deep Sets / Set Transformer** over board units ([1703.06114](https://arxiv.org/abs/1703.06114), [1810.00825](https://arxiv.org/abs/1810.00825)) | 10^5 boards (DraftRec scale) | Reachable only with sustained crawling | torch on CPU or MPS, fine | Low now, maybe later | Patch drift: a 2-week patch never reaches that scale. Pool sets and set-condition the model |
| **Fight model from recordings** (round win/loss and HP lost vs. own board and stage) | Per-round own board, HP, ideally opponent identity | Partly: HP and round result yes, board from ledger only, no opponent board | Logistic, trivial | **High**: the only same-moment label; needed by `lines.py` and any search | A handful of games; opponent unknown, so it learns "vs. an average lobby" |
| **Behaviour cloning / descriptive norms** (what strong players do at 3-2 with X gold and Y HP) | Per-round states of good players | Yes via `record.py --vod` on high-elo VODs, plus own games | Counts or a small logistic, trivial | **High** for review: replaces hand thresholds in `review.py` with "top players here levelled 80% of the time" | Copies habits, not optimal play; VOD use is the user's call (ROADMAP) |
| **Contextual bandit for augments** (offers → pick → placement; OPE per [Dudík et al.](https://arxiv.org/abs/1103.4601)) | Thousands of logged offer sets with the pick and placement | No: the Riot API has no augments, and recordings log offers but not the pick | Trivial once data exists | Low now; only with many users | Augment pick is confounded with board state. Offers are random, which helps, but the pick is not |
| **MCTS / expectimax with a learned value model** (econ decisions over `reach.py` shops + fight model) | A trustworthy fight model plus econ simulator | Econ yes; fight model no | Seconds per position if abstracted (comp buckets, coarse actions) | Medium-high **for post-game counterfactuals**, once the fight model exists | Garbage in, garbage out: the search is only as good as the fight model |
| **Combat simulator** | Every unit ability and item, each set and patch | No | Months per set | Low | Never current; Riot itself chose a learned predictor instead |
| **Full RL self-play** (MuZero, PPO, league) | A simulator | No | GPU-weeks in published work | Low for a pre/post-game tool | Policy output can't be shown live; exploits simulator errors |
| **Offline RL from replays** | 10^4+ trajectories with actions | No (a handful) | Medium | Low until data exists | Distribution shift, confounding |

## Ranked recommendations (after parsing is solid)

**Step 1: make the board model honest and patch-ready** (`engine/board_model.py`, about a day). **Done 2026-11-19**: Plackett-Luce is in and Bradley-Terry was retired (PL matched or beat it on every measure). Models are scored same-round first, then gold-matched. Priors are in (`--prior`, `--since`), and the backtest is in [STRENGTH.md](STRENGTH.md#launch-day-and-patches-priors). Not done: down-weighting old lobbies (a prior per patch replaces it), top-4 log loss, and the date-to-patch table, because `--since` takes the patch date by hand.
- Add `--loss pl`. The Plackett–Luce negative log-likelihood of a lobby ranked best first is the sum over k of [log Σ_{j≥k} exp s_j − s_k], with s = w·features. Use the same sparse features and Adagrad loop. Keep BT for comparison.
- Select and report models by **same-round accuracy** and top-4 log loss, not all-pairs accuracy, which rewards proxies for survival (gold alone: 74.8%). Add a "gold-matched" check: accuracy on pairs whose board gold values are within 10%.
- Replace `l2 * w[k]` with `l2 * (w[k] - prior[k])`. The prior is the previous patch's weight where the feature exists, else a back-off: the mean weight of same cost×star unit-stars, of same tier-step traits, and of `it:` across units. Down-weight old lobbies by patch distance. The patch has to come from `game_datetime` mapped to patch release dates: the 506 crawled Set 18 lobbies all report `game_version` as "TFT Unreal Version ?.?.?.?". This is what makes the 2026-12-02 launch day and every 2-week patch usable with a few hundred lobbies.
- Validate the way it will be used: train on patch N, test on the first ~200 lobbies of N+1 (needs the date-to-patch map; until then, train on older lobbies and test on the newest).

**Step 2: crawl for volume, then test interactions** (`tools/crawl.py`, `tools/launch_day.py`)
- Keep crawling every patch toward 5–10k lobbies (several overnight runs on a personal key). Rerun the learning curve; stop when it flattens.
- At ~5k lobbies, train a LightGBM ranker (`group` = lobby, same features, monotone where obvious) as a challenger. Only if it beats the linear PL model on same-round and next-patch accuracy by more than about a point, add a factorization-machine term to the linear model (keeps it readable). Skip deep set models until 10^5 boards per stable patch window.
- Apply empirical-Bayes shrinkage to every rate shown to the user (comp `avg_place` in `engine/plans.py`, augment and item stats): shrink toward the mean with a pseudo-count of ~50–100 games.

**Step 3: round-level labels and strong-player norms from recordings** (`capture/record.py`, `engine/review.py`, `engine/lines.py`)
**Started 2026-11-20**: the fight rows and the first fight model are in `engine/fights.py` (see ROADMAP "Fight model"); other players' levels are read from the player list badges. On 2 games the fit can't beat the prior yet. Not done: strong-player norms, `lines.py` weights.
- From each recorded game's `state.jsonl`, emit one row per PvP round: stage, level, gold, HP before, HP lost, win/loss, owned-board features (`board_model.features`), unread flags. A per-stage logistic model of round loss and HP lost on those features is the first fight model. Bootstrap it with the board model's score as a feature so it needs few games.
- Run `record.py --vod` over a corpus of high-elo VODs (ROADMAP covers the terms) and tabulate the decisions at checkpoints (level at 3-2/4-1, gold kept, roll-downs by HP band). Use these norms to set `review.py`'s `LINE`, `DANGER_*`, `BLEED_*` thresholds and to phrase notes as "strong players in this spot…". This is behaviour cloning in its simplest, explainable form.
- Fit `lines.py`'s `LINE_WEIGHT/UNLOCK_WEIGHT` on the same rows: does a line-keeping board at stage 3 predict final placement once strength now is controlled for?

**Later (needs Step 3's fight model):** post-game counterfactuals ("level at 3-2 instead of 3-5"). Do them model-based: replay the game from the decision point with `reach.py` shops, `econ.py` income and the fight model for HP loss; run a few hundred rollouts with a fixed simple policy for the rest of the game; report a placement range, not a point. This is depth-limited search over an abstraction, Pluribus-style, on a CPU, and it stays post-game.

## What not to do yet

- **RL self-play or MuZero.** It needs a simulator we don't have. The community's Set 4 effort shows no published strength after years, and Riot used a learned fight predictor even with source access. A learned policy also has nowhere legal to run live (POLICY.md: no "apps that dictate player decisions").
- **A combat simulator.** It costs months per set and is out of date at the next patch.
- **Deep set models or transformers now.** 500 lobbies is roughly 4k boards. Published wins over linear models use 10^5+ games. They would memorise the patch.
- **Augment bandits or augment win rates from our own data.** We have no logged picks and only a handful of games. Use the category-fit rules (`engine/augments.py`) plus private-reference stats until users generate data.
- **Causal claims from observational data** ("players who levelled at 3-2 placed 0.8 better"). Strong players both level on time and place well. Present such stats as norms, and present counterfactuals only from the model-based replay.
- **Selecting models on all-pairs accuracy.** It rewards survival proxies and would push the model toward "expensive boards win".

## Data to start collecting now

1. **Patch-tagged crawl, continuously.** Every patch from 2026-12-02. Tag each lobby with its patch from `game_datetime` plus a small table of patch dates (the API's `game_version` is a placeholder on the Unreal client), and keep the rank tier. Consider adding Diamond lobbies with rank as a feature to widen coverage.
2. **The augment actually picked.** Now stored as `picked` when the player opens the Augments panel later in the game (2026-11-19); otherwise unknown. Next: augment icon matching, or ask once after the game. Offers are randomised by the game, so offers plus pick plus placement is the dataset that later allows unbiased augment evaluation.
3. **The lobby's HP each round** from the player list on the right of the HUD. Now recorded (2026-11-19) as `lobby_hp` per round: the most common of 2+ readings for each of the 7 most-read names, small digits re-read 3x enlarged. The review uses it for HP rank. That gives same-moment strength labels for all 8 players, not just us, and the elimination order.
4. **Combat opponent per round** (name shown during combat). Joined to the opponents' final boards from the API, this gives an approximate opponent strength for the fight model.
5. **Match ID per recording.** Fetch the Riot match after the game by PUUID and timestamp, and store the join. This links our per-round partial states to the full lobby's final boards, items and placements.
6. **Items on board and bench** once M9 recognition lands. The fight model and the item planner need them.
7. **Model registry.** Save each fitted model with its patch, data window and held-out same-round and next-patch scores, so drift is measured rather than guessed.
8. **What the tool recommended pre-game.** Log the focus comps suggested and chosen, plus the outcome. If the tool ever has users, this is the log needed to evaluate its own suggestions offline.
