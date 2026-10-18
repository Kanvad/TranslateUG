"""
TRICH XUAT (buoc 0 + 1 cua pipeline viet hoa game Unity).

- Doc cac TextAsset goc truc tiep tu bundle (theo game profile).
- KIEM CHUNG tai tao nguyen byte (byte-exact) truoc khi lam bat cu thu gi.
- Sinh "don vi dich" (translation units) da unique hoa + da mask placeholder/tag/glossary.

Dau ra (local/ khong day len GitHub):
  local/build/raw/*                 bytes goc (doi chieu)
  local/build/units.jsonl           moi dong 1 chuoi CAN DICH
  local/build/units_index.json      thu tu xuat hien goc -> uid (cho buoc tai nap)
  local/build/extract_report.json   thong ke + hash

Dung:
  .venv/bin/python src/extract_units.py                # profile duy nhat tim thay
  .venv/bin/python src/extract_units.py --game mygame  # chon profile (local/games/mygame.py)
"""
import hashlib
import json
import os
import sys

import UnityPy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg          # noqa: E402
from formats import loads_json, dumps_json, load_csv, dump_csv  # noqa: E402
from paths import BUILD                            # noqa: E402

# Nap profile + ap style/entity/glossary TRUOC khi lay ten regex tu protect.
PROFILE = load_profile(game_arg())
PROFILE.apply()
from protect import Protector, RE_HAS_WORD, glossary_hits  # noqa: E402

os.makedirs(f"{BUILD}/raw", exist_ok=True)

_CACHE = {}


def read_textasset(bundle_path, name):
    env = _CACHE.get(bundle_path)
    if env is None:
        env = _CACHE[bundle_path] = UnityPy.load(bundle_path)
    for o in env.objects:
        if o.type.name == "TextAsset":
            d = o.read()
            if d.m_Name == name:
                s = d.m_Script
                return s if isinstance(s, bytes) else s.encode("utf-8")
    raise KeyError(f"{name} not found in {bundle_path}")


def fmt_opts(p):
    j = p.json_opts
    return dict(indent=j["indent"], newline=j["newline"], escape=tuple(j["escape"]))


def main():
    p = PROFILE
    jo = fmt_opts(p)
    print(f"GAME: {p.name}  ({p.game_dir})")
    assert os.path.isdir(p.bundle_dir), f"Khong thay thu muc bundle: {p.bundle_dir}"

    # --- BUOC 1: doc raw ---
    print("\nBUOC 1 — Doc TextAsset goc")
    raw = {}
    for a in p.assets:
        r = read_textasset(p.bundle_path(a.bundle), a.textasset)
        raw[a.textasset] = r
        open(f"{BUILD}/raw/{a.raw_name}", "wb").write(r)
        print(f"   {a.raw_name:38s} {len(r):>9,} bytes  "
              f"sha256={hashlib.sha256(r).hexdigest()[:16]}")

    # --- BUOC 2: kiem chung byte-exact ---
    print("\nBUOC 2 — Kiem chung byte-exact (bat buoc truoc khi sua bat cu thu gi)")
    parsed, byte_exact, sha = {}, {}, {}
    for a in p.assets:
        r = raw[a.textasset]
        if a.fmt == "json":
            obj = loads_json(r)
            ok = dumps_json(obj, **jo) == r
            n = len(obj)
            parsed[a.textasset] = obj
        else:
            rows = load_csv(r)
            ok = dump_csv(rows, header=p.csv_header, newline=jo["newline"]) == r
            n = len(rows)
            parsed[a.textasset] = rows
        byte_exact[a.textasset] = ok
        sha[a.textasset] = hashlib.sha256(r).hexdigest()
        print(f"   {a.textasset:34s} {'OK' if ok else 'FAIL':4s}  {n:>7,} muc")
    if not all(byte_exact.values()):
        sys.exit("DUNG: serializer khong tai tao duoc nguyen byte.")

    # --- BUOC 3: sinh don vi dich ---
    print("\nBUOC 3 — Sinh don vi dich (unique hoa + mask)")
    units, unit_list = {}, []

    def add(kind, en):
        key = (kind, en)
        if key in units:
            uid = units[key]
            unit_list[uid]["n_occ"] += 1
            return uid
        prot = Protector(style="brace", dialogue=(kind == "dialogue")).protect(en)
        uid = len(unit_list)
        units[key] = uid
        unit_list.append(dict(uid=uid, kind=kind, en=en, prefix=prot.prefix,
                              masked=prot.masked,
                              maps=[[k, v] for k, v in prot.mapping.items()],
                              skip=not RE_HAS_WORD.search(prot.masked), n_occ=1))
        return uid

    sources, total_occ = [], 0
    for a in p.assets:
        if not a.translated:
            continue
        kind = "dialogue" if a.dialogue else "ui"
        entries = []
        for item in parsed[a.textasset]:
            entries.append({"id": item[a.id_field],
                            "uid": add(kind, item[a.text_field])})
        total_occ += len(entries)
        sources.append(dict(textasset=a.textasset, bundle=a.bundle, fmt=a.fmt,
                            id_field=a.id_field, text_field=a.text_field,
                            raw=a.raw_name, dialogue=a.dialogue, entries=entries))
        print(f"   {a.textasset:34s} {len(entries):>7,} muc  (kind={kind})")

    with open(f"{BUILD}/units.jsonl", "w", encoding="utf-8") as f:
        for u in unit_list:
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
    json.dump({"game": p.name, "sources": sources},
              open(f"{BUILD}/units_index.json", "w", encoding="utf-8"),
              ensure_ascii=False)

    # --- BUOC 4: bao cao ---
    todo = [u for u in unit_list if not u["skip"]]
    report = dict(
        game=p.name,
        sources=[dict(textasset=s["textasset"], entries=len(s["entries"]),
                      translated=True) for s in sources]
        + [dict(textasset=a.textasset, entries=0, translated=False)
           for a in p.assets if not a.translated],
        total_occurrences=total_occ,
        units=len(unit_list),
        units_dialogue=sum(u["kind"] == "dialogue" for u in unit_list),
        units_skip_no_text=len(unit_list) - len(todo),
        units_to_translate=len(todo),
        units_with_prefix=sum(bool(u["prefix"]) for u in unit_list),
        units_with_glossary_name=sum(bool(glossary_hits(u["en"])) for u in unit_list),
        total_sentinels=sum(len(u["maps"]) for u in unit_list),
        chars_to_translate=sum(len(u["masked"]) for u in todo),
        byte_exact=byte_exact,
        sha256=sha,
    )
    json.dump(report, open(f"{BUILD}/extract_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"   Tong lan xuat hien   : {report['total_occurrences']:>8,}")
    print(f"   DON VI DUY NHAT      : {report['units']:>8,}")
    print(f"   Bo qua (khong chu)   : {report['units_skip_no_text']:>8,}")
    print(f"   CAN DICH             : {report['units_to_translate']:>8,}")
    print(f"   Co tien to nguoi noi : {report['units_with_prefix']:>8,}")
    print(f"   Co ten glossary      : {report['units_with_glossary_name']:>8,}")
    print(f"   Tong sentinel        : {report['total_sentinels']:>8,}")
    print(f"   Ky tu can dich       : {report['chars_to_translate']:>8,}")
    print("\nBUOC 4 — Xong. Dau ra: local/build/units.jsonl, local/build/units_index.json, "
          "local/build/extract_report.json, local/build/raw/")


if __name__ == "__main__":
    main()
