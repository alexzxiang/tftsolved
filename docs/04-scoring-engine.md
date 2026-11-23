# 04 — Scoring Engine

Turns a game state into ranked plans and actions.

## Overview

```
state S ──► candidate plans ──► economy simulation (per plan) ──► plan values
                                        │                              │
                                 unlock trackers                 action deltas
                                                                       │
                                               play-now board, shop/item/augment hints, alerts
```

## 1. Plans

A plan is a path, not a final board:

```yaml
id: pentakill-7-morde
stages:
  early:   {core: [Gnar, Olaf, Karthus], traits: {Pentakill: 3}}
  mid:     {core: [Viego, Yorick, Kayle], traits: {Pentakill: 5}, level: 7}
  capped:  {core: [Mordekaiser, ...],     traits: {Pentakill: 7}, level: 9}
carries:   [{unit: Kayle, items: [...]}, {unit: Mordekaiser, items: [...]}]
unlocks:   [{unit: Kayle, by: "4-1"}, {unit: Mordekaiser, by: "5-2"}]
flex_slots: 2                    # filled by best available units
placement_prior: {mean: 3.9, n: 0}   # updated from match data
```

**Where plans come from**

- *Before live data exists (now through early December)*: generate from structure. For each band, build verticals at each breakpoint, add the band's capstone unlock, fill remaining slots with the highest-value class splashes. Add hand-written plans from PBE content creators. Give all a weak, equal placement prior.
- *After launch*: cluster final boards from high-rank matches (see `06`). Each cluster becomes a plan with a measured placement distribution, conditioned on items and augments where sample size allows. Early and mid stages are back-filled from the cluster's cheap units and from own-game recordings.

Plan count target: 40–80. Plans containing mutually exclusive unlocks are rejected at load.

## 2. Board strength

No fight simulator in v1. Strength is a scalar from a small learned model:

`strength = f(unit costs and stars, active trait tiers, item quality and fit, augments, level)`

- Start with a hand-weighted linear model (gold value of units, bonus per trait tier, bonus per completed item on a suitable holder).
- After launch, fit to match data: final-board features → placement. Then recalibrate on own-game recordings: board features → round win/loss.
- Fight win probability against the lobby = logistic(strength − lobby strength at this stage). Lobby strength per stage starts as a typical curve and is adjusted by observed results and by visible lobby HP and levels.

This is the weakest part of the system. Every output that depends on it (streaks, HP loss, risk) should carry wider uncertainty.

## 3. Economy simulator

A Monte Carlo rollout of shops and gold, with no fights.

State: gold, level, XP, HP, streak, bench, board, items, shop, unlock tracker states, round.

Per simulated round:

1. Income: base + interest + streak.
2. Policy acts: buy plan units and pairs, level or roll per the plan's curve, field the policy board.
3. Shop draws: by level odds and remaining pool. Unlockables appear only once unlocked. **[assumed-16]** a newly unlocked unit is guaranteed in the next shop; unlockables with zero copies held appear at reduced odds. Both are parameters until verified.
4. Fight outcome: Bernoulli from the strength model; HP loss from stage and survivors estimate.
5. Trackers advance (see `03`).

Policies are simple and per-plan: "buy plan units; hold pairs of plan units; level at these rounds; roll to gold floor X at these rounds; pursue unlocks U". Two or three policy variants per plan (greedy tempo, econ, unlock-first) are simulated and the best kept.

Output per plan: P(reach each stage by its deadline), distribution of unlock rounds, expected HP at each stage, P(dying before capped).

Budget: about 2,000 rollouts × ~15 rounds × ~60 plans. Prune first with a cheap analytic bound (units still needed × copies left in pool × expected shops) and fully simulate the top ~15. Rollouts are independent, so they vectorise or parallelise easily. Target under 1 second.

## 4. Plan value

```
Value(A | S) = Σ over outcomes [ P(outcome) × PlacementValue(outcome) ]
```

where outcomes are: reach capped board, stall at mid board, die early. `PlacementValue` maps expected placement to a score (for ranked, LP-like: 1st ≫ 4th > 5th ≫ 8th). In practice:

```
Value(A|S) ≈ P(capped) · V_capped(A, items, augments)
           + P(mid only) · V_mid(A)
           − P(bleed out) · penalty
```

`V_capped` comes from match data: average placement of that cluster, adjusted for how well the player's items match the plan's carries and for augment fit.

## 5. Early and mid game: option value

Early boards are flexible, so they are not scored as members of an archetype. A board `B` playable now is scored as:

```
PlayNow(B | S) = Strength(B) · w_now(HP, stage)
               + λ(HP) · Σ_top-k plans  Value(A | S after fielding B)
               + UnlockProgress(B)
```

- `Strength(B)` protects HP and streaks.
- The second term is option value: how much the board keeps the best plans reachable. Shared units, shared items, and gold preserved all show up through the simulator.
- `UnlockProgress(B)` is the gain in net unlock value from this round's progress (Rock fielded → +1 Vayne combat; Xayah fielded → Wukong/Janna/Lee Sin counters run).
- `λ` falls as HP falls: at 20 HP the present dominates.

Candidate boards: enumerate subsets of owned units up to board size. With ≤ 18 owned units this is small enough after pruning dominated units; otherwise greedy plus local swaps.

Keeping top-k plans rather than top-1 is what makes this "flexible": a unit that serves three live plans beats one that serves the current favourite slightly better.

## 6. Action hints

Every hint is a value delta computed with a cheap re-score (fewer rollouts, top plans only):

| Action | Delta computed |
|---|---|
| Buy shop unit | Σ plan value with unit owned − without, minus gold's alternative value |
| Roll vs. level vs. save | Best policy variant in the simulator for the next 1–2 rounds |
| Slam item X on unit Y | Strength now + unlock progress − loss of flexibility for plan carries |
| Augment option | Re-score top plans with the augment applied; include plans it newly enables |
| Position for an unlock | Net unlock value − fight risk this round |

Augment effects need a small per-augment adapter (economy augments change income; item augments change components; trait augments add emblems; Prismatic Tour augments add a quest). Start with the adapters for common categories and treat the rest as "strength + small constant".

## 7. Explanations

Each recommendation carries its top two contributing reasons, generated from the terms above, e.g. "Buy Xayah: gate for Wukong, Janna, Lee Sin (Gu Feng plan +9); pairs with held copy." No recommendation is shown without a reason.

## 8. Things deliberately left out of v1

- Opponent modelling beyond lobby HP/levels. Contested-unit estimates use only what the player has scouted and copies the player holds.
- Full fight simulation and positioning.
- Search over long action sequences. One-step lookahead with rollouts is the starting point; deeper search only if review-mode analysis shows it matters.

## 9. Evaluation

- **Calibration**: predicted reach and unlock probabilities vs. outcomes in recorded games.
- **Ablation in review mode**: for recorded games by strong players, how often does their next action fall in the engine's top 3?
- **Counterfactual sanity**: hand-built scenarios with an obvious right answer (accumulator never started at stage 5 → DEAD; free item unlock → Free alert; Akali fork).
