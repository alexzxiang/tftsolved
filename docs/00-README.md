# TFT Solver — Preparation Docs

Snapshot date: 2026-11-16 (Set 19 "Prismatic Tour" on PBE; live 2026-12-01 with patch 19.1).

## What we are building

A screen-reading companion for Teamfight Tactics that, at every decision point, answers two questions:

1. **What is the best board to play right now** with the units, items and gold I have?
2. **What is the best board to end on**, given my items, augments, gold, HP, shop odds, and **which unlockable champions I can realistically unlock from here**?

Everything else (shop highlights, item slams, augment picks, "start this unlock now" alerts) is derived from those two answers.

## Why unlocks are the core of the problem

Set 19 has 94 champions, 36 of which start locked. Unlocks are now a permanent TFT mechanic. Every late-game board worth playing includes units that only exist if you did something earlier, so "which endgame is best" is no longer a static lookup. It depends on the path you took and the path still open. Existing overlays show the unlock conditions; none score reachability.

## Reading order

| File | Contents |
|---|---|
| `01-problem-definition.md` | Decisions the tool supports, outputs, non-goals, policy limits |
| `02-set19-data.md` | Set 19 roster, traits, all 36 unlock conditions, known thresholds, gaps |
| `03-unlock-model.md` | Condition taxonomy, rule format, progress tracking, feasibility math |
| `04-scoring-engine.md` | Game plans, economy simulation, scoring, early/mid-game boards |
| `05-state-capture.md` | What to read off the screen, how, and the game-state schema |
| `06-data-pipeline.md` | Data sources, match crawler, archetype mining, per-patch refresh |
| `07-roadmap-and-risks.md` | Milestones, PBE verification checklist, open questions, risks |

## Glossary

- **Unlockable**: a champion absent from your shop until its condition is met in the current game.
- **Gate unit**: a base champion that other unlocks require you to field (Xayah in Set 19, Azir in Set 16).
- **Plan / archetype**: a path of boards (early, mid, level 8, capped) with its required units, items and unlocks.
- **Reach probability**: chance of fielding a plan's key board by its deadline from the current state.
- **Accumulator**: an unlock that counts something over many rounds (Hype, damage, combats fielded).
- **Flex / Capstone / Chase**: Riot's own three categories of unlock in Set 19 (see `02`).
- **Tempo cost**: board strength (and so HP) given up to pursue a condition.

## Confidence labels used in these docs

- **[confirmed]** stated by Riot or consistent across multiple data sites.
- **[pbe]** from PBE-derived listings; will change before live.
- **[unknown]** not public yet; must be read in-game or from CommunityDragon PBE data.
- **[assumed-16]** true in Set 16, not yet verified for Set 19.
