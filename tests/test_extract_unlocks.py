# Set 16 regression for the unlock extractor. Needs data/raw/pbe (run tools/extract_unlocks.py once).
#   python3 -I tests/test_extract_unlocks.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "data/raw/pbe/map22.bin.json").exists():           # CommunityDragon game files, fetched locally
    print("skip: needs CommunityDragon files (python3 -I tools/extract_unlocks.py --refresh)")
    sys.exit()
sys.path.insert(0, str(ROOT / "tools"))
from extract_unlocks import extract, load  # noqa: E402

u = {x["api"]: x for x in extract(*load(ROOT / "data/raw/pbe"), "TFTSet16")}
assert len(u) == 40, len(u)

bard = u["TFT16_Bard"]["conditions"][0]
assert (bard["required"], bard["milestones"], bard["text"]) == \
    (3, [2, 3], "Reroll 3 times before Stage 2 Carousel")
assert u["TFT16_Bard"]["min_level"] is None and u["TFT16_BaronNashor"]["min_level"] == 10
assert u["TFT16_Renekton"]["conditions"][0]["escalates"]
assert u["TFT16_Veigar"]["conditions"][0]["item"] == "TFT_Item_RabadonsDeathcap"
assert u["TFT16_Galio"]["conditions"][0]["traits"] == ["TFT16_Demacia"]
assert all(c["required"] is not None and c["text"] and "@" not in c["text"]
           for x in u.values() for c in x["conditions"])
print("ok")
