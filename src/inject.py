"""
TAI NAP (buoc cuoi): rap ban dich -> repack bundle -> va catalog.json -> fix font.

Su dung:
  .venv/bin/python src/inject.py --identity          # test toan bo duong ong bang EN
  .venv/bin/python src/inject.py                     # dung ban dich trong local/build/
  .venv/bin/python src/inject.py --game mygame       # game khac (src/games/mygame.py)

Dau ra (staging trong local/, KHONG dung vao game va KHONG day len GitHub):
  local/build/mod/<bundle dir>/<cac bundle da sua>
  local/build/mod/catalog.json
  local/build/mod/apply.sh
"""
import argparse, hashlib, json, os, re, struct, sys
import UnityPy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg                       # noqa: E402
from formats import loads_json, dumps_json, load_csv, dump_csv  # noqa: E402
from paths import BUILD                                        # noqa: E402

# Nap profile + ap style/entity/glossary TRUOC khi lay ten regex tu protect.
PROFILE = load_profile(game_arg())
PROFILE.apply()
from protect import (qa, glossary_hits, RE_SPRITE, RE_BRACE,   # noqa: E402
                     RE_ANGLE, RE_OPTION, RE_STYLE)

JO = dict(indent=PROFILE.json_opts["indent"], newline=PROFILE.json_opts["newline"],
          escape=tuple(PROFILE.json_opts["escape"]))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def bundle_assets(path):
    """Tra ve dict ten -> (obj, bytes) cho moi TextAsset."""
    env = UnityPy.load(path)
    out = {}
    for o in env.objects:
        if o.type.name == "TextAsset":
            d = o.read()
            s = d.m_Script
            out[d.m_Name] = (o, s.encode("utf-8") if isinstance(s, str) else s)
    return env, out


def bundle_key(name):
    """Ten entry trong catalog dung m_Hash = token cuoi cua ten bundle."""
    return name.rsplit("_", 1)[-1].replace(".bundle", "")


def compression_type(path):
    b = open(path, "rb").read(64)
    off = 8 + 4
    off = b.index(b"\0", off) + 1
    off = b.index(b"\0", off) + 1
    off += 8
    off += 4 + 4
    flags, = struct.unpack(">I", b[off:off + 4])
    return flags & 0x3F, flags


def repack(bundle_path, replacements, out_path):
    """Thay m_Script cua cac TextAsset roi ghi bundle moi."""
    env = UnityPy.load(bundle_path)
    applied = set()
    for o in env.objects:
        if o.type.name != "TextAsset":
            continue
        d = o.read()
        if d.m_Name in replacements:
            new = replacements[d.m_Name]
            d.m_Script = new.decode("utf-8") if isinstance(new, bytes) else new
            o.save_typetree(d)
            applied.add(d.m_Name)
    missing = set(replacements) - applied
    if missing:
        raise KeyError(f"khong tim thay TextAsset: {missing}")
    ctype, flags = compression_type(bundle_path)
    packer = {0: "none", 2: "lzma", 3: "lz4"}.get(ctype, "lz4")
    data = env.file.save(packer=packer)
    open(out_path, "wb").write(data)
    return len(data), packer


