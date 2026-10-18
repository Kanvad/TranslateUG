"""
Do do phu glyph tieng Viet cua cac font trong game (theo game profile).

Phan biet ro 2 loai font (day la bay da gap):
  - TextMeshPro FontAsset (MonoBehaviour) -> atlas da "nuong", chi co glyph da bake san.
    Neu thieu glyph thi KHONG the bu luc chay (tru khi atlas o che do Dynamic).
  - UnityEngine.Font (TTF that) -> day du glyph, render duoc moi ky tu co trong font.

Chay: .venv/bin/python src/check_fonts.py [--game ten]
Doc:  local/build/raw/  (ban goc byte-exact do extract_units.py ghi ra)
"""
import os, sys
import UnityPy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg                     # noqa: E402
from formats import loads_json, load_csv                     # noqa: E402
from paths import BUILD                                      # noqa: E402

P = load_profile(game_arg())

# --- 1. Gom moi ky tu ma phan van ban nguon (EN) su dung ---
full = []
for a in P.translated_assets:
    raw = open(f"{BUILD}/raw/{a.raw_name}", "rb").read()
    data = loads_json(raw) if a.fmt == "json" else load_csv(raw)
    full += [x[a.text_field] for x in data if isinstance(x.get(a.text_field), str)]
used = {ord(c) for c in "".join(full)}
print(f"Van ban nguon: {len(full):,} chuoi, {sum(map(len, full)):,} ky tu, "
      f"{len(used)} ky tu khac nhau")

# --- 2. Doc truc tiep tu cac bundle cua game ---
tmp_fonts, legacy = {}, {}
for bundle in P.bundles():
    path = P.bundle_path(bundle)
    if not os.path.exists(path):
        print(f"  (bo qua, khong thay bundle: {bundle})")
        continue
    env = UnityPy.load(path)
    for o in env.objects:
        if o.type.name == "MonoBehaviour":
            try:
                d = o.read(check_read=False)
            except Exception:
                continue
            ct = getattr(d, "m_CharacterTable", None)
            if ct is None:
                continue
            uni = {getattr(e, "m_Unicode", None) for e in ct}
            uni.discard(None)
            tmp_fonts[getattr(d, "m_Name", "") or "?"] = (
                uni, getattr(d, "m_AtlasPopulationMode", None),
                bool(getattr(d, "m_FallbackFontAssetTable", None)),
                getattr(d, "m_SourceFontFile", None))
        elif o.type.name == "Font":
            d = o.read()
            fd = getattr(d, "m_FontData", None)
            if fd:
                legacy[d.m_Name] = len(fd)

# --- 3. Bao cao ---
VN = {ord(c) for c in [chr(c) for c in range(0x1EA0, 0x1EFA)]
      + list("àáâãèéêìíòóôõùúýăđơưĂĐƠƯÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ")}
print("\n=== TextMeshPro FontAsset (atlas da nuong) ===")
for n, (uni, pop, fb, src) in sorted(tmp_fonts.items()):
    miss_vn = sorted(VN - uni)
    miss_en = sorted(used - uni)
    mode = {0: "Static", 1: "Dynamic", 2: "DynamicOS"}.get(pop, str(pop))
    print(f"  {n:30s} glyph={len(uni):6d} atlasMode={mode:9s} "
          f"fallback={'co' if fb else 'KHONG':5s} "
          f"srcFont={'co' if src and getattr(src, 'm_PathID', 0) else 'KHONG'}")
    print(f"      thieu ky tu tieng Viet: {len(miss_vn):3d}/130   "
          f"thieu ky tu trong van ban nguon: {len(miss_en):3d}")
    if miss_vn:
        print(f"      vi du thieu: {''.join(chr(c) for c in miss_vn[:30])}")

print("\n=== UnityEngine.Font (TTF that, khong phai TMP) ===")
for n, size in sorted(legacy.items()):
    print(f"  {n:34s} ttf_bytes={size:,}")

if P.font_fix:
    print("\n=== Font fix khai bao trong profile ===")
    for textasset, fix in P.font_fix.items():
        for entry_id, fields in fix.items():
            for field, url in fields.items():
                print(f"  {textasset}: {entry_id}.{field} -> {url}")
