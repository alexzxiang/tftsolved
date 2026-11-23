# 07 — Roadmap, PBE Checklist, Risks

## Decisions needed from Alex

1. **Live vs. review first.** Review mode is policy-safe and easier to test; live mode is the stated goal. Recommendation: build the engine against the state log, ship review mode first, add the live overlay on the same engine.
2. **Capture source for prototyping.** Pure screen reading from day one, or an Overwolf adapter to feed the engine while vision is built.
3. **Stack.** Suggested: Python for capture, engine and data (OpenCV, ONNX Runtime, NumPy); a transparent always-on-top window (Qt or a small Electron/Tauri shell) for the overlay; simulator hot loop in NumPy or Rust if needed.
4. **Ranked use.** Whether live mode is used in ranked at all, given the policy position in `01`.

## PBE verification checklist (do this first, while Set 19 is on PBE)

Record screenshots for each.

**Unlock mechanics**
- [ ] Threshold for every one of the 36 conditions (tooltip text). Fill `unlocks.yaml`.
- [ ] Where unlock progress is displayed; numeric or bar; visible without clicking?
- [ ] Is a newly unlocked unit guaranteed in the next shop?
- [ ] Are shop odds reduced for an unlocked unit you hold no copies of?
- [ ] Does unlocking happen instantly or at round start/end?
- [ ] Do conditions check during PvE rounds? During planning or only at combat start?
- [ ] Do bench units count for BOARD-type conditions, or only fielded?
- [ ] "Unique star levels": confirm it means sum of stars across distinct units.
- [ ] Akali exclusion: is the other one greyed out immediately? Any way to reverse?
- [ ] Aphelios: confirm current condition (Alune/Yone stars vs. Recurve Bow).
- [ ] Teemo: Hype amount and how Hype is earned (per cast? per star level?).
- [ ] Baron: do instruments cost gold, take shop slots, need bench space? Is damage counted before or after collecting?
- [ ] Rakan: streak length; does it count streaks begun before level 8?
- [ ] Vayne / Janna / Wukong / Lee Sin: does progress pause or reset when the gate is removed?
- [ ] Pyke: gold threshold; checked every combat end?
- [ ] Vladimir / Taliyah: exact positional rule; what a "Beach Pop hex" is and how many there are.

**Set systems**
- [ ] Shop odds per level; XP per level; pool size per cost; pool for unlockables and 7-costs.
- [ ] Class trait breakpoints; True Damage breakpoints and A/B-Side rules.
- [ ] Prismatic Tour augment quests: list and thresholds.
- [ ] Collab: how the per-game roster is shown.
- [ ] Classical scroll options; level 11 odds.

**Capture**
- [ ] Standalone client window/process name; capture works with Vanguard.
- [ ] HUD positions at 1920×1080; any change from Set 18.
- [ ] Location of trait currency counters (Hype, Bling).

**Data**
- [ ] Download CommunityDragon PBE JSON; confirm unlock strings and numeric variables are present; script extraction.

## Milestones

| # | Deliverable | Depends on | Rough effort |
|---|---|---|---|
| M0 | Static data build + `unlocks.yaml` for 19.1 (and Set 16 regression file) + loader tests | PBE checklist | 3–4 days |
| M1 | Capture v1: HUD, stage, shop, augments, lobby HP → state log | — | 1 week |
| M2 | Unlock trackers + rule evaluator; "what is unlocked / ready / dead" from a state log | M0, M1 | 1 week |
| M3 | Economy simulator + Tier A/B/C feasibility; structural plans; plan values | M0 | 1.5–2 weeks |
| M4 | Bookkeeping inventory, trait checksum, unlock-progress reader | M1, PBE | 1 week |
| M5 | Review mode: replay a recorded game, show plan values and alerts per round | M2–M4 | 1 week |
| M6 | Crawler + archetype mining (after 2026-12-01) | Riot personal key | 1 week + ongoing |
| M7 | Live overlay UI (3 panels, shop highlights) | M5 | 1 week |
| M8 | Strength model fit; calibration reports; augment adapters | M6, recordings | ongoing |
| M9 | Unit classifier, items on units, board detector | recordings | 2+ weeks |

M0, M1 and M3 are independent and can start now. The first end-to-end result worth having is M5 on a single recorded PBE game.

Timeline anchor: Set 19 goes live 2026-12-01. Realistic target for launch day is M0–M2 plus a basic M3: unlock tracking and feasibility with structural plans. Data-driven plans follow in mid-December.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Riot policy / enforcement on screen-reading assistants | Could make live mode unusable or risky | Read-only, no injection; review mode as primary deliverable; keep it personal |
| Unlock progress not readable on screen | Combat-stat unlocks untrackable | Extrapolate from rates; prompt player to open the panel; mark as estimate |
| Strength model too crude | Wrong streak, HP and risk estimates | Wide uncertainty; calibrate on recordings; keep outputs that depend on it visibly hedged |
| PBE → live changes | Rules file stale on day one | Automated string diff per patch; thresholds are one-line edits |
| Mid-set unlock rework (as in 16.6) | Taxonomy gap | Primitives are composable; regression file from Set 16 |
| No early/mid-game data | Weak play-now advice | Option-value formulation needs no early-board library; own recordings accumulate |
| Unit recognition accuracy | Wrong state → wrong advice | Bookkeeping first; confidence gating; trait-panel checksum |
| Set rotation every ~3.5 months | Maintenance load | Data-driven everything; per-set asset checklist in `05` |
| Scope | Never finishing | M5 is a complete, useful product on its own |
| Simulator speed | Latency above 1 s | Analytic pruning; vectorise; fewer rollouts for hints |

## Open design questions

- How many rollouts are needed before plan rankings stabilise? Measure rank correlation vs. rollout count.
- Should "deliberately lose" be a policy the engine can recommend (Rakan, True Damage B-Side), or only something it prices when the player is already doing it?
- How to present the Akali fork and other irreversible choices without nagging.
- Whether to model contest from scouting at all in v1, given the policy line on opponent tracking.
- Placement value function: average placement, top-4 rate, or LP-weighted.

## Reference: Set 16 lessons

- Riot eased many unlock conditions in patch 16.6 after finding that strict conditions limited pivots. Expect Set 19 conditions to move.
- Set 16 had a gate unit (Azir) with escalating thresholds per Shurima unlock; Set 19's analogue is Xayah for Gu Feng.
- Set 16 guaranteed a newly unlocked unit in the next shop and reduced the odds of unlockables you held no copies of.
- Easy unlocks had no downside to completing, which is the basis of the "Free" alert.
