# Fork notes (Ktsierra)

This fork tracks [MonChiSub/WoWForever_TSM](https://github.com/MonChiSub/WoWForever_TSM) and adds a few fixes on top.

**Import from `Patched/`, not `Export/`.** `Export/` stays exactly as upstream ships it.

## What's changed

| File | Change |
|---|---|
| `patterns.txt` | Sell Pattern & Plans min price 30% → 70% |
| `xmogCrafted.txt` | Had no operations; now uses Sell Xmog & Gear |
| `xmogLooted_a-j`, `xmogLooted_k-z`, `xmogStarterShirts`, `xmogVendor`, `xmogCrafted` | Sell Xmog & Gear min price 30% → 70% |
| `miscellaneous.txt` | Sell Misc 45% → 60%, Sell Quest Item 35% → 60% |
| `consumables.txt` | Sell Consumables 50% → 60% |
| `materials.txt` | Unchanged |
| `z - lockboxes.txt` | Unchanged on purpose: no operations, so TSM never posts them (rogue opens them) |

All min prices are `X% min(DBMarket, DBRegionMarketAvg)`. Below the min, these operations post at normal price instead of chasing the undercut.

## Importing

1. `/tsm` → Settings → Profiles: make a fresh profile. If you already imported the upstream strings, use a new profile so the old operations don't stick around.
2. For each file in `Patched/`, use **Copy raw file**, then `/tsm` → My Groups → **Import Group**, paste, confirm. `/reload` after the two big `xmogLooted` files.

## Staying in sync

`Export/` is never edited, so syncing with upstream never conflicts. The `Sync upstream and rebuild` GitHub Action:

- runs daily, syncs `main` with upstream, and rebuilds `Patched/` if anything changed
- also runs when you push changes to `Export/` or `tools/`, or when you start it by hand from the Actions tab

Forks start with Actions disabled. Enable them once from the repo's **Actions** tab.

After an upstream update, re-import only the files that changed in `Patched/`.

## Changing a setting

Edit `tools/tweaks.json` (for example, a different `minPrice`) and push. The Action rebuilds `Patched/`. To run it locally instead:

```sh
python tools/patch.py          # rebuild Patched/
python tools/patch.py --check  # exit 1 if Patched/ is out of date
```

If upstream renames an operation listed in `tweaks.json`, the script stops with an error instead of silently skipping it.

`tools/tsmcodec.py` reads and writes TSM export strings (LibDeflate print encoding, raw DEFLATE, LibSerialize) in plain Python.
