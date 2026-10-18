"""Nap game profile theo ten.

Profile cua game dang dich la **du lieu rieng** (ten game, bundle, glossary, app id...) nen
KHONG nam trong `src/`: dat `local/games/<ten>.py` (khong day len GitHub). `src/games/` chi
chua khuon mau trung tinh. Xem SKILL.md.

    from games import load_profile, game_arg
    P = load_profile(game_arg())     # game_arg doc --game tren argv
    P.apply()                        # nap style/entity/glossary vao protect.py
"""
from __future__ import annotations

import importlib.util
import os
import sys

from .profile import Asset, GameProfile

_SRC_GAMES = os.path.dirname(os.path.abspath(__file__))
_LOCAL_GAMES = os.path.join(os.path.dirname(os.path.dirname(_SRC_GAMES)), "local", "games")

# Thu tu tim: du lieu rieng truoc, khuon mau trong src/ sau.
SEARCH_DIRS = (_LOCAL_GAMES, _SRC_GAMES)

# Module phu tro cua chinh package nay, khong phai game profile.
_HELPERS = ("profile",)


def available() -> list:
    """Ten cac profile tim thay (khong trung lap, giu thu tu SEARCH_DIRS)."""
    out = []
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".py") and not f.startswith("_"):
                    name = f[:-3]
                    if name not in out and name not in _HELPERS:
                        out.append(name)
    return out


def _find(name: str):
    for d in SEARCH_DIRS:
        p = os.path.join(d, f"{name}.py")
        if os.path.isfile(p):
            return p
    return None


def load_profile(name: str | None = None) -> GameProfile:
    """Nap `local/games/<ten>.py` (hoac `src/games/<ten>.py`) va goi `build()`.

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
                "  -> Tao local/games/<ten>.py (khung mau: xem SKILL.md)")
        else:
            raise SystemExit(
                f"Co nhieu game profile: {', '.join(names)}\n"
                "  -> Chon bang --game <ten>")
    path = _find(name)
    if path is None:
        raise SystemExit(
            f"Khong thay game profile '{name}' trong {_LOCAL_GAMES} hay {_SRC_GAMES}.\n"
            f"  -> Tao local/games/{name}.py (khung mau: xem SKILL.md)")
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
