r"""
Lop bao ve placeholder / markup / glossary cho pipeline dich game — phan MAY MOC.

Ba bai hoc rut ra:
  1. Kieu sentinel quyet dinh thanh/bai: sentinel unicode bi model xoa sach (0/14 song sot),
     con dang {...} giu duoc 12/14.  => mac dinh dung STYLE "brace".
  2. Cac token NAM SAT NHAU ("</color><color=#00FFA5>") pha vo sentinel.
     => gop cac token lien ke (khoang trang giua chung khong chua chu) thanh MOT sentinel.
  3. Tien to nguoi noi ("aside: ...") de nguyen van thi model van dich ("Ben canh:").
     => CAT tien to ra truoc khi dich va gan lai nguyen trang sau khi dich.

Bay du lieu: trong bang UI, [...] CON la noi dung that, khong phai tag.
=> chi bao ve DUNG tap tag phong cach cua game, va chi trong file hoi thoai.

Ba danh sach style_ids / entity_ids / glossary la DU LIEU RIENG cua tung game nen KHONG co
mac dinh o day — chung nam trong game profile (xem games/profile.py). Phai goi
`profile.apply()` (hoac `configure(...)`) TRUOC khi dung cac regex; khong goi thi ca ba lop
bao ve TAT (regex khong bao gio khop).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# --- Du lieu cua game, duoc `configure()` nap vao ---
STYLE_IDS: list = []
ENTITY_IDS: list = []
GLOSSARY: list = []


def _compile(style_ids, entity_ids, glossary):
    """Bien ba danh sach cua game thanh regex. List RONG => lop bao ve do TAT."""
    st = "|".join(style_ids) or r"(?!)"
    en = "|".join(re.escape(e) for e in entity_ids) or r"(?!)"
    gl = "|".join(re.escape(n) for n in glossary) or r"(?!)"
    return (
        re.compile(r"\[/?(?:" + st + r")(?:\s[^\[\]\n]{0,40})?/?\]"),
        # Tien to nguoi noi co HAI dang: "name: text" (co khoang trang) va "name:Text"
        # (khong). Ban dau chi bat dang dau tien => phan lon bi model xoa/dich tien to.
        re.compile(r"^(?:" + en + r"):[ \t]*"),
        re.compile(r"(?<![\w-])(" + gl + r")(?![\w-])"),
    )


RE_BRACE = re.compile(r"\{[^{}]{0,24}\}")
RE_SPRITE = re.compile(r"<sprite[^<>\n]{0,60}>")
RE_ANGLE = re.compile(r"<[^<>\n]{1,60}>")
RE_OPTION = re.compile(r"\[option\s[^\[\]\n]{0,60}?/?\]")
RE_STYLE, RE_ENTITY_PREFIX, RE_GLOSSARY = _compile(STYLE_IDS, ENTITY_IDS, GLOSSARY)

# Chuoi co it nhat 1 tu that su (>=2 chu cai) -> moi can dich
RE_HAS_WORD = re.compile(r"[A-Za-z]{2,}")


def configure(style_ids=None, entity_ids=None, glossary=None):
    r"""Nap style/entity/glossary cua MOT game cu the (xem games/profile.py).

    Goi TRUOC khi import cac regex RE_* ra ten rieng (vi `from protect import RE_STYLE`
    bind gia tri ngay):

        from games import load_profile
        load_profile("mygame").apply()      # -> configure(...)
        from protect import RE_STYLE        # bay gio moi lay gia tri MOI

    qa()/glossary_hits()/Protector doc bien module luc GOI nen tu dong
    thay gia tri moi, khong can import lai.

    Truyen thang list (co the RONG): list rong nghia la TAT lop bao ve do —
    khong duoc de ro ri gia tri cua game khac.
    """
    global STYLE_IDS, ENTITY_IDS, GLOSSARY
    global RE_STYLE, RE_ENTITY_PREFIX, RE_GLOSSARY
    if style_ids is not None:
        STYLE_IDS = list(style_ids)
    if entity_ids is not None:
        ENTITY_IDS = list(entity_ids)
    if glossary is not None:
        GLOSSARY = sorted(set(glossary), key=len, reverse=True)
    RE_STYLE, RE_ENTITY_PREFIX, RE_GLOSSARY = _compile(STYLE_IDS, ENTITY_IDS, GLOSSARY)


# Kieu sentinel. Mac dinh dung STYLE "brace".
STYLES = {
    "brace": ("{", "}"),
    "xnum": ("XQ", "QX"),
    "bracket": ("[[", "]]"),
    "hash": ("#", "#"),
    "unicode": ("\u27e6", "\u27e7"),
}


@dataclass
class Protected:
    masked: str
    mapping: dict = field(default_factory=dict)
    prefix: str = ""

    def restore(self, translated: str) -> str:
        # THAY THE MOT LUOT (single-pass). Khong duoc replace tuan tu:
        # sentinel co the TRUNG SO voi placeholder that (vd sentinel {3} -> "{0}"),
        # replace tuan tu se bien placeholder that thanh tag -> pha hong ban dich.
        if not self.mapping:
            return self.prefix + translated
        pat = re.compile("|".join(
            re.escape(s) for s in sorted(self.mapping, key=len, reverse=True)))
        return self.prefix + pat.sub(lambda m: self.mapping[m.group(0)], translated)

    def missing(self, translated: str) -> list:
        return [s for s in self.mapping if s not in translated]


class Protector:
    def __init__(self, style: str = "brace", use_glossary: bool = True,
                 dialogue: bool = False, merge_adjacent: bool = True):
        self.open, self.close = STYLES[style]
        self.use_glossary = use_glossary
        self.dialogue = dialogue
        self.merge_adjacent = merge_adjacent
        self._n = 0

    def _sentinel(self) -> str:
        s = f"{self.open}{self._n}{self.close}"
        self._n += 1
        return s

    def _spans(self, text: str) -> list:
        raw = []
        patterns = [RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION]
        if self.dialogue:
            patterns.append(RE_STYLE)
        for rx in patterns:
            raw += [m.span() for m in rx.finditer(text)]

        raw.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        tok_spans = []
        for s in raw:
            if tok_spans and s[0] < tok_spans[-1][1]:
                continue
            tok_spans.append(s)

        spans = list(tok_spans)
        if self.use_glossary:
            cursor, gaps = 0, []
            for a, b in tok_spans:
                if a > cursor:
                    gaps.append((cursor, a))
                cursor = b
            if cursor < len(text):
                gaps.append((cursor, len(text)))
            for ga, gb in gaps:
                spans += [m.span() for m in RE_GLOSSARY.finditer(text, ga, gb)]

        spans.sort()
        return spans

    def protect(self, text: str) -> Protected:
        prefix = ""
        if self.dialogue:
            m = RE_ENTITY_PREFIX.match(text)
            if m:
                prefix, text = m.group(0), text[m.end():]

        spans = self._spans(text)
        if not spans:
            return Protected(text, {}, prefix)

        mapping = {}
        out = []
        cursor, i = 0, 0
        while i < len(spans):
            a = spans[i][0]
            end = spans[i][1]
            j = i
            if self.merge_adjacent:
                while j + 1 < len(spans):
                    na, nb = spans[j + 1]
                    if re.fullmatch(r"\s*", text[end:na]):
                        end = nb
                        j += 1
                    else:
                        break
            s = self._sentinel()
            mapping[s] = text[a:end]
            out.append(text[cursor:a])
            out.append(s)
            cursor = end
            i = j + 1
        out.append(text[cursor:])
        return Protected("".join(out), mapping, prefix)


def qa(text_en: str, text_vi: str, dialogue: bool = False) -> dict:
    def tokens(t: str) -> list:
        found = []
        pats = [RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION] + ([RE_STYLE] if dialogue else [])
        for rx in pats:
            found += rx.findall(t)
        return found

    a, b = Counter(tokens(text_en)), Counter(tokens(text_vi))
    return {"missing": list((a - b).elements()),
            "extra": list((b - a).elements()),
            "ok": a == b}


def glossary_hits(text: str) -> list:
    return RE_GLOSSARY.findall(text)
