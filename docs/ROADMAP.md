# Roadmap and status

Status as of 2026-11-18. This file is the live plan; the design docs `00`–`07` are the original brief (copied from the prep folder, not yet edited), and the evidence behind changes is in [the research report](../reports/TFT%20decisions%20that%20win%20games.md).

Dates: Set 19 on PBE since 2026-11-17/18. Live 2026-12-01 per Riot's patch schedule, 2026-12-02 per Riot's Set 19 videos.

## Built

| Piece | What it does | Verified by |
|---|---|---|
| `tools/extract_unlocks.py` | Unlock rules from game files: thresholds, milestones, level gates, filters, condition text, on-screen progress text | Set 16: 40/40 unlocks; level gates match all 17 in Riot's 16.6 notes (`tests/test_extract_unlocks.py`) |
| `tools/build_static.py` | One file per set: roster, pool size per unit, unlockable flags, traits + breakpoints, shop odds levels 1–11, rules, unlocks | Set 18 pools 30/25/18/10/9 and odds match patch notes |
| `data/constants.json` | Hand rules that live in game scripts: XP table, income, interest, streak gold, stage damage | Sourced per value; streak threshold unresolved |
| `engine/econ.py` | Exact P(hit N copies within G gold), gold needed for a target chance, level cost, income, damage, losses to death | DP within 0.4 pts of a slot-by-slot shop simulation (`tests/test_econ.py`) |
| `tools/postgame.py` | Post-game report from Riot's API, benchmarked against your own lobbies | Ran on 20 real ranked games (`tests/test_postgame.py` for the logic) |
| `data/manual/TFTSet19.json` | Hand-made Set 19 data: 94 units, 47 traits with breakpoints, 36 unlocks as structured rules. Odds and pools assumed from Set 18 | Roster cross-checked against TFTips trait lists (one fix: Rakan) |
| `engine/unlocks.py` | Unlock checker: status of every unlock for a game state (READY, NEEDS_LEVEL, PROGRESS x/N, LOCKED, BLOCKED, DEAD, UNKNOWN), Akali-fork warning, gates shown as paused | 20 scenario checks on Set 19 rules (`tests/test_unlocks.py`); CLI: `python3 -I engine/unlocks.py TFTSet19 state.json` |
| `capture/tftcap.swift`, `capture/hud.py` | Mac capture: find and grab the TFT window (ScreenCaptureKit), OCR with Apple Vision, parse stage / level / XP / gold / shop (names fuzzy-matched to the roster). Regions are window fractions, not yet calibrated | Synthetic 3024x1890 frame read exactly, incl. a misread name and decoy lobby HP (`tests/test_hud.py`) |
| `capture/record.py` | Recorder (with purchase ledger: buys from emptied slots + matching gold drop, sells from a unique sell-value match, unexplained gold changes counted): reads the TFT window ~1/s, writes one state per planning phase to `recordings/<time>/state.jsonl`, counts rerolls (gold -2 + shop replaced) incl. before the 2-4 carousel, waits when TFT is closed, `--frames` keeps a PNG per stage. Shows nothing in game | Scripted readings incl. purchases, missed fields and a loading screen; log replays into `alerts.py` (`tests/test_record.py`) |
| `tools/crawl.py`, `tools/riot.py` | Crawler: Challenger/GM/Master ladders -> match IDs -> ranked matches of one set, trimmed (no puuids or names) and gzipped in batches; resumable; shared rate-limited Riot client (20/s, 100/2 min) | Fake-API test on the cached matches: set/queue filter, identities dropped, 14 matches in 17 KB vs 297 KB raw, no refetch on resume, limits held on a fake clock (`tests/test_crawl.py`) |
| VOD + storage (`capture/tftcap.swift` `vod`, `capture/record.py --vod/--replay/--mask`) | Read any video file (AVFoundation, no ffmpeg needed at runtime). Game located in stream layouts from two HUD landmarks (stage, Lvl.), last mapping reused when a webcam hides them; `--mask` hides webcam/overlay text; `--area` crops a known game box. Storage: OCR text per read in rows.jsonl.gz (~0.3-1 KB a frame), re-parsable with `--replay`; optional JPEG frames (1280 px, ~120 KB) | Scaled, boxed stream video with a webcam over the HP: stage, level, XP, gold, board, shop, traits read; HP reported unread (`tests/test_vod.py`) |
| `engine/strength.py` | Relative board strength: learned build quality (gold value, units, carry stars, items, carry itemization, 3-stars; pairwise within-lobby fit) plus a hand-set synergy prior (trait tier k worth k; solo traits 0). `search` finds high-synergy boards within a level's gold budget; `--save` adds them as two-trait plans | 520 lobbies, 5-fold by lobby: 79.3% of pairs (gold alone 74.8%), 81.6% with per-trait weights in Set 18; same-round ~57% (`tests/test_strength.py`) |
| `engine/board_model.py` | Learned board evaluator per set: value per unit-star, per trait tier step, per unit's items and best-in-slot items, plus gold/carry; listwise ranking of the whole finishing order (Plackett-Luce), Adagrad; `--prior` starts from an older model (launch day, each patch). Design: [STRENGTH.md](STRENGTH.md) | Set 18 (1,962 lobbies), 5-fold by lobby: 59.0% same-round, 77.2% gold-matched, 84.1% all pairs (`tests/test_board_model.py`) |
| Focus list (`plans.py --suggest / --focus / --clear`) | Player picks comps before the game; alert targets and review plan notes follow them | `tests/test_board_model.py` |
| `engine/lines.py` | Line selection (post-game): best board from owned units = strength now (board model, or cost/stars + learned trait values) + lambda(HP) x (line keeping toward anchor comps + their unlock progress, incl. counter gates); explained trade-off vs the strongest board; pivot map (comps sharing core units/unlocks, other main trait, weighted by placement). Anchors = focus list, else fit x placement. LINE notes in the review | `tests/test_lines.py` |
| `engine/plans.py` | Structural Set 19 plans (12 bands, capstone unlocks, level covering gates; no meta data exists before launch), plan matching from trait panel + owned units, plan reach (core units x unlock chances; shown as an upper bound when an unlock chance is unknown). Plans set alert targets and add a PLAN note at 3-2 / 4-1 / 4-5 in the review | `tests/test_plans.py` |
| `engine/review.py` | Post-game review: tempo notes (behind the levelling line with gold, one-two losses from death with gold banked, banking while bleeding, over the interest cap, losing streak under 40 HP, out holding gold) merged with unlock alerts | Scripted bleed-out (shaped like your 2026-05-08 game) gets 3 distinct calls; a clean game and a reroll comp get none (`tests/test_review.py`) |
| `engine/alerts.py` | Review-mode unlock alerts over a game log: Free (one cheap action), Start now (gate unit benched, or roll-now beats econ for a target), Closing (under 50% by the deadline), Dead | Scripted 5-state Set 19 game (`tests/test_alerts.py`) |
| `tools/eval_hud.py` | HUD reader vs hand-read truth frames: per field right / wrong / missed / phantom | 44 frames of the robinsongz 1080p game: stage/level/XP 100%, gold 97%, HP 98%, lobby HP 99%, shop 95%, streak 89% |
| `engine/advise.py`, `tools/eval_advice.py` | Per-round advice: line (comp fit x shop-simulated reach with scouted contest x placement), shop buys, items from held components, augment fit; scored vs the recorded player | 2 games: line on the final trait 91% (baseline 78%), buys 61% recall / 28% precision (hold-copies baseline 35% / 30%); `tests/test_advise.py` |
| `engine/fights.py` | Fight model from recordings: one row per PvP fight; P(win) from form, level vs the lobby's level badges, board strength vs the stage; HP per loss vs the rules; prior-shrunk, leave-one-game-out scored; feeds `tempo.py` | 2 games, 48 fights: fit near the prior, held-out log loss 0.572 vs 0.600 hand-set; `tests/test_fights.py` |
| `tools/audit.py` | Parse-health audit: per field, the rounds that break the game's rules (XP, HP, streak, shop odds, ...) and frame-level OCR noise, no labels needed; rule notes where the HUD contradicts the rules file | 7 recordings (see "Parse-health audit" below); `tests/test_audit.py` injects one misread per field |
| `engine/reach.py` | Chance each unlock happens by a stage: shop simulation for units to find (standard line with its level-8 roll-down vs roll down now; XP paid for, passive XP, pool depletion by stage), rate model for counters, exact streak math (Rakan), saving (Pyke), level gates; item/position conditions marked as your choice | `tests/test_reach.py`; CLI: `python3 -I engine/reach.py TFTSet19 state.json 5-1` |

## What changed from the original plan

1. **Augments are not in Riot's match data** (0 of 160 player records, checked 2026-11-16). The crawler in `06` cannot condition on augments; augment value must come from own recordings.
2. **Unlock rules are generated, not hand-written.** `03`'s YAML becomes a thin hand mapping from condition kind to primitive on top of the extracted file.
3. **Unlock progress is shown in-game** (Set 16 tracker, "x/N" for every condition), but only for champions pinned in Team Planner with Reminder on. Pinning becomes a pre-game step.
4. **`03`'s taxonomy needs four more primitives** for Set 16 regression: unit stat at combat start (Aatrox, Volibear), combat event (Mel), player action such as selling (Sylas), HP-lost accumulator (Singed). Multi-condition unlocks (Singed, Warwick) have unknown AND/OR semantics.
5. **Live advice is dropped** (pending your confirmation). Riot's TFT rules ban in-game suggestions based on current game state, and the account risk applies to private tools too. Shape: pre-game planner that exports a Team Planner code, a recorder that shows nothing in game, and post-game review. Details and monetization rules: [POLICY.md](POLICY.md).
6. **Tempo engine before plan values.** HP through stages 3–4 and gold left at death are the best-measured drivers of placement. `04`'s simulator needs the damage formula, losses to death, spend-before-death and a streak plan (direction, HP floor, exit round) first.
7. **Exact math for single-unit hits** (`engine/econ.py`); Monte Carlo only for whole-plan reach.
8. **Contest from play rates**, never from scouting opponents in live use. Scouted boards only in review.
9. **Placement value**: weight toward top 4 with a switch to seek 1st; show placement distributions.
10. Riot's API sits behind Cloudflare, which blocks Python's default User-Agent (error 1010).
11. **Set 19 is not in CommunityDragon** (checked 2026-11-18, PBE live): its dump tracks League's PBE and has no `tft19` files; TFT's standalone client ships data separately. Set 19 rules are hand-made from TFTips and tactics.tools PBE listings until a game-file source appears. PBE differs from `02`: Seraphine needs 4 rerolls (not 3), Mordekaiser 10 star levels (not 11), Galio is "2 of Bodyguard/Juggernaut/Frontman active".
12. **You play on Mac.** Capture is ScreenCaptureKit, not DXGI/WGC (`05`); no Overwolf adapter (Windows-only). CommunityDragon is fine for development, but a shipped product must ingest data from Riot-supported services.

## Unlock coverage from a real recording (2026-11-18)

