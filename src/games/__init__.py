"""Nap game profile theo ten.

Profile cua game dang dich la **du lieu rieng** (ten game, bundle, glossary, app id...) nen
KHONG nam trong `src/`. Moi game co mot thu muc du lieu rieng:

    local/<ten>/         game.py (profile), build/, kaggle_*.ipynb, SKILL.md, aa_backup_*/...

kieu cu `local/games/<ten>.py` van duoc tim cho tuong thich. `src/games/` chi chua khuon mau
trung tinh. Xem SKILL.md.

    from games import load_profile, game_arg
    P = load_profile(game_arg())     # game_arg doc --game tren argv
    P.apply()                        # nap style/entity/glossary vao protect.py
"""
from __future__ import annotations

import importlib.util
import os
import sys

from .profile import Asset, GameProfile
import paths as _paths

_SRC_GAMES = os.path.dirname(os.path.abspath(__file__))

# Thu tu tim: local/<ten>/game.py (cau truc moi, moi game mot thu muc) truoc,
# local/games/<ten>.py (cau truc cu — tuong thich), khuon mau trong src/ sau.
SEARCH_DIRS = ("local/<ten>/", _paths.GAMES, _SRC_GAMES)

# Module phu tro cua chinh package nay, khong phai game profile.
_HELPERS = ("profile",)


def available() -> list:
    """Ten cac profile tim thay (khong trung lap, giu thu tu tim)."""
    out = []
    if os.path.isdir(_paths.LOCAL):
        for d in sorted(os.listdir(_paths.LOCAL)):
            if d in ("games",):
                continue
            if os.path.isfile(os.path.join(_paths.LOCAL, d, "game.py")):
                if d not in out:
                    out.append(d)
    if os.path.isdir(_paths.GAMES):
        for f in sorted(os.listdir(_paths.GAMES)):
            if f.endswith(".py") and not f.startswith("_"):
                name = f[:-3]
                if name not in out and name not in _HELPERS:
                    out.append(name)
    if os.path.isdir(_SRC_GAMES):
        for f in sorted(os.listdir(_SRC_GAMES)):
            if f.endswith(".py") and not f.startswith("_"):
                name = f[:-3]
                if name not in out and name not in _HELPERS:
                    out.append(name)
    return out


def _find(name: str):
    p = os.path.join(_paths.LOCAL, name, "game.py")
    if os.path.isfile(p):
        return p
    for d in (_paths.GAMES, _SRC_GAMES):
        p = os.path.join(d, f"{name}.py")
        if os.path.isfile(p):
            return p
    return None


def load_profile(name: str | None = None) -> GameProfile:
    """Nap profile cua game `name` va doi BUILD sang `local/<name>/build`.

    Mac dinh tim kiem:
      1. local/<ten>/game.py     (cau truc moi — khuyen dung, moi game mot thu muc)
      2. local/games/<ten>.py    (cau truc CU — tuong thich)
      3. src/games/<ten>.py      (khuon mau trung tinh)
    Khong truyen `name`: dung luon profile duy nhat tim thay; nhieu profile thi phai
    chon bang `--game <ten>`.
    """
    if name is None:
        names = available()
        if len(names) == 1:
            name = names[0]
        elif not names:
            raise SystemExit(
                "Chua co game profile nao.\n"
                "  -> Tao local/<ten>/game.py (khung mau: xem SKILL.md)")
        else:
            raise SystemExit(
                f"Co nhieu game profile: {', '.join(names)}\n"
                "  -> Chon bang --game <ten>")
    path = _find(name)
    if path is None:
        raise SystemExit(
            f"Khong thay game profile '{name}' (tim local/{name}/game.py, "
            f"{_paths.GAMES}/{name}.py, {_SRC_GAMES}/{name}.py).\n"
            f"  -> Tao local/{name}/game.py (khung mau: xem SKILL.md)")
    _paths.set_game(name)
    spec = importlib.util.spec_from_file_location(f"{__name__}.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.build()


def game_arg(default: str | None = None, argv=None) -> str | None:
    """Doc `--game <ten>` tren argv (de nap profile TRUOC khi import protect)."""
    argv = sys.argv if argv is None else argv
    if "--game" in argv:
        i = argv.index("--game")
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


__all__ = ["Asset", "GameProfile", "load_profile", "game_arg", "available", "SEARCH_DIRS"]