def patch_catalog(catalog_path, bundle_sizes, out_path):
    """
    Dat m_Crc = 0 va m_UseCrcForCachedBundles = false cho cac bundle da sua,
    cap nhat m_BundleSize. Giu nguyen moi byte khac cua catalog.json.

    m_ExtraDataString = base64 cua blob; blob gom nhieu entry:
        [typename string][uint32 LE do dai][JSON dang UTF-16LE]

    BAY co: m_EntryDataString / m_BucketDataString cua catalog luu OFFSET
    BYTE TUYET DOI vao blob. Neu sua entry lam DOI TONG DO DAI blob thi moi
    entry theo sau bi troi offset -> doc du lieu rac -> game treo loading voi
    "RemoteProviderException : Invalid path in AssetBundleProvider: ''"
    ngay o Wwise Init bank (da xac nhan bang A/B test thuc te).

    => BAT BUOC giu nguyen TONG DO DAI MOI ENTRY: thay doi lam rut ngan
    bao nhieu ky tu thi chen dung bay nhieu space vao JSON (space la
    whitespace hop le, parser bo qua).
    """
    txt = open(catalog_path, encoding="utf-8").read()
    m = re.search(r'"m_ExtraDataString":\s*"([^"]*)"', txt)
    if not m:
        raise KeyError("khong tim thay m_ExtraDataString")
    import base64
    blob = base64.b64decode(m.group(1))

    pat = '{"m_Hash"'.encode("utf-16-le")
    starts = []
    i = blob.find(pat)
    while i != -1:
        starts.append(i)
        i = blob.find(pat, i + 1)

    out = bytearray()
    pos = 0
    patched = []
    for js in starts:
        depth, j = 0, js
        while j < len(blob):
            ch = blob[j:j + 2].decode("utf-16-le", errors="ignore")
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 2
        je = j + 2
        raw = blob[js:je].decode("utf-16-le")
        obj = json.loads(raw)
        if obj["m_Hash"] in bundle_sizes:
            newsize = bundle_sizes[obj["m_Hash"]]
            s = re.sub(r'("m_Crc":)\d+', r'\g<1>0', raw)
            s = s.replace('"m_UseCrcForCachedBundles":true',
                          '"m_UseCrcForCachedBundles":false')
            s = re.sub(r'("m_BundleSize":)\d+', r'\g<1>%d' % newsize, s)
            # GIU NGUYEN DO DAI ENTRY (offset byte tuyet doi tro vao blob!):
            do_dai_cu = (je - js) // 2
            lech = do_dai_cu - len(s)
            if lech > 0:
                need = lech
                soc = s.count(",")
                if need > soc:
                    raise ValueError(
                        "entry %s rut ngan %d ky tu nhung chi co %d dau phay "
                        "de chen space — khong the giu offset!"
                        % (obj["m_Hash"], need, soc))
                s = s.replace(",", ", ", need)
            elif lech < 0:
                raise ValueError(
                    "entry %s dai hon vanilla %d ky tu (m_BundleSize tang qua "
                    "nhieu chu so?) — khong the giu offset!"
                    % (obj["m_Hash"], -lech))
            newj = s.encode("utf-16-le")
            assert len(newj) == je - js, (
                "entry %s: %d != %d byte — offset se sai!"
                % (obj["m_Hash"], len(newj), je - js))
            out += blob[pos:js - 4]
            out += struct.pack("<I", len(newj))
            out += newj
            pos = je
            patched.append(obj["m_Hash"])
        else:
            out += blob[pos:je]
            pos = je
    out += blob[pos:]

    if len(out) != len(blob):
        raise ValueError("TONG DO DAI BLOB LECH: %d -> %d — offset trong "
                         "catalog se sai, game se treo loading!"
                         % (len(blob), len(out)))

    newb64 = base64.b64encode(bytes(out)).decode("ascii")
    newtxt = txt[:m.start(1)] + newb64 + txt[m.end(1):]
    open(out_path, "w", encoding="utf-8").write(newtxt)
    return patched, len(blob), len(out)


def parse_raw(a, raw):
    return loads_json(raw) if a.fmt == "json" else load_csv(raw)


def dump_raw(a, obj):
    if a.fmt == "json":
        return dumps_json(obj, **JO)
    return dump_csv(obj, header=PROFILE.csv_header, newline=JO["newline"])