All 36 Set 19 conditions are encoded; 32 agree between TFTips and tactics.tools, the other 4 (Nasus, Renata Glasc, Galio, Syndra) come from tactics.tools. `tests/test_unlock_audit.py` builds a satisfying state for every rule and checks it reads READY (and that an empty state doesn't).

| Unlocks | Condition kind | Where the recorder gets it | Works from screen? |
|---|---|---|---|
| Evelynn, Alune, Kayle, Zac, Yasuo, Syndra, Mordekaiser, Akali (K/DA) | units / star levels of traits | Trait panel (lower bound) + owned units from the purchase ledger | Yes, conservative |
| Galio, Smeech | traits active | Trait panel | Yes, exact |
| Aphelios | unit at N stars | Purchase ledger (copies -> stars) | Yes (misses carousel/augment copies) |
| Kobuko, Tibbers | unit at N stars + items | Ledger for stars; items on units not visible | Stars only; item part UNKNOWN |
| Ashe, Nasus, Renata Glasc, Samira, Jinx, Alistar | items on a unit | Items on units not visible | No (needs item recognition, M9) |
| Seraphine | rerolls before 2-4 | Recorder's own reroll count, only if recording from 1-2; tracker otherwise | Yes if recording from the start |
| Vayne, Janna | Rock combats; interest with Xayah | Derived by the recorder (panel + gold); tracker overrides | Yes, estimate |
| Rakan | win/loss streak at level 8+ | HUD streak length + win/loss from HP changes, counted from level 8 | Yes |
| Pyke | gold at end of combat | Last gold reading of the round | Yes |
| Lulu, Tristana, Thresh, Wukong, Lee Sin, Gwen, Teemo, Akali (TD), Sona, Baron | combat/resource counters | In-game unlock tracker "x/N" (pin targets in Team Planner); parser matches threshold + wording | Only if the tracker is on screen; parser not yet checked on a real Set 19 tracker |
| Vladimir, Taliyah | positions | Board hexes not visible | No (needs board detector, M9) |

## Would a real player use it? (checked on a real Set 19 PBE frame, 2026-11-18)

- **Reading the screen works.** On a letterboxed PBE video frame the reader gets stage, level, XP, gold, streak length, shop odds, board count, all five shop units, the full trait panel and your HP, with nothing unread. Some lobby HP values are missed (reported as unread).
- **Unlock advice from the screen alone was silent** before this pass: the HUD shows traits, not which units you own. The checker now uses the trait panel as a lower bound, which turns on board-trait unlocks (Zac, Alune, Kayle, Yasuo, Smeech) but not unit-specific ones (Kobuko, Tibbers, Aphelios, item conditions).
- **Advice a player would act on today:** the post-game tempo notes (they target the decisions the research ties most to placement and need only HUD fields), Seraphine's reroll count, and Free/Start-now unlock alerts once units are known.
- **Since then:** purchase bookkeeping gives owned units (with stars from copies), split into board/bench by the trait panel. That turns on Aphelios, gated counters (Xayah benched) and the star part of Kobuko/Tibbers; their item part is reported as not visible rather than guessed.
- **Not yet trustworthy:** reachability percentages (Set 18 odds, 25% pool assumption, uncalibrated), anything about *whether* an unlock is worth chasing (needs plan values from live match data after 2026-12-02), and unit-specific unlock alerts (need purchase bookkeeping or unit recognition).
- **What a player would not take:** generic notes that ignore intent (a reroll comp told to level). Guarded for rerolls; streak intent (deliberate loss streak at high HP) is respected by only flagging under 40 HP.

## Board strength: what the data supports (refit 2026-11-19 on 520 lobbies)

Data: 500 crawled Set 18 Master+ ranked lobbies (0.4 MB) + 20 own lobbies; 4,160 boards; 5-fold held out by lobby.

| Model | All pairs | Same-round pairs (1,347) |
|---|---|---|
| Gold value only | 74.8% | 56% |
| Generic synergy prior only (tier k worth k) | 47.4% | 40% |
| Build quality (gold, units, carry stars, items, carry itemization, 3-stars) | 79.3% | 57% |
| + generic synergy prior | 79.4% | 57% |
| + per-trait weights, within Set 18 (80/20 split) | 81.6% | - |

- **Build quality is the strength signal.** The 84% from 20 lobbies was optimistic.
- **Counting trait tiers does not predict winning**; vertical depth is negative with 25x the data. High-rank end boards trade tiers for unit power.
- **Traits matter individually.** One weight per trait, learned within a set, adds 2.3 points. Set 18's strongest: Elderwood, Ravager, Rapidfire, Hunter, Invoker, Executioner; weakest: Rival, Sprykin, Lunar. Invoker/Executioner match SeeMeta's top 18.6 comps; the Set 18 search with these weights centres on Elder Dragon + Mama Beak (Summoner/Riftbeast), also SeeMeta S-tier.
- **Weak at a single moment:** ~57% of same-round pairs. End-of-game boards are a blunt tool for fight odds; recordings (HP per round) are the fix.
- **Set 19 pipeline:** after 2026-12-02, `crawl.py --set 19 --since 2026-12-02` -> `strength.py traits 19` -> `strength.py search TFTSet19 8 --save` (search uses learned weights automatically when the file exists). Until then the Set 19 synergy plans are trait-coherent boards, not strength-ranked.

## Set 19 PBE data from MetaTFT (2026-11-19)

MetaTFT's PBE comps page (patch 19.1, last 3 days, 1.2M boards collected by its desktop app; Riot's public API has no PBE) gives 43 comps with avg placement, win and pick rates. Their ToS (6.1) makes the data MetaTFT's property, so it is used as a private reference only: read from the public page, saved to `data/manual/TFTSet19.metatft_pbe.json`, and everything derived from it is gitignored (`data/manual/*metatft*`). No bulk pulls from their internal API.

