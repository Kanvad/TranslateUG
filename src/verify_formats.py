"""Kiem chung byte-exact cho cac TextAsset dung cho viec tai nap (theo game profile).

Dung:
  .venv/bin/python src/verify_formats.py
  .venv/bin/python src/verify_formats.py --game mygame
"""
import hashlib, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from games import load_profile, game_arg                     # noqa: E402
from formats import loads_json, dumps_json, load_csv, dump_csv  # noqa: E402
from paths import BUILD                                        # noqa: E402

P = load_profile(game_arg())
JO = dict(indent=P.json_opts["indent"], newline=P.json_opts["newline"],
          escape=tuple(P.json_opts["escape"]))

checks = []
for a in P.assets:
    raw = open(os.path.join(BUILD, "raw", a.raw_name), "rb").read()
    if a.fmt == "json":
        obj = loads_json(raw)
        ok = dumps_json(obj, **JO) == raw
        n = len(obj)
    else:
        rows = load_csv(raw)
        ok = dump_csv(rows, header=P.csv_header, newline=JO["newline"]) == raw
        n = len(rows)
    checks.append(ok)
    print(f"{'OK ' if ok else 'FAIL'}  {a.raw_name:38s} {len(raw):>9,} bytes  {n:>6,} muc  "
          f"sha256={hashlib.sha256(raw).hexdigest()[:16]}")
print(f"\nTAT CA BYTE-EXACT: {all(checks)}   (game: {P.name})")
sys.exit(0 if all(checks) else 1)
