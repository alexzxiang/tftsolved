"""Where every number on the line finder's path comes from. tools/audit_weights.py checks that each module-level
constant in the audited modules is listed here, and tests/test_audit_weights.py fails if a constant that moves a comp's
expected place isn't measured or derived from a measurement.

kind:
  measured   fitted by a script on data (the script and data are named)
  derived    computed from measured values by a stated rule
  fact       a game rule, a name mapping or a unit of measure, not a judgement
  structural a modelling choice (a functional form or a definition), not a magnitude
  prior      a judgement; allowed only where it doesn't move the expected place (display, sorting, fallbacks)
moves_place: True if the number changes a comp's expected place in the line finder.
"""

P = {
    # engine/linefinder.py
    "linefinder.ROOT": ("fact", False, "project path"),
    "linefinder.BIS_PER_UNIT": ("structural", True, "best-in-slot definition = a unit's 3 most common items, the same definition tools/calibrate.py items measured the premium with"),
    "linefinder.COMPONENT_SHARE": ("fact", True, "a component is half a completed item (recipes take two): an unpaired component = half the measured premium (BIS) or cost (off-type)"),
    "linefinder.ODDS_FLOOR": ("prior", False, "fallback before tools/eval_lines.py fit (fitted floor in odds_calibration.json); odds, realistic set and sorting only"),
    "linefinder.ODDS_OPENER": ("prior", False, "fallback before tools/eval_lines.py fit (fitted opener likelihood); odds, realistic set and sorting only"),
    "linefinder.ROUNDS": ("structural", False, "rounds offered for 'vs lobby at a round'; display only (tempo keeps the size comparison)"),
    "linefinder.SUGGESTIONS_MIN": ("prior", False, "fewest suggested lines with units held; display only"),
    "linefinder.INVESTED_COST": ("prior", False, "a 2-star this dear (5- and 7-costs) anchors the comps that carry it, like a 3-star or a unit holding two items; realistic set only, moves no place"),
    "linefinder.VARIANT_OVERLAP": ("prior", False, "comps sharing this share of units show as one family on the suggestion strip; display only"),
    "linefinder.OFF": ("fact", False, "the other damage type"),
    "linefinder.SUGGESTIONS": ("prior", False, "number of suggested lines shown; display only"),
    "linefinder.TIERS_PRIOR": ("prior", False, "fallback cut points, used only before tools/calibrate.py tiers has run"),
    "linefinder.ARTIFACT_BASE": ("derived", False, "mean MetaTFT artifact-holder change, computed at run time; used to pick the best holder shown"),
    "linefinder.COMPONENT_KIND": ("fact", False, "component -> AD / AP / tank, from the game's item stats"),
    "linefinder.COUNTERS": ("fact", False, "unlock counter names -> words"),
    "linefinder.LP": ("prior", False, "LP by place at an even MMR (Riot's real gains vary with MMR); expected-LP display and sort only"),
    # engine/augvalue.py (the measured path is augment_kaggle.json; anchors are a fallback before it exists)
    "augvalue.ROOT": ("fact", False, "project path"),
    "augvalue.TIER": ("prior", False, "fallback anchors only (measured tier effects replace them: tools/kaggle_augments.py)"),
    "augvalue.ANCHOR": ("prior", False, "fallback anchors only (measured kind x round x fit effects replace them)"),
    "augvalue.ECON_GOLD": ("prior", False, "fallback anchors only"),
    "augvalue.SCALE_MIN": ("prior", False, "fallback anchors only"),
    "augvalue.SCALE_MAX": ("prior", False, "fallback anchors only"),
    "augvalue.SHRINK": ("measured", False, "tools/calibrate.py needs: per-comp needs don't match controlled estimates (Spearman ~0) -> halfway to the archetype; fallback path"),
    "augvalue.HP_GOLD": ("prior", False, "gold per HP in the stage-2/3 Monte Carlo; shown as 'worth about +X gold' only"),
    "augvalue.ARCH_COMBAT": ("prior", False, "fallback anchors only"),
    "augvalue.GROUP": ("fact", False, "augment kind -> measured kind group"),
    "augvalue.EXPERT_PLACES": ("derived", False, "letter -> places from the measured spread of archived augment outcomes"),
    "augvalue.EXPERT_WEIGHT": ("measured", True, "0: tools/expert_letter_check.js found no signal (S +0.06, A +0.05, B +0.01, C -0.04, Set 12)"),
    "augvalue.MEASURED_KIND": ("fact", False, "catalog category -> measured kind"),
    "augvalue.ROUNDS": ("fact", False, "augment rounds"),
    # engine/power.py
    "power.ROOT": ("fact", False, "project path"),
    "power.MIN_BOARDS": ("prior", False, "Set 18 features with fewer boards stay out of the transfer slope fit (noise floor)"),
    "power.SHARE_K": ("prior", False, "shrinkage of MetaTFT star shares in the transfer; the fine-tune (measured) sits on top"),
    "power.GAMES_K": ("prior", False, "shrinkage of MetaTFT trait tiers in the transfer; the fine-tune (measured) sits on top"),
    "power.STAR": ("fact", True, "game rule: each star multiplies a unit's HP and attack damage by 1.8; fight power (HP x damage) by 3.24"),
    "power.PARTS": ("fact", False, "names of the fight score's parts (units, items, traits)"),
    # engine/survival.py (the HP chain behind tempo scenarios)
    "survival.ROOT": ("fact", False, "project path"),
    "survival.FIT": ("fact", False, "where the fitted chain parameters are saved"),
    "survival.LAST_STAGE": ("fact", True, "game rule: lobbies end by stage 7; the chain runs its PvP rounds from 2-1 to 7-6"),
    "survival.ANCHOR_ITERS": ("structural", True, "fixed-point passes anchoring each comp's chain to its MetaTFT average (converged: max error 0.023 places)"),
    "survival.GH5": ("fact", True, "5-point Gauss-Hermite nodes and weights for a normal distribution (numerical integration over the game's strength offset)"),
    "power.PAR": ("prior", False, "fallback typical boards; measured par (tools/calibrate.py par) replaces levels 4-10"),
}

