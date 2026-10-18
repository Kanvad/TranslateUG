"""
Serializer BYTE-EXACT cho cac TextAsset nguon (JSON/CSV).
Da kiem chung tai tao nguyen byte 100% tren du lieu that.

  bang JSON (vd bang UI) :
      json.dumps(obj, ensure_ascii=False, indent=<json_opts.indent>)
      + escape cac ky tu trong json_opts.escape        (dau hieu Newtonsoft.Json)
      + xuong dong <json_opts.newline>, KHONG BOM, KHONG newline cuoi file
  file CSV (vd hoi thoai) :
      header <csv_header>, csv QUOTE_MINIMAL, lineterminator <newline>, UTF-8 khong BOM

Tham so lay tu game profile (xem games/profile.py); game khac thi do bang discover_game.py.
"""
import csv, io, json

# Cac ky tu ma serializer goc escape du ensure_ascii=False
ESCAPED = ("\u00a0", "\u2003")


def dumps_json(obj, indent=2, newline="\r\n", escape=ESCAPED) -> bytes:
    s = json.dumps(obj, ensure_ascii=False, indent=indent)
    for ch in escape:
        s = s.replace(ch, "\\u%04X" % ord(ch))
    if newline != "\n":
        s = s.replace("\n", newline)
    return s.encode("utf-8")


def loads_json(raw: bytes):
    return json.loads(raw.decode("utf-8"))


def dump_csv(rows, header=("language", "id", "text"), newline="\r\n") -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator=newline, quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    for r in rows:
        w.writerow([r[c] for c in header])
    return buf.getvalue().encode("utf-8")


def load_csv(raw: bytes):
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def verify_json(obj, raw: bytes) -> bool:
    return dumps_json(obj) == raw


def verify_csv(rows, raw: bytes) -> bool:
    return dump_csv(rows) == raw
