# 05 — State Capture

Reading the game state from the screen, read-only.

## Capture approach

- Windows Graphics Capture (or DXGI Desktop Duplication) on the TFT window. Borderless windowed, fixed 1920×1080 for v1. Other resolutions are not exact scalings, so each needs its own layout file.
- **Event-driven, not every N frames.** Sample at ~5 fps only to detect phase and change; run the expensive readers when something changes:
  - phase transition (planning ↔ combat ↔ carousel ↔ augment select)
  - shop region hash changed
  - gold digits changed
  - board/bench region hash changed during planning
- TFT moved to a standalone client on 2026-11-04. Confirm window title/process name and that capture works with Vanguard running. Never inject, hook, or read memory.

## What to read, by difficulty

| Field | Region | Method | Difficulty |
|---|---|---|---|
| Stage-round | Top bar | Digit templates / OCR | Easy |
| Gold, level, XP, HP | HUD | Digit templates | Easy |
| Win/loss streak | HUD icon + number | Template | Easy |
| Shop (5 slots: name, cost) | Bottom | OCR of name text + cost-colour check; fuzzy-match to roster | Easy |
| Special shop offerings (Baron's instruments etc.) | Shop | Template per offering | Medium (new art) |
| Item bench | Left side | Icon template match | Medium |
| Active traits + tiers | Left panel | Icon + count OCR | Medium |
| Augment choices | Centre cards | OCR of titles; fuzzy-match | Easy |
| Lobby HP list | Right side | OCR | Easy |
| **Unlock progress** | Unlock UI / tooltip | OCR of "x / N" | **Unknown until inspected on PBE** |
| Trait currencies (Hype, Bling) | Trait tooltip or HUD | OCR | Unknown |
| Bench units (9 slots): identity, stars | Fixed slots, 3D models | Classifier on slot crops | Hard |
| Board units: identity, stars, hex | 3D, perspective, overlapping | Detector + hex mapping | Hardest |
| Items on units | Small icons under units | Template on per-unit crop | Hard |
| Round result | Banner / HP delta | Derive from HP change | Easy |

## Avoiding the hard problem

Unit identity on board and bench is the costliest part. Reduce reliance on it:

1. **Inventory by bookkeeping.** Every unit enters through a known event: a shop purchase (shop slot goes empty and gold drops by the cost), a carousel pick, or an augment/drop. Track purchases and sales from shop and gold deltas, and the engine knows what the player owns without recognising models.
2. **Use the trait panel as a checksum.** Active trait counts constrain which owned units are fielded.
3. **Right-click / hover info panel** shows a unit's name, stars and items as text and icons when the player inspects it. Read it opportunistically.
4. **Vision classifier last.** Train a small CNN on bench-slot crops (fixed position, consistent scale) for identity and star level; use it to confirm bookkeeping. Add the board detector (YOLO-class model, hex grid homography) later.

Training data for (4) can be collected automatically: bookkeeping gives labels for bench crops in the player's own games.

Star level: read from the star pips above the health bar or the unit's size/glow; bookkeeping (three copies combine) also predicts it.

## Unlock progress: the key unknown

Combat-stat unlocks (casts, kills, damage, Captivated seconds, cheers, inspires) can only be tracked by reading the game's own progress display. First PBE task: find where each unlock's progress is shown (a dedicated panel, the team planner, trait tooltips, hover on the locked unit), whether it is numeric, and whether it is visible without input. If it requires opening a panel, the tool reads it whenever the player opens it and otherwise extrapolates from the last known value and rate, flagged as an estimate.

## Per-set assets

Each new set needs:

- Roster name list for OCR fuzzy matching (from static data, automatic).
- Item and trait icon templates (from CommunityDragon assets, automatic).
- Unit classifier retrain (semi-automatic via bookkeeping labels; needs ~10–20 recorded games).
- Layout file check if the HUD moved.
- Templates for set-specific shop offerings and counters (manual).

## Game-state schema

One JSON object per decision point, appended to a per-game log. This log is the interface between capture and engine, and the format review mode replays.

```json
{
  "patch": "19.1",
  "t": "3-2",
  "phase": "planning",
  "player": {
    "level": 6, "xp": [10, 36], "gold": 34, "hp": 71,
    "streak": {"type": "win", "n": 2}
  },
  "shop": [
    {"slot": 1, "unit": "Xayah", "cost": 4},
    {"slot": 2, "unit": null, "sold": true}
  ],
  "special_shop": [],
  "board": [
    {"unit": "Olaf", "stars": 2, "hex": [0, 3], "items": ["Bloodthirster"], "conf": 0.97}
  ],
  "bench": [{"unit": "Karthus", "stars": 1, "items": [], "conf": 0.99}],
  "item_bench": ["BFSword", "ChainVest"],
  "traits": [{"name": "Pentakill", "count": 3, "tier": 1}],
  "augments": {"owned": ["..."], "offered": null},
  "unlocks": [
    {"unit": "Vayne", "state": "IN_PROGRESS", "progress": 2, "target": 5, "source": "ui"},
    {"unit": "Seraphine", "state": "DEAD"}
  ],
  "counters": {"rerolls_total": 4, "rerolls_before_2_carousel": 1, "hype": 0, "bling": 0},
  "lobby": [{"name": "p2", "hp": 64, "level": 6}],
  "history": {"results": ["W", "W", "L"], "hp_lost": [0, 0, 7]},
  "quality": {"unread": ["unlock:Wukong"], "low_conf": []}
}
```

Rules:

- Every vision-derived value has a confidence; the engine ignores or widens anything below threshold.
- `quality.unread` lists what could not be read this tick, so the UI can say so.
- The log also stores the raw frame hash (and optionally the frame) for debugging and for building training sets.

## Alternative source

Overwolf's game-events feed already exposes gold, XP, HP, shop slots, board and bench with stars and items, item bench, carousel, round info and roster. It would replace most of this document for a desktop app, but: publishing requires Riot approval that this feature set would not get, it is unverified against the standalone client, and it is not known to expose unlock progress. Keep the schema above source-agnostic so an Overwolf adapter could feed it for prototyping the engine before the vision work is done.

## Milestones for capture

1. HUD + stage + shop + augment cards + lobby HP (text and digits only).
2. Bookkeeping inventory + trait-panel checksum + item bench.
3. Unlock progress reader (after PBE inspection).
4. Bench classifier; items on units.
5. Board detector with hex positions (needed for POSITIONAL unlocks and, later, positioning).
