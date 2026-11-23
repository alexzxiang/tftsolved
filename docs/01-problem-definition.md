# 01 — Problem Definition

## The player's decisions

TFT is a sequence of small decisions under uncertainty. The tool supports these:

| Decision | When | What the tool must know |
|---|---|---|
| Buy / skip each shop unit | Every shop | Plans in play, pairs held, unlock progress the unit feeds |
| Roll, level, or save | Every planning phase | Gold, level, XP, HP, shop odds, plan deadlines |
| Which units to field | Every planning phase | Current strength vs. unlock progress vs. economy |
| Slam or hold items | Whenever components arrive | Plan item needs, unlocks gated on items |
| Augment choice | 3 times per game | How each option shifts plan values |
| **Start, continue or abandon an unlock** | Continuously | Progress, remaining rounds, cost, payoff |
| Commit to an endgame | Mid game | Reach probability of each plan |

The unlock decision is the new one. It has properties the others lack:

- **Deadlines and dead ends.** Some conditions expire (reroll before Stage 2 Carousel) or become unreachable in practice (an accumulator never started).
- **Up-front cost, delayed payoff.** Fielding off-plan units or slamming items for a condition costs strength now.
- **Dependencies.** Some unlocks require another unlockable or a gate unit first.
- **Exclusivity.** Some unlocks permanently close others (the two Akalis).

## Outputs

Three panels, in priority order.

**1. Endgame plans (top 2–3).**
Each shows: target board, reach probability, expected placement value, the unlocks it needs with per-unlock status, and the single next action that most improves it.

> *Pentakill 7 + Mordekaiser. Reach 41%. Needs: Kayle (ready next round), Mordekaiser (7/11 star levels, likely by 4-5).*

**2. Play now.**
The board to field this round and why, with the trade-off stated when strength and progress conflict.

> *Field Rock 3 over Bodyguard 2: -6% fight win, +1 Vayne combat (3/5).*

**3. Unlock alerts.** Four kinds only, to stay quiet:

- **Free**: a fitting unlockable is one cheap action away.
- **Start now**: a valuable unlock whose window closes or whose counter must begin.
- **Closing**: a tracked unlock is falling behind the rate it needs.
- **Dead**: an unlock (and any plan depending on it) is no longer reachable.

Shop, item and augment hints are overlays on the game UI, ranked by how much each option changes the top plan values.

## Design principles

1. **One value function.** Every hint is "how much does this action change the value of my best reachable plans". No separate heuristics per feature.
2. **Rules are data.** Units, traits, unlock conditions, shop odds and pool sizes live in per-patch files. Riot retuned Set 16's unlocks mid-set; expect the same.
3. **Probabilities, not verdicts.** Show reach percentages and what they depend on. The player decides.
4. **Track from round 1.** Many conditions cannot be evaluated from a single frame.
5. **Degrade honestly.** If a value could not be read, say so and widen the estimate; never guess silently.
6. **Survive a set rotation.** Sets change every ~3.5 months. Only data files and vision templates should need replacing.

## Non-goals

- No input automation of any kind. Read-only.
- No fight simulator in v1. Board strength is a learned estimate.
- No positioning advice in v1 (except positional unlock conditions).
- No opponent-prediction features.

## Policy boundary

Riot's TFT developer policy prohibits published apps from making suggestions based on the player's current game state, from tracking opponents' boards, and from showing real-time data that immediately improves performance. It permits static pre-game recommendations and encourages post-game analysis. Memory reading is blocked for unknown apps as of October 2026.

Consequences for this project:

- **Live mode** is a personal, read-only tool. It is not publishable under the current policy, and using it sits in a gray area of Riot's terms. Decide deliberately whether to use it in ranked.
- **Review mode** runs the same engine over recorded games ("at 3-2 you could have started Vayne; it would have been ready by 4-1"). This is the form Riot's policy encourages and the form that could be shared.
- Build the engine so both modes use the same code. Review mode is also the test harness.

## Success criteria

- State capture: 99%+ field accuracy on HUD values and shop; unlock progress read correctly whenever visible.
- Unlock feasibility: predicted unlock-by-round probabilities are calibrated against recorded games (within ~10 points per bucket).
- Plan ranking: in review mode, the plan the engine ranked first at stage 3 is the one strong players actually ended on more often than any single alternative.
- Latency: full re-score under 1 second per planning phase on a normal desktop.
