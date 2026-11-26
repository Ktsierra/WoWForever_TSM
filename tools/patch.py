"""Build Patched/ from the upstream strings in Export/ plus tools/tweaks.json.

    python tools/patch.py          rebuild Patched/
    python tools/patch.py --check  exit 1 if Patched/ is out of date

Upstream files are never edited, so syncing the fork with upstream never
conflicts. Files with no tweaks are copied to Patched/ unchanged.
"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tsmcodec as tc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "Export"
PATCHED = ROOT / "Patched"
TWEAKS = ROOT / "tools" / "tweaks.json"

MODULES = [b"Auctioning", b"Crafting", b"Shopping", b"Sniper", b"Vendoring", b"Warehousing"]

# Positions of the values inside a TSM_EXPORT string.
I_MAGIC, I_VERSION, I_NAME, I_ITEMS, I_GROUPS, I_GROUP_OPS, I_OPS, I_CUSTOM = range(8)


def b(s):
    return s.encode("utf-8")


def u(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def strip_notes(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_exports():
    out = {}
    for path in sorted(EXPORT.glob("*.txt")):
        text = path.read_text()
        values, _ = tc.decode_export(text)
        if values[I_MAGIC] != b"TSM_EXPORT":
            raise SystemExit(f"{path.name}: not a TSM export string")
        out[path.name] = (text, values)
    return out


def find_operation(exports, module, name):
    for fname, (_, values) in exports.items():
        op = values[I_OPS].get(module, {}).get(name)
        if op is not None:
            return copy.deepcopy(op), fname
    return None, None


def assign(values, exports, fname, wanted, log):
    ops = values[I_OPS]
    for module in MODULES:
        ops.setdefault(module, tc.LuaTable())
    group_ops = values[I_GROUP_OPS]
    for mod_name, op_name in strip_notes(wanted).items():
        module, op = b(mod_name), b(op_name)
        if op not in ops[module]:
            settings, src = find_operation(exports, module, op)
            if settings is None:
                raise SystemExit(f"{fname}: operation {mod_name} / {op_name} not found in any Export file")
            ops[module][op] = settings
            log.append(f"added operation {mod_name} / {op_name} (copied from {src})")
        for path in values[I_GROUPS]:
            entry = group_ops.setdefault(path, tc.LuaTable())
            for m in MODULES:
                entry.setdefault(m, tc.LuaTable())
                if path == b"":
                    entry[m][b"override"] = True
            entry[module][1] = op
        log.append(f"assigned {mod_name} / {op_name} to {len(values[I_GROUPS])} group(s)")


def override_operations(values, overrides, log):
    for mod_name, by_name in strip_notes(overrides).items():
        module_ops = values[I_OPS].get(b(mod_name), {})
        for op_name, fields in strip_notes(by_name).items():
            settings = module_ops.get(b(op_name))
            if settings is None:
                continue
            for key, new in strip_notes(fields).items():
                new_v = b(new) if isinstance(new, str) else new
                old = settings.get(b(key))
                if old != new_v:
                    settings[b(key)] = new_v
                    log.append(f"{mod_name} / {op_name}: {key} {u(old)!r} -> {u(new_v)!r}")


def main():
    check = "--check" in sys.argv
    tweaks = json.loads(TWEAKS.read_text())
    exports = load_exports()

    # Every overridden operation must exist somewhere, so an upstream rename fails loudly.
    for mod_name, by_name in strip_notes(tweaks.get("operations", {})).items():
        for op_name in strip_notes(by_name):
            if find_operation(exports, b(mod_name), b(op_name))[0] is None:
                raise SystemExit(f"tweaks.json: operation {mod_name} / {op_name} not found in any Export file")
    for fname in strip_notes(tweaks.get("assign", {})):
        if fname not in exports:
            raise SystemExit(f"tweaks.json: assign target {fname} not found in Export/")

    PATCHED.mkdir(exist_ok=True)
    stale = []
    for fname, (text, original) in exports.items():
        values = copy.deepcopy(original)
        log = []
        wanted = strip_notes(tweaks.get("assign", {})).get(fname)
        if wanted:
            assign(values, exports, fname, wanted, log)
        override_operations(values, tweaks.get("operations", {}), log)

        if values == original:
            new_text = text
        else:
            new_text = tc.encode_export(values)
            decoded, _ = tc.decode_export(new_text)
            if decoded != values:
                raise SystemExit(f"{fname}: round-trip check failed")

        target = PATCHED / fname
        if target.exists():
            existing = target.read_text()
            # Keep the existing file if it already holds the same data (avoids churn
            # from different zlib builds producing different bytes).
            if existing == new_text or tc.decode_export(existing)[0] == tc.decode_export(new_text)[0]:
                print(f"{fname}: up to date" + (f" ({len(log)} change(s))" if log else ""))
                continue
        stale.append(fname)
        if not check:
            target.write_text(new_text)
        print(f"{fname}: {'STALE' if check else 'written'}")
        for line in log:
            print(f"    {line}")

    for extra in sorted(set(p.name for p in PATCHED.glob("*.txt")) - set(exports)):
        stale.append(extra)
        print(f"{extra}: no longer upstream" + ("" if check else ", removed"))
        if not check:
            (PATCHED / extra).unlink()

    if check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