# measured inputs that move the expected place, read from files the calibration scripts write
MEASURED_FILES = {
    "data/models/item_calibration.json": "tools/calibrate.py items: Set 18 crawl, 22,784 Master+ boards; premiums over a normal item with 95% bootstrap intervals (BIS on the main carry / a second carry / a tank, off-type item on the carry; artifacts on a usual holder or not; radiants on a BIS holder, a holder of their type, or neither; emblems in a trait the comp runs, activating a splash, or dead)",
    "data/models/augment_kaggle.json": "tools/kaggle_augments.py: 40,344 Master+ games (Sets 7-8); augment kind x round x fit (hero: carry / fielded / off; trait: deep / light / off; econ, reroll: on / off), tier",
    "data/models/survival_TFTSet19.json": "engine/survival.py fit: the game's strength spread sigma by multinomial maximum likelihood on Set 18 knockout stages (placements 2-8), and each comp's curve offset anchoring its HP chain to its MetaTFT average place; drives the tempo (HP) shift",
    "data/models/tempo_calibration.json": "tools/calibrate.py tempo: MetaTFT comps' opener round win rates vs avg place, and how those round win rates follow the board score's gap (172 openers; flat, so early strength moves no place)",
    "data/models/tier_calibration.json": "tools/calibrate.py tiers: MetaTFT's own tier letters",
    "data/manual/TFTSet19.lolchess_comps.json": "tools/import_lolchess.py: lolchess variants (within-comp offsets) and new comps (median site offset) on MetaTFT's scale",
    "data/models/odds_calibration.json": "tools/eval_lines.py fit: naive-Bayes floor, opener likelihood, alpha, cost weight, the 90% conformal cut-off (realistic lines) and the 99% one (stretch lines padding a short list), on 8,000 boards sampled from MetaTFT comps (decides realistic lines; moves no place)",
    "data/board_model_TFTSet19.json": "engine/power.py build: Set 18 Plackett-Luce + transfer (incl. per-unit best-in-slot weights, Set 18 r = -0.48) + fine-tune on MetaTFT boards (place offsets at the Plackett-Luce rate, 1.75 places per score unit) + measured par + temperature; "
                                      "fight: gamma (damage x cost^gamma), k, unit / item / trait weights and the off-type item term by maximum likelihood on 2,807 Set 18 final fights (1st vs 2nd), typical board per size from MetaTFT boards",
}
