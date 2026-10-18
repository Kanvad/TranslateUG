"""Duong dan dung chung — NOI DUY NHAT biet du lieu local nam o dau.

`local/` gom moi thu chi thuoc ve may nay: ket qua build, ban sao game goc de doi
chieu, nhat ky do luong. Ca thu muc `local/` nam trong `.gitignore` nen KHONG duoc
day len GitHub — muon doi cho thi sua o day, khong sua rai rac trong tung script.

    ROOT    goc repo (chua README.md, src/, local/)
    LOCAL   thu muc du lieu local (khong publish)
    BUILD   dau ra cua pipeline: raw/, units.jsonl, translations_hymt2.jsonl, mod/...
    GAMES   game profile rieng cua may nay (local/games/<ten>.py)
"""
import os

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
LOCAL = os.path.join(ROOT, "local")
BUILD = os.path.join(LOCAL, "build")
GAMES = os.path.join(LOCAL, "games")


def notebook_path(profile) -> str:
    """Duong dan notebook Kaggle cua mot game profile (sinh ra trong local/).

    Notebook chua ten game + glossary nen khong duoc nam trong phan publish.
    Profile co the dat `notebook_name` de giu ten rieng; mac dinh theo ten profile.
    """
    name = profile.notebook_name or f"kaggle_{profile.name}_llamacpp.ipynb"
    return os.path.join(LOCAL, name)
