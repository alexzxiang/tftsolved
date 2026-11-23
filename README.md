# TFTSolved

A line finder for Teamfight Tactics (Set 19) that ranks the lines a board can reach, with every number traced to data. **Case study: [tftsolved.vercel.app](https://tftsolved.vercel.app)**: what it does, the methods and how each was validated.

What's inside:
- `engine/linefinder.py`: ranks lines (naive Bayes and split-conformal prediction for which lines are realistic; measured item, artifact, emblem and augment effects).
- `engine/power.py`: board strength (a Lanchester fight model fitted on 1st-vs-2nd final fights).
- `engine/survival.py`: tempo (an absorbing Markov chain over round and HP).
- `engine/provenance.py` with `tests/test_audit_weights.py`: fails if any number that moves a prediction isn't measured.
- `tools/line_finder.html`: the team builder UI.
- `capture/`: a macOS screen reader for post-game review (ScreenCaptureKit and Vision).

Python standard library only; no installs.

**About the data.** The Set 19 meta statistics the line finder runs on come from MetaTFT and lolchess, whose terms keep that data private, so they aren't in this repository. Neither are Riot's art, match data, game recordings, or the models fitted on them. `data/` holds only the game rules and the Set 19 roster, so most commands below need data you collect yourself. Tests that need private data skip.

Plan and status: [docs/ROADMAP.md](docs/ROADMAP.md). Riot rules, monetization and Mac notes: [docs/POLICY.md](docs/POLICY.md). Design brief: `docs/00`–`07`.

Nothing here gives advice during a game: Riot's TFT rules prohibit suggestions based on live game state.

```bash
python3 -I tools/extract_unlocks.py --refresh          # list set modes with unlock data (downloads ~120 MB once)
python3 -I tools/build_static.py --set TFTSet18        # roster, pools, odds, traits, rules, unlocks -> data/pbe/
RIOT_API_KEY=... python3 -I tools/postgame.py "Name#TAG"   # post-game report on your recent games
python3 -I engine/unlocks.py TFTSet19 state.json      # where every unlock stands for a game state
python3 -I engine/reach.py TFTSet19 state.json 5-1    # chance of each unlock by a stage
python3 -I engine/plans.py TFTSet19 state.json 5-1    # plans the board fits, ranked by expected placement
python3 -I engine/plans.py TFTSet19 --suggest          # strongest comps; then --focus "PLAN" "PLAN" to pick yours
python3 -I engine/lines.py TFTSet19 state.json         # line-keeping board vs strongest board (post-game)
python3 -I engine/lines.py TFTSet19 --graph            # pivots from your focused comps
python3 -I engine/tempo.py TFTSet19 recordings/<dir>/state.jsonl -v   # roll now vs save vs level, per round (post-game)
python3 -I engine/fights.py fit TFTSet19        # learn the fight model from every recorded game (tempo then uses it)
python3 -I engine/advise.py TFTSet19 recordings/<dir>/state.jsonl   # per round: line, buys, items, augment, scouted boards
python3 -I tools/eval_advice.py                  # advice vs what the recorded players did, with baselines
python3 -I tools/audit.py [recordings/<dir> ...]   # where reading breaks: rule violations per field, OCR noise
python3 -I tools/eval_hud.py data/raw/labels/hud/<game>.jsonl recordings/<dir> -v   # reader vs hand-read frames
capture/tftcap held FRAME.png --model data/models/items.mlmodel   # items held on the bench (left HUD column)
python3 -I tools/fetch_icons.py                        # once: champion, item and augment art (CommunityDragon) -> data/assets/icons
python3 -I tools/line_finder.py                        # team builder + line finder (hex board, drag and drop) at http://127.0.0.1:8766
python3 -I engine/linefinder.py Ziggs:2 Lulu --items "Spear of Shojin" --augments "X"   # same, in the terminal
python3 -I engine/power.py build                       # Set 19 board strength: transfer, fine-tune on MetaTFT boards, measured par
python3 -I tools/calibrate.py needs                    # test the augment model's per-comp scales on Set 18 data
python3 -I tools/calibrate.py augments                 # rescale augment values to measured outcomes (archived tactics.tools)
python3 -I tools/calibrate.py items|tempo|tiers         # item premiums (Set 18), tempo slope and tier cut points (MetaTFT)
python3 -I tools/eval_lines.py fit          # fit where your units lead + the realistic-line cut-off on sampled MetaTFT boards
python3 -I tools/eval_lines.py eval         # test the line finder on sampled openers, late boards, random boards, components
python3 -I tools/eval_lines.py comps        # flag comps that aren't reasonable lines (closed unlocks, duplicates, gaps)
python3 -I tools/eval_lines.py carry        # an itemised carry among filler leads to its comp; artifacts / emblems alone
python3 -I engine/survival.py fit           # HP chain: game-strength spread (Set 18 knockouts) + anchors to MetaTFT averages
python3 -I engine/survival.py check         # its knockouts by stage vs Set 18, and each comp's anchored power curve
python3 -I engine/power.py bis               # per-unit best-in-slot weights (Set 18 transfer onto MetaTFT builds)
python3 -I engine/power.py fight            # refit board strength (fight power: stars, board size)
python3 -I tools/import_lolchess.py data/raw/lolchess/<file>.json   # add lolchess comps/variants on MetaTFT's scale
python3 -I tools/audit_weights.py                      # every number on the line finder's path and its basis
python3 -I tools/kaggle_augments.py                    # augment effects from 40k Master+ games (unzip the Kaggle download into data/raw/kaggle_tft/extracted)
python3 -I tools/playbook_review.py [recordings/<dir>]  # post-game: a recorded game against the pro playbook
python3 -I tools/build_playbook.py                     # regenerate docs/knowledge/pro_playbook.md + data/manual/pro_rules.json
python3 -I engine/board_model.py fit 18                # learned per-unit/trait/item board model (needs crawled matches)
python3 -I engine/board_model.py fit 19 --prior 18     # launch day: few lobbies, start from what Set 18 taught
python3 -I engine/board_model.py fit 19 --since DATE --prior 19   # new patch: its lobbies + last patch's model
python3 -I engine/plans.py TFTSet19 --unlocks          # unlock payoff from PBE comp placements (needs the private MetaTFT file)
python3 -I engine/strength.py fit                     # learn board-strength weights from stored matches
python3 -I engine/strength.py traits 18               # learn per-trait strength within one set
python3 -I engine/strength.py search TFTSet19 8 --save  # high-synergy level-8 boards -> extra plans
python3 -I engine/alerts.py TFTSet19 game.jsonl       # review a game: Free / Start now / Closing / Dead
swiftc -O -parse-as-library capture/tftcap.swift capture/units.swift -o capture/tftcap   # Mac capture tool (once)
capture/tftcap shot frame.png && python3 -I capture/hud.py frame.png  # read the HUD from your TFT window
python3 -I capture/record.py --frames                # record your game (Ctrl-C to stop); shows nothing in game
python3 -I capture/record.py --vod game.mp4 --mask 0.7,0.6,1,1   # someone's VOD; mask their webcam (frame fractions)
python3 -I capture/record.py --window YouTube --mask 0.7,0.6,1,1   # a VOD playing in your browser (keeps OCR text only)
python3 -I capture/record.py --replay recordings/<dir>/rows.jsonl.gz   # re-parse stored OCR with a newer reader
RIOT_API_KEY=... python3 -I tools/launch_day.py         # Set 19 launch day: crawl, train, learn traits, refresh plans
RIOT_API_KEY=... python3 -I tools/crawl.py --platform na1 --set 18 --max-matches 500   # high-rank matches for training
python3 -I engine/review.py TFTSet19 recordings/<time>/state.jsonl   # post-game review: tempo + unlocks
python3 -I engine/augments.py TFTSet19 recordings/<dir>/state.replay.jsonl   # augment offers vs the line taken
python3 -I tools/harvest_items.py recordings/<dir> game.mp4       # item icons from tooltips (review, then train)
swiftc -O tools/train_items.swift -o /tmp/train_items && /tmp/train_items --backgrounds <frames dir> --extra data/raw/labels/items
python3 -I tools/reread_units.py recordings/<dir> game.mp4        # refresh unit bars + items with the current model
python3 -I tools/label_units.py prepare recordings/<dir> game.mp4 # unit crops per round, grouped, for labelling
python3 -I tools/label_units.py serve                             # label champions at http://127.0.0.1:8765
for t in tests/test_*.py; do python3 -I "$t"; done     # all checks (stdlib only, no installs)
```
