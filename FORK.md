# Fork notes (Ktsierra)

This fork tracks [MonChiSub/WoWForever_TSM](https://github.com/MonChiSub/WoWForever_TSM) and adds a few fixes on top.

**Import from `Patched/`, not `Export/`.** `Export/` stays exactly as upstream ships it.

## What's changed

### Selling floors (Auctioning)

| Operation | Upstream min price | Here |
|---|---|---|
| Sell Pattern & Plans | 30% | 70% |
| Sell Xmog & Gear | 30% | 70% |
| Sell Misc | 45% | 60% |
| Sell Quest Item | 35% | 60% |
| Sell Consumables | 50% | 60% |
| Sell Materials | 60% | unchanged |

Percentages are of `min(DBMarket, DBRegionMarketAvg)`. Below the min, these operations post at normal price instead of chasing the undercut. `xmogCrafted` shipped with no operations and now uses Sell Xmog & Gear.

### Operations upstream doesn't ship

| Operation | Type | What it does | On |
|---|---|---|---|
| Snipe Deals | Sniper | Flags listings under 60% of `min(DBMarket, DBRegionMarketAvg)`, or under vendor price | All groups except lockboxes |
| Buy Below Market | Shopping | Group searches only show listings at or under 80% of that market value | All groups except lockboxes |
| Move All | Warehousing | Bank ↔ bags moves whole stacks, keeps nothing behind | All groups except lockboxes |
| Craft Supplies | Crafting | Keep 20, queue in batches of 5+, profit ≥ max(1g, 15% of cost) | Materials, Consumables, Miscellaneous |
| Craft Gear | Crafting | Keep 2, queue when short, profit ≥ max(5g, 20% of cost) | Xmog & Gear Crafted |
| Vendor Junk | Vendoring | Sells to a merchant only when AH value < 125% of vendor price. Never sells items with no price data or soulbound items | All Xmog & Gear groups |

Crafting restock only queues recipes you know, so it covers Engineering now and Leatherworking later (Xmog Crafted has a Leatherworking subgroup, Consumables has armor kits). Subgroups that upstream deliberately overrides (Consumables "Lure" for Auctioning, Miscellaneous "Toy`1) Profession" for Crafting) are left alone.

`z - lockboxes.txt` has no operations at all, so TSM never posts, snipes, vendors or moves lockboxes.

### Mailing (set up in game)

TSM blocks Mailing operations from group import/export, so this one can't ship in the strings. On your main:

1. `/tsm` → Operations → Mailing → create an operation named `To Bank Alt`.
2. Set **Target** to the bank alt's name. Leave Keep Quantity at 0.
3. Under the operation's groups, add every top-level group **except** `Materials` (keeps your crafting mats on the main) and `ZZ - Lockbox`.
4. At a mailbox, TSM's mail window → Groups → select them → send.

## Importing

1. `/tsm` → Settings → Profiles: make a fresh profile. (Or delete the existing top-level groups first. Importing over a group that already exists makes a copy like `Materials 1`.)
2. For each file in `Patched/`, use **Copy raw file**, then `/tsm` → My Groups → **Import Group**, paste, confirm. Leave **Include operations** and **Replace existing operations** checked (the defaults). `/reload` after the two big `xmogLooted` files.

After an upstream update, delete just the changed group in TSM and re-import that file.

## Staying in sync

`Export/` is never edited, so syncing with upstream never conflicts. The `Sync upstream and rebuild` GitHub Action:

- runs daily, syncs `main` with upstream, and rebuilds `Patched/` if anything changed
- also runs when you push changes to `Export/` or `tools/`, or when you start it by hand from the Actions tab

Forks start with Actions disabled. Enable them once from the repo's **Actions** tab.

## Changing a setting

Edit `tools/tweaks.json` and push. The Action rebuilds `Patched/`. To run it locally instead:

```sh
python tools/patch.py          # rebuild Patched/
python tools/patch.py --check  # exit 1 if Patched/ is out of date
```

`tweaks.json` sections:

- `operations`: change fields on upstream operations
- `new_operations`: full definitions for operations upstream doesn't ship
- `assign`: which operation each file's top-level group gets (`"*"` = every file not in `leave_unassigned`)
- `leave_unassigned`: files that get no operations at all

If upstream renames an operation listed in `tweaks.json`, the script stops with an error instead of silently skipping it.

`tools/tsmcodec.py` reads and writes TSM export strings (LibDeflate print encoding, raw DEFLATE, LibSerialize) in plain Python.
