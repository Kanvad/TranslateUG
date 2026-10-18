"""Kieu du lieu "game profile" — phan cau hinh rieng cho tung game Unity.

Engine (extract_units / inject / eval_translations / check_fonts / make_kaggle /
discover_game) chi doc profile, nen them game moi = them mot file
`local/games/<ten>.py` dinh nghia ham `build() -> GameProfile` roi truyen `--game <ten>`
(khong co profile nao thi dung luon cai duy nhat tim thay).

Vi du profile toi thieu:
    from games.profile import Asset, GameProfile
    def build():
        return GameProfile(
            name="mygame",
            game_dir="~/Desktop/My Game",
            data_subdir="MyGame_Data",
            assets=[Asset(textasset="text_en", bundle="<hash>.bundle", fmt="json")],
        )
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field


@dataclass
class Asset:
    """Mot TextAsset nam trong mot bundle Addressables."""

    textasset: str            # ten TextAsset (vd "ui_text_en")
    bundle: str               # ten file bundle (vd "configs_assets_all_ab12….bundle")
    fmt: str = "json"         # "json" (array object) | "csv" (co header)
    id_field: str = "key"     # truong dinh danh muc (json) / ten cot khoa (csv)
    text_field: str = "text"  # truong chua chu can dich
    dialogue: bool = False    # True -> bao ve style tag + cat tien to nguoi noi
    translated: bool = True   # False -> chi luu raw (vd bang font), khong tao don vi

    @property
    def raw_name(self) -> str:
        return f"{self.textasset}.{'csv' if self.fmt == 'csv' else 'json'}"


@dataclass
class GameProfile:
    name: str
    game_dir: str                              # thu muc goc game (tuyet doi hoac ~)
    data_subdir: str                           # <Ten>_Data
    display_name: str = ""                      # ten hien thi (mac dinh = name)
    aa_rel: str = "StreamingAssets/aa"         # tuong doi trong <Ten>_Data
    bundle_subdir: str = "StandaloneWindows64"
    catalog_name: str = "catalog.json"
    assets: list = field(default_factory=list)  # list[Asset]

    # dinh dang byte-exact (xem formats.py) — gia tri duoi la truong hop Windows/Newtonsoft
    # thuong gap; game khac thi do bang discover_game.py roi sua cho khop.
    json_opts: dict = field(default_factory=lambda: dict(
        indent=2, newline="\r\n", escape=("\u00a0", "\u2003")))
    csv_header: tuple = ("language", "id", "text")

    # bao ve placeholder / QA (xem protect.py)
    style_ids: list = field(default_factory=list)
    entity_ids: list = field(default_factory=list)   # id tien to nguoi noi
    glossary: list = field(default_factory=list)     # ten rieng khong dich

    # tai nap (inject.py)
    #   {textasset: {gia_tri_id: {ten_truong: url_moi}}}
    font_fix: dict = field(default_factory=dict)
    steam_appid: str = ""
    company: str = ""     # thu muc LocalLow/<company>/<product> (de xoa cache)
    product: str = ""

    # generator notebook (make_kaggle_llamacpp.py)
    genre_desc: str = "a video game"
    notebook_name: str = ""   # ten file notebook trong local/ (mac dinh kaggle_<name>_llamacpp.ipynb)

    def __post_init__(self):
        self.game_dir = os.path.expanduser(self.game_dir)
        self.display_name = self.display_name or self.name

    # --- duong dan ---
    @property
    def aa_dir(self) -> str:
        return os.path.join(self.game_dir, self.data_subdir, self.aa_rel)

    @property
    def bundle_dir(self) -> str:
        return os.path.join(self.aa_dir, self.bundle_subdir)

    @property
    def catalog(self) -> str:
        return os.path.join(self.aa_dir, self.catalog_name)

    def bundle_path(self, bundle: str) -> str:
        return os.path.join(self.bundle_dir, bundle)

    # --- truy van asset ---
    @property
    def translated_assets(self) -> list:
        return [a for a in self.assets if a.translated]

    def asset(self, textasset: str) -> Asset:
        for a in self.assets:
            if a.textasset == textasset:
                return a
        raise KeyError(f"profile '{self.name}' khong co asset '{textasset}'")

    def bundles(self) -> list:
        seen, out = set(), []
        for a in self.assets:
            if a.bundle not in seen:
                seen.add(a.bundle)
                out.append(a.bundle)
        return out

    # --- ap cau hinh vao protect.py ---
    def apply(self) -> None:
        """Nap style/entity/glossary cua game vao protect.py (goi TRUOC khi dung regex).

        Truyen thang list (co the RONG): list rong nghia la TAT lop bao ve do —
        khong duoc de ro ri gia tri mac dinh cua game khac.
        """
        import protect
        protect.configure(
            style_ids=list(self.style_ids),
            entity_ids=list(self.entity_ids),
            glossary=list(self.glossary),
        )