- **Unlock payoff** (`python3 -I engine/plans.py TFTSet19 --unlocks`): Hyperpop chain (Kobuko, Lulu, Teemo, Tristana) 3.10, Baron 3.49, K/DA Akali 3.83; weakest Yasuo 5.38, Galio 5.19, Smeech 5.01; True Damage Akali, Alistar, Rakan, Seraphine, Sona appear in no listed comp. More unlocks in a comp correlates with better placement (r = -0.33).
- **Synergy matters in Set 19** (unlike Set 18 end boards): synergy prior vs comp placement r = -0.52; gold value r = +0.15. Trait value is set-specific.
- **Set 19 trait values** (`strength.py comp-traits TFTSet19`, ridge on comp averages, bands only): Hyperpop, Prodigy, Ionic Spark, K/DA, Bodyguard strongest; R&B, EDM, Juggernaut weakest. With them the search rediscovers the S tier (Hyperpop + Prodigy, Prodigy Malzahar, Ionic Spark).
- **PBE comps are plans** with placement (first 6 listed units = core, rest flex). `plans.py` ranks candidate plans by expected placement = P(reach) x PBE placement + rest x 5.0 (fallback guess). Review PLAN notes cite the PBE placement.
- **Caveats:** PBE play is not ranked play; comp averages mix skill levels; 43 comps is a coarse sample; the data moves daily (re-read it, don't trust a stale copy). Our own crawl replaces this after 2026-12-02.

## Training status and launch day (2026-11-19)

- **Board model needs more data, not tuning.** Learning curve on Set 18 (fixed 106 held-out lobbies): 50 -> 76.8%, 100 -> 78.3%, 200 -> 81.1%, 300 -> 82.2%, 400 -> 83.0%; still ~+0.8 pts per 100 lobbies. Regularisation and epochs barely matter (83.0-83.1%).
- **Calibrated:** predicted 70% -> right 71%, 94% -> 93%, 55% -> 51%. Its probabilities can be used as odds.
- **Waiting on data:** line/unlock weights and a same-moment fight model (recordings); Set 19 per-unit model (ranked games from 2026-12-02).
- **Launch day:** `python3 -I tools/launch_day.py` (key exported) crawls 2,000 Set 19 ranked games since 2026-12-02 (~45 min at personal-key rates), trains the board model, learns our own trait values (these replace the MetaTFT-derived ones automatically), refreshes synergy plans, and prints what is still manual: the 19.1 economy numbers in `data/constants.json`, and any Riot unit ids the resolver could not map onto the roster.

## VOD sources (checked 2026-11-19)

| Source | What | Use |
|---|---|---|
| dpei (Challenger), Phaethon, leduckVODs on YouTube | Unedited multi-hour Set 19 PBE streams | Best: every planning phase present |
| Subzeroark (Rank 1 NA), robinsongz | ~20-30 min single games, edited | Usable; cuts leave gaps in purchase tracking |
| Send, Redox, emilyywang, Tyan, CammyTFT, leduck, JugTFT | Highlights / first looks | Partial only |
| MetaTFT VOD library (metatft.com/tft-vods) | Streamers' *ranked* games matched to their Twitch VODs, with skip-to-stage, result, rank, final traits; no PBE | From 2026-12-02: labeled Set 19 games (known outcome) |

Rules: YouTube and Twitch terms don't allow downloading their videos. The way in keeping with normal viewing: play the VOD in your own browser (theater or full screen, 1080p) and run `capture/record.py --window YouTube --mask <webcam>`; the recorder reads the window as it plays and keeps only OCR text, never a video file. Frames without the HUD (ads, menus) are skipped. Using other people's videos for analysis is the user's call. The built-in browser pane is too small (~500x280 video) to read the HUD; use a full-size window.

## First real game recorded (2026-11-19)

Subzeroark's Set 19 PBE "fast 9" VOD, read from a Chrome window: 35 planning phases (2-1 to 6-5), 1,051 frames, 0.6 MB of game-area OCR text (no video kept).

- **Read well:** stage, level, XP; gold after dropping the coin icon misread as a leading digit; HP after taking each round's most common reading and rejecting implausible jumps (100 -> 93 through stage 3 -> 54 -> 30); purchase ledger ~7 units; a Gwen tracker line (71/250 cheers).
- **Fixed after review (replay of the same OCR, 33 phases):**
  - Trait panel: counts checked against the set's breakpoints; an unread count is unknown (not inactive); per round, traits seen in a third of readings, count = mode capped by level. Plausible lists now (Ionic Spark 3, Jazz, Prodigy, Encore, Frontman).
  - Shop: a reroll is 3+ slots changing (no gold needed); a buy is a slot missing for 2 readings with gold paid (compared to the reading before it vanished), confirmed even if a reroll follows. 12 rerolls read.
  - Stage repeats (4-4, 4-5 twice) were a real rewind in the video, not misreads: a replayed stage now replaces its earlier copy; one-frame backward misreads are still ignored.
  - Owned units: sells are mostly invisible (gold also rises from income, orbs, trait gold), so owned is capped at level + 9 (board + bench), dropping the longest-held first; gold rises in a stage's first 6 s are income, never sales.
- **Known limit:** 42 gold rises stay unattributed (diagnostic only). The owned list is an upper bound, so line advice may name a unit already sold.
- **Same game from a downloaded MP4 (720p, 2x speed edit), `--vod FILE --speed 2 --mask 0,0,0.16,0.22 --mask 0.785,0.78,1,1`:** read in 2 min (vs 20 min watching), 0.5 MB OCR, stages 1-1 onward, no rewinds. `--speed` reads twice as often in video time and stores game seconds, so per-round reading counts and the income window match a normal-speed source. Comparing the two reads exposed and fixed:
  - HP: ability tooltips ("30/25/25", x~0.89) were taken as your HP when few lobby HPs were read, so a false 30 locked in. Your HP is now the tallest number in its own column (centre x 0.925-0.957); "000" is never HP. Both reads now agree every round: 100 -> 96 -> 93 -> 82 -> 68 -> 54 (a 1st-place game).
  - Win/loss: a planning phase shows HP left by the *previous* combat, so its result is that combat's, and only counts if that round was PvP (4-6's loss shows at 4-7; the 4-4 carousel no longer yields a "win"). Both reads give identical results.
  - Shop: "onar" (a half-hidden card) fuzzy-matched Sona and logged a false unlock; a loose name match must now agree with the traits printed on the card.
  - Traits: OCR misreads ("JorlcSpark") get a looser match inside the panel when one name clearly wins; unknown traits listed above a known-active one are active (the panel sorts active first); the panel scrolls (top/bottom halves), so a trait read active 80%+ of the time is kept even if seen in only 1/6 of readings. Checked against frames: 3-1 exact in both reads; 6-5 11 of 12 active traits in each (the file misses Jazz, which Vision doesn't detect at 720p; the window misses Renegade).
  - Verdict: a file is better (faster, rerunnable, full game, no Space/window problems); 1080p would help the small trait digits.
- **Features on the replayed game:** review, alerts, unlock check, reach, plans and lines all ran without errors and agree with each other (e.g. Jazz Kayle 0% by 5-1 because Smeech needs level 9, while Kayle alone is 100%).
- **Data correction:** Nasus, Renata Glasc, Galio, Syndra appeared in shops at levels 4-5 in stage 2 (Galio below his level-7 gate; the recorder now flags such rule conflicts). With TFTips listing no condition for these four, they are treated as normal units on current PBE: 32 unlockables.
- **Review fixes from reading it as a player:** an unread counter is unknown, not dead; "no path by 5-1" is now "OFF PACE", DEAD only for closed windows / exclusive unlocks; past the deadline, chances look to the end of the game.
- **Capture fixes:** CLI capture needed `CGMainDisplayID()` to open the window-server connection; macOS full screen moves the video to another Space (use a maximised window + theater mode); `!` commands in this app lack Screen Recording permission (use the terminal panel).

## Second real game: robinsongz Beach Pop Taliyah (2026-11-19, MP4, 720p, normal speed)

`--vod FILE --every 1 --mask 0,0.84,0.2,1 --mask 0.82,0.78,1,1` (chat + webcam). 31 min of video read in ~6 min; 36 planning phases, 0.8 MB.

**What the screen gives, checked against frames:**

| Needed | Status | How / limit |
|---|---|---|
| Stage, level, XP, HP | reliable | HP can exceed 100 (103 here; cap raised to 150). HP 103 -> 94 -> 84 -> 61 -> 43 -> 26 -> 24 (2nd place) |
| Gold | partial | single-digit gold ("9 4": coin read as 9) often undetected; 17 of 39 rounds unread |
| Shop (5 cards) | reliable | the round keeps its last *seen* shop (a dragged unit hides it briefly) |
| Rerolls, buys | good / approximate | 22 rerolls; buys need gold readings; sells mostly invisible (owned list is an upper bound) |
| Trait panel | good | counts + active; scrolling halves visibility; emblems show up as counts no unit explains |
| Augment offers | **new, reliable** | the "Choose One" cards (name + effect text) every augment round, including rerolled cards: 2-1 Patience Is A Virtue / Expedition / Silver Destiny (rerolled away Punch Line, Called Shot); 3-2 Missed Connections / Crit Rune+ / Dummify; 4-2 Soul Awakening / Nesting Anvils+ / Giant and Mighty. The pick itself isn't shown |
| Board (which units are fielded) | **inferred** | `engine/unlocks.py infer_board`: the n units (n = level / board count) whose traits best reproduce the panel, preferring owned units; a surplus on the panel is explained by emblems. Exact on synthetic boards; on this game residual 2-6 trait points (emblems: a Choreographer Emblem tooltip was seen; the ledger misses some units) |
| Star levels | approximate | from copies bought; star icons over health bars are not text |
| Items on units | **not readable** | item icons are pictures, not text; hovered tooltips sometimes show one item (Choreographer Emblem, Tear, Bloodthirster). Needs icon matching (Set 18 item icons from CommunityDragon cover most core items) or, for your own games after 12-02, the Riot match API (exact final board, items, stars) |
| Unlocks available / gone | good | shop sightings mark unlocks; Taliyah's tooltip shows a "1/5" tracker; Zac progress from the panel |

**Suggestions on this game:** by 3-2 the plan ranking named Beach Pop (80% fit; Beach Pop Graves / Zac / R&B Mel), the board the streamer built (Beach Pop 7 + Taliyah). Line notes at 4-1/4-5 pushed Renekton, Syndra, Taliyah, Zac onto the board; 5-6 flagged rolling at 43 HP with 52 gold. Fixed from reading it as a player: the plan fit no longer counts benched ledger units fully or one-unit traits (R&B from Rell made unrelated comps "100%"); banking past 50 gold to level within 3 rounds (fast 9) is no longer a CAP mistake.

## Exact board and items from pixels (started 2026-11-19)

Goal: the real board (which champion on which hex, stars, items) instead of estimates. Text OCR can't do it; picture matching can.
- **Health bars** (`capture/units.swift`, `tftcap units`): your units' green bars found per frame (planning), board and bench; the info panel's own HP bar filtered. Works on the 720p VODs.
- **Items under each bar:** three slots cut relative to the bar; a CreateML classifier (`tools/train_items.swift`, model in gitignored `data/models/`) trained on synthetic in-game-looking icons (CommunityDragon art for 206 core/radiant/artifact items, framed, shrunk to 15-40 px, JPEG-blurred, on real board backgrounds) plus an empty class. Slots fill left to right, so the first empty slot ends the row. On a 5-2 frame it read Zac's Choreographer Emblem + Warmog's Armor + Protector's Vow (matches the info panel) and a Beach Pop Emblem; some real 720p icons still fall under the 0.6 confidence floor.
- **Set 19 items CommunityDragon lacks** (emblems, new artifacts) come from the game itself: `tools/harvest_items.py` crops the icon beside every item tooltip's title (46 curated crops, 23 items, 7 Set 19 emblems) and they join training.
- **Exact labels available on screen:** item tooltips (name + icon, and the holder: "Zac" with portrait), the unit info panel when a unit is clicked (name, stars, three large item icons), augment cards, trackers.
- **Next:** (1) a labelled under-bar evaluation set from hovered tooltips (clean crop of the same slot a second earlier) and stage-1 empties, then accuracy numbers; (2) champion identity: info panel / tooltip names give labelled crops, the trait panel + stars + items + purchase ledger constrain the set, appearance matching assigns hexes; (3) record frames at native resolution. **Resolution is the limit:** 720p VOD icons are ~17 px and units ~50 px; your 3024x1964 screen gives ~2.7x that.

### Sources for Set 19 art and models (checked 2026-11-19)

- CommunityDragon: Set 18 characters only. modelviewer.lol/extras: up to Set 18 (Enchanted Wilds); its Set 10 "Rumble Remix" entries (K/DA, True Damage, Pentakill, Heartsteel, Hyperpop, EDM, Jazz, Disco) may share models with Set 19's returning music traits: worth checking against real footage once more VODs exist.
- The local `Teamfight Tactics (PBE).app` is an Unreal Engine build whose content containers (pakchunk0/1) are **encrypted**. Off-limits: reading them would mean extracting Riot's key.
- So Set 19 art comes from the screen: item tooltips (name + large icon), the info panel, purchases. More 1080p+ VODs = more coverage.

### Parsing audit: 720p vs 1080p reads of the same game (2026-11-19)

Every disagreement was checked against the frame:
- **False purchases:** the whole shop leaving the screen (combat camera) with gold unread was booked as 3-4 buys. A buy now needs the shop on screen and an *observed* gold drop covering its cost (cards vanishing together share the drop, in vanish order; a sale right after doesn't hide it). Unread gold means a missed buy, never an invented one.
- **Gold:** the coin icon is read as a glyph ("9 4", "• 35", or fused "94" for 4). Separate: certain; lone digit in a coin-wide box: dropped; fused digits: both readings offered, the recorder picks the one nearer the last certain gold. An enlarged (3x) second OCR pass on the gold box reads lone thin digits Vision misses at frame scale. A round keeps its last *read* gold.
- **Trait counts:** at 1080p the count digits ("4" beside Beach Pop) were skipped, so counts fell back to the first breakpoint (Beach Pop 3 instead of 4, Choreographer 2 instead of 3). The enlarged re-read of the count column fixes it: frames at 540 s, 680 s, 1745 s now read exactly; unread inactive traits stay unknown (never guessed).
- **Breakpoints:** checked all hand-entered Set 19 breakpoints against the panel's own "3 > 5 > 7" / "1 / 2" lines in three recordings: all ~30 seen traits match; True Damage had none, now [3] (higher tiers unseen).
- Agreement between the two reads: identical stages, augment offers, unlocks, results.

### Item reader status (1080p)

- Debug items (Damage Amp, Ace, Taunt...) and anvils removed from the classes: "Damage Amp" was absorbing emblems.
- "Empty" is learned only from 129 reviewed empty slots of stage-1 units (random board patches contained item icons and taught the model that icons can be empty).
- 82 reviewed tooltip crops for 26 items incl. 9 Set 19 emblems; each slot is classified 5 times (1 px nudges) and averaged; the recorder keeps per round only items at least two readings and half of that unit's readings agree on.
- On 22 hand-checked readings: ~86% right before these fixes; remaining confusion: same-colour icons at ~26 px (Protector's Vow vs Beach Pop Emblem). Precision-first: uncertain slots read as unknown.

- `tools/reread_units.py REC VIDEO`: re-reads only bars + items with the current model (no OCR, ~10 min for a 31-min 1080p VOD) and swaps them into rows.jsonl.gz, so recordings improve as the model does. Round consensus on the robinsongz game: Zac Choreographer Emblem + Warmog's Armor; the Void Staff + Morellonomicon + Arcanist Emblem carrier; Striker's Flail + Radiant Jeweled Gauntlet; Bloodthirster; Beach Pop Emblems. Uncertain slots (Zac's Protector's Vow) are left out rather than guessed.

### Champion labels (precision-first)

- `tools/harvest_units.py`: a purchase labels the unit that appears in the **leftmost empty bench slot** (the game's rule), only when the bench reading before is in the same planning phase, nothing left the bench, and cards bought in the same reading are the same champion (else the order is unknown). Tooltip "holder" links are disabled unless the bar carries that item: emblem tooltips name the drag *target*.
- Yield is low (a few verified crops per game): coverage of ~100 champions needs many VODs plus a quick human confirm/correct pass.

### Champion label review (2026-11-19)

`tools/label_units.py`: `prepare` crops every unit (board and bench) once per round, from a calm planning-phase frame, with its own health bar and items on top so it's clear which unit is meant; crops are grouped by look-alike (Vision fingerprints; same unit across rounds measured at 0.27-0.55 apart, different units 0.60-0.87, threshold 0.5). `serve` opens a local page (127.0.0.1 only, crops never leave the Mac): label a whole group with one click or Enter, or select thumbnails to label part of a mixed group; chips suggest names from the round's inferred board (board crops) or owned units (bench), and from labelled look-alikes after `regroup`. The **round check** compares each fully labelled board (plus emblems read on units) with the game's trait panel and flags rounds that don't add up, so a wrong label shows itself. Confirmed crops are exported to `data/raw/labels/units/<Champion>/` for training. First game: 396 crops in 148 groups (robinsongz Beach Pop); the Subzeroark fast-9 game is added via `reread_units.py --speed 2`.

Next: once a few hundred crops are labelled, train a champion classifier (CreateML, like the item model) and use it to pre-fill the page, then to name units in recordings.

### What the hand labels taught us (2026-11-19, 555 crops labelled by the user, 2 games)

- **Champion recognition from 3D models: parked.** Trained on one game and tested on the other, a CreateML classifier named only 49% of champions (20-30% with the bar and items cropped off); within one game it's ~100%, which says nothing. Wait for Set 19 art (CommunityDragon / modelviewer once the client is no longer encrypted) or many more games. `tools/train_units.swift` is kept for then.
- **Round check fixed:** emblems come from the round's item consensus; a short trait is a soft note (an unread emblem or an uncaptured unit can explain it) and only units *exceeding* the panel are flagged as a likely wrong label. Across 14 fully labelled rounds: 0 contradictions.
- **Board inference, scored on those boards** (`tools/eval_boards.py`): 73% precision / 78% recall / 2 of 14 exact before; now 88% / 85% / 6 of 14, from using what the screen already gives: emblems read on board units (their trait point isn't a unit's), the number of health bars on the board (capped at the level), last round's board (boards change little; reviews and alerts now infer round by round), units the shop can't offer at that level, a softer penalty for units the ledger missed (it drops early units), and cheap/owned/continuing units first on ties (ties went alphabetically). Reach planning counts only units actually seen bought as owned, never inferred guesses.

### Ways to improve now, without champion models

1. ~~Board model upgrade~~ Done 2026-11-19, see [STRENGTH.md](STRENGTH.md#launch-day-and-patches-priors): Plackett-Luce, same-round and gold-matched scoring, priors from the previous patch or set. Launch day runs `fit 19 --prior 18`.
2. More Set 18 lobbies while Set 18 is live (until 12-02): `tools/crawl.py --max-matches 5000` with your key (~3 h at personal-key limits), to fit and test (1).
3. ~~Which augment was picked~~ Done 2026-11-19: the game's Augments panel (hovering the icons by the player's name) lists held augments in order; `hud.read_held_augments` reads it and the recorder stores `picked` per augment round = the one final card that later shows there (augments granted by other augments, like Silver Destiny's, were never offered, so they don't interfere). robinsongz game: 2-1 Silver Destiny, 3-2 Missed Connections (both match the panel on screen); 4-2 unknown because the panel was never opened again. `engine/augments.py` marks the taken card. Left: a scouted player's panel looks the same (a clash needs one of our final cards in their list); icon matching for rounds where the panel never opens.
4. ~~Board inference~~ Improved 2026-11-19: board size is at least level - 1 (health bars miss units late game: 6/7/8 bars read for boards of 8/9/9). `tools/eval_boards.py` now also scores the rounds whose labels explain the trait panel (elsewhere the crops missed units, so finding them counted as wrong): all 14 boards 88% precision / 88% recall / 6 exact (was 88/85/6); consistent 7: 94% / 92% / 4 exact (was 94/89). An exact search isn't needed: the remaining misses come from the objective (wrong panel reads, incomplete labels), not the search.
5. Lobby HP (2026-11-19): `hud.read_lobby` reads every other player's HP from the player list (name and number on one line; the HP column is re-read 3x enlarged because late-game values are tiny single digits; skipped while the end-of-combat damage chart covers it). The recorder keeps the most common of 2+ readings per round for the 7 most-read names (toasts like "Level 4!" and unit tooltips line up with a number now and then). The review fills a player unread in a round with their last reading (HP only falls) and ranks you once 5+ of the 7 are known: the rank goes into BLEED notes, a LOW note says once when you fall into the bottom two while 5+ players are still in, and "roll before you're out" (SPEND) and "was that your exit" (OUT) are held back while you're top two in HP. Checked on the robinsongz 1080p re-read: late-game values match the frame (5-4: 55 vs 21/17/15/6/6/0/0), and the two notes it used to get (SPEND at 5-6 while leading the lobby, OUT at the 7-1 finish while ahead of the last opponent) are gone. 720p recordings without the zoomed column read too few names, so the review stays silent there.

## Star levels from health bars (2026-11-20)

Set 19 shows a unit's star level as the badge at the left end of its health bar: a small **bronze chevron = 1 star, a larger silver diamond = 2 stars**, gold = 3 stars (no 3-star in our recordings: the gold class is unverified). `capture/units.swift` (`starLevel`) counts badge-coloured pixels in a window left of each bar (scaled to the bar width) and returns 1/2/3 or nothing; `tftcap units` and VOD reads now carry `"stars"` per bar, the recorder keeps each unit's most common reading per round, and `infer_board` gives every silver/gold read to the likeliest units (stars the ledger saw, then most copies bought, then the cheapest), so a board's star count comes from the screen even when which unit holds it is a guess.
- **Checked by eye** on 29 bars from 4 frames across the robinsongz game: all 24 real badges right (bronze and silver); 3 green background shapes the bar finder took for bars got no star, 2 others read bronze. Silver reads give 35-45 badge pixels, bronze 5-25, nothing in between.
- In that game: 2 of 6 units 2-star at 3-2, 4 of 8 at 5-5, 9 of 10 at 6-2.
- Left: a gold sample (a 3-star in a recording); dropping "bars" with no badge at all (the bar finder's false positives); which unit holds which star (needs champion identity).

## MetaTFT PBE comps, early boards and items (read 2026-11-20)

The private comp file (`data/manual/TFTSet19.metatft_pbe.json`, gitignored; read from the public page at a normal pace) now holds, per comp (43 with stats, 1.8M boards, last 3 days): the final board with **star targets and the items listed on its carries** (Set 19 best-in-slot: e.g. Ziggs 3-star Guinsoo's / Jeweled Gauntlet / Striker's Flail), the **most common board at levels 4-7 of players who ended in the comp, with its round win rate**, the **stage each level is reached**, and the share of games ending at each level. Names are mapped to the roster (Akali is an unlock fork here; Beach Pop's instruments on early boards aren't shop units). As the user noted, openers and endgames differ: K/DA comps open Neeko/Gragas/Evelynn, Rock Vayne and Pentakill both open Olaf/Karthus/Swain, Frontman Shyvana players often open Hyperpop.

## Held-out game: Subzeroark's reroll Bodyguard Jax (1080p, 2026-11-20)

A third game, used for nothing before it was scored: `recordings/vod-Wasianiverson Already Discovered an INSA-20261120-170917` (two webcams and a chat line masked), 38 rounds 1-1..6-6. 34 frames (one per round) were hand-read the same blind way: `data/raw/labels/hud/subzeroark-reroll-1080p.jsonl`.

| Field | robinsongz (fixes tuned on it) | held-out game |
|---|---|---|
| stage, level | 100%, 100% | 100%, 100% |
| XP | 100% | 89% |
| gold | 97% | 94% (6 read as 9 again) |
| streak (per frame) | 89% | 94% |
| your HP | 98% | 93% |
| shop | 95% | 99% |
| other players' HP | 99% | 62% -> 82% after three fixes found here: the top row of the list was excluded (it isn't always your own row), an augment's text "Weaken: Reduce Damage Dealt" was taken for the end-of-combat chart and blanked the list, and I/l/1 look alike in names ("nmSIIIII" reads "nmSHllll"). The rest are names spelled differently (Izby/Jzby, a popup over a row), not wrong HP values |
| trait counts | 67% exact, rest mostly lower bounds | 53% exact; 4 of 270 wrong, the rest flagged lower bounds (gold/silver hexagons, K/DA's star count) |

Audit over all recordings: 0 broken rounds for stage, level, gold, HP, traits, shop; streak 3/173; lobby 1/298.
- **3-star badges confirmed**: the gold badge (a larger double chevron) was first read as bronze (the guessed colour rule); measured on real badges, gold is big (23-31 px) and yellow (median G/R 0.91-0.95), bronze small or browner (0.73-0.89), so gold needs both. The game reads Jax, Nasus and Renata Glasc at 3 stars by 6-1: exactly MetaTFT's 3-star targets for Bodyguard Jax.
- **Advisor on 3 games** (each once): line choice on the final traits in 23/29 rounds (robinsongz), **24/26 on the held-out game** (baseline "biggest active trait" 22/26), 3/25 on the fast-9 game (the advisor picks Jazz Kayle, he played Ionic Spark Jinx; baseline 20/25). Overall 62% vs the baseline's 82%: the advisor doesn't price switching lines (strong players keep their main trait); a pivot cost needs more games to fit. Buys: recall 58% / precision 23% vs hold-copies 33% / 29% (the ledger saw only 11 buys in a reroll game: it misses many). Fight model on 72 fights: held-out log loss 0.581 vs 0.606 hand-set.

## Line finder (2026-11-20)

A tftflow-like page, searched by board: `python3 -I tools/line_finder.py` (127.0.0.1:8766). Manual input only: units with stars, items of every kind (components, completed, artifacts, radiants, emblems) and augments. It also takes hard conditions: reroll / fast 8 / fast 9, AD or AP carry, minimum tier, must-include and exclude units, and traits. It's a static filter over static tables (docs/POLICY.md): nothing is read from the game, and nothing is computed from gold, level or HP.

- **Comps:** all 43 MetaTFT PBE comps (private file). With a board entered, the list shows the comps that use it, ordered tftflow-style: tier first, then how much of your board each one uses. A unit's weight is stars^1.5 × √cost, so 2-stars count most.
- **Tier:** MetaTFT's average place, moved by what you hold, then cut into OP ≤ 3.5, S+ ≤ 3.8, S ≤ 4.1, A ≤ 4.4, B ≤ 4.7, C above. Each part is capped and shown under "Why this tier".
  - **Items** on the comp's itemized units. MetaTFT's unit-page change (with vs without, among 3-item boards) × (1 − its play rate), since the comp's average already includes the players who build it. Also × play/(play + 0.05) for noise. Unlisted BIS items count 0.1 places, an item of the right kind (AD/AP/tank) 0.04, a component toward a carry's BIS item 0.05. Radiants count 2×.
  - **Artifacts** on their best holder in the comp, measured against the average holder (MetaTFT holder changes run −0.46 on average), capped at 0.6.
  - **Emblems** that add a breakpoint to the final board: 0.3.
  - **Augments:** `engine/augments.py` fit (hero → its unit, trait → its trait, otherwise what the archetype wants), 0.3 places per point above 0.5. Econ augments favour fast 9 and cost reroll comps a little. Expert tiers are shown but are **Set 18's** list: MetaTFT hasn't ranked Set 19.
  - **Conditions:** 30 tftflow-style "if X → comp" rows in `data/manual/TFTSet19.conditions.json`, paraphrased from Mobalytics and pro VOD reasoning (docs/knowledge/set19_meta.md). Each counts 0.15, total capped at 0.45. An item condition counts once, on its holder.
- **Per comp:**
  - openers at levels 4-7, with MetaTFT's round win rate and how the opener's strength ranks among same-size openers;
  - midgame boards at levels 7-8: MetaTFT's level variants once scraped, else built from the level-7 opener plus the final board, cheapest first, and marked "constructed";
  - +1 / flex units, unlocks with their conditions in words, and levelling stages;
  - final-level share, the endgame board with MetaTFT's best-in-slot items and per-item place changes, and the best artifact holders.
- **Your board's strength:** from `engine/power.py`, as a percentile among meta openers with the same number of units. MetaTFT lists core units only, so boards are compared by size, not by level.
- **Not validated:** the conditions' place values are priors, not fitted. There is no Set 19 per-game data to fit them on until the Set 19 crawl (2026-12-02) and recorded games.

### Team builder (2026-11-20, later)

The page is now a team builder modelled on MetaTFT's builder and tftflow:
- **Layout:** a traits column (bronze, silver, gold and prismatic badges, emblems included), a 4×7 hex board plus a 9-slot bench and held items, and a champion/item pool below with cost, trait and search filters.
- **Moving things:** drag a unit onto a hex, between hexes or to the bench. Drag it off the board, right-click it or press Delete to remove it. Click a pool tile to auto-place it: melee units go to the front row, ranged units to the back.
- **Items:** drag them onto units (3 max). Two components on one unit combine, as in game.
- **Augments:** three slots, chosen from a picker with search, tier and kind filters.
- **Conditions:** reroll / fast 8 / fast 9, AD or AP carry, minimum tier, sort order. Shift-click a champion to require it, alt-click to exclude it.
- **Results:** tftflow-style tier rows of comp cards (the carry's art, style badge, BIS items, your fit, expected place). A card opens to an Opener → Midgame → Endgame line with unit portraits (your units ringed in green), unlocks, itemization, artifact holders and "why this tier".
- **Board strength:** uses only units on the board; the bench counts toward fit.
- **Safety:** the page is built with DOM methods only (a test checks it parses and has no `innerHTML`).

Art comes from `tools/fetch_icons.py` (gitignored `data/assets/icons/`):
- **Champions:** all 94 Set 19 portraits, with their Set 19 skins (2026-11-23). CommunityDragon and Riot's Data Dragon still have no Set 19 art, so they come from MetaTFT's CDN, which hosts Riot's Set 19 art (128 px; downloaded with your OK; private).
- **Traits:** all 47 Set 19 trait icons from the same CDN. Riot's internal names differ for seven: Slayer is "mosher", Gu Feng "heavenscale", Rock "demonvision", Beach Pop "oceansong", Hyperpop "glitterbomb", Classical "virtuosos", R&B "rnb".
- **Items:** 122 from CommunityDragon and our VOD crops. The 17 Set 19 emblems without art show their trait icon on an emblem badge.
- **Augments:** 222 of 364, the ones that carried over. New Set 19 augments get drawn tiles.

The page also has:
- a TFT-style champion card on hover or focus in the selector: portrait, cost, traits, Riot role, range, HP, damage type, ability, unlock;
- a trait panel on clicking a trait: what it does, each breakpoint (reached ones lit) and every champion with it, yours lit, names on hover.


### Tempo: lines your HP can carry you into (2026-11-23)

You enter your HP and a round (planning or post-game review: Riot's rules don't allow suggestions from your live game state during a game). Each line's expected place then moves by what that HP can survive into.

- **No direct data.** Neither Set 18's crawl, the Kaggle games nor MetaTFT has HP over time.
  - MetaTFT's per-comp placement histograms are no substitute. Their spread is the same across archetypes (sd 2.1–2.2), because players choose fast 9 when they're healthy (selection). They can't say what happens when a low-HP player goes fast 9.
  - So the effect is modelled from measured pieces and checked against what data exists.
- **The model** (`engine/survival.py`): an absorbing Markov chain over (PvP round, HP), solved exactly by dynamic programming over integer HP.
  - **Power curve per comp:** its level by round (MetaTFT levelling).
    - Units: openers' core filled from its final board to level 7. From 8, the units its MetaTFT level boards play most, so an unlock carry arrives when those boards show it.
    - Stars: openers' until its main roll-down (the stage MetaTFT shows its players spending the most rerolls: rerolls at 3-2/4-1, fast 9 at 5-x), then its final targets.
    - Items: Set 18's count by round.
    - The final-fight board score turns each round into a win chance against the lobby: every comp's curve, pick-weighted.
  - **Damage per loss:** stage damage plus typical survivors, × the 1.04 HP-loss ratio measured on recorded games.
  - **Placement:** 1 + opponents alive when you go out (7 independent opponents from the same mixture).
  - **Game-to-game variation:** a per-game strength offset u ~ N(0, σ²) (hitting or missing, augments, positioning), integrated by 5-point Gauss–Hermite quadrature.
- **Fit** (`survival.py fit`, 13 s):
  - σ by multinomial maximum likelihood on Set 18's 19,647 knockouts by stage (placements 2–8, stages 2–6): σ = 1.25, an interior optimum (log-likelihood −0.945 vs −1.025 at σ = 0).
  - Knockouts at stages 4/5/6 come out 9/57/34% (Set 18: 7/54/38).
  - Then each comp's curve gets one offset so its chain from 2-1 reproduces its MetaTFT average (fixed point; within 0.023 places). The fight model gives a curve's shape (when a comp is strong), MetaTFT its level.
- **Scenario:** a comp's expected place from your round and HP, minus a typical player's of that comp alive then, added to MetaTFT's average. Your HP with average luck from here: the offset is integrated over its prior.
  - Lolchess variants use their parent's curve. Lolchess-only comps use their archetype's mean shift.
  - Cards say when a line rolls down and how often you reach it alive. A line's unlock carries show the first level most of its MetaTFT boards play them.
- **What it says:**
  - HP sensitivity (25 vs 95 HP at 4-1) is reroll 3.30 < fast 8 3.53 < fast 9 3.81 places. The most sensitive lines roll at 5-2 (Gu Feng Xayah, Choreographer Garen, Ionic Spark Jinx); the least roll at 3-2 to 3-6.
  - From one board at 4-1: with 20 HP, Hyperpop Kobuko (rolled) 5.76 vs Ionic Spark Jinx 7.36 (you reach its 5-2 roll 13% of the time). With 90 HP the gap closes to 1.0.
  - Gu Feng Wukong (4-2) beats Gu Feng Xayah (5-2) at 20 HP; the order flips at 90 HP. High HP buys the greedy fast 9.
- **New sort:** "Top 4 chance". MetaTFT's top-4 share, moved by the chain. Lolchess-only comps get it from their average place: top 4 is linear in average place across MetaTFT's 43 comps (r = −0.992).
- **Considered, not built:**
  - **Streak gold:** measured small. An econ augment's ~18 gold moves fast-9 lines against the rest by 0.03–0.10 places (Kaggle), and a 5-round streak earns about 5–8 gold, so a streak's real effect is its HP. That is what the chain uses.
  - **Your current board in the chain:** our board score doesn't predict MetaTFT's opener round win rates (correlation 0.06), so the chain uses the line's curve, not your board.
  - **Comebacks:** the chain has no roll-down-to-stabilise behaviour, so it is pessimistic at very low HP and optimistic at very high HP. σ absorbs part of this.
  - **Contested lines:** MetaTFT's players-per-game is shown, not modelled.
- **Removed:** the board-strength tempo term. Its link was measured flat, so it was already zero.

### Full data and feature check (2026-11-22)

Every data source cross-checked, board strength and line selection tested against intuition, and the page used end to end. What was wrong, and what changed:

- **Data** (`tests/test_data_integrity.py`, new): every unit, trait, item, comp, opener, artifact holder, condition and unlock resolves against the Set 19 roster.
  - MetaTFT names a doubled item "2nd Gargoyle Stoneplate"; it took a best-in-slot place for Kobuko, Gragas, Ekko and Renata. Now folded into the item.
  - Trait-granted items (Gu Feng's Scrolls, Bard's Horn, Tactician's Crown) filled best-in-slot slots no component can build. Now skipped.
  - Not bugs: final-level shares cover levels 7–10 only; two MetaTFT openers run a unit over their level; one leftover comp panel (Heartsteel Sett).
- **Board strength: the scale.** The fight score was fitted on Set 18 players knocked out in the same round. Their order follows HP left, not a fight between them, and that flattened every weight.
  - Refitted on 1st vs 2nd (2,807 lobbies): the last combat is those two boards fighting. Log-likelihood −0.609 vs −0.665 on the old label.
  - k 0.85 → 1.57; units 0.36 → 0.59; items 0.20 → 0.33; traits 0.27 → 0.42. The ratio of items to stars barely moved.
  - A lone 3★ now beats a typical single slot 94% of the time (was 81%); a full board one star up is a different board (1★ 1% vs 2★ 15% with no items).
- **Board strength: trait weights.** The MetaTFT fine-tune converted its place offsets into weights by dividing by the carried-over score's slope (−0.165 places per unit). That slope is tiny because the score barely predicts place, so the trait weights came out ~10× too big. Indie, whose boards average 7.37, got +2.18.
  - Set 19's trait part spread 4.4× wider than Set 18's (sd 3.24 vs 0.74). Jazz Jhin's real final board scored 5%.
  - Now converted at the Plackett-Luce rate (8 players: 7 × ¼ = 1.75 places per score unit). Trait spread 0.57; MetaTFT final boards average 0.52 against a typical board their size.
  - Correlation with MetaTFT average place fell from −0.56 to −0.42. The old figure was partly in-sample, since the fine-tune was fitted on those boards.
- **Board strength: what it's compared with.** The typical 8-unit board was the average *final* board (10+ items, late game).
  - With no round picked, a board is now compared with the lobby at the round when boards are usually its size: 3–4 units → 2-1, 5–6 → 3-2, 7 → 4-1, 8 → 5-1, 9 → 6-1.
  - 1–2 unit boards (stage 1) and 10-unit boards keep the same-size comparison.
- **Early strength (tempo).** The slope was measured per unit of MetaTFT's real round win rate, but the model's win chance was fed in as if it were one.
  - On 172 MetaTFT openers, the board score's gap doesn't predict round win rates (correlation +0.06; fitted scale 0). The slope itself has a 95% interval that reaches zero (−5.0 to +0.03).
  - Early strength now goes through that measured link, so it moves no place. Before, a normal Ziggs + Lulu opener shifted every comp by +0.55. The HP/gold estimate from recorded games is still shown.
- **Line selection.**
  - 150 of 172 MetaTFT openers show their own comp. Of the 22 misses, 14 are openers MetaTFT lists for the comps shown, and the rest lean that way (Hyperpop units under Frontman Shyvana).
  - Filters: MetaTFT's style label now decides the archetype. Four "Fast 8/Standard" comps were being called fast 9 by a three-5-costs rule.
  - The AD/AP filter passed a comp if any carry matched (38 AD + 37 AP of 57). It now uses the main damage carry's MetaTFT role, skipping tank-role carries: 30 AD + 27 AP, no overlap.
  - Item typing had read Annie as AD (Flail, Nashor's) and Yorick's tank items as AP (Spirit Visage's Tear). Off-type item penalties now use the same damage carry.
- **Augments:**
  - Hero augments pay only where the hero is itemised (+0.25 to +0.36 vs −0.15 to −0.25).
  - Trait augments: deep +0.16, abandoned −0.14, splashed −0.25.
  - Econ augments: slightly better on fast 8/9 lines than rerolls.
  - Reroll augments help only reroll comps.
- **Page and API:**
  - The round picker and a comp's Opener/Midgame/Late tabs shared one state field. Clicking a tab sent an object as the round and crashed the request (the page showed nothing). Separate fields now, and old saves are cleaned.
  - `find` validates its input (bad shapes → a 400 with a message; unknown units listed; stars clamp to 1–4). The server answers unexpected errors with a 500 instead of dropping the connection.
  - Star keys 1–3 never worked after a mouse click (the re-render dropped focus). Now a page-level shortcut on the selected unit.
  - Clear left the condition menus showing old filters. It now reloads into the blank state.
  - "Stronger than 0% of openers" for the standard opener came from ties. Ties now count half.
- **Still open:** in the Set 18 learned weights, a 3★ 4-cost (2.08) ranks above a 3★ 5-cost (1.36), from very few 3★ 5-cost boards. In the fight score the Lanchester term dominates stars, so this doesn't change who out-fights whom.

### Radiants, artifacts, emblems by fit; your carry anchors its lines (2026-11-22)

- **What was wrong:**
  - An emblem alone suggested nothing: emblems were worth 0 in every comp and didn't count toward item fit.
  - Artifacts gave the full premium to comps MetaTFT had no holder data for, so Lich Bane favoured AD comps over Hyperpop Ziggs.
  - Every radiant, even Warmog's, got the carry premium in every comp.
- **Special items measured by fit** (`tools/calibrate.py items`, Set 18 crawl, 22,784 boards). Premium over a normal item, 95% interval; − = better.

  | Item | Where | Premium |
  |---|---|---|
  | Artifact | On one of its 6 most common holders | −0.263 [−0.309, −0.238] |
  | Artifact | Elsewhere | +0.113 [+0.054, +0.193] |
  | Radiant | Normal version is the holder's best-in-slot | −0.063 [−0.116, +0.023] |
  | Radiant | Same damage type (a tank item on a tank) | +0.024 [−0.106, +0.109] |
  | Radiant | Neither | +0.143 [+0.026, +0.224] |
  | Emblem | Trait the comp already runs (deeper or bonus to the holder) | −0.035 [−0.072, +0.001] |
  | Emblem | Activates a splash trait | +0.082 [+0.044, +0.105] |
  | Emblem | Trait stays inactive | +0.209 [+0.116, +0.252] |

  - An artifact on a holder of the same kind but not a usual one measured no better than a wrong-kind holder (+0.17 vs +0.00, overlapping), so artifacts are two-way.
  - "Deeper" (+0.031) and "already active" (−0.245) are pooled: which one a comp lands on depends on exact counts.
  - Set 19: an artifact's usual holders are MetaTFT's six; a radiant fits by the comp's best-in-slot sets, else the carry's damage type; emblems are judged on the comp's final board at its star levels (K/DA counts stars).
- **Your carry anchors its lines.** The odds answer "where did boards like this come from", so four filler units outvoted a 3★ Vayne or a 2★ Jinx holding Rageblade and Kraken.
  - Invested = 3★, holding two items, or a 2★ 5- or 7-cost. An unitemised 2★ 4-cost is frontline that fits many lines, not yet a carry.
  - A comp is realistic if it itemises an invested unit as its main carry (named in the comp) or second carry (unless a tank).
  - Those lines come first; the card says "builds around your 3★ Vayne". This is a display and selection rule; it moves no place.
- **Short lists.** Padding now happens after variants merge, so a full K/DA board still shows more than one card.
  - Stretch lines come only from the 99% conformal set (`tau_stretch` = 2.1% of the best line's odds, 99.1% held-out coverage), and must keep or open with a unit you hold.
  - So a settled 3★ Kobuko/Ziggs board no longer gets Frontman Renekton.
- **Checks** (`tools/eval_lines.py carry`):
  - A comp's main carry (2★, two listed items) among four random units: its comp is suggested 100% (was 75%) and is the first card 100% (was 36%).
  - Every artifact alone: all 32 suggest only comps that play a usual holder.
  - Every emblem alone: 26 of 27 suggest only comps that run the trait; the 27th suggests nothing, since no comp runs it.
  - General harness unchanged: late boards 100%, openers 81%, random 8 units 3.6 realistic.
  - `tests/test_scenarios.py` adds Lich Bane, three emblems, radiant damage types, the settled board, 3★ Vayne, the itemised Jinx and 3★ Annie.
- **Not done:**
  - Spatula and Frying Pan: Set 19's emblem recipes aren't in CommunityDragon (encrypted client), so they're left out rather than guessed.
  - MetaTFT's holder-specific artifact changes (e.g. Statikk on Ziggs −1.27 vs Kai'Sa +0.09) are shown but not weighted: no data to check how much is selection.

### Items by unit, augments by comp, availability, reasonable comps (2026-11-21)

- **Best-in-slot vs random items** (Set 18 crawl, 22,784 boards; `tools/calibrate.py items`). A best-in-slot item vs a normal one is worth:

  | Holder | Places gained (95% interval) |
  |---|---|
  | Main carry | 0.059 [0.039, 0.084] |
  | Second carry | 0.113 [0.099, 0.130] |
  | Tank | 0.066 [0.051, 0.083] |

  - An off-type item on the carry costs +0.075. So random items on the carry cost about 0.13 places per item against best-in-slot.
  - Main carries almost always get three good items (22,609 of 22,758 boards), so their non-BIS items are still sensible. A second carry's are often leftovers.
- **Per-unit need** (`engine/power.py bis`). On Set 18, a unit's learned best-in-slot weight follows its MetaTFT-style best-build place change (r = −0.48, 43 units). Carried onto Set 19 through MetaTFT's builds, weights run 0.06–0.41.
  - Carries need their items: Jax, Viego, Nasus, Malzahar, Seraphine. Tanks don't: Dr. Mundo, Vi, Illaoi, Galio, K'Sante.
  - Board strength now has per-unit best-in-slot weights; Set 19 had none, so best-in-slot vs random made no difference before.
  - The line finder's item premium is the pooled premium × the unit's need (0.36–2.39×).
- **Items in the fight score.** Tested items as raw stats (CommunityDragon AD / AP / AS / crit / HP / resists on the holder). They fit Set 18 worse than the learned weights (−0.671 vs −0.666), and adding them to the learned weights fits worse too (−0.670), so they're not used.
  - Splitting the rest of the score into unit / item / trait weights fits better (−0.664): units 0.36, items 0.20, traits 0.27, off-type −0.012 per item, γ = 0.55.
  - Stage-4 knockouts are too few (65 pairs) to tell whether items matter more early.
- **Augments by comp** (Kaggle, 40k games, vs a combat augment in the same round).
  - Hero augment, hero is the itemised carry: −0.25 / −0.08 / −0.07 at 2-1 / 3-2 / 4-2. Fielded without items: +0.27 / +0.46 / +0.62. Not fielded: +0.26 / +0.52 / +1.00.
  - Trait augment, trait deep (2nd tier+): −0.11 / −0.02 / 0.00. Splashed (1st tier): +0.31 / +0.26 / +0.49, worse than abandoning it. Off: +0.20 / +0.18 / +0.11.
  - Set 19 comps use the hero's role (an itemised holder or not) and the trait's depth on the final board. Econ augments use each comp's measured share of games ending on level 9+; reroll augments use whether the board has a 3★ target.
  - Effects per augment now span 0.4–0.6 places between comps.
- **Availability and pivot cost.** Each comp's unlock-gated units are checked against your board with `engine/unlocks.py` conditions: ready, progress n/target, in-game (counters), or missed.
  - Seraphine's window closes at 2-4. A board past it (more units than the typical level at 2-4, from MetaTFT levelling, or a picked round) closes Hyperpop Seraphine unless you hold her.
  - "To finish": the units still to buy and their gold at each unit's usual star level (MetaTFT star shares; 3★ targets kept). Shown on cards and in the pivot plan; it moves no place.
- **Reasonable comps** (`tools/eval_lines.py comps`).
  - MetaTFT averages show no sampling noise by pick rate (regression slope ≈ 0), so no shrinkage there.
  - lolchess-only comps carry the cross-site offset's uncertainty (sd 0.49), so empirical Bayes keeps 61% of their distance from MetaTFT's mean. Hyperpop Seraphine 2.81 → 3.57.
  - Comps sharing 80%+ units collapse into one suggestion card that lists the variants (K/DA Neeko / Leona / Kai'Sa).
  - Flags left: lolchess-only comps have no openers or levelling. Vayne, Wukong, Thresh and Pyke unlock by in-game conditions.
- **Harness after all this:** late boards' source comp suggested 99%, openers 82%. Random 8 units: 3.6 realistic comps. Never the plain top 4; 50 of 57 comps suggested somewhere.
  - A comp's own carry components beat 65% of comps on item gain, down from 98%: comps whose carries need items gain more from the same components.
  - `tests/test_scenarios.py` adds the Seraphine window, Kobuko unlock-ready, the Annie hero augment (+0.3 over a non-Annie comp) and the Pentakill trait augment.

### Realistic lines, components that steer, and a test harness (2026-11-21)

- **Problem:**
  - With many units on the board, every comp kept at least one of them, so all 57 counted as "reachable". Suggestions were just the best comps.
  - Components counted as half a best-in-slot item whenever they built anything a comp wanted, which was almost always, so every comp got the same small bump.
- **Test harness:** `tools/eval_lines.py` samples boards from MetaTFT's own comps. Each draws a comp by pick rate, then takes either an opener (its listed units, other slots filled from everyone's openers) or part of its final board, sometimes with a stray unit.
  - `fit` fits "where your units lead" on 4,000 boards: floor 0.3, opener likelihood 0.7, alpha 2.0. A cost weight was tried and fitted to 0 (no help). Held-out log-likelihood: −0.88, vs −1.37 before and −3.87 for chance. The top guess is the source comp 69% of the time; it's in the top 3 91% of the time.
  - Split conformal on 2,000 more boards: τ = 0.20 of the best odds keeps the source comp in the realistic set 90% of the time (89.5% on 2,000 test boards).
  - `eval` runs the line finder on 300 boards. Late boards: source realistic and suggested 100%, from 1.1–2.1 realistic comps. Openers: realistic 82%, suggested 79%, from 2.5–4.4 comps. 8 random units: 3.7 realistic comps (was 43). Suggestions are never just the 4 best comps (was 18%), and 56 of 57 comps get suggested somewhere (was 27).
- **Suggestions:** the best 4 by expected place within the realistic set. A mixed board with fewer than 3 realistic lines gets the next likeliest ones, marked "stretch".
- **Components:** matched to the comp's best-in-slot recipes in slam order, main carry first. MetaTFT names a comp after its carry, e.g. Gu Feng *Aphelios*.
  - A pair that builds one = that item's premium. An unpaired component that's half of a wanted item = half.
  - New Set 18 measurements (`tools/calibrate.py items`, 22,784 boards): best-in-slot on the carry −0.094 places [−0.116, −0.071], elsewhere −0.079. An off-type item on the carry (an AD item on an AP carry, typed by recipe components) costs +0.065 [+0.026, +0.102] vs a normal item. So a leftover off-type component counts against that comp.
  - With your units, items reorder the realistic lines. With items only, the realistic lines are the top quarter of comps by item fit.
  - On sampled boards, a comp's own carry components give it an item gain that ties or beats 98% of comps, and it gets suggested 83% of the time.
- **Tempo:** the early-strength term (measured on level 4–6 openers) now applies only to boards of up to 6 units. A full K/DA Kai'Sa board was losing 0.7 places to it.
- **Pro-intuition scenarios:** `tests/test_scenarios.py`. Openers lead to their families. A 2★ Renekton or Jax/Annie 2★s don't force a reroll. A late K/DA or Rock Vayne board is that comp. Many units narrow the lines. A 2★ Baron offers Prodigy Malzahar first. AP and AD components steer by about 0.04–0.05 places on average.
- **Limits:**
  - Sampled boards are a model of real ones: MetaTFT lists opener core units only, and the filler is drawn from everyone's openers.
  - Coverage on openers is 82%, below the 90% target, because the page also requires a kept or opener unit.
  - The item effects are Set 18's. Items can't overcome a full place of comp strength, so with items alone the strongest AP- or AD-fitting comps still lead.

### Board strength reworked: fight power (2026-11-21)

- **The problem:** board strength barely moved with stars (Renekton alone read 41% / 43% / 46% at 1★ / 2★ / 3★). There were two causes.
  - The ranking model is linear in board gold value, which is fine between 8-unit boards and wrong between small ones: a 3★ 2-cost is about 10× a 1★ in a fight, not "+16 gold".
  - Its temperature (0.35) came from boards knocked out in the same round. Their order mostly follows HP lost, not fights, so every gap got squashed. A 1-unit board was also compared with the 3-unit typical board.
- **Fight power** (`engine/power.py fight`): Lanchester's square law, a team's strength = total effective HP × total damage per second.
  - HP per unit comes from the Set 19 audit (tftips + Blitz).
  - Armor + MR come from Set 18 bands by cost and melee/ranged, damage per second from Set 18 bands by cost (CommunityDragon).
  - Each star multiplies HP and attack damage by 1.8 (game rule).
- **Fight score** = k × ln(fight power) + T × the ranking model without its gold and unit-count terms (unit identity, traits, items, carry).
  - k = 0.75 and T = 0.275, fitted together by maximum likelihood on 7,351 Set 18 same-round pairs with Set 18's own unit stats. Log-likelihood is −0.670 per pair, vs −0.661 for the ranking model and −0.693 for chance: as good at endgame, and right for stars and board size.
- **Typical board per size:** pick-weighted over MetaTFT's Set 19 boards.
  - 4–7 units: openers, filled as in `calibrate.py par`.
  - 8+ units: final boards' average slot × n.
  - 1–3 units: the level-4 average slot × n.
- **Results:**
  - Renekton alone reads 54% / 74% / 88% at 1★ / 2★ / 3★.
  - In Ziggs, Lulu, Swain, Teemo (all 1★), a 3★ Ziggs takes the board from 68% to 80%.
  - Tempo gold follows: +2 / +14 / +25.
- **Checks and limits:**
  - On MetaTFT's 172 opener boards, fight power tracks round win rate slightly better than the ranking score (corr +0.10 vs +0.07). Both are weak because MetaTFT records no stars or items for openers.
  - k is a floor: same-round order is a noisy view of fights, so real fights are probably more one-sided than shown.
  - Ability damage isn't in CommunityDragon's Set 18 file, so damage is by cost and casters' 3★ ability scaling isn't modelled.
- **Follow-up (same day): a level-8 board with a 2★ Baron read 39%.**
  - *Real flaw:* damage per second was attack damage × attack speed only, which barely rises with cost (29 → 36 from 1- to 4-costs), because casters' ability damage isn't in CommunityDragon's file. So expensive units, and the 7-cost Baron (capped at the 5-cost band), hit no harder than 1-costs.
  - *Fix:* damage × cost^γ, with γ = 0.5 fitted with k and T on the same Set 18 pairs. Log-likelihood improves from −0.670 to −0.666 (the ranking model gets −0.661). Now k = 0.86, T = 0.26, and costs above 5 use their own cost^γ.
  - *What remains is real.* In Set 18 data, level-8 boards carry about 11 completed items with their 4-costs at 1.7★; even those knocked out in stage 4 carry 8.5 items at 1.4★. That board had 3 items and four 1★s, so it reads 40%. Adding 6 items brings it to 51%; all 2★, 57%. Swapping the 2★ Baron for a 2★ Braum drops it to 28%.
  - *The strength card now explains itself:* units & stars / items (held vs typical) / traits, each part's gap alone in points of win chance.
  - Finished boards with fewer than 8 units no longer count toward the level-7 typical board.
  - *Open question:* the opener reference uses PAR's item counts (1/2/3/4 at levels 4–7, a knowledge prior). Set 18 deaths suggest boards carry more items earlier; measuring items by stage needs Set 19 games.

- **"vs lobby at a round" picker** on the strength card, offering 2-1, 3-2, 4-1, 4-2, 4-5, 5-1, 5-5 and 6-1; the default stays "vs same size".
  - Win chance = the chance of beating each MetaTFT comp's board at that round, averaged with weights from how often each comp is played. Each comp sits at the level its MetaTFT levelling gives it then: at 4-1 the lobby is 80% level 7; at 4-5, 71% level 8.
  - Rounds before 4-2 use the openers, with the star rule and PAR item counts. From 4-2 on, rounds use Set 18 boards knocked out at that round: completed items (6.6 at 4-2, 8.6 at 4-5, 10.3 at 5-1, 11.8 at 5-5, 12.8 at 6-1) and mean stars by cost (4-costs 1.25★ at 4-2, 1.83★ at 6-1).
  - The level-8 board with a 2★ Baron and 3 items reads 98% vs the lobby at 2-1, 72% at 4-2, 63% at 4-5, 55% at 5-1 and 41% at 6-1.
  - Display only: tempo and comps' places keep the size comparison the tempo slope was measured on, and the "gold over stages 2-3" line hides while a round is picked.
  - Seam: 4-1 (PAR's 4 items at level 7) → 4-2 (6.6 measured). PAR's early item counts look low next to Set 18 and need Set 19 games to measure.
- **Layout:** the items panel is wider (8 columns of 34 px icons, `clamp(260px, 27vw, 400px)`), so every item tab ends level with the board instead of running far below it.

### More comps, pivot-aware suggestions, cleaner layout (2026-11-21)

- **More comps: lolchess.gg "Meta Trends" (Set 19 PBE).** 30 comps read in the browser; `tools/import_lolchess.py`; private, since lolchess is "All Rights Reserved". MetaTFT's page has 44 comps and no more; its "Situational" toggle adds none.
  - 25 of lolchess's 30 comps use exactly the units of a MetaTFT comp. lolchess splits them by carry and itemization (K/DA Evelynn / K/DA Neeko / K/DA Kai'Sa are all MetaTFT's K/DA Neeko).
  - So a straight-line fit between the sites is meaningless (slope 0.39). Instead:
    - a variant sits at its parent's MetaTFT average plus its gap from the parent's lolchess average (same site, same days);
    - new comps take the median site offset (+0.18 places, sd 0.49, over 20 comps).
  - Result: 57 comps, adding 9 carry variants (K/DA Evelynn 3.29 vs K/DA Kai'Sa 4.17; Gu Feng Aphelios 3.81 vs Gu Feng Xayah 4.46) and 5 new comps (Hyperpop Seraphine 2.81; Beach Pop Renekton, Renegade Qiyana, True Damage Senna are weak).
  - The tier list stays bottom-heavy because the PBE meta is: both sites put about a third of comps at 4.8+. The page folds the C and D tiers away by default.
- **Pivot-aware suggestions.**
  - Every comp is shown, not just those using your units.
  - **Where your units lead** (naive Bayes) treats a unit a comp doesn't play as possible tempo filler. Its likelihood is the comp's measured tempo share (the fraction of its MetaTFT opener units that never reach its final board; mean 0.41) times how often anyone opens with that unit. It no longer counts as near-impossible, so a 2★ 2-cost no longer pins you to the one reroll comp that plays it.
  - **Suggested lines:** the strongest comps (expected place with your items, augments and board strength) among those that keep or open with at least one of your units. Each shows its pivot plan: keep, fits its openers, tempo now and sell on the way.
  - Example: Jax 2★, Annie 2★, Elise, Yunara suggests Hyperpop Kobuko (keep Elise and Yunara), Prodigy Malzahar Ekko, Ionic Spark Jinx and Hyperpop Kobuko Ziggs, not Swiftstriker Annie.
- **Layout:**
  - augments (labelled 2-1 / 3-2 / 4-2), board strength and conditions sit in a bar above the board, with no sidebar;
  - the selected unit is a strip under the bench;
  - all 94 champions are visible with no inner scroll (40 px portraits grouped by cost, names on hover);
  - the suggested lines come first, and each comp card shows how many of your units it keeps.

### Data-backed calibration and the pro playbook (2026-11-21)

- **Board model, fine-tuned on Set 19:** refitted on MetaTFT's 470 level 7-10 boards with their average places, using ridge regression on trait-tier offsets toward the transfer model. Tested on whole comps held out: error 0.779 → 0.691 places, within-level Spearman 0.26 → 0.45. Per-unit offsets were tried and generalised worse.
- **Typical board per level:** measured, not guessed. Levels 4-7 come from MetaTFT openers weighted by pick rate; levels 8-10 from Set 18 boards placing 4th-5th. The early-level prior held; the late-level prior was far too low (L8 6.40 vs 9.02 measured).
- **Augment scales:** the per-comp "needs" are stable (split-half 0.8) but don't match within-comp regressions on Set 18. They're shrunk halfway to their archetype's mean.
- **New in the line finder:**
  - where your units lead (naive Bayes on pick and play rates);
  - expected LP and top-4 rate per comp;
  - item value from each comp's own item table;
  - "Pro playbook for this line": the archetype's rules first.
- **Pro playbook:** 100 rules with numbers and dated sources, 11 of them flagging where sources disagree. Files: `docs/knowledge/pro_playbook.md` and `data/manual/pro_rules.json`, generated by `tools/build_playbook.py`.
- **`tools/playbook_review.py`:** the checkable rules applied to a recorded game, post-game. On the 3 recorded pro games, every checked rule held once two exemptions learned from those games were added:
  - win-streaking players at 80+ HP spend under the 4-1 gold checkpoint;
  - fast-9 players go level 8 without roll gold.

### Team builder, round 3 (2026-11-20, night)

- **Layout:** the item pool moved to a left column beside the traits. The augment slots and board strength share one panel, so the right sidebar is shorter.
- **Unlock text:** plain English for all 13 condition kinds; a test checks that no raw keys show.
- **Board strength:** the old "stronger than X% of same-size meta openers" metric always read 0% for 1★ boards, because MetaTFT's openers are partial, starred-up cores. It is now the win chance against a *typical board of the same level*:
  - the typical board per level is a TFT-knowledge prior (`power.PAR`);
  - the chance is a sigmoid of the score gap, with temperature 0.35 fitted on 7,351 Set 18 boards eliminated in the same round;
  - a Monte Carlo of the stage-2/3 fights turns it into gold-equivalent (streak gold plus HP kept).
- **New MetaTFT data:** every comp's panel was scraped (`data/manual/TFTSet19.metatft_details.json`, private). It has:
  - level 7-10 boards with average places and level shares;
  - final-board hex positions;
  - levelling stages with rerolls spent per level;
  - carousel priority;
  - in-comp unit and item tables (average place, play rate);
  - the placement distribution and how often 3+ players are on the comp.

  MetaTFT shows **no augment data per comp** (or at all for Set 19).
- **Augment model** (`engine/augvalue.py`, documented in docs/knowledge/techniques.md):
  - TFT-knowledge anchors per augment kind, scaled by each comp's measured need for levels, 3-stars and items, and by trait breakpoint gaps; clamped to 0.3-1.8×.
  - Values are centred on an average augment for that comp.
  - Augments are now the largest weight (±1.2), then artifacts/radiants (1.0; a radiant counts 3×), then early strength (±0.4).
  - Expected place uses gains on the distance from 1st (`linefinder.adjust`), so it stays in 1-8.
- **Comp detail:**
  - "Why this tier" comes first: a waterfall from MetaTFT's average through each kind of adjustment to your expected place, with every reason and its value.
  - Stage tabs (Opener levels 4-6, Midgame 7-8, Late 9-10, Final) each show a real hex board. Units keep their MetaTFT final positions; the rest go front or back by range. Stars and items follow the stage.
  - Below the tabs:
    - **Progression:** levelling stages with reroll bars, carousel priority, top-4 / 1st / contest rates.
    - **Optimal itemization:** BIS per carry, the comp's item table, artifact holders.
    - **Crucial conditions:** the augments the model rates best for the comp, unlocks, and the +1 / flex units with their in-comp average place.
- **Not validated:** the augment anchors and the typical boards are knowledge priors. Nothing can fit them until Set 19 augment stats or our own recorded games exist.

## Board strength for Set 19: transfer from Set 18 (2026-11-20)

`engine/power.py build` writes `data/board_model_TFTSet19.json` (gitignored: MetaTFT-derived).

- **Method:** on Set 18, regress each Plackett-Luce weight's distance from its kind's mean on the average-place gap MetaTFT would publish (from the crawl). Then set each Set 19 weight to Set 18's kind mean plus slope × MetaTFT's Set 19 gap, shrunk by sample.
- **Transfer correlations on Set 18:** unit-stars −0.09, trait tiers −0.21, items −0.31 (MetaTFT's averages carry a little signal).
- **Check against the 43 comps' average places (Spearman):**

  | Model | Spearman |
  |---|---|
  | Transfer | 0.36 |
  | Kinds only | 0.26 |
  | Structural early score | 0.24 |
  | Gold value | 0.08 |

- **Earlier attempt:** a fit on MetaTFT's opener round win rates lost to "every board at a level alike" (held-out 0.50 vs 0.50). Those early boards are partial (core units only) and biased (mean round win rate 0.56-0.68), so they're displayed, not fitted.
- **Launch day:** `board_model.py fit 19 --prior 19` starts from this model.

## Research files (2026-11-20)

docs/knowledge/:
- **tft_fundamentals.md:** star and cost scaling, openers, midgame, items, augments, counters, the factors a strength model needs.
- **board_strength_methods.md:** what MetaTFT's numbers are (back-solved), biases and fixes, the recommended early-power method.
- **set19_meta.md:** PBE comps, openers, unlocks, conditions, augments, mechanics.
- **set19_catalog_audit.md** (+ `data/manual/TFTSet19.audit.json`): roster, traits, augments, artifacts and radiants checked against public sources.
- **techniques.md:** which ML/CS technique does what with MetaTFT data, now and once Set 19 data exists.

Applied from them:
- True Damage breakpoints [3, 5].
- 2 confirmed augments added, plus 15 unconfirmed ones with a status field.
- Renames (Stakeholder Management+, Bundle o' Shrooms II) and stale summaries fixed.
- Akali (True Damage) bling 350 and Janna interest 25 (Mobalytics, newest).
- The level-11 scroll is Gu Feng's, not Classical's.

**Open:** MetaTFT's level-7 to level-10 comp variants. The first scrape read a stale panel and was discarded; the fixed scraper needs the browser pane visible.

## Artifacts (2026-11-20)

Some units are far better with certain artifacts, so artifacts now count in line choice and in item choices.
- **Data**: MetaTFT's PBE artifact list (32 artifacts, average place and estimated place change: Eternal Pact -0.74 ... Rapid Firecannon +0.12) and each artifact's six best holders with their own place change (Lich Bane on Ziggs -1.22, Blighting Jewel on Renata Glasc -1.28, Statikk Shiv on Ziggs -1.27). Private file `data/manual/TFTSet19.metatft_artifacts.json` (gitignored). Holder rows under 0.1% of a unit's games are dropped (one Katarina game read "avg place 1.00").
- **Reading**: item choices replace the shop strip with named cards; `hud.read_item_offers` reads them (2+ known item names in a row) and the recorder keeps each round's offer (`item_offer`). In the robinsongz game: artifacts at 4-2 (Aegis of Dusk, Manazane, Zhonya's Paradox, Death's Defiance), components at 4-4 and 5-1, completed items at 6-1 and 7-1. Held artifacts come from the item bench and the items read under your units' bars; the item model knows 30 of the 32 (not Talisman of Ascension, Horizon Focus).
- **Line choice**: each held artifact lowers a line's expected place by what it's worth on that line's best holder (capped at 1 place).
- **Item choice**: artifacts ranked by their best holder among the line's units ("Death's Defiance: on Renekton -0.29 places"), then items MetaTFT lists on the line's carries, then components that complete one with a component you hold; else "no pick for this line".
- Not known: which card was taken (an offer's pick isn't read yet), artifact icons in Set 19 art (the classifier learned older art for the same names).

## Advisor: line, buys, items, augments (2026-11-20)

`engine/advise.py` gives per-round advice from what the screen showed (post-game, POLICY.md), and `tools/eval_advice.py` scores it against what the recorded (strong) player did. Each round is judged from the spot before acting: last round's panel, board and copies owned, this round's shops.
- **What it can see now**: your trait panel; **every card offered in the round** (`shop_seen`, rerolls included, new in the recorder); copies bought (ledger); held components; augment offers and picks; other players' HP and level badges; and **other players' trait panels while you scout them** (`scouted`: panels read while your HUD bar is hidden, one per board, ours told apart by trait counts). From a scouted panel, `infer_board` guesses that board's units, so the advisor knows which units others hold. Not visible: other boards' stars and items, your own stars beyond the ledger, Set 19 best-in-slot items.
- **Line**: the best-fitting comps (MetaTFT PBE; up to level 7 a comp also fits by its **early board** for your level), each priced by the shop simulation: the **share of its core you can expect to hold** by the comp's own deadline (when its players reach its final level on MetaTFT: fast 9 ~5-2, rerolls when they roll), at your level, gold and the odds by level, with the pool reduced by copies on scouted boards (3 per board from stage 3); expected place = that share x the comp's placement + the rest x 5. From stage 4 a line needs half its core held (no late pivots to a 40% line). A share, not P(own all of it): with every core unit required, every comp read ~0% in stage 3 and the ranking was noise.
- **Buys**: copies of units you hold (toward 2-star; 3-star for carries and reroll comps), the line's core and flex and its early board for your level, first copies that add to your active traits (4-5 costs count more from stage 4), less for units on scouted boards, a penalty late for units that fit nothing.
- **Items**: completed items your held components make (36 standard recipes), those MetaTFT lists on the line's carries first ("for Ziggs"), else Riot match data's best-in-slot after 12-02.
- **Augments**: the final offer ranked for the top lines (`augments.review_offers`).

Scored on the 2 recorded games (69 purchases seen, 2 known augment picks):

| | Advisor | Baseline |
|---|---|---|
| Buys: purchases it said to buy (recall) / its picks that were bought (precision) | 61% / 27% | buy only units you hold: 35% / 30%; a random card: 17% precision |
| Line: top line is one of the game's final main traits (3+ units), rounds from 3-1 | 89% of 54 (91% with the 11-19 comp data and the 4-5 deadline; 81-82% while reach meant "own every core unit") | your biggest active trait then: 78% |
| Augments: best fit was the card taken | 0 of 2 | random: 1 in 3 |

Read with care: the buy weights were changed after looking at these two games (the first version, line-units-first, scored 19% / 28%: strong players buy many first copies that fit their traits), so these numbers are optimistic; the next recorded games are the real test. Precision is understated: the ledger misses buys. Agreement with a strong player measures "plays like them", not "optimal". Augments: 2 picks say nothing yet. Two scouted boards in the robinsongz game (K/DA at 4-6, a Frontman board at 6-6): **scouting each opponent once a stage in your own games** is what lets the advisor see the lobby's comps.

## Fight model (2026-11-20)

`engine/fights.py` turns recorded games into one row per PvP fight and learns from them (ML_RESEARCH step 3):
- **Row**: the round's planning phase (recent form over the last 4 fights, your level, the mean level of the other living players from the **level badges on their portraits**, now read by `hud.read_lobby_levels` and kept per round as `lobby_level`, only reads from the last 3 rounds; board strength of the inferred board) and the outcome from the next round's HP (won, HP lost, whether it killed). A game read several times counts once (the read with the most of the lobby, then the newest).
- **Win model**: logistic regression on logit(form), level gap and strength relative to the stage's mean, fitted by Newton's method with an L2 pull toward the hand-set tempo model (form 1.0, strength 3.0, plus a guessed 0.5 per level of gap) about as strong as ~30 fights. **HP per loss**: a multiple of the rules' damage, shrunk toward 1 by 5 pseudo-losses.
- **Use**: `python3 -I engine/fights.py fit TFTSet19` saves `data/models/fights_TFTSet19.json`; the tempo evaluator then takes its starting win chance, strength slope and HP per loss from it (hand-set otherwise; the tests pin the hand-set path).
- **Now, on 2 games (48 fights, 12 losses)**: the fit stays near the prior (form 0.81, level gap 0.58, strength 2.99, bias +0.08; HP per loss 0.98 x rules). Leave-one-game-out log loss 0.600 hand-set vs 0.559 fitted (a coin flip is 0.693): the level gap helps, but two held-out games are thin evidence. The damage rules hold up: 1.6 HP mean error per loss (the fitted ratio, 1.9, is no better).
- **Strength only where the bars were read**: with star badges a board scores ~40% stronger late than the same board scored from ledger stars, so mixing the two made strength a "which game" flag (held-out log loss 0.713, worse than a coin flip). Rounds without bar reads now have no strength value.
- **How many games**: on simulated fights whose true effects differ from the prior (level gap 1.0 instead of 0.5), the fit gets most of the possible gain by ~10 games (250 fights; log loss 0.593 vs 0.590 at 40 games and 0.631 for the prior). Real effects are unknown, so this is the order of magnitude, not a promise.
- Not yet: the opponent of each fight (the name over the board in combat), which would turn "vs the lobby" into "vs this player"; streak and HP-rank features; strong-player norms (behaviour cloning) for the review's thresholds.

## Tempo evaluator (2026-11-19)

`engine/tempo.py`, also shown in `review.py` as TEMPO notes (they replace the SPEND/BLEED rule of thumb at that round). At each PvP planning phase it rebuilds the spot before you acted (gold = last round's gold + income, natural XP, last round's board) and prices six options: save, level, roll to 20, roll to 0, level + roll to 20, level + roll to 0.
- **Accounting is now-vs-later**: levels, units and rolls get bought either way, so gold spent counts as kept. Acting now costs the interest given up; waiting costs HP. Streak gold is included, so loss-streaking is valued like any other way of trading HP for gold.
- **Rolling** = chance to buy the copies that star up units you field (`econ.hit_chance` at your level's odds, pool minus copies out by stage); several targets share one budget. **Levelling** adds a slot: your best benched unit, else a 1-star of the likeliest cost.
- **Fight model (placeholder)**: the chance to win a round starts from your last 4 PvP results and moves with the strength an option adds (`FIGHT_SLOPE`). HP lost = expected losses x stage damage over the next 3 PvP rounds; death risk = enough losses to end the game.
- **HP price**: gold per HP rises as losses-to-death fall (1/2/4), the game ending costs 100, and both are scaled by your place in the lobby's HP (on top, the others go out first).
- **Calls** only compare rolling and saving under the level choice you made (what a level buys beyond its slot isn't modelled yet), need 20+ gold at stake and a 10-gold-equivalent gap.

Checked: a synthetic bleed (30 HP, loss streak, banking 60) is called ("roll to 20: est. 8 HP lost instead of 22, death risk 1% instead of 30%, giving up 8 gold of interest"); the same bank at 90 HP on a win streak isn't. On the two recorded games (a lobby leader, a Rank 1 fast 9) it calls nothing, which fits but doesn't prove much. Hand-set until recordings can fit them: `FIGHT_SLOPE`, `HP_GOLD`, `DEATH_GOLD`, `HORIZON`. Not modelled: finding new units while rolling, odds gained by levelling, pool contest from other players.

## Item bench: held items (2026-11-20)

- **Where**: held items are not on the board; they're a column of 10 square slots down the HUD's left edge, beside the trait panel (1080p: first slot at y 261, 54 px apart, 45 px wide; kept in units of frame height). Empty slots are black inside, so emptiness is read from brightness, not the classifier. Lines up at 720p too.
- **Reading**: `tftcap held FRAME --model M` for one frame; during `--units` VOD/live reads every frame gets a `held` list (slot, item, confidence), stored in rows.jsonl.gz. The recorder keeps reads at 0.9+ (`BENCH_MIN_CONF`) and per round stores the most common reading as `items_held`.
- **Model**: consumables were forced onto the nearest item (the Reforger's fire anvil read as "The Eternal Flame", the Magnetic Remover as an emblem). Fix: `tools/fetch_consumable_icons.py` adds 11 consumable icons (anvils, duplicators, dummies, remover, reforger, tome) as their own classes; a third of the synthetic samples are now drawn bench-style (bigger, gold frame, sometimes a use-count badge or dimmed); and 39 real bench crops I checked by eye (Magnetic Remover, Reforger, Tear, Giant's Belt, Recurve Bow) were added to `data/raw/labels/items`. Unit item slots got better too on the frame checked (3 of 4 disputed reads now right, e.g. a footprint Choreographer Emblem had read as Beach Pop Emblem).
- **Accuracy so far**: components read at 0.99-1.00 (Tear, Giant's Belt, Recurve Bow); Reforger 0.91-1.00; Magnetic Remover 0.65-0.95 (0.95 on the held-out 720p game). Below 0.9 and dropped: an unknown purple consumable (read as Needlessly Large Rod 0.78), stream chat over a low slot, dimmed icons. Not yet measured on a held-out set of labelled bench crops. Full robinsongz 1080p game with the retrained model: per-round held items follow the frames (Recurve Bow and Giant's Belt early, Magnetic Remover and Reforger, Tear of the Goddess late); two unverified reads remain (Gargoyle Stoneplate at 3-4, Bodyguard Emblem at 5-7). No SLAM note fires, which is right: no buildable pair was held through losses.
- **Use**: the review's SLAM note: two components that build an item (the 36 standard recipes from CommunityDragon; Spatula/Frying Pan emblems left out) held through 2+ lost rounds in a row, once per stage: "held B.F. Sword and Sparring Gloves through 2 lost rounds: together they make Infinity Edge...".
- Left: a slam option in the tempo evaluator (needs item value in the Set 19 strength model, which has no item terms until the board model is trained on Set 19 lobbies); recipe suggestions for the carry; emblem identities on the bench beyond the ones verified.

## Parse-health audit (2026-11-20)

`python3 -I tools/audit.py [recordings/<dir> ...]` checks every recorded round against the game's own rules, so it needs no labels. Hard rules: no skipped rounds, level never falls, XP rises by the free 2 plus 4 per purchase, HP rises at most a few points (Set 19 has small heals), a loss costs at most stage damage + a full board, a streak grows by one or restarts, shops offer only costs the level allows, other players' HP barely rises. Softer flicker checks: the trait panel adding up to far less than both neighbouring rounds, the item bench changing for one round, health bars that can't be the board. A frame pass over rows.jsonl.gz measures raw OCR noise (a value differing from both neighbouring frames) and how often each field is unread. Reads that contradict the rules file every time are listed as rule notes.

Results on the 7 recordings (3 games):

| Field | Broken / checked | What breaks |
|---|---|---|
| stage, level, XP, shop | 1/260, 0/248, 0/168, 0/210 | Nothing in the VOD reads (the one stage break is the old browser-window recording) |
| HP | 15/259 | Almost all in the old browser-window recording (50 read for 100); the 720p VOD read 61 for 67 once |
| streak | 4/95 | The HUD's "6" reads as "9": robinsongz's streak of 6 (after the 3-1 win, through 3-2 planning) read 9 in 42 frames and 6 in 6 |
| traits | 25/248 | Rounds where the panel is mostly unreadable (4-6: 29 of 39 frames sum to 1-2 units) still count toward the 1/3 threshold, so the real traits drop out |
| board (health bars) | 47/144 | Bars outside level-2 .. level+1 in 7 of 36 rounds on the latest 1080p read (26/36 on the first read) |
| items (bench) | 6/70 | One-round flicker: Gargoyle Stoneplate at 3-4, Bodyguard Emblem at 5-7, a Reforger missing at 3-5 |
| augments | 9/15 picks unknown | The older recordings predate pick detection; robinsongz's 4-2 pick is still unknown |

- **Frame noise** (latest 1080p read): one-frame blips are 0-2% for stage, level, XP, gold and HP, 6% for the item bench. Unread share of frames with a stage on screen: XP 31%, gold 22%, streak 20%, level 11%, HP 9%. Not yet split into combat (shop closed) vs planning frames.
- **Purchase ledger**: 32-80 gold rises a game it couldn't explain. The weakest part of the recorder.
- **Rules file, fixed**: the XP to go from level 7 to 8 is 60 in Set 19, not Set 18's 56. The XP bar reads "/60" at level 7 100-207 times in each of three games and never "/56". `data/constants.json` updated.
- ~~**Rules file, open**: losses far past the damage cap~~ **Misreads, not rules** (corrected the same day): after the HP reader fixes below, both reads of the subzeroark game agree on 93 -> 82 -> 68 -> 54 (the old reader read 59 and 30), and on the 12 losses in the two games the rules' damage (stage damage + typical survivors) predicts the HP lost within 1.6 HP on average (`engine/fights.py`).
- **HP heals are real**: robinsongz 100 -> 103 at 2-1 (56 of 80 frames read 103) and one opponent +2 a round at 3-5..3-7 (44-50 frames each). The audit allows up to 5 a round.

Done since (same day, see next section): (1) streaks follow the streak rule, (2) the trait panel ignores collapsed/partial and scouted readings, (3) the unread gold/XP frames are frames where the HUD bar isn't on screen. Left: (4) the purchase ledger.

## Is the parser ready to record real games? Truth check (2026-11-20)

The audit only proves reads are consistent. To know they're *right*, 44 frames of the robinsongz 1080p game (one mid-planning frame per round + 8 random, combat and overlays included) were read by hand from zoomed crops of the stage, HUD bar, shop, trait panel and player list, without seeing the reader's output: `data/raw/labels/hud/robinsongz-beachpop-1080p.jsonl`. `python3 -I tools/eval_hud.py LABELS recordings/<dir> -v` scores the reader per field (right / wrong / missed where shown, phantom where not shown).

| Field (per frame) | Before fixes | After | What was wrong |
|---|---|---|---|
| stage, level, XP | 100% | 100% | — |
| gold | 78% (3 phantom) | 97% (0 phantom) | Lone digits 1-6 dropped though the 3x re-read had them; "998" (coin + misread 2) beat the re-read's "28"; board text read as gold while the HUD bar was hidden |
| your HP | 95% | 98% | The player list shifts right ~1% late game, out of the HP column |
| other players' HP | 74% | 99% | Same shift (late 0s unread); HP fused onto names ("Meneyota 42", "LooptheLoop40"); the 3x column caught name tails ("Woo" -> "00") and the reader then gave up |
| shop | 95% | 95% | Misses are cards mid-animation |
| streak | 89% | 89% per frame, 98% per round | Vision misses the digit on the flame now and then; per round, the streak rule keeps only readings that are the last streak + 1 or 1 (the "6" read as "9" in 42 frames is gone) |
| traits | names 97%; count right or a correct lower bound 87% | same frames | Inactive "1/2" counts now read from the 3x rows ("I/1", "]/3" too); a hexagon's 1 read as "I". Left: ~10% of counts unread or under (lower bound) on silver/gold hexagons |

Round-level fixes found on the way (all recordings re-parsed; the audit now finds 0 broken rounds for HP and traits, was 15 and 25):
- **Scouting**: looking at another player's board hides your HUD bar and shows *their* trait panel, units and item bench (robinsongz 4-6: 160 frames of Meneyota's K/DA board read as his). Frames without the HUD bar no longer feed traits, units or held items.
- **The trait panel collapses in combat** to a few inactive traits plus a "+9" badge, and in planning shows "1+".."4+" when traits don't fit. The badge is read (`traits_hidden`); a round whose panel hid traits keeps last round's hidden ones marked `carried`, which board inference treats as allowed but unverified.
- **Stage 1 OCR was never stored** (no layout landmark yet), so re-parses began at 2-1; kept from now on.
- **Fresh end-to-end read** of the 1080p video with all of the above (`recordings/vod-New Set Beachpop Taliyah Summons a Tsuna-20261120-155711`): 39 rounds from 1-2, audit 0 broken rounds for gold, HP, streak, traits and lobby HP; the truth score is unchanged from the re-parse.

Board inference on the 14 hand-labelled boards: 87% precision / 86% recall / 6 exact (94% / 92% / 4 of 7 on rounds whose labels explain the panel), unchanged from before.

**Verdict.** The HUD numbers that drive the economy, tempo and HP notes are ready: 97-100% per frame, and the per-round rules catch what slips. Traits are good for board inference. What is *not* solved by parsing: champion identity from pixels (parked; board units are inferred, 87%), the purchase ledger (34-64 unexplained gold rises a game), and anything beyond one game: every fix was checked on one 1080p streamer layout. The first own game is the real test.

**How to record your own games so none is wasted:**
1. Play in a **16:9 window** (e.g. 1920x1080 or 2560x1440 windowed), default HUD scale. The reader's layout is 16:9; your 3024x1964 screen is 16:10, which hasn't been checked.
2. **Record the window to a video file** (OBS window capture, or macOS Cmd+Shift+5 > record selected portion). The live recorder reads only text; a video can be re-read later with every new reader (bars, items, bench, champion models), so recording never goes stale.
3. After the game: `python3 -I capture/record.py --vod GAME.mov`, then `python3 -I engine/review.py ...`.
4. **First game = calibration.** Its frames get the same hand check (44 frames, `tools/eval_hud.py`) before recording more.

## Augments by line (2026-11-19)

- Catalog: `data/manual/augments.json`, 345 Set 19 PBE augments (tftips.app, preliminary; ~95% of the set) tagged econ_gold / econ_xp / reroll / item / artifact_radiant / emblem / hero / combat / units, summaries in our own words; 7 hero augments (Olaf, Elise, Lillia, Kennen, Sett, Renekton, Annie).
- Cards not in the catalog are tagged from their on-screen effect text, so new augments still work.
- `engine/augments.py`: archetype per plan (reroll = rolls at 7 or below; fast 9 = 3+ five-costs or a level-9 unit in the core; else fast 8) -> setup (tftflow's Set 18 pattern: fast 9 Econ + Econ + Item, reroll Reroll + Combat + Item, fast 8 Econ/Item + Combat + Item) and "strong" augments (hero augments for its units, its trait's Crown/Circlet/Prismatic Tour/trait augments). Shown with every plan in `plans.py --suggest` (pre-game, static: allowed). Post-game, each augment round's offer is ranked for the line in play.
- Not yet: weighting by augment tier, combat augments rising when a board is already strong (cap-out), whether the pick happened (only inferable from effects like Called Shot's streak), and real per-comp augment placement data (none public for PBE; Riot's API has no augments).

## Next: can start now

| # | Task | Done when |
|---|---|---|
| ~~N1/N2~~ | Done for Set 19: state format in `engine/unlocks.py`, checker + scenarios. Left: map Set 16's extracted kinds to the same primitives for regression | — |
| ~~N8~~ | Done: `engine/reach.py`. Known limits: ignores bench space and other players buying during the window; pool depletion by stage is a guess; counters need 2+ rounds of history (review builds it from the log) | — |
| ~~N9~~ | Done: `engine/alerts.py` replays a game log (one state per line) and lists Free / Start now / Closing / Dead once per change; chance-based alerts only for targets and counters | — |
| ~~N10~~ | Done as `engine/review.py` (text). Left: tune thresholds on recorded games | — |
| ~~N3~~ | Built 2026-11-19 as `engine/tempo.py` (see "Tempo evaluator" below); fight model and HP per loss fitted from recordings since 2026-11-20 (`engine/fights.py`, "Fight model" below). Left: enough games for the fit to matter (~10); value what a level buys beyond its slot | — |
| ~~N4~~ | Done as generated structural plans (`engine/plans.py`). Left: replace with clusters of real final boards plus placement values after 2026-12-02 (M6); multi-band plans | — |
| ~~N12~~ | Purchase bookkeeping built into `capture/record.py`. Left: carousel/augment units and items on units stay invisible (unit recognition, M9); real-game check of how often gold changes go unattributed | — |
| N13 | Crawler run on Set 18 (500 lobbies) and model refit. Left: crawl 19.1 from 2026-12-02 and learn Set 19 trait weights; cluster boards into data-driven plans with top-4 rate | Set 19 trait weights file exists; plans carry placement data |
| ~~N14~~ | Line selection built (`engine/lines.py`). Left: tune LINE/UNLOCK weights on recordings; early boards per comp from MetaTFT/tftflow (manual, private) | — |
| N5 | Post-game report v2: carry identified from items, "with N gold you had X% to 2-star it" using `econ.py` | Runs on cached matches |
| N6 | Team Planner code export from a plan. Unit IDs probably come from the hashed field `{4d4e5cf5}` in each shop record (1002 for Set 18 Akali); public codes look like hex IDs + set name | A generated code pastes into your client and shows the right units |
| N7 | Mac capture: tool built (`capture/tftcap`: ScreenCaptureKit window grab + Apple Vision OCR; `capture/hud.py` reads stage, level, XP, gold, shop). Left: **calibrate `LAYOUT` on a real frame from your Mac** | `hud.py` on your frame returns the numbers on screen with nothing unread |
| ~~N11~~ | Recorder built (`capture/record.py`). Left: a real game once calibrated; then bookkeeping of purchases (gold deltas + shop slots) to fill the board for the unlock checker | — |

## Set 19 data: open items

| Task | How |
|---|---|
| Watch for a game-file source | `python3 -I tools/extract_unlocks.py --refresh` lists a Set 19 mode if CommunityDragon adds the standalone client; then `build_static.py` replaces the hand file |
| Conditions for Nasus, Renata Glasc, Galio, Syndra | Read the tooltip on PBE (or confirm they are no longer unlockable) |
| Odds, pools, XP, 7-cost odds | 19.1 patch notes; `data/constants.json` `TFTSet19` is a copy of Set 18 |
| PBE checklist items | `07` checklist: PvE rounds, check timing, bench counting, next-shop guarantee, 20% odds floor, where Hype/Bling counters show |

## Needs you

- ~~Where you play~~: Mac (answered 2026-11-17).
- **Confirm dropping live advice** (point 5 above, [POLICY.md](POLICY.md)).
- **Screen Recording permission** for the terminal you run `capture/tftcap` from (System Settings > Privacy & Security > Screen Recording), then one frame from a live or PBE game: `capture/tftcap shot frame.png`.
- **Which client the Mac uses after 18.6** (League client or a standalone build): look at the window title / app name next time you play. Decides the capture layout.
- **Riot personal API key**: apply now; development keys expire daily and can't run a crawler.
- **Record PBE games as video** (16:9 window; see "Is the parser ready" above): one calibration game first, then 3–5 more. Screenshots of the unlock tracker help the tracker reader.

## Later

| When | Milestone |
|---|---|
| Launch week | Crawler on 19.1 (personal key); patch prior per plan from top-4 rate and win share |
| December | Capture v1 on Mac (ScreenCaptureKit): HUD, stage, shop, augment cards, item bench, trait panel against recorded video; tracker "x/N" reader. Recorder shows nothing in game |
| December | Review mode: replay a recorded game through the engine (M5) |
| January | Strength model fitted on matches + recordings; items (best per carry within comp, holder/remover planner); augment fit rules; Prismatic Tour quests as unlock-style rules |
| Later | Bench classifier, board detector (needed for Vladimir/Taliyah and positioning), static counter-positioning cards |
