#!/usr/bin/env python
"""
Danh gia chat luong CAP file dich (units + translations) cua pipeline dich game.

    units.jsonl            : don vi EN goc (nguon tham chieu, co uid)
    translations_*.jsonl   : ban dich VI tuong ung theo uid

Script CHI DOC hai file dau vao, KHONG sua gi. Moi ket qua ghi vao --out-dir:
    report.json   : toan bo so lieu + vi du
    *.png         : bieu do matplotlib

Noi dung danh gia:
    1. Toan ven schema : thieu/trung/la uid, thu tu, key bat buoc, dong hong.
    2. Can chinh nguon : do lech uid bang tin hieu duoc bao toan (so, glossary,
       literal trong maps, tien to nguoi noi) -> phat hien lech ca file hoac lech cuc bo.
    3. 5 lop QA        : token, glossary, prefix, trunc, empty_tag (giong pipeline).
    4. Doi chieu co luu: tinh lai QA va so voi qa_ok/problems da ghi trong file dich.
    5. Tin hieu noi dung: rong, con nguyen EN, khong dau, trung lap, ty le do dai.
    6. Diem tong hop    : 3 thanh phan (dinh dang / noi dung / dau tieng Viet).

Dung:
    .venv/bin/python src/eval_translations.py
    .venv/bin/python src/eval_translations.py --units local/<ten>/build/units.jsonl \\
        --trans local/<ten>/build/translations_hymt2.jsonl --out-dir local/<ten>/build/eval
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from games import load_profile, game_arg  # noqa: E402
import paths                                                    # noqa: E402

PROFILE = load_profile(game_arg())
PROFILE.apply()
from protect import (  # noqa: E402
    RE_ANGLE, RE_BRACE, RE_OPTION, RE_SPRITE, RE_STYLE, glossary_hits,
)

BASE_PATS = [RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION]
ALL_PATS = BASE_PATS + [RE_STYLE]
ALL_TOK = re.compile("|".join(r.pattern for r in ALL_PATS))
EMPTY_TAG = re.compile(
    r"\[(?:" + "|".join(PROFILE.style_ids) + r")\]\s*\[/"
    r"|<color=#[0-9A-Fa-f]{6}>\s*</color>")
TRUNC_RATIO = 0.50          # nguong trunc cua pipeline
TRUNC_MIN_CHARS = 60        # chi xet khi EN (da bo token) dai hon nguong nay

NUM = re.compile(r"\d[\d.,]*")
HAS_ALPHA = re.compile(r"[A-Za-z]")
ASCII_LETTER = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{3,}")
# Latin mo rong + dau to hop: du de nhan dien "co dau tieng Viet"
VN_RANGES = ((0x00C0, 0x024F), (0x1E00, 0x1EFF), (0x0300, 0x036F))
REQ_UNIT_KEYS = ("uid", "kind", "en", "prefix", "maps", "skip")
REQ_TRANS_KEYS = ("uid", "vi")

# Bang mau dung cho bieu do
C_OK, C_WARN, C_BAD, C_NEU, C_ACC = "#2E7D32", "#EF6C00", "#C62828", "#546E7A", "#1565C0"
C_GRID = "#DDE3E8"
LAYER_ORDER = ["miss", "extra", "trunc", "names", "empty_tag", "prefix_bad"]
LAYER_VI = {
    "miss": "Thieu token",
    "extra": "Thua token",
    "trunc": "Bi cat ngan",
    "names": "Mat ten rieng",
    "empty_tag": "Tag rong",
    "prefix_bad": "Sai tien to",
}


# --------------------------------------------------------------------------
# 1. Nap du lieu
# --------------------------------------------------------------------------
def load_jsonl(path: str):
    """Doc JSONL -> (records, danh sach dong hong)."""
    recs, bad = [], []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                bad.append({"line": n, "error": str(e)})
                continue
            if not isinstance(obj, dict):
                bad.append({"line": n, "error": "khong phai object"})
                continue
            recs.append(obj)
    return recs, bad


def pct(a, b) -> float:
    return 100.0 * a / b if b else 0.0


# --------------------------------------------------------------------------
# 2. 5 lop QA (giong pipeline: verify_formats / repair_sentinels / make_kaggle)
# --------------------------------------------------------------------------
def tokens_of(text: str) -> list:
    out = []
    for rx in ALL_PATS:
        out += rx.findall(text)
    return out


def bare_tokens(text: str) -> str:
    return ALL_TOK.sub(" ", text)


def qa_layers(unit: dict, vi: str) -> dict:
    a, b = Counter(tokens_of(unit["en"])), Counter(tokens_of(vi))
    miss = list((a - b).elements())
    extra = list((b - a).elements())
    names = [n for n in glossary_hits(unit["en"]) if n not in vi]
    prefix = unit.get("prefix") or ""
    prefix_bad = bool(prefix) and not vi.startswith(prefix)
    be, bv = bare_tokens(unit["en"]), bare_tokens(vi)
    trunc = len(be) > TRUNC_MIN_CHARS and len(bv) < TRUNC_RATIO * len(be)
    empty_tag = bool(EMPTY_TAG.search(vi))
    return {
        "miss": miss, "extra": extra, "names": names,
        "prefix_bad": prefix_bad, "trunc": trunc, "empty_tag": empty_tag,
        "ok": not (miss or extra or names or prefix_bad or trunc or empty_tag),
    }


def stored_layers(rec: dict) -> dict | None:
    """Lay ket qua QA da luu trong file dich (neu co)."""
    if "qa_ok" not in rec:
        return None
    p = rec.get("problems") or {}
    out = {"ok": bool(rec["qa_ok"])}
    for k in LAYER_ORDER:
        v = p.get(k)
        out[k] = (v or []) if k in ("miss", "extra", "names") else bool(v)
    return out


# --------------------------------------------------------------------------
# 3. Tin hieu nguon duoc bao toan -> kiem tra can chinh uid
# --------------------------------------------------------------------------
def source_signals(unit: dict, terms: set = frozenset()) -> set:
    """Chuoi dac trung cua don vi nguon: so, ten rieng, literal maps, tien to, thuat ngu duoc giu.

    Tat ca tra ve chuoi da casefold de so khop khong phan biet hoa/thuong.
    """
    sig = set()
    sig |= {n for n in NUM.findall(unit["en"]) if len(n) >= 2}
    sig |= set(glossary_hits(unit["en"]))
    for _, val in (unit.get("maps") or []):
        if len(val) >= 4 and HAS_ALPHA.search(val):
            sig.add(val)
    prefix = (unit.get("prefix") or "").strip()
    if len(prefix) >= 3:
        sig.add(prefix)
    if terms:
        sig |= {w for w in WORD.findall(unit["en"]) if w in terms}
    return {s.casefold() for s in sig}


def learn_kept_terms(by_uid: dict, recs: list, min_n: int = 4,
                     min_rate: float = 0.60) -> tuple:
    """Hoc cac thuat ngu EN duoc BAN DICH GIU NGUYEN (Jetpack, Goldcoin, HP...).

    Mot tu duoc coi la "giu nguyen" neu no xuat hien trong >= min_n don vi EN va
    xuat hien lai trong ban dich VI cua >= min_rate so don vi do. Nho vay script
    co tin hieu kiem tra can chinh ca voi cac dong van xuoi khong co token/so.
    Nguong la heuristic; danh sach day du + ty le giu nguyen nam trong report.json
    (can_chinh.thuat_ngu_giu_nguyen).
    """
    stats = defaultdict(lambda: [0, 0])
    for r in recs:
        u = by_uid.get(r.get("uid"))
        if u is None:
            continue
        vi = str(r.get("vi", "")).casefold()
        for w in set(WORD.findall(u["en"])):
            st = stats[w]
            st[0] += 1
            st[1] += int(w.casefold() in vi)
    kept = {w for w, (n, h) in stats.items() if n >= min_n and h / n >= min_rate}
    detail = {w: {"so_don_vi": stats[w][0], "giu_nguyen": stats[w][1],
                  "ty_le": round(pct(stats[w][1], stats[w][0]), 1)}
              for w in sorted(kept, key=lambda w: -stats[w][0])}
    return kept, detail


def classify_alignment(unit: dict, prev: dict | None, vi: str, terms: set) -> tuple:
    """-> (nhan, co_tin_hieu, khop_uid, khop_uid_truoc)."""
    cur = source_signals(unit, terms)
    pre = source_signals(prev, terms) if prev else set()
    v = vi.casefold()
    m_cur = bool(cur) and all(s in v for s in cur)
    m_pre = bool(pre) and all(s in v for s in pre)
    if m_cur:
        return "khop", True, True, m_pre
    if m_pre:
        return "lech_1", True, False, True
    if cur:
        return "khong_khop", True, False, False
    return "khong_tin_hieu", False, False, False


def offset_pass_rates(by_uid: dict, recs: list, terms: set, offsets=range(-3, 4)) -> dict:
    out = {}
    for off in offsets:
        info = hit = 0
        for r in recs:
            u = by_uid.get(r.get("uid", -10**9) + off)
            if u is None:
                continue
            sig = source_signals(u, terms)
            if not sig:
                continue
            info += 1
            v = str(r.get("vi", "")).casefold()
            hit += all(s in v for s in sig)
        out[off] = {"co_tin_hieu": info, "khop": hit, "ty_le": pct(hit, info)}
    return out


def anomaly_clusters(labels: list, gap: int = 3, only: str | None = None) -> list:
    """Gom cac uid bat thuong (lech_1 / khong_khop) thanh cum lien vung."""
    if only:
        bad = [(uid, lab) for uid, lab in labels if lab == only]
    else:
        bad = [(uid, lab) for uid, lab in labels if lab in ("lech_1", "khong_khop")]
    out = []
    for uid, lab in bad:
        if out and uid - out[-1]["uid_cuoi"] <= gap:
            c = out[-1]
            c["uid_cuoi"] = uid
            c["so_dong"] += 1
            c["lech_1"] += int(lab == "lech_1")
            c["khong_khop"] += int(lab == "khong_khop")
        else:
            out.append({"uid_dau": uid, "uid_cuoi": uid, "so_dong": 1,
                        "lech_1": int(lab == "lech_1"),
                        "khong_khop": int(lab == "khong_khop")})
    for c in out:
        c["do_dai"] = c["uid_cuoi"] - c["uid_dau"] + 1
        c["mat_do"] = round(pct(c["so_dong"], c["do_dai"]), 1)
    return out


def shift_blocks(labels: list) -> list:
    """Gop cac uid lech lien tiep thanh tung khoi."""
    blocks = []
    for uid, lab in labels:
        if lab == "lech_1":
            if blocks and uid == blocks[-1]["uid_cuoi"] + 1:
                blocks[-1]["uid_cuoi"] = uid
                blocks[-1]["so_dong"] += 1
            else:
                blocks.append({"uid_dau": uid, "uid_cuoi": uid, "so_dong": 1})
    return blocks


# --------------------------------------------------------------------------
# 4. Tin hieu noi dung
# --------------------------------------------------------------------------
def has_vn_mark(text: str) -> bool:
    for ch in text:
        o = ord(ch)
        if any(a <= o <= b for a, b in VN_RANGES):
            return True
    return False


def ascii_letter_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return len(ASCII_LETTER.findall(text)) / len(letters)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def content_flags(unit: dict, rec: dict, dup_ids: set) -> dict:
    en, vi = unit["en"], str(rec.get("vi", ""))
    by_design = bool(unit.get("skip")) or bool(rec.get("still_en"))
    empty = not vi.strip()
    same = vi.strip() == en.strip() or (bool(vi.strip()) and norm(vi) == norm(en))
    no_mark = bool(vi.strip()) and not has_vn_mark(vi)
    ratio = ascii_letter_ratio(vi)
    be, bv = bare_tokens(en), bare_tokens(vi)
    len_ratio = (len(bv) / len(be)) if len(be) else None
    if empty:
        kind = "rong"
    elif by_design:
        kind = "giu_en_theo_thiet_ke"
    elif same:
        kind = "con_nguyen_en"
    elif no_mark:
        kind = "khong_dau_nghi_chua_dich"
    else:
        kind = "da_dich"
    return {
        "rong": empty, "con_nguyen_en": same and not by_design,
        "khong_dau": no_mark and not by_design and not same,
        "theo_thiet_ke": by_design, "trung_lap": unit["uid"] in dup_ids,
        "ty_le_ascii": round(ratio, 3),
        "ty_le_do_dai": (round(len_ratio, 3) if len_ratio is not None else None),
        "nhom": kind,
    }


def find_duplicates(units: dict, recs: list, min_len: int = 12) -> set:
    """uid co ban dich VI trung voi uid khac nhung EN khac nhau."""
    groups = defaultdict(list)
    for r in recs:
        vi = str(r.get("vi", "")).strip()
        if len(vi) >= min_len:
            groups[vi].append(r.get("uid"))
    dup = set()
    for vi, uids in groups.items():
        ens = {units[u]["en"].strip() for u in uids if u in units}
        if len(uids) > 1 and len(ens) > 1:
            dup.update(uids)
    return dup


# --------------------------------------------------------------------------
# 5. Tong hop
# --------------------------------------------------------------------------
def analyse(units_path: str, trans_path: str) -> dict:
    unit_recs, unit_bad = load_jsonl(units_path)
    trans_recs, trans_bad = load_jsonl(trans_path)
    by_uid = {}
    dup_unit_uid = []
    for u in unit_recs:
        if u.get("uid") in by_uid:
            dup_unit_uid.append(u.get("uid"))
        by_uid[u.get("uid")] = u
    trans_uid = [r.get("uid") for r in trans_recs]
    recs_by_uid = {r.get("uid"): r for r in trans_recs}
    dup_rec_uid = [u for u, c in Counter(trans_uid).items() if c > 1]

    # --- 1. toan ven ---
    missing_keys_unit = [u.get("uid") for u in unit_recs if any(k not in u for k in REQ_UNIT_KEYS)]
    missing_keys_trans = [r.get("uid") for r in trans_recs if any(k not in r for k in REQ_TRANS_KEYS)]
    only_in_units = sorted(set(by_uid) - set(recs_by_uid), key=lambda x: (x is None, x))
    only_in_trans = sorted(set(recs_by_uid) - set(by_uid), key=lambda x: (x is None, x))
    order_ok = trans_uid == sorted(trans_uid)

    integrity = {
        "units": {"duong_dan": units_path, "so_dong": len(unit_recs), "dong_hong": unit_bad,
                  "uid_trung": dup_unit_uid, "thieu_key": missing_keys_unit},
        "trans": {"duong_dan": trans_path, "so_dong": len(trans_recs), "dong_hong": trans_bad,
                  "uid_trung": dup_rec_uid, "thieu_key": missing_keys_trans},
        "uid_chi_co_trong_units": only_in_units,
        "uid_chi_co_trong_trans": only_in_trans,
        "thu_tu_uid_tang_dan": order_ok,
    }

    # --- 2. can chinh ---
    kept_terms, term_detail = learn_kept_terms(by_uid, trans_recs)
    offsets = offset_pass_rates(by_uid, trans_recs, kept_terms)
    off_best = max(offsets, key=lambda k: (offsets[k]["ty_le"], -abs(k))) if offsets else 0
    align_rows = []
    for r in trans_recs:
        uid = r.get("uid")
        u = by_uid.get(uid)
        if u is None:
            continue
        prev = by_uid.get(uid - 1)
        lab, info, m_cur, m_pre = classify_alignment(u, prev, str(r.get("vi", "")), kept_terms)
        align_rows.append({"uid": uid, "nhan": lab, "co_tin_hieu": info,
                           "khop_uid": m_cur, "khop_uid_truoc": m_pre})
    align_counts = Counter(a["nhan"] for a in align_rows)
    labels = [(a["uid"], a["nhan"]) for a in align_rows]
    blocks = shift_blocks(labels)
    blocks_big = [b for b in blocks if b["so_dong"] >= 2]
    clusters = sorted(anomaly_clusters(labels), key=lambda c: (-c["so_dong"], c["uid_dau"]))
    clusters_lech = sorted(anomaly_clusters(labels, gap=2, only="lech_1"),
                           key=lambda c: (-c["so_dong"], c["uid_dau"]))
    clusters_miss = sorted(anomaly_clusters(labels, gap=3, only="khong_khop"),
                           key=lambda c: (-c["so_dong"], c["uid_dau"]))

    # --- 3..5. QA + noi dung ---
    dup_vi = find_duplicates(by_uid, trans_recs)
    align_by_uid = {a["uid"]: a["nhan"] for a in align_rows}
    layer_counts = Counter()
    layer_kind = defaultdict(Counter)
    kind_tot = Counter()
    kind_ok = Counter()
    agree = disagree = 0
    disagreements = []
    content_counts = Counter()
    len_ratio_ok, len_ratio_bad = [], []
    examples = defaultdict(list)
    per_uid_rows = []
    n_skip_like = 0

    for r in trans_recs:
        uid = r.get("uid")
        u = by_uid.get(uid)
        if u is None:
            continue
        vi = str(r.get("vi", ""))
        qa = qa_layers(u, vi)
        cf = content_flags(u, r, dup_vi)
        kind = u.get("kind", "?")
        kind_tot[kind] += 1
        kind_ok[kind] += int(qa["ok"])
        for k in LAYER_ORDER:
            if qa[k]:
                layer_counts[k] += 1
                layer_kind[k][kind] += 1
        if cf["theo_thiet_ke"]:
            n_skip_like += 1
        content_counts[cf["nhom"]] += 1
        if cf["ty_le_do_dai"] is not None:
            (len_ratio_ok if qa["ok"] else len_ratio_bad).append(cf["ty_le_do_dai"])
        st = stored_layers(r)
        if st is not None:
            if st["ok"] == qa["ok"]:
                agree += 1
            else:
                disagree += 1
                if len(disagreements) < 40:
                    disagreements.append({
                        "uid": uid, "qa_luu": st["ok"], "qa_tinh_lai": qa["ok"],
                        "lop_tinh_lai": [k for k in LAYER_ORDER if qa[k]],
                        "lop_da_luu": [k for k in LAYER_ORDER if st[k]],
                        "en": u["en"][:120], "vi": vi[:120],
                    })
        per_uid_rows.append({
            "uid": uid, "kind": kind, "qa_ok": qa["ok"], "nhom": cf["nhom"],
            "nhan_can_chinh": align_by_uid.get(uid),
            "lop_loi": [k for k in LAYER_ORDER if qa[k]],
            "ty_le_do_dai": cf["ty_le_do_dai"], "ty_le_ascii": cf["ty_le_ascii"],
        })
        for key, flag in (("thieu_token", qa["miss"]), ("thua_token", qa["extra"]),
                          ("mat_ten", qa["names"]), ("cat_ngan", qa["trunc"]),
                          ("tag_rong", qa["empty_tag"]), ("sai_tien_to", qa["prefix_bad"]),
                          ("rong", cf["rong"]), ("con_nguyen_en", cf["con_nguyen_en"]),
                          ("khong_dau", cf["khong_dau"]), ("trung_lap", cf["trung_lap"])):
            if flag and len(examples[key]) < 10:
                examples[key].append({"uid": uid, "en": u["en"][:140], "vi": vi[:140]})
    # vi du cho lech cuc bo
    shift_uids = {a["uid"] for a in align_rows if a["nhan"] == "lech_1"}
    for r in trans_recs:
        uid = r.get("uid")
        if uid in shift_uids and len(examples["lech_nguon"]) < 10:
            u, prev = by_uid.get(uid), by_uid.get(uid - 1)
            if u:
                examples["lech_nguon"].append({
                    "uid": uid, "en_uid": u["en"][:140],
                    "en_uid_truoc": (prev or {}).get("en", "")[:140],
                    "vi": str(r.get("vi", ""))[:140]})

    # --- diem ---
    n_total = len(per_uid_rows)
    n_design = n_skip_like
    n_check = max(n_total - n_design, 1)
    fmt_ok = sum(1 for p in per_uid_rows if p["qa_ok"])
    rows_check = [p for p in per_uid_rows if p["nhom"] != "giu_en_theo_thiet_ke"]
    content_ok = sum(1 for p in rows_check if p["nhom"] in ("da_dich", "khong_dau_nghi_chua_dich"))
    vn_ok = sum(1 for p in rows_check if p["nhom"] == "da_dich")
    scores = {
        "dinh_dang": pct(fmt_ok, n_total),
        "noi_dung": pct(content_ok, len(rows_check)),
        "dau_tieng_viet": pct(vn_ok, len(rows_check)),
    }
    overall = 0.55 * scores["dinh_dang"] + 0.25 * scores["noi_dung"] + 0.20 * scores["dau_tieng_viet"]

    return {
        "file": {"units": os.path.abspath(units_path), "trans": os.path.abspath(trans_path)},
        "toan_ven": integrity,
        "can_chinh": {
            "ty_le_khop_theo_offset": {str(k): v for k, v in offsets.items()},
            "offset_tot_nhat": off_best,
            "phan_loai": dict(align_counts),
            "khoi_lech": blocks_big,
            "cum_bat_thuong": clusters[:20],
            "cum_lech_uid": clusters_lech[:20],
            "cum_mat_thuat_ngu": clusters_miss[:20],
            "so_uid_lech": len(shift_uids),
            "tong_thuat_ngu_tin_hieu": len(kept_terms),
            "thuat_ngu_giu_nguyen": dict(list(term_detail.items())[:80]),
        },
        "qa": {
            "tong": n_total,
            "dat": fmt_ok,
            "loi": n_total - fmt_ok,
            "ty_le_dat": round(pct(fmt_ok, n_total), 2),
            "theo_lop": dict(layer_counts),
            "theo_lop_va_kind": {k: dict(v) for k, v in layer_kind.items()},
            "theo_kind": {k: {"tong": kind_tot[k], "dat": kind_ok[k],
                              "ty_le_dat": round(pct(kind_ok[k], kind_tot[k]), 2)}
                          for k in kind_tot},
            "doi_chieu_co_luu": {"khop": agree, "lech": disagree,
                                 "chi_tiet_lech": disagreements},
        },
        "noi_dung": {
            "theo_nhom": dict(content_counts),
            "theo_thiet_ke": n_design,
            "ty_le_do_dai": {
                "dat": _describe(len_ratio_ok),
                "loi": _describe(len_ratio_bad),
            },
        },
        "diem": {**{k: round(v, 2) for k, v in scores.items()}, "tong_hop": round(overall, 2)},
        "vi_du": examples,
        "per_uid": per_uid_rows,
    }


def _describe(xs: list) -> dict:
    if not xs:
        return {"n": 0}
    ys = sorted(xs)
    return {"n": len(ys), "min": round(ys[0], 3), "p25": round(ys[len(ys) // 4], 3),
            "trung_vi": round(ys[len(ys) // 2], 3), "p75": round(ys[3 * len(ys) // 4], 3),
            "max": round(ys[-1], 3)}


# --------------------------------------------------------------------------
# 6. Bao cao console
# --------------------------------------------------------------------------
def print_report(res: dict) -> None:
    L = "=" * 78
    iv, cc, qa, nd, sc = (res["toan_ven"], res["can_chinh"], res["qa"],
                          res["noi_dung"], res["diem"])
    print(L)
    print("DANH GIA CAP FILE DICH")
    print(f"  units : {iv['units']['duong_dan']}")
    print(f"  trans : {iv['trans']['duong_dan']}")
    print(L)

    print("\n[1] TOAN VEN FILE")
    print(f"  units : {iv['units']['so_dong']:>7,} dong | dong hong {len(iv['units']['dong_hong'])}"
          f" | uid trung {len(iv['units']['uid_trung'])} | thieu key {len(iv['units']['thieu_key'])}")
    print(f"  trans : {iv['trans']['so_dong']:>7,} dong | dong hong {len(iv['trans']['dong_hong'])}"
          f" | uid trung {len(iv['trans']['uid_trung'])} | thieu key {len(iv['trans']['thieu_key'])}")
    print(f"  uid chi co trong units : {len(iv['uid_chi_co_trong_units'])}"
          f"  {iv['uid_chi_co_trong_units'][:12]}")
    print(f"  uid chi co trong trans : {len(iv['uid_chi_co_trong_trans'])}"
          f"  {iv['uid_chi_co_trong_trans'][:12]}")
    print(f"  thu tu uid tang dan     : {'CO' if iv['thu_tu_uid_tang_dan'] else 'KHONG'}")

    print("\n[2] CAN CHINH NGUON (uid trong trans co dung voi units khong)")
    print("  offset | co tin hieu |  khop  |  ty le")
    for off, v in cc["ty_le_khop_theo_offset"].items():
        mark = "  <-- tot nhat" if int(off) == cc["offset_tot_nhat"] else ""
        print(f"   {int(off):+d}   |   {v['co_tin_hieu']:>7,}  | {v['khop']:>6,} |"
              f" {v['ty_le']:>5.1f}%{mark}")
    pl = cc["phan_loai"]
    print(f"  phan loai tung dong: khop={pl.get('khop',0):,} | lech_1={pl.get('lech_1',0):,}"
          f" | khong_khop={pl.get('khong_khop',0):,} | khong_tin_hieu={pl.get('khong_tin_hieu',0):,}")
    print(f"  so thuat ngu dung lam tin hieu: {cc.get('tong_thuat_ngu_tin_hieu', 0)}"
          f"  {list(cc.get('thuat_ngu_giu_nguyen', {}))[:8]}")
    print(f"  khoi lech lien tuc (>=2 dong): {len(cc['khoi_lech'])}")
    for b in cc["khoi_lech"][:10]:
        print(f"    uid {b['uid_dau']}..{b['uid_cuoi']}  ({b['so_dong']} dong)")
    print("  cum bat thuong day dac nhat (lech_1 hoac khong_khop):")
    for c in cc["cum_bat_thuong"][:8]:
        print(f"    uid {c['uid_dau']:>6}..{c['uid_cuoi']:<6} do_dai={c['do_dai']:<4}"
              f" bat thuong={c['so_dong']:<4} mat_do={c['mat_do']:>5}%"
              f" (lech_1={c['lech_1']}, khong_khop={c['khong_khop']})")
    print("  cum NGHI LECH UID (dong dich khop voi nguon cua uid-1):")
    if not cc["cum_lech_uid"]:
        print("    (khong co)")
    for c in cc["cum_lech_uid"][:8]:
        print(f"    uid {c['uid_dau']:>6}..{c['uid_cuoi']:<6} so_dong={c['so_dong']:<4}"
              f" do_dai={c['do_dai']:<4} mat_do={c['mat_do']:>5}%")
    print("  cum MAT THUAT NGU nguon (ban dich bo sot thuat ngu duoc giu nguyen):")
    for c in cc["cum_mat_thuat_ngu"][:5]:
        print(f"    uid {c['uid_dau']:>6}..{c['uid_cuoi']:<6} so_dong={c['so_dong']:<4}"
              f" do_dai={c['do_dai']:<4} mat_do={c['mat_do']:>5}%")

    print("\n[3] 5 LOP QA")
    print(f"  dat QA : {qa['dat']:>7,}/{qa['tong']:,}  ({qa['ty_le_dat']:.1f}%)"
          f"   |   loi: {qa['loi']:,}")
    for k in LAYER_ORDER:
        n = qa["theo_lop"].get(k, 0)
        print(f"    {LAYER_VI[k]:<16s} {n:>6,}")
    print("  theo loai:")
    for kind, v in qa["theo_kind"].items():
        print(f"    {kind:<10s} {v['dat']:>6,}/{v['tong']:,}  ({v['ty_le_dat']:.1f}%)")

    print("\n[4] DOI CHIEU CO qa_ok DA LUU")
    d = qa["doi_chieu_co_luu"]
    tot = d["khop"] + d["lech"]
    print(f"  khop: {d['khop']:,}/{tot:,} ({pct(d['khop'], tot):.2f}%)"
          f"   |   lech: {d['lech']:,}")
    for x in d["chi_tiet_lech"][:5]:
        print(f"    uid {x['uid']:>6} luu={x['qa_luu']} tinh_lai={x['qa_tinh_lai']}"
              f" lop_tinh_lai={x['lop_tinh_lai']}")

    print("\n[5] TIN HIEU NOI DUNG")
    for k, v in sorted(nd["theo_nhom"].items(), key=lambda kv: -kv[1]):
        print(f"    {k:<28s} {v:>6,}")
    print(f"  giu EN theo thiet ke (skip/still_en): {nd['theo_thiet_ke']:,}")
    dd = nd["ty_le_do_dai"]
    print(f"  ty le do dai VI/EN (bo token): dat n={dd['dat'].get('n',0):,}"
          f" trung_vi={dd['dat'].get('trung_vi')} | loi n={dd['loi'].get('n',0):,}"
          f" trung_vi={dd['loi'].get('trung_vi')}")
    con_lai = {k: v for k, v in nd["theo_nhom"].items() if k in ("con_nguyen_en", "rong")
               and v > 0}
    if con_lai:
        print("\n  !! CẢNH BÁO — CHƯA ĐẠT: nhóm " + ", ".join(sorted(con_lai))
              + " > 0 (bản dịch bị _write_err fallback ghi vi=EN gốc, phải MODE=\"failed\" dịch lại);"
                " tham khảo report.json -> noi_dung.theo_nhom + vi_du.con_nguyen_en")

    print("\n[6] DIEM")
    print(f"    dinh dang (5 lop QA)   {sc['dinh_dang']:>6.2f}/100")
    print(f"    noi dung (khong rong)  {sc['noi_dung']:>6.2f}/100")
    print(f"    dau tieng Viet         {sc['dau_tieng_viet']:>6.2f}/100")
    print(f"    TONG HOP (0.55/0.25/0.20) {sc['tong_hop']:>6.2f}/100")
    print(L)


# --------------------------------------------------------------------------
# 7. Bieu do matplotlib
# --------------------------------------------------------------------------
def make_plots(res: dict, out_dir: str, dpi: int = 150) -> list:
    import tempfile
    cache = os.path.join(tempfile.gettempdir(), "dsh_mplconfig")
    try:
        os.makedirs(cache, exist_ok=True)
    except OSError:
        cache = os.path.join(out_dir, ".mplconfig")
        os.makedirs(cache, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = cache
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Patch

    plt.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "white",
        "axes.edgecolor": C_GRID, "axes.labelcolor": "#263238",
        "text.color": "#263238", "xtick.color": "#455A64", "ytick.color": "#455A64",
        "axes.titlesize": 12, "axes.titleweight": "bold", "font.size": 10,
        "axes.grid": True, "grid.color": C_GRID, "grid.linewidth": 0.8,
        "axes.axisbelow": True, "savefig.bbox": "tight",
    })
    files = []

    def save(fig, name):
        path = os.path.join(out_dir, name)
        fig.savefig(path, dpi=dpi)
        plt.close(fig)
        files.append(path)

    def bar_labels(ax, bars, fmt="{:.0f}", pad=3, color="#263238"):
        for b in bars:
            w = b.get_width()
            ax.text(w + pad, b.get_y() + b.get_height() / 2, fmt.format(w),
                    va="center", ha="left", fontsize=9, color=color)

    qa, cc, nd, sc = res["qa"], res["can_chinh"], res["noi_dung"], res["diem"]

    # ---- 01 tong quan -------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.5))
    fig.suptitle("Tổng quan chất lượng bản dịch", fontsize=15, fontweight="bold")

    ax = axes[0][0]
    kinds = ["Tất cả"] + list(qa["theo_kind"])
    oks = [qa["dat"]] + [qa["theo_kind"][k]["dat"] for k in qa["theo_kind"]]
    tots = [qa["tong"]] + [qa["theo_kind"][k]["tong"] for k in qa["theo_kind"]]
    y = range(len(kinds))
    ax.barh(y, oks, color=C_OK, label="Đạt 5 lớp QA")
    ax.barh(y, [t - o for t, o in zip(tots, oks)], left=oks, color=C_BAD, label="Lỗi QA")
    ax.set_yticks(list(y), kinds)
    ax.invert_yaxis()
    ax.set_xlabel("số dòng")
    ax.set_title("Đạt / lỗi QA theo loại đơn vị")
    for i, (o, t) in enumerate(zip(oks, tots)):
        ax.text(t + t * 0.01, i, f"{o:,}/{t:,}  ({100*o/t:.1f}%)", va="center", fontsize=9)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False)
    ax.set_xlim(0, max(tots) * 1.28)

    ax = axes[0][1]
    items = [(LAYER_VI[k], qa["theo_lop"].get(k, 0)) for k in LAYER_ORDER]
    items.sort(key=lambda kv: kv[1])
    bars = ax.barh([k for k, _ in items], [v for _, v in items], color=C_WARN)
    bar_labels(ax, bars)
    ax.set_title("Số dòng lỗi theo từng lớp QA")
    ax.set_xlabel("số dòng")
    ax.set_xlim(0, max([v for _, v in items] + [1]) * 1.2)

    ax = axes[1][0]
    names = ["Định dạng\n(5 lớp QA)", "Nội dung\n(không rỗng/nguyên EN)", "Dấu tiếng Việt"]
    vals = [sc["dinh_dang"], sc["noi_dung"], sc["dau_tieng_viet"]]
    cols = [C_OK if v >= 80 else (C_WARN if v >= 50 else C_BAD) for v in vals]
    bars = ax.barh(names, vals, color=cols)
    for b, v in zip(bars, vals):
        ax.text(v + 1, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=10)
    ax.set_xlim(0, 118)
    ax.set_xlabel("điểm thành phần /100")
    ax.set_title(f"Điểm tổng hợp: {sc['tong_hop']:.1f}/100")

    ax = axes[1][1]
    nhom = nd["theo_nhom"]
    order = ["da_dich", "giu_en_theo_thiet_ke", "khong_dau_nghi_chua_dich",
             "con_nguyen_en", "rong"]
    nhan = {"da_dich": "Đã dịch", "giu_en_theo_thiet_ke": "Giữ EN theo thiết kế",
            "khong_dau_nghi_chua_dich": "Không dấu (nghi chưa dịch)",
            "con_nguyen_en": "Còn nguyên EN", "rong": "Rỗng"}
    vals = [nhom.get(k, 0) for k in order]
    cols = [C_OK, C_ACC, C_WARN, C_BAD, "#8E24AA"][:len(order)]
    bars = ax.bar([nhan[k] for k in order], vals, color=cols)
    ax.set_title("Phân loại nội dung bản dịch")
    ax.set_ylabel("số dòng")
    ax.tick_params(axis="x", rotation=20)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,}", ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, max(vals + [1]) * 1.15)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    save(fig, "01_tong_quan.png")

    # ---- 02 loi theo lop x kind ---------------------------------------
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    kind_names = list(qa["theo_kind"])
    layers = [k for k in LAYER_ORDER]
    idx = np.arange(len(layers))
    w = 0.8 / max(len(kind_names), 1)
    pal = [C_ACC, C_WARN, C_OK]
    for i, kind in enumerate(kind_names):
        vals = [qa["theo_lop_va_kind"].get(k, {}).get(kind, 0) for k in layers]
        bars = ax.bar(idx + i * w, vals, w, label=kind, color=pal[i % len(pal)])
        for b, v in zip(bars, vals):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,}", ha="center",
                        va="bottom", fontsize=8)
    ax.set_xticks(idx + w * (len(kind_names) - 1) / 2,
                  [LAYER_VI[k] for k in layers])
    ax.set_ylabel("số dòng lỗi")
    ax.set_title("Lỗi QA theo lớp và theo loại đơn vị (ui / dialogue)")
    ax.legend(frameon=False)
    save(fig, "02_loi_theo_lop_va_kind.png")

    # ---- 03 ty le do dai ----------------------------------------------
    ok_r = [p["ty_le_do_dai"] for p in res["per_uid"]
            if p["qa_ok"] and p["ty_le_do_dai"] is not None]
    bad_r = [p["ty_le_do_dai"] for p in res["per_uid"]
             if not p["qa_ok"] and p["ty_le_do_dai"] is not None]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    bins = [i / 20 for i in range(0, 61)]
    ax.hist([r for r in ok_r if r <= 3], bins=bins, color=C_OK, alpha=0.75,
            label=f"Đạt QA (n={len(ok_r):,})")
    ax.hist([r for r in bad_r if r <= 3], bins=bins, color=C_BAD, alpha=0.65,
            label=f"Lỗi QA (n={len(bad_r):,})")
    ax.axvline(1.0, color="#263238", ls="--", lw=1.2)
    ax.text(1.02, ax.get_ylim()[1] * 0.92, "VI = EN", fontsize=9)
    ax.axvline(TRUNC_RATIO, color=C_WARN, ls=":", lw=1.4)
    ax.text(TRUNC_RATIO + 0.03, ax.get_ylim()[1] * 0.55, "ngưỡng cắt ngắn 0.5", fontsize=9,
            color=C_WARN, rotation=90, va="center")
    ax.set_xlabel("độ dài VI / EN (đã bỏ token)")
    ax.set_ylabel("số dòng")
    ax.set_title("Phân bố tỷ lệ độ dài")
    ax.legend(frameon=False)
    ax = axes[1]
    for data, col, lab in ((ok_r, C_OK, "Đạt QA"), (bad_r, C_BAD, "Lỗi QA")):
        if not data:
            continue
        xs = sorted(data)
        ys = [(i + 1) / len(xs) * 100 for i in range(len(xs))]
        ax.plot(xs, ys, color=col, lw=2, label=f"{lab} (n={len(xs):,})")
    ax.axvline(1.0, color="#263238", ls="--", lw=1.2)
    ax.set_xlim(0, 2.5)
    ax.set_xlabel("độ dài VI / EN")
    ax.set_ylabel("% số dòng tích lũy")
    ax.set_title("Tỷ lệ tích lũy — lỗi thường ngắn hơn")
    ax.legend(frameon=False)
    fig.suptitle("Tỷ lệ độ dài bản dịch so với bản gốc", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(fig, "03_ty_le_do_dai.png")

    # ---- 04 dong xuat hien loi ----------------------------------------
    n = len(LAYER_ORDER)
    mat = [[0] * n for _ in range(n)]
    sets = [set(p["lop_loi"]) for p in res["per_uid"]]
    for s in sets:
        for i, a in enumerate(LAYER_ORDER):
            for j, b in enumerate(LAYER_ORDER):
                if a in s and b in s:
                    mat[i][j] += 1
    fig, ax = plt.subplots(figsize=(8.2, 6.6))
    im = ax.imshow(mat, cmap="YlOrRd")
    ax.set_xticks(range(n), [LAYER_VI[k] for k in LAYER_ORDER], rotation=30, ha="right")
    ax.set_yticks(range(n), [LAYER_VI[k] for k in LAYER_ORDER])
    for i in range(n):
        for j in range(n):
            v = mat[i][j]
            ax.text(j, i, f"{v:,}" if v else "-", ha="center", va="center", fontsize=9,
                    color="white" if v > max(max(r) for r in mat) * 0.6 else "#263238")
    ax.set_title("Số dòng mắc đồng thời hai lớp lỗi\n(đường chéo = tổng số dòng lỗi của lớp)")
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.8, label="số dòng")
    save(fig, "04_dong_xuat_hien_loi.png")

    # ---- 05 can chinh uid ---------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2),
                             gridspec_kw={"width_ratios": [1, 2.1]})
    ax = axes[0]
    offs = sorted(int(k) for k in cc["ty_le_khop_theo_offset"])
    vals = [cc["ty_le_khop_theo_offset"][str(o)]["ty_le"] for o in offs]
    cols = [C_OK if o == cc["offset_tot_nhat"] else C_NEU for o in offs]
    bars = ax.bar([f"{o:+d}" for o in offs], vals, color=cols)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
    ax.set_xlabel("độ lệch uid (trans so với units)")
    ax.set_ylabel("% dòng khớp tín hiệu nguồn")
    ax.set_ylim(0, 108)
    ax.set_title("Dò độ lệch toàn file")

    ax = axes[1]
    code = {"khong_tin_hieu": 0, "khop": 1, "lech_1": 2, "khong_khop": 3}
    labels = [code.get(p["nhan_can_chinh"], 0) for p in res["per_uid"]]
    ax.imshow(np.array([labels]), aspect="auto", cmap=matplotlib.colors.ListedColormap(
        ["#ECEFF1", C_OK, C_BAD, C_WARN]), vmin=0, vmax=3,
        extent=(0, len(labels), 0, 1))
    ax.set_yticks([])
    ax.set_xlabel("uid (tăng dần)")
    ax.set_title("Bản đồ cần chỉnh theo uid — mọi dòng lệch nguồn")
    hot = ([("lệch uid", c) for c in cc.get("cum_lech_uid", []) if c["so_dong"] >= 2][:2]
           + [("mất thuật ngữ", c) for c in cc.get("cum_mat_thuat_ngu", [])[:2]])
    for i, (tag, b) in enumerate(hot):
        y = 1.10 + i * 0.19
        col = C_BAD if tag == "lệch uid" else C_WARN
        ax.annotate("", xy=(b["uid_dau"], y), xytext=(b["uid_cuoi"], y),
                    arrowprops=dict(arrowstyle="|-|,widthA=0.4,widthB=0.4", color=col, lw=2))
        ax.text(b["uid_dau"], y + 0.04,
                f"{tag} {b['uid_dau']}–{b['uid_cuoi']} ({b['so_dong']} dòng)",
                ha="left", fontsize=7.5, color=col)
    ax.set_ylim(-0.4, 1.95)
    ax.legend(handles=[Patch(color="#ECEFF1", label="không đủ tín hiệu"),
                       Patch(color=C_OK, label="khớp uid"),
                       Patch(color=C_BAD, label="lệch về uid-1"),
                       Patch(color=C_WARN, label="không khớp")],
              loc="lower right", frameon=False, ncol=2, fontsize=8)
    fig.suptitle("Kiểm tra canh chỉnh uid giữa units.jsonl và file dịch",
                 fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, "05_can_chinh_uid.png")
    return files


# --------------------------------------------------------------------------
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Danh gia 2 file dich (units + translations)")
    ap.add_argument("--units", default=os.path.join(paths.BUILD, "units.jsonl"),
                    help="file don vi EN goc (JSONL)")
    ap.add_argument("--trans", default=os.path.join(paths.BUILD, "translations_hymt2.jsonl"),
                    help="file ban dich VI (JSONL)")
    ap.add_argument("--out-dir", default=os.path.join(paths.BUILD, "eval"),
                    help="thu muc ghi report.json + bieu do")
    ap.add_argument("--no-plots", action="store_true", help="chi in bao cao, khong ve bieu do")
    ap.add_argument("--top", type=int, default=10, help="so vi du luu trong report.json")
    ap.add_argument("--game", default=game_arg(), help="game profile trong src/games/")
    a = ap.parse_args()

    for p in (a.units, a.trans):
        if not os.path.isfile(p):
            print(f"LOI: khong thay file {p}")
            return 2
    os.makedirs(a.out_dir, exist_ok=True)

    res = analyse(a.units, a.trans)
    print_report(res)

    per_uid = res.pop("per_uid")
    res["per_uid_loi"] = [p for p in per_uid if not p["qa_ok"]][:400]
    res["vi_du"] = {k: v[: a.top] for k, v in res["vi_du"].items() if v}

    report_path = os.path.join(a.out_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"da ghi bao cao : {report_path}")

    if not a.no_plots:
        try:
            files = make_plots({**res, "per_uid": per_uid}, a.out_dir)
            for p in files:
                print(f"da ghi bieu do : {p}")
        except ImportError as e:
            print(f"CANH BAO: khong ve duoc bieu do ({e})."
                  f" Cai dat: uv pip install --python .venv/bin/python matplotlib")
    return 0


if __name__ == "__main__":
    sys.exit(main())
