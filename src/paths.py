"""Duong dan dung chung — NOI DUY NHAT biet du lieu local nam o dau.

Cau truc `local/` chia THEO GAME de khong lam quen khi co game thu hai:

    local/<ten>/              toan bo du lieu cua game '<ten>'
      game.py                profile (data rieng, KHONG day len GitHub)
      build/                 dau ra pipeline: raw/, units.jsonl, translations_*.jsonl,
                             mod/, eval/, extract_report.json, qa_canh_bao.json...
      kaggle_*.ipynb         notebook Kaggle doi cho (chua ten game + glossary)
      SKILL.md, prompt_*.md  so do + runbook + nhat ky do luong
      aa_backup_*/           ban sao vanilla cua cac bundle de doi chieu

Ca thu muc `local/` nam trong `.gitignore` nen KHONG duoc day len GitHub. Scripts doc
`paths.BUILD` (attribute, late-binding) nen `paths.set_game()` do load_profile() goi
luc chay cap nhat GAME_ROOT/BUILD dung cho game da chon — khong dung thu tu import.

    ROOT        goc repo (chua README.md, src/, local/)
    LOCAL       vi tri du lieu khong publish
    GAME        ten game hien tai (dat boi set_game)
    GAME_ROOT   local/<GAME>
    BUILD       local/<GAME>/build
"""
import os

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
LOCAL = os.path.join(ROOT, "local")

GAME = None                                  # dat boi set_game()
GAME_ROOT = LOCAL                            # fallback: cau truc cu local/... (build/)
BUILD = os.path.join(LOCAL, "build")
GAMES = os.path.join(LOCAL, "games")         # vi tri CU (legacy) cua profile: local/games/


def set_game(name: str):
    """Dat game hien tai -> GAME_ROOT = local/<name>, BUILD = local/<name>/build."""
    global GAME, GAME_ROOT, BUILD
    GAME = name
    GAME_ROOT = os.path.join(LOCAL, name)
    BUILD = os.path.join(GAME_ROOT, "build")


def notebook_path(profile) -> str:
    """Duong dan notebook Kaggle cua mot game profile (local/<ten>/ kaggle_*.ipynb).

    Notebook chua ten game + glossary nen khong duoc nam trong phan publish.
    Profile co the dat `notebook_name` de giu ten rieng; mac dinh theo ten profile.
    """
    name = profile.notebook_name or f"kaggle_{profile.name}_llamacpp.ipynb"
    return os.path.join(GAME_ROOT if GAME else LOCAL, name)
