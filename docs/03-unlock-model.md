# 03 — Unlock Model

How unlock conditions are represented, tracked, and turned into a probability.

## Condition taxonomy

Derived from Set 16's 40 conditions and Set 19's 36. Every condition seen so far is a combination of these primitives.

| Type | Meaning | Set 19 examples | Evaluable from one frame? | Can become impossible? |
|---|---|---|---|---|
| `BOARD` | Field N (unique) units of trait set T | Evelynn, Alune, Kayle, Zac | Yes | No |
| `BOARD_STARS` | Sum of star levels across units of T | Syndra, Yasuo, Mordekaiser, K/DA Akali | Yes | No |
| `TRAITS_ACTIVE` | N traits active (from a list, or any) | Galio, Smeech | Yes | No |
| `ITEMS_ON` | N items (or a specific item) on a unit of T | Ashe, Nasus, Renata, Samira, Jinx, Alistar | Yes | No (but needs components) |
| `UNIT_STATE` | Named unit at N stars and/or N items | Kobuko, Tibbers, Aphelios | Yes | Practically, if contested |
| `POSITIONAL` | Board layout constraint at combat start | Vladimir, Taliyah | Yes | No |
| `ECON_SNAPSHOT` | Gold ≥ N at a moment | Pyke | Yes | No |
| `WINDOW` | Do X N times before round R | Seraphine | No (needs history) | **Yes, hard deadline** |
| `ACCUM_ROUNDS` | Field T for N combats | Vayne | No | Practically, late |
| `ACCUM_COMBAT` | Combat stat total (damage, casts, kills, seconds, cheers) | Lulu, Tristana, Thresh, Wukong, Lee Sin, Gwen, Sona, Baron (part) | No, and not computable | Practically, late |
| `ACCUM_RESOURCE` | Trait currency total | Teemo (Hype), TD Akali (Bling) | No (read counter) | Practically, late |
| `ACCUM_ECON` | Economy total while a condition holds | Janna (interest with Xayah) | No | Practically, late |
| `STREAK` | N consecutive wins or losses | Rakan | No | No, but costly |
| `COLLECT` | Acquire a set of special shop offerings | Baron's ensemble | No | Practically, late |

Modifiers that wrap any primitive:

- `min_level`: player level gate (7, 8, 9, 10).
- `requires_fielded`: a gate unit or active trait must be present while counting (Xayah, Malzahar, "with Hyperpop active").
- `excludes`: fails permanently if another unlock has happened (the Akalis).
- `escalates`: threshold rises after related unlocks (Set 16 Shurima). Not seen yet in Set 19; keep support.
- `all_of` / `any_of`: composition (Baron = collect AND damage; Rakan = win-streak OR loss-streak).

## Rule format

One YAML file per patch, e.g. `data/19.1/unlocks.yaml`. Hand-authored; ~2 hours per set, minutes per patch.

```yaml
- unit: Mordekaiser
  cost: 5
  role: capstone            # flex | capstone | chase (Riot's categories)
  when:
    board_stars: {traits: [Pentakill], unique: true, n: 11}

- unit: Vayne
  cost: 4
  role: flex
  min_level: 7
  when:
    accum_rounds: {requires_trait_active: Rock, n: null}   # null = threshold not yet known

- unit: Wukong
  cost: 4
  role: chase
  when:
    accum_combat: {stat: ally_damage, requires_fielded: Xayah, n: null}

- unit: Akali_KDA
  cost: 5
  role: capstone
  excludes: [Akali_TrueDamage]
  when:
    board_stars: {traits: [KDA], unique: true, n: null}

- unit: Aphelios
  cost: 5
  role: capstone
  when:
    any_of:
      - unit_state: {unit: Alune, stars: null}    # Alune is itself an unlock
      - unit_state: {unit: Yone, stars: null}

- unit: Baron_Nashor
  cost: 7
  role: chase
  pool: special
  when:
    all_of:
      - collect: {set: baron_ensemble, n: 5, requires_fielded: Malzahar}
      - accum_combat: {stat: unit_damage, unit: Malzahar, n: null}

- unit: Seraphine
  cost: 2
  role: flex
  when:
    window: {event: reroll, n: null, before: "2-carousel"}
```

A `null` threshold makes the engine treat the unlock as "progress unknown" and exclude it from scoring until filled. A loader test must fail on any unit, trait or item name not in the patch's static data.

The dependency graph (Ziggs→Kobuko, Annie→Tibbers, Xayah→{Wukong, Janna, Lee Sin}, Alune|Yone→Aphelios, Malzahar→Baron, Akali⊕Akali) is derived from these rules at load, not written separately.

## Progress tracking

Each unlock has a tracker with one of these states:

`LOCKED_IDLE → IN_PROGRESS → READY (will unlock next check) → UNLOCKED`, plus `DEAD` and `BLOCKED` (excluded or gate missing).

Per-round tracker inputs:

