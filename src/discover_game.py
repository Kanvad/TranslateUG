"""
Do (discover) mot ban Unity Addressables de onboard game moi nhanh.

Quet thu muc game, doc catalog.json + cac *.bundle, liet ke moi TextAsset
(ten, kich thuoc, dinh dang doan duoc) va in ra goi y `src/games/<ten>.py`.

Dung:
  .venv/bin/python src/discover_game.py "~/Desktop/My Game"
  .venv/bin/python src/discover_game.py "/path/to/Game_Data/StreamingAssets/aa"
  .venv/bin/python src/discover_game.py "~/Desktop/My Game" --bundle configs

Sau khi co goi y:
  1. Copy phan `Asset(...)` vao src/games/<ten>.py (xem docs/PORTING.md).
  2. Chay: .venv/bin/python src/extract_units.py --game <ten>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import UnityPy

# Giu nguyen: doan "co phai van ban nguoi dung?" la phong doan, khong chinh xac 100%.
WORDY = re.compile(r"[A-Za-z]{3,}")


def find_aa_dir(path: str) -> str | None:
    """Nhan: thu muc game / *_Data / StreamingAssets/aa / aa. Tra ve thu muc aa."""
    path = os.path.expanduser(path)
    cands = [path,
             os.path.join(path, "StreamingAssets", "aa"),
             os.path.join(path, "aa")]
    for c in cands:
        if os.path.isfile(os.path.join(c, "catalog.json")):
            return c
    # do sau 4: tim catalog.json
    for root, dirs, files in os.walk(path):
        if root.count(os.sep) - path.count(os.sep) > 4:
            dirs[:] = []
            continue
        if "catalog.json" in files:
            return root
    return None


def guess_fmt(raw: bytes):
    """Tra ve (fmt, meta) — fmt in {json, csv, text}."""
    body = raw
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    head = body.lstrip(b" \t\r\n")
    if head[:1] in (b"[", b"{"):
        text = body[:4000].decode("utf-8", "ignore")
        indent = 2 if re.search(r"\n  \"", text) else (4 if re.search(r"\n    \"", text) else 0)
        newline = "\\r\\n" if b"\r\n" in body[:4000] else "\\n"
        return "json", f"indent={indent} newline={newline}"
    first = body.split(b"\n", 1)[0]
    if b"," in first and len(first) < 300:
        cols = [c.strip().strip(b'"').decode("utf-8", "ignore")
                for c in first.rstrip(b"\r").split(b",")]
        return "csv", "cot=" + ",".join(cols)
    return "text", ""


def textassets(bundle_path):
    env = UnityPy.load(bundle_path)
    out, fonts = [], []
    for o in env.objects:
        try:
            if o.type.name == "TextAsset":
                d = o.read()
                s = d.m_Script
                out.append((d.m_Name, s.encode("utf-8") if isinstance(s, str) else s))
            elif o.type.name == "MonoBehaviour":
                d = o.read(check_read=False)
                if getattr(d, "m_CharacterTable", None) is not None:
                    fonts.append(getattr(d, "m_Name", "") or "?")
        except Exception:
            continue
    return out, fonts


def main():
    ap = argparse.ArgumentParser(description="Do TextAsset trong ban Unity (Addressables)")
    ap.add_argument("path", help="thu muc game (hoac *_Data, hoac StreamingAssets/aa)")
    ap.add_argument("--bundle", default=None, help="chi xet bundle co ten chua chuoi nay")
    ap.add_argument("--max", type=int, default=0, help="gioi han so bundle quet (0 = tat ca)")
    a = ap.parse_args()

    aa = find_aa_dir(a.path)
    if not aa:
        sys.exit(f"Khong thay catalog.json trong: {a.path}")
    aa = aa.rstrip("/")
    if aa.endswith(os.path.join("StreamingAssets", "aa")):
        data_dir = os.path.dirname(os.path.dirname(aa))
        root_game = os.path.dirname(data_dir)
        data_subdir = os.path.basename(data_dir)
    else:
        root_game = aa
        data_subdir = "<Ten>_Data"
    print(f"Addressables dir: {aa}")
    print(f"Game dir        : {root_game}")
    print(f"Data subdir     : {data_subdir}")

    # cac thu muc bundle (thuong la StandaloneWindows64, Android, iOS...)
    subdirs = sorted(d for d in os.listdir(aa)
                     if os.path.isdir(os.path.join(aa, d)) and not d.startswith("."))
    print(f"Bundle subdirs  : {subdirs}")

    bundles = []
    for d in subdirs:
        for fn in sorted(os.listdir(os.path.join(aa, d))):
            if fn.endswith(".bundle") and (a.bundle is None or a.bundle in fn):
                bundles.append((d, fn))
    if a.max:
        bundles = bundles[: a.max]
    print(f"Bundle se quet  : {len(bundles)}")

    csv_header = None
    suggestion = []

    for subdir, fn in bundles:
        path = os.path.join(aa, subdir, fn)
        try:
            tas, fonts = textassets(path)
        except Exception as e:
            print(f"  !! {fn}: khong doc duoc ({e})")
            continue
        if not tas and not fonts:
            continue
        print(f"\n=== {subdir}/{fn} ({os.path.getsize(path):,} bytes) "
              f"| TextAsset={len(tas)} | TMP font={len(fonts)} ===")
        for name, raw in sorted(tas):
            fmt, meta = guess_fmt(raw)
            n_wordy = bool(WORDY.search(raw[:4000].decode("utf-8", "ignore")))
            print(f"  {name:44s} {len(raw):>10,} bytes  {fmt.upper():5s} {meta}")
            # goi y: asset JSON/CSV co chu that => ung vien dich
            if fmt in ("json", "csv") and n_wordy:
                idf, tf = "key", "text"
                if fmt == "csv" and meta.startswith("cot="):
                    cols = meta[4:].split(",")
                    idf = next((c for c in cols if c.lower() in ("id", "key", "uid")), cols[0])
                    tf = next((c for c in cols if c.lower() in ("text", "value", "en")), cols[-1])
                    csv_header = tuple(cols)
                suggestion.append(dict(subdir=subdir, bundle=fn, name=name, fmt=fmt,
                                       id_field=idf, text_field=tf))
        if fonts:
            print(f"  TMP font assets: {', '.join(sorted(set(fonts))) or '(khong ten)'}")

    print("\n" + "=" * 72)
    print("GOI Y game profile (src/games/<ten>.py):")
    print("=" * 72)
    rel = os.path.relpath(root_game, os.path.expanduser("~"))
    rel = "~/" + rel if not rel.startswith("..") else root_game
    print(f"""
from .profile import Asset, GameProfile

def build():
    return GameProfile(
        name="mygame",
        game_dir="{rel}",
        data_subdir="{data_subdir}",
        bundle_subdir="{subdirs[0] if subdirs else 'StandaloneWindows64'}",
        assets=[
""".rstrip())
    for s in suggestion:
        print(f"""            Asset(textasset="{s['name']}",
                  bundle="{s['bundle']}",
                  fmt="{s['fmt']}", id_field="{s['id_field']}",
                  text_field="{s['text_field']}", dialogue=?, translated=True),""")
    print("""        ],
        # style_ids=[...], entity_ids=[...], glossary=[...],  # xem docs/PORTING.md
        # font_fix={...},                                    # neu font thieu glyph
    )""")
    if csv_header:
        print(f"\n# csv_header de xuat: {csv_header!r} (kiem tra lai thu tu cot)")
    print("\n# `dialogue=?`: dat True cho file hoi thoai (bao ve style tag + cat tien to"
          " nguoi noi), False cho bang UI.")
    print("# Sau khi dien xong: .venv/bin/python src/extract_units.py --game mygame")


if __name__ == "__main__":
    main()
