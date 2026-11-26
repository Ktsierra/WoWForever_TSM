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

# Operation types TSM allows in group import/export (Mailing is excluded by TSM itself).
MODULES = [b"Auctioning", b"Crafting", b"Shopping", b"Sniper", b"Vendoring", b"Warehousing"]

# Positions of the values inside a TSM_EXPORT string.
I_MAGIC, I_VERSION, I_NAME, I_ITEMS, I_GROUPS, I_GROUP_OPS, I_OPS, I_CUSTOM = range(8)


def b(s):
    return s.encode("utf-8")


def u(v):
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def strip_notes(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def to_lua(v):
    """JSON value -> the shape tsmcodec decodes to (bytes strings, LuaTable tables)."""
    if isinstance(v, dict):
        t = tc.LuaTable()
        for k, x in strip_notes(v).items():
            t[b(k)] = to_lua(x)
        return t
    if isinstance(v, str):
        return b(v)
    return v


def load_exports():
    out = {}
    for path in sorted(EXPORT.glob("*.txt")):
        text = path.read_text()
        values, _ = tc.decode_export(text)
        if values[I_MAGIC] != b"TSM_EXPORT":
            raise SystemExit(f"{path.name}: not a TSM export string")
        out[path.name] = (text, values)
    return out


def find_operation(exports, new_ops, module, name):
    """Return (settings, source) for an operation from tweaks or any Export file."""
    defined = strip_notes(new_ops.get(u(module), {})).get(u(name))
    if defined is not None:
        return to_lua(defined), "tweaks.json"
    for fname, (_, values) in exports.items():
        op = values[I_OPS].get(module, {}).get(name)
        if op is not None:
            return copy.deepcopy(op), fname
    return None, None


def wanted_for(fname, tweaks):
    assign = strip_notes(tweaks.get("assign", {}))
    skip = strip_notes(tweaks.get("leave_unassigned", {}))
    wanted = {}
    if fname not in skip:
        wanted.update(strip_notes(assign.get("*", {})))
    wanted.update(strip_notes(assign.get(fname, {})))
    return wanted


def assign(values, exports, new_ops, fname, wanted, log):
    ops = values[I_OPS]
    for module in MODULES:
        ops.setdefault(module, tc.LuaTable())
    group_ops = values[I_GROUP_OPS]
    # Every group needs an entry for every module, and the top-level group must set override.
    for path in values[I_GROUPS]:
        entry = group_ops.setdefault(path, tc.LuaTable())
        for m in MODULES:
            entry.setdefault(m, tc.LuaTable())
            if path == b"":
                entry[m][b"override"] = True

    for mod_name, op_name in wanted.items():
        module, op = b(mod_name), b(op_name)
        if module not in MODULES:
            raise SystemExit(f"{fname}: {mod_name} operations can't be imported by TSM")
        if op not in ops[module]:
            settings, src = find_operation(exports, new_ops, module, op)
            if settings is None:
                raise SystemExit(f"{fname}: operation {mod_name} / {op_name} not found")
            ops[module][op] = settings
            log.append(f"added operation {mod_name} / {op_name} (from {src})")
        previous = group_ops[b""][module].get(1)
        if previous not in (None, op):
            log.append(f"replaced {mod_name} / {u(previous)} with {op_name} on the top-level group")
        count = 0
        for path in values[I_GROUPS]:
            entry = group_ops[path][module]
            if path != b"" and entry.get(b"override"):
                continue  # upstream deliberately set this subgroup's own rules
            for k in [k for k in entry if isinstance(k, int)]:
                del entry[k]
            entry[1] = op
            count += 1
        log.append(f"assigned {mod_name} / {op_name} to {count} of {len(values[I_GROUPS])} group(s)")

    # Drop operations that no group references any more.
    for module in MODULES:
        used = {name for e in group_ops.values() if module in e
                for k, name in e[module].items() if isinstance(k, int)}
        for name in [n for n in ops[module] if n not in used]:
            del ops[module][name]
            log.append(f"removed unused operation {u(module)} / {u(name)}")


def override_operations(values, overrides, log):
    for mod_name, by_name in strip_notes(overrides).items():
        module_ops = values[I_OPS].get(b(mod_name), {})
        for op_name, fields in strip_notes(by_name).items():
            settings = module_ops.get(b(op_name))
            if settings is None:
                continue
            for key, new in strip_notes(fields).items():
                new_v = to_lua(new)
                old = settings.get(b(key))
                if old != new_v:
                    settings[b(key)] = new_v
                    log.append(f"{mod_name} / {op_name}: {key} {u(old)!r} -> {u(new_v)!r}")


def main():
    check = "--check" in sys.argv
    tweaks = json.loads(TWEAKS.read_text())
    new_ops = strip_notes(tweaks.get("new_operations", {}))
    exports = load_exports()

    # Fail loudly on anything that no longer lines up with upstream.
    for mod_name, by_name in strip_notes(tweaks.get("operations", {})).items():
        for op_name in strip_notes(by_name):
            if find_operation(exports, {}, b(mod_name), b(op_name))[0] is None:
                raise SystemExit(f"tweaks.json: operation {mod_name} / {op_name} not found in any Export file")
    for fname in strip_notes(tweaks.get("assign", {})):
        if fname != "*" and fname not in exports:
            raise SystemExit(f"tweaks.json: assign target {fname} not found in Export/")

    PATCHED.mkdir(exist_ok=True)
    stale = []
    for fname, (text, original) in exports.items():
        values = copy.deepcopy(original)
        log = []
        wanted = wanted_for(fname, tweaks)
        if wanted:
            assign(values, exports, new_ops, fname, wanted, log)
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
                print(f"{fname}: up to date")
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