| Input | Source | Needed by |
|---|---|---|
| Board units, stars, items, positions | Vision | BOARD, BOARD_STARS, ITEMS_ON, UNIT_STATE, POSITIONAL, TRAITS_ACTIVE |
| Level, gold, interest earned | HUD | min_level, ECON_SNAPSHOT, ACCUM_ECON |
| Reroll count (from gold deltas and shop refreshes) | Derived | WINDOW |
| Round result, streak | HUD | STREAK |
| Combats with trait T active | Derived from board each combat | ACCUM_ROUNDS |
| Trait currency (Hype, Bling) | Trait tooltip / HUD counter | ACCUM_RESOURCE |
| Combat-stat progress | **Unlock UI progress text only** | ACCUM_COMBAT |
| Special shop items bought | Shop vision | COLLECT |

**Two sources of truth, reconciled.** Where the game shows "x / N" for an unlock, read it and treat it as authoritative. Where the engine can also compute progress (BOARD-type), compare the two each round; a mismatch is a vision bug or a rules-file bug and is logged. For ACCUM_COMBAT the UI is the only source. If it is not visible, the tracker reports "progress unknown" rather than estimating from nothing.

Rates for accumulators are an exponentially weighted average of per-round progress over the last 3–4 combats, scaled by expected board changes (more Hyperpop units → more casts).

## Feasibility: P(unlock by round r)

Handled in three tiers by how the condition behaves.

**Tier A: board-determined** (`BOARD`, `BOARD_STARS`, `TRAITS_ACTIVE`, `ITEMS_ON`, `UNIT_STATE`, `POSITIONAL`, `ECON_SNAPSHOT`).
The condition is a predicate on a future board. The economy simulator (see `04`) rolls shops forward under a buying policy and checks the predicate each round. No special math. Correlation with the plan is handled automatically: building Pentakill 7 is most of the way to Mordekaiser's 11 star levels.

**Tier B: accumulators** (`ACCUM_*`, `COLLECT`).
With progress `p`, threshold `N`, per-round rate `μ` and variance `σ²`, rounds needed is approximately `(N − p) / μ`. Model remaining progress over `k` rounds as Normal(`kμ`, `kσ²`) and take P(sum ≥ N − p). The rate applies only in rounds where the gate holds (Xayah fielded, trait active), and that comes from the simulator. Before any rate has been observed, use a per-unlock prior rate stored in the rules file and learned from recorded games.

**Tier C: path-dependent** (`WINDOW`, `STREAK`, `excludes`).
- WINDOW: exact. Rounds left in the window × actions affordable. Zero after the deadline.
- STREAK: Markov chain over streak length with per-round win probability from the strength model. Deliberate losing is a policy option the engine prices (HP cost) rather than assumes.
- EXCLUDES: not a probability. A hard constraint in plan enumeration: no plan may contain both sides.

Dead-end detection falls out: an unlock is `DEAD` when P(unlock by the last round the player is expected to survive) is below a small epsilon. Expected survival comes from HP and recent damage taken.

## Cost of pursuing an unlock

Feasibility alone would recommend everything. Each pursuit is priced:

| Cost | How estimated |
|---|---|
| Gold | Units bought that are not in the plan (minus sell-back) |
| Tempo | Strength lost by fielding condition units instead of the best board, converted to expected HP loss per round |
| Item commitment | Components slammed onto a non-carry (recoverable only by selling the unit) |
| Economy | Interest forgone (rerolling for Seraphine) or rolls forgone (holding gold for Pyke/Janna) |
| Bench/board slots | Slots occupied by gate units |
| Exclusion | Value of the plans the unlock closes |

**Net value of an unlock** = (best plan value with it available by round r) − (best plan value without it) − cost. Alert types map directly:

- **Free**: net value > 0 and cost ≈ 0 (typical for ITEMS_ON on a unit already fielded).
- **Start now**: net value > 0 and delaying one round drops P(unlock) materially.
- **Closing**: tracked unlock whose required rate now exceeds observed rate.
- **Dead**: state `DEAD`; also greys out dependent plans.

## Set 19 specifics to model explicitly

- **Xayah gate.** Three unlocks and the whole Gu Feng trait hang on one 4-cost. The engine should surface "Xayah seen/owned" as a named fact and value an early Xayah copy above its board strength.
- **Hyperpop chain.** Start condition is a 1-cost (Ziggs). The "start now" alert for Hyperpop fires in stage 2 or not at all.
- **Akali fork.** When both Akali conditions are in progress, show both plan values side by side before either completes. If K/DA star levels are about to cross the threshold while the True Damage plan is worth more, warn.
- **Level-7 checkpoint.** At the round the player hits 7, re-evaluate all nine level-7 unlocks at once and show which become READY.
- **Positional reminders.** Vladimir and Taliyah are one-combat conditions. The engine picks the round where the fight is least at risk (PvE round or a large strength lead) and prompts once.
- **Prismatic Tour quests.** Same machinery, different payoff (a trait tier, not a unit). Model as unlock rules with `grants: trait_tier`.

## Validation plan

1. Encode Set 16's final (16.6+) conditions in the same format as a regression set; the taxonomy must cover all 40 without new primitives.
2. Unit-test each primitive against hand-built states.
3. From recorded Set 19 games: compare predicted unlock round distributions with actual unlock rounds; plot calibration per type.