def main():
    p = PROFILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--identity", action="store_true", help="dung EN lam VI (test duong ong)")
    ap.add_argument("--translations", default=None,
                    help="mac dinh tu tim trong local/build/ (translations.jsonl, translations_hymt2.jsonl, ...)")
    ap.add_argument("--out", default=None, help="mac dinh local/build/mod (that) hoac local/build/mod_identity")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--game", default=game_arg(), help="game profile trong src/games/")
    args = ap.parse_args()
    print(f"GAME: {p.name}  ({p.game_dir})")

    if args.out is None:
        # che do identity KHONG duoc de vao mod/ that de tranh ap nham ban chua dich
        args.out = f"{BUILD}/mod_identity" if args.identity else f"{BUILD}/mod"

    if args.translations is None:
        for cand in ("translations.jsonl", "translations_hymt2.jsonl",
                     "translations_hymt2_fixed.jsonl", "translations_fixed.jsonl"):
            path = f"{BUILD}/{cand}"
            if os.path.exists(path):
                args.translations = path
                break
        if args.translations is None:
            sys.exit("DUNG: khong thay ban dich nao trong local/build/.\n"
                     "  -> Chay notebook Kaggle (local/kaggle_*_llamacpp.ipynb) roi tai ket qua ve\n"
                     "     local/build/translations_hymt2.jsonl")
        print(f"Ban dich: {os.path.relpath(args.translations, os.path.dirname(BUILD))}")

    units = load_jsonl(f"{BUILD}/units.jsonl")
    index = json.load(open(f"{BUILD}/units_index.json", encoding="utf-8"))
    by_uid = {u["uid"]: u for u in units}

    # ---------- 1. nap ban dich ----------
    if args.identity:
        print("CHE DO IDENTITY: dung nguyen tieng Anh lam 'ban dich' (test duong ong)")
        tr = {u["uid"]: u["en"] for u in units}
    else:
        tr = {}
        for r in load_jsonl(args.translations):
            tr[r["uid"]] = r["vi"]
    todo = [u for u in units if not u["skip"]]
    miss = [u["uid"] for u in todo if u["uid"] not in tr or not str(tr[u["uid"]]).strip()]
    print(f"Don vi: {len(units)} | can dich: {len(todo)} | thieu ban dich: {len(miss)}")
    if miss:
        print(f"  !! thieu uid: {miss[:10]} ...")
        sys.exit("DUNG: thieu ban dich.")

    # ---------- 2. QA ----------
    # QA gom 4 lop: token (multiset), ten rieng, tien to nguoi noi, cat cut noi dung.
    # KHONG kiem tra "sentinel sot lai": sentinel co the trung so voi placeholder that.
    ALL_TOK = re.compile("|".join(r.pattern for r in
                                  (RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION, RE_STYLE)))

    def bare(t):
        return ALL_TOK.sub(" ", t)

    EMPTY_TAG = re.compile(
        r"\[(?:" + "|".join(p.style_ids) + r")\]\s*\[/"
        r"|<color=#[0-9A-Fa-f]{6}>\s*</color>")

    bad = []
    untranslated, empty_tag, dbl_space = [], [], []
    for u in todo:
        vi = str(tr[u["uid"]])
        chk = qa(u["en"], vi, dialogue=(u["kind"] == "dialogue"))
        names = [n for n in glossary_hits(u["en"]) if n not in vi]
        pbad = bool(u["prefix"]) and not vi.startswith(u["prefix"])
        be, bv = bare(u["en"]), bare(vi)
        trunc = len(be) > 60 and len(bv) < 0.50 * len(be)
        if args.identity:
            names, pbad, trunc = [], False, False
        etag = bool(EMPTY_TAG.search(vi))
        if not chk["ok"] or names or pbad or trunc or etag:
            bad.append((u["uid"], chk, names, pbad, trunc, etag))
        elif not args.identity:
            if vi.strip() == u["en"].strip():
                untranslated.append(u["uid"])
            if EMPTY_TAG.search(vi):
                empty_tag.append(u["uid"])
            if "  " in vi.replace("\n", " "):
                dbl_space.append(u["uid"])
    print(f"QA cung: {len(todo)-len(bad)}/{len(todo)} dat | loi cung: {len(bad)}")
    print(f"QA mem : chua dich (van tieng Anh)={len(untranslated)} | "
          f"tag rong={len(empty_tag)} | 2 dau cach={len(dbl_space)}")
    json.dump(dict(untranslated=untranslated, empty_tag=empty_tag, double_space=dbl_space),
              open(f"{BUILD}/qa_canh_bao.json", "w"))
    if untranslated[:5]:
        print(f"  vi du chua dich: {[by_uid[i]['en'][:28] for i in untranslated[:5]]}")
    if empty_tag[:5]:
        print(f"  vi du tag rong : {[by_uid[i]['en'][:28] for i in empty_tag[:5]]}")
    if bad:
        from collections import Counter as _C
        c = _C()
        for _, chk, names, pbad, trunc, etag in bad:
            if chk["missing"] or chk["extra"]: c["token"] += 1
            if names: c["ten_rieng"] += 1
            if pbad: c["tien_to"] += 1
            if trunc: c["cat_cut"] += 1
            if etag: c["tag_rong"] += 1
        print(f"  chi tiet: {dict(c)}")
        print(f"  vi du: uid={bad[0][0]} {bad[0][1: ]}")
    if bad and not args.skip_verify:
        sys.exit("DUNG: QA khong dat.\n"
                 "  -> Chay notebook Kaggle (local/kaggle_*_llamacpp.ipynb), tai ket qua ve "
                 "local/build/ roi thu lai.")

    # ---------- 3. rap bang ----------
    def vi_of(uid, original):
        u = by_uid[uid]
        return original if u["skip"] else str(tr[uid])

    new_bytes = {}
    for src in index["sources"]:
        a = p.asset(src["textasset"])
        raw = open(f"{BUILD}/raw/{src['raw']}", "rb").read()
        obj = parse_raw(a, raw)
        assert len(obj) == len(src["entries"]), f"so muc {a.textasset} doi!"
        for item, ix in zip(obj, src["entries"]):
            assert str(item[a.id_field]) == str(ix["id"]), \
                f"{a.id_field} lech thu tu: {item[a.id_field]} vs {ix['id']}"
            item[a.text_field] = vi_of(ix["uid"], item[a.text_field])
        out = dump_raw(a, obj)
        new_bytes[a.textasset] = out
        print(f"{a.textasset:34s} {len(raw):>9,} -> {len(out):>9,} bytes  "
              f"({len(obj)} muc)")

    # font fix: {textasset: {entry_id: {field: url}}}
    font_changed = []
    for textasset, fix in p.font_fix.items():
        a = p.asset(textasset)
        raw = new_bytes.get(textasset) or \
            open(f"{BUILD}/raw/{a.raw_name}", "rb").read()
        obj = loads_json(raw)
        for item in obj:
            for field, newurl in (fix.get(str(item[a.id_field])) or {}).items():
                node = item.get(field)
                if node is None:
                    continue
                old = node.get("url")
                if old != newurl:
                    node["url"] = newurl
                    font_changed.append((a.id_field, item[a.id_field], field, old, newurl))
        new_bytes[textasset] = dumps_json(obj, **JO)
    if font_changed:
        print(f"Font fix: {font_changed}")

    # gom theo bundle
    repl = {}
    for a in p.assets:
        if a.textasset in new_bytes:
            repl.setdefault(a.bundle, {})[a.textasset] = new_bytes[a.textasset]

    # ---------- 4. repack ----------
    out_bdir = os.path.join(args.out, p.bundle_subdir)
    os.makedirs(out_bdir, exist_ok=True)
    sizes, expectations = {}, {}
    for bundle, repl_map in repl.items():
        src_path = p.bundle_path(bundle)
        out_path = os.path.join(out_bdir, bundle)
        before = {n: sha(b) for n, (_, b) in bundle_assets(src_path)[1].items()}
        n_out, packer = repack(src_path, repl_map, out_path)
        sizes[bundle_key(bundle)] = n_out
        expectations[bundle] = (before, repl_map)
        print(f"Repack {bundle[:52]:54s} -> {n_out:>11,} bytes ({packer})")

    # ---------- 5. kiem tra sau repack ----------
    print("\nKiem tra sau repack:")
    ok_all = True
    for name, (before, expect) in expectations.items():
        out_path = os.path.join(out_bdir, name)
        _, after = bundle_assets(out_path)
        after_b = {n: b for n, (_, b) in after.items()}
        if len(before) != len(after_b):
            print(f"  !! {name[:40]}: so asset {len(before)} -> {len(after_b)}")
            ok_all = False
        allowed = set(expect)
        n_changed = [k for k in before if sha(after_b.get(k, b"")) != before[k]]
        outside = [k for k in n_changed if k not in allowed]
        print(f"  {name[:44]:46s} asset {len(before)}->{len(after_b)} | "
              f"doi: {sorted(n_changed)}")
        if outside:
            print(f"     !! asset NGOAI PHAM VI bi doi: {outside}")
            ok_all = False
        for tname, want in expect.items():
            got = after_b.get(tname)
            if got != want:
                print(f"     !! {tname}: noi dung khong khop byte")
                ok_all = False
            else:
                print(f"     OK {tname}: {len(want):,} bytes khop chinh xac")
        for k in before:
            if k not in allowed and sha(after_b.get(k, b"")) != before[k]:
                ok_all = False
    print(f"  => {'TAT CA OK' if ok_all else 'THAT BAI'}")

    # ---------- 6. va catalog ----------
    patched, ob, nb = patch_catalog(p.catalog, sizes,
                                    os.path.join(args.out, "catalog.json"))
    print(f"\nVa catalog.json: {len(patched)} bundle | blob {ob} bytes "
          f"(sau sua: {nb} — phai bang dung, offset byte tuyet doi!)")
    assert ob == nb, "blob catalog lech do dai -> offset sai -> game se treo!"
    for h in patched:
        print(f"  m_Crc=0, m_UseCrcForCachedBundles=false, m_BundleSize={sizes[h]:,}  ({h})")

    # ---------- 7. apply.sh ----------
    cache = (f"$HOME/.local/share/Steam/steamapps/compatdata/{p.steam_appid}/pfx/"
             f"drive_c/users/steamuser/AppData/LocalLow/{p.company}/{p.product}/"
             f"com.unity.addressables")
    apply = f"""#!/usr/bin/env bash
# Copy ban mod vao game.  Dung: bash {os.path.basename(os.path.dirname(args.out))}/apply.sh [thu-muc-game]
set -euo pipefail
GAME="${{1:-{p.game_dir}}}"
SRC="{args.out}"
echo "Game: $GAME"
[ -f "$GAME/{p.data_subdir}/StreamingAssets/aa/catalog.json" ] || {{ echo "Khong phai thu muc game!"; exit 1; }}
cp -v "$SRC/catalog.json" "$GAME/{p.data_subdir}/StreamingAssets/aa/catalog.json"
cp -v "$SRC/{p.bundle_subdir}/"*.bundle "$GAME/{p.data_subdir}/StreamingAssets/aa/{p.bundle_subdir}/"
echo
echo "Xong. NHO XOA CACHE ADDRESSABLES truoc khi chay game:"
echo '  rm -rf "{cache}"'
"""
    open(os.path.join(args.out, "apply.sh"), "w").write(apply)
    os.chmod(os.path.join(args.out, "apply.sh"), 0o755)
    print(f"\nDa ghi staging: {args.out}/  (catalog.json, {len(repl)} bundle, apply.sh)")
    print("Chua dung vao game. Chay apply.sh de ap dung.")


if __name__ == "__main__":
    main()
