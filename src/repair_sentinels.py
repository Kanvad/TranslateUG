"""
Sua loi sentinel trong ban dich da tai ve — KHONG can chay lai GPU.

Model dich thinh thoang bien dau `}` cua sentinel thanh `>` hoac `<`:
    {0} -> {0>        {2} -> {2<}        {0} -> {0<
Vi sentinel khong khop nen buoc restore() da bo qua, va ban dich bi giu nguyen dang {0>...

Script nay sua sentinel bi hong ({0>} -> {0}, {0< -> {0}) trong ban dich da tai ve.
KHONG goi restore(): ban dich trong file da o dang restored (notebook da restore roi);
goi restore() lan nua se double-apply va lam hong file (xem nhat ky muc AF).

Dung:
  .venv/bin/python src/repair_sentinels.py local/<ten>/build/translations_hymt2.jsonl
  .venv/bin/python src/repair_sentinels.py local/<ten>/build/translations_hymt2.jsonl --out local/<ten>/build/fixed.jsonl
"""
import argparse, json, os, re, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from games import load_profile, game_arg  # noqa: E402
import paths                                                    # noqa: E402

PROFILE = load_profile(game_arg())
PROFILE.apply()
from protect import (RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION, RE_STYLE,  # noqa: E402
                     glossary_hits)

RES = [RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION, RE_STYLE]
ALL_TOK = re.compile("|".join(r.pattern for r in RES))
EMPTY_TAG = re.compile(
    r"\[(?:" + "|".join(PROFILE.style_ids) + r")\]\s*\[/"
    r"|<color=#[0-9A-Fa-f]{6}>\s*</color>")

_SENT_FIX = [re.compile(r"\{(\d+)\s*[<>]\s*\}"), re.compile(r"\{(\d+)\s*[<>]")]


def fix_sentinels(t):
    for rx in _SENT_FIX:
        t = rx.sub(r"{\1}", t)
    return t


def restore(maps, text):
    if not maps:
        return text
    pat = re.compile("|".join(re.escape(s) for s, _ in sorted(maps, key=lambda kv: -len(kv[0]))))
    d = dict(maps)
    return pat.sub(lambda m: d[m.group(0)], text)


def qa(u, vi):
    def toks(t):
        o = []
        for rx in RES:
            o += rx.findall(t)
        return o
    a, b = Counter(toks(u["en"])), Counter(toks(vi))
    miss, extra = list((a - b).elements()), list((b - a).elements())
    names = [n for n in glossary_hits(u["en"]) if n not in vi]
    pbad = bool(u["prefix"]) and not vi.startswith(u["prefix"])
    be, bv = ALL_TOK.sub(" ", u["en"]), ALL_TOK.sub(" ", vi)
    trunc = len(be) > 60 and len(bv) < 0.50 * len(be)
    etag = bool(EMPTY_TAG.search(vi))
    return dict(miss=miss, extra=extra, names=names, prefix_bad=pbad,
                trunc=trunc, empty_tag=etag,
                ok=not (miss or extra or names or pbad or trunc or etag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("translations")
    ap.add_argument("--units", default=f"{paths.BUILD}/units.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--game", default=game_arg(), help="game profile trong src/games/")
    a = ap.parse_args()
    out = a.out or a.translations
    units = {json.loads(l)["uid"]: json.loads(l)
             for l in open(a.units, encoding="utf-8") if l.strip()}
    recs = [json.loads(l) for l in open(a.translations, encoding="utf-8") if l.strip()]
    print(f"doc {len(recs):,} ban dich | {len(units):,} don vi goc")

    fixed = changed = 0
    still = []
    for r in recs:
        u = units.get(r["uid"])
        if u is None:
            continue
        old = str(r.get("vi", ""))
        # CHI sua sentinel bi hong ({0>} -> {0}, {0< -> {0}). KHONG goi restore(): vi trong file
        # da o dang restored (notebook da restore roi). Goi restore() lan nua se double-apply va
        # lam hong ban dich (xem nhat ky muc AF).
        new = fix_sentinels(old)
        if new != old:
            r["vi"] = new
            changed += 1
        c = qa(u, new)
        r["qa_ok"] = c["ok"]
        if not c["ok"]:
            r["problems"] = c
            still.append(r["uid"])
        else:
            r.pop("problems", None)
            fixed += 1
    print(f"  sua noi dung sentinel : {changed:,} dong")
    print(f"  dat QA sau khi sua     : {fixed:,}/{len(recs):,}  ({100*fixed/max(len(recs),1):.1f}%)")
    print(f"  con loi                : {len(still):,}  -> {still[:15]}")
    if out == a.translations:
        bak = a.translations + ".bak"
        if not os.path.exists(bak):
            os.rename(a.translations, bak)
            print(f"  da sao luu ban cu -> {os.path.basename(bak)}")
    with open(out, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"da ghi {out}")


if __name__ == "__main__":
    main()
