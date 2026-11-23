# Add consumables (anvils, duplicators, dummies, removers, reforgers, tomes) to the item icon set, so the item
# bench reader can tell them from real items instead of forcing them onto the nearest one. Public
# CommunityDragon art, saved under data/raw/cdragon/items/ (gitignored) with kind "consumable".
#   python3 -I tools/fetch_consumable_icons.py
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data/raw/cdragon/items"
BASE = "https://raw.communitydragon.org/pbe/game/"
# apiName in tft_pbe.json -> class name (two arts can share a class)
WANT = {"TFT17_MarketOffering_ComponentAnvil": "Component Anvil", "TFT_Item_GrantCompletedAnvil": "Completed Item Anvil",
        "TFT_Item_GrantOrnnAnvil": "Artifact Anvil", "TFT_Item_GrantTomeOfTraits": "Tome of Traits",
        "TFT_Assist_ChampionDuplicator": "Champion Duplicator",
        "TFT17_MarketOffering_LesserDupe_Varus": "Lesser Champion Duplicator",
        "TFT17_MarketOffering_2TinyDupes": "Tiny Champion Duplicator", "TFT_Assist_TrainingDummy": "Training Dummy",
        "TFT17_MarketOffering_Dummy_Evelynn": "Training Dummy", "DA_Consumable_ItemRemover": "Magnetic Remover",
        "TFT_Assist_Reforger_2": "Reforger"}


def main():
    items = {i["apiName"]: i for i in json.loads((ROOT / "data/raw/cdragon/tft_pbe.json").read_text())["items"]}
    index = json.loads((ITEMS / "index.json").read_text())
    have = {e["file"] for e in index}
    for api, name in WANT.items():
        icon = items[api]["icon"].lower().replace(".tex", ".png")
        file = f"consumable_{Path(icon).stem}.png"
        if file in have:
            continue
        req = urllib.request.Request(BASE + icon, headers={"User-Agent": "tftsolver/0.1"})   # CDragon 403s the default
        (ITEMS / file).write_bytes(urllib.request.urlopen(req, timeout=30).read())
        index.append({"file": file, "api": api, "name": name, "kind": "consumable"})
        have.add(file)
        print(f"{name}: {file}")
    (ITEMS / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
