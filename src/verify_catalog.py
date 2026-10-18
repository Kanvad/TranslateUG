"""Kiem chung catalog.json da va: JSON hop le, entry nguyen ven, chi entry du kien doi.

Dung:
  .venv/bin/python src/verify_catalog.py [catalog_moi] [--game ten]
"""
import argparse, base64, json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg  # noqa: E402
from paths import BUILD                   # noqa: E402

P = load_profile(game_arg())
ORIG = P.catalog


def entries(path):
    txt = open(path, encoding="utf-8").read()
    m = re.search(r'"m_ExtraDataString":\s*"([^"]*)"', txt)
    blob = base64.b64decode(m.group(1))
    pat = '{"m_Hash"'.encode("utf-16-le")
    out, i = [], blob.find(pat)
    while i != -1:
        depth, j = 0, i
        while j < len(blob):
            ch = blob[j:j + 2].decode("utf-16-le", errors="ignore")
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 2
        out.append(json.loads(blob[i:j + 2].decode("utf-16-le")))
        i = blob.find(pat, j + 2)
    return txt, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalog", nargs="?", default=os.path.join(BUILD, "mod", "catalog.json"))
    ap.add_argument("--game", default=game_arg(), help="game profile trong src/games/")
    a = ap.parse_args()
    new = a.catalog
    if not os.path.exists(new):
        print(f"Khong thay {new} — hay chay src/inject.py truoc.")
        return 2

    ot, oe = entries(ORIG)
    nt, ne = entries(new)
    print(f"catalog.json: {len(ot):,} -> {len(nt):,} bytes")
    print(f"JSON hop le: {bool(json.loads(nt))}")
    print(f"so entry: {len(oe)} -> {len(ne)}")
    assert len(oe) == len(ne), "so entry doi!"
    assert {e["m_Hash"] for e in oe} == {e["m_Hash"] for e in ne}, "tap hash doi!"
    o_by = {e["m_Hash"]: e for e in oe}
    changed = []
    for e in ne:
        o = o_by[e["m_Hash"]]
        d = {k: (o.get(k), e.get(k)) for k in e if o.get(k) != e.get(k)}
        if d:
            changed.append((e["m_Hash"], d))
    print(f"entry bi doi: {len(changed)}")
    for h, d in changed:
        print(f"  {h}:")
        for k, (a_, b_) in d.items():
            print(f"     {k}: {a_} -> {b_}")
    print("\n=> CATALOG OK" if changed else "\n=> khong co thay doi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
