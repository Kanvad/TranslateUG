#!/usr/bin/env python
r"""Sinh notebook Kaggle dich bang llama.cpp + GGUF (tencent/Hy-MT2-7B-GGUF).

Thay cho ban transformers: GGUF Q4_K_M + llama-server (continuous batching, C++/CUDA)
tren T4 nhanh hon nhieu. 2 server, moi T4 mot server.

Moi khoi CO() dung raw string de tranh loi escape (\n, \d, \1) tung lam hong notebook.
Trong CO() KHONG duoc co ba dau nhay kep lien nhau -> dung comment thay docstring.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Game profile chua style/entity/glossary + mo ta the loai. Notebook sinh ra van
# TU CHUA (khong import profile luc chay tren Kaggle) — gia tri duoc chen vao day.
from games import load_profile, game_arg  # noqa: E402
from paths import notebook_path          # noqa: E402

PROFILE = load_profile(game_arg())
GENRE = PROFILE.genre_desc
STYLE_PIPE = "|".join(PROFILE.style_ids)
NPC_SRC = "[" + ", ".join(json.dumps(n, ensure_ascii=False) for n in PROFILE.glossary) + "]"
TITLE = PROFILE.display_name

# Notebook la du lieu rieng cua tung game (chua ten game + glossary) nen sinh vao local/.
OUT = notebook_path(PROFILE)
CELLS = []


def MD(text):
    CELLS.append({"cell_type": "markdown", "metadata": {}, "source": text.strip().splitlines(True)})


def CO(code):
    CELLS.append({"cell_type": "code", "execution_count": None, "metadata": {},
                  "outputs": [], "source": code.strip().splitlines(True)})


MD((r"""
# Dịch @@TITLE@@ — `tencent/Hy-MT2-7B-GGUF` + `llama.cpp`

Model **7B lượng tử hoá Q4_K_M** (4,6 GB) chạy bằng **`llama-server`** — **không** `transformers`, **không** PyTorch.

| | |
|---|---|
| Kaggle | Internet **On**, Accelerator **GPU T4 ×2** |
| Input | dataset chứa `units.jsonl` (do `src/extract_units.py` sinh ra) |
| Output | `/kaggle/working/translations_hymt2.jsonl` |
| Chạy lại | Được — đơn vị đã dịch sẽ bỏ qua |

Runtime llama.cpp dùng **continuous batching** (`--parallel`) và chạy **2 server, mỗi T4 một server**
để dùng cả hai GPU.

Quy trình: QA 5 lớp, `masked`/`maps`/`prefix`, sentinel, ghép lô theo ngân sách
ký tự, sắp xếp theo độ dài, chia **bloc round-robin**, checkpoint/resume theo `uid`.

Sinh file này bằng `python src/make_kaggle_llamacpp.py`.
""").replace("@@TITLE@@", TITLE))

# ---------------------------------------------------------------- 1. Config
MD("## 1. Cấu hình")
CO(r"""
import glob, json, os, re, shutil, subprocess, time
from collections import Counter

# ---- Model: GGUF luong tu hoa, chay bang llama.cpp (KHONG dung transformers) ----
# tencent/Hy-MT2-7B-GGUF: kien truc "hunyuan-dense" (llama.cpp ho tro san),
# chat template NHUNG SAN trong file GGUF -> llama-server dung --jinja.
GGUF_REPO = "tencent/Hy-MT2-7B-GGUF"
GGUF_FILE = "Hy-MT2-7B-Q4_K_M.gguf"     # Q4_K_M (4,6 GB) | Q6_K | Q8_0 (nhe va nhanh hon)
GGUF_URL  = f"https://huggingface.co/{GGUF_REPO}/resolve/main/{GGUF_FILE}"

# --- tim units.jsonl trong dataset da gan ---
_c = (sorted(glob.glob("/kaggle/input/*/units.jsonl"))
      + sorted(glob.glob("/kaggle/input/*/*/units.jsonl"))
      + sorted(glob.glob("/kaggle/input/*/*/*/units.jsonl")))
if not _c:
    raise SystemExit("Khong thay units.jsonl trong /kaggle/input. Da gan dataset chua?")
UNITS_PATH = _c[0]

WORK       = "/kaggle/working"
GGUF_DIR   = f"{WORK}/gguf"
GGUF_PATH  = f"{GGUF_DIR}/{GGUF_FILE}"
LLAMA_ROOT = f"{WORK}/llama.cpp"
OUT_PATH    = f"{WORK}/translations_hymt2.jsonl"
REVIEW_PATH = f"{WORK}/review_hymt2.jsonl"

MODE = "all"             # "all" = dich toan bo | "failed" = chi sua don vi dang loi
BATCH = 8               # so don vi TOI DA trong 1 request (giam tu 12 de model de bao toan tag hon)
MAX_BATCH_CHARS = 3000   # gioi han TONG ky tu moi request (chong cat cut)
MAX_NEW_TOKENS = 2048    # tran token moi request

# ---- llama.cpp ----
# Chon asset theo TEN THAT (ten file doi theo tung ban build -> KHONG doan).
LLAMA_CUDA = "ubuntu-cuda-12.8-x64.tar.gz"
FORCE_COMPILE = False    # True = bien dich tu ma nguon bang CUDA toolkit cua Kaggle
N_WORKERS = 2            # 1 server / GPU (Kaggle cho 2 x T4) -> 2 GPU chay song song
BATCH_PER_WORKER = 32    # so request DONG THOI moi server == --parallel
PARALLEL = 32            # slot cua llama-server (continuous batching)
CTX = 65536             # 65536 / 32 = 2048 token moi slot: du cho prompt ~1250 + output 2048 (7B max context 8K)
BATCH_TOKENS = 4096      # -b
UBATCH_TOKENS = 1024     # -ub
PORT0 = 8080             # server 0 = 8080, server 1 = 8081
PORTS = [PORT0 + i for i in range(N_WORKERS)]
USE_SCHEMA = True        # rang buoc JSON schema -> llama-server bien dich thanh GBNF grammar

# ---- cua so truot (PIPELINE) ----
# True = giu deu BATCH_PER_WORKER request trong buffer: request nao xong thi nap ngay request ke.
# Thang A/B feeder 1,07-1,13x va chat hon chia lo. O 8 (chay that) dung co nay.
PIPELINE = True

print("model :", GGUF_REPO, "/", GGUF_FILE, "(GGUF + llama.cpp)")
print("units :", UNITS_PATH, f"({os.path.getsize(UNITS_PATH)/1e6:.1f} MB)")
print("out   :", OUT_PATH)
print(f"mode  : {MODE} | batch {BATCH} | max {MAX_BATCH_CHARS} ky tu | "
      f"{N_WORKERS} server x {BATCH_PER_WORKER} request | ctx {CTX} | parallel {PARALLEL}")
""")

# ---------------------------------------------------------------- 2. GPU
MD("## 2. Kiểm tra GPU + driver")
CO(r"""
import subprocess

_gpu = [l.strip() for l in subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                                          text=True).stdout.splitlines() if l.strip()]
for _i, _l in enumerate(_gpu):
    print(f"  {_l}")
N_GPU = len(_gpu)
_q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                     "--format=csv,noheader"], capture_output=True, text=True).stdout
print("name, memory.total, driver_version:")
print(_q.strip())
print("so GPU:", N_GPU)
print("  (driver CUDA 12.x tro len -> binary build san cua llama.cpp chay duoc)")
""")

# ---------------------------------------------------------------- 3. llama.cpp
MD("""
## 3. Tải `llama.cpp` (binary CUDA build sẵn, tự lùi sang biên dịch)

**Không đoán tên file.** Tên asset của llama.cpp không theo `tag` (ví dụ `llama-v0.7.0-…`) mà là
`llama-b11696-bin-ubuntu-cuda-12.8-x64.tar.gz`, và `/releases/latest` **bỏ qua** các bản `b…` vì chúng
là *prerelease*. Nên ô này **quét danh sách release và khớp theo tên asset thật**.

Nếu binary không chạy được (driver quá cũ), đặt `FORCE_COMPILE = True` ở ô 1: biên dịch bằng CUDA toolkit
có sẵn của Kaggle, **chỉ 1 target** và **chỉ kiến trúc SM 7.5** của T4.
""")
CO(r"""
import tarfile, urllib.request


def _gh(path):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "kaggle-hymt2"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def find_llama_assets(sub=LLAMA_CUDA):
    # Quet 40 ban gan nhat, khop theo ten asset THAT (khong doan).
    for rel in _gh("/repos/ggml-org/llama.cpp/releases?per_page=40"):
        main = rt = None
        for a in rel.get("assets", []):
            n = a["name"]
            if n.startswith("llama-") and sub in n:
                main = a["browser_download_url"]
            elif n.startswith("cudart-") and sub in n:
                rt = a["browser_download_url"]
        if main:
            return rel["tag_name"], main, rt
    return None, None, None


def _download(url, dst):
    print(f"  tai {os.path.basename(dst)} ...", flush=True)
    urllib.request.urlretrieve(url, dst)


def _extract(url, dest):
    tmp = f"{WORK}/_dl_" + os.path.basename(url)
    _download(url, tmp)
    with tarfile.open(tmp) as t:
        t.extractall(dest)
    os.remove(tmp)


os.makedirs(LLAMA_ROOT, exist_ok=True)
LLAMA_SERVER = LLAMA_BIN_DIR = None
CUDART_LIBS = []
TAG = None

if not FORCE_COMPILE:
    try:
        TAG, MAIN_URL, RT_URL = find_llama_assets()
        assert MAIN_URL, "khong thay asset llama-*-" + LLAMA_CUDA
        LLAMA_DIR = f"{LLAMA_ROOT}/{TAG}"
        # don sach: xoa moi ban llama-*/cudart-* khac + file .tar.gz cu (tran /kaggle/working)
        for _d in glob.glob(f"{LLAMA_ROOT}/*"):
            if not os.path.isdir(_d):
                os.remove(_d)
            elif os.path.basename(_d) != TAG:
                shutil.rmtree(_d, ignore_errors=True)
        if not glob.glob(f"{LLAMA_DIR}/**/llama-server", recursive=True):
            os.makedirs(LLAMA_DIR, exist_ok=True)
            _extract(MAIN_URL, LLAMA_DIR)
            if RT_URL:
                _extract(RT_URL, LLAMA_DIR)
        _srv = sorted(glob.glob(f"{LLAMA_DIR}/**/llama-server", recursive=True))
        assert _srv, "tarball khong chua llama-server"
        LLAMA_SERVER = _srv[0]
        LLAMA_BIN_DIR = os.path.dirname(LLAMA_SERVER)
        CUDART_LIBS = sorted(set(os.path.dirname(p)
                                 for p in glob.glob(f"{LLAMA_DIR}/**/libcudart.so*", recursive=True)))
        print(f"llama.cpp {TAG} -> {LLAMA_SERVER}")
        print("  cudart di kem:", CUDART_LIBS or "(khong co -> dung lib CUDA cua torch)")
    except Exception as _e:
        print("binary build san loi:", type(_e).__name__, _e, "-> chuyen sang BIEN DICH")
        FORCE_COMPILE = True

if FORCE_COMPILE:
    assert shutil.which("nvcc") or os.path.exists("/usr/local/cuda/bin/nvcc"), \
        "khong co CUDA toolkit de bien dich"
    SRC = f"{WORK}/llama.cpp-src"
    if not os.path.exists(SRC):
        subprocess.run(["git", "clone", "--depth", "1",
                        "https://github.com/ggml-org/llama.cpp.git", SRC], check=True)
    _env = dict(os.environ, PATH="/usr/local/cuda/bin:" + os.environ.get("PATH", ""))
    BUILD = f"{SRC}/build"
    # CHI 1 target (llama-server) + CHI 1 kien truc GPU (75 = T4/SM 7.5) -> nhanh hon nhieu lan
    subprocess.run(["cmake", "-B", BUILD, "-DGGML_CUDA=ON", "-DLLAMA_CURL=OFF",
                    "-DCMAKE_CUDA_ARCHITECTURES=75", "-DCMAKE_BUILD_TYPE=Release"],
                   cwd=SRC, check=True, env=_env)
    subprocess.run(["cmake", "--build", BUILD, "--target", "llama-server",
                    "-j", str(os.cpu_count() or 4)], cwd=SRC, check=True, env=_env)
    LLAMA_SERVER = f"{BUILD}/bin/llama-server"
    LLAMA_BIN_DIR = os.path.dirname(LLAMA_SERVER)
    CUDART_LIBS = []

print("LLAMA_SERVER =", LLAMA_SERVER)
""")

# ---------------------------------------------------------------- 4. GGUF
MD("## 4. Tải GGUF")
CO(r"""
import urllib.request

os.makedirs(GGUF_DIR, exist_ok=True)
# xoa moi .gguf khac -> khong tron model, khong tran /kaggle/working
for _g in glob.glob(f"{GGUF_DIR}/*.gguf"):
    if os.path.basename(_g) != GGUF_FILE:
        os.remove(_g)
        print("  xoa gguf cu:", os.path.basename(_g))

if not os.path.exists(GGUF_PATH) or os.path.getsize(GGUF_PATH) < 100e6:
    print("  tai GGUF ...", flush=True)
    urllib.request.urlretrieve(GGUF_URL, GGUF_PATH)
print("GGUF:", GGUF_PATH, f"{os.path.getsize(GGUF_PATH)/2**30:.2f} GiB")

# kiem tra header GGUF: dung kien truc + co chat template nhung san
with open(GGUF_PATH, "rb") as _f:
    _head = _f.read(65536)
print("  arch 'hunyuan-dense':", b"hunyuan-dense" in _head,
      "| chat template nhung san:", b"tokenizer.chat_template" in _head)
""")

# ---------------------------------------------------------------- 5. Server
MD("""
## 5. Khởi động `llama-server` (2 server, mỗi T4 một server)

Ba điểm đã trả giá để rút ra, đều nằm trong ô này:

1. **Kiểm tra cổng trước khi khởi động.** Server cũ còn giữ cổng 8080 thì server mới **không bind được**,
   nhưng `/health` vẫn trả 200 (của server cũ) → mọi phép đo sau đó do cấu hình cũ phục vụ.
2. **Cờ có giá trị rõ ràng.** Bản llama.cpp này `--flash-attn` và `-sm` nhận *giá trị tuỳ chọn*; viết
   `--flash-attn --no-webui` thì nó **nuốt `--no-webui` làm giá trị** → server thoát. Dùng `-fa on`.
3. **Xác minh GPU bằng `nvidia-smi`, không bằng log.** llama.cpp đổi định dạng log theo từng bản, và
   `--flash-attn` thiếu sẽ khiến nó **lặng lẽ lùi về CPU**. Hỏi thẳng driver xem PID nào đang chiếm VRAM.

Bốn bộ cờ lùi dần: `-fa on -sm none --no-webui` → `-fa on -sm none` → `-fa on --no-webui` → `-fa on` →
`--no-webui` → không cờ.
""")
CO(r"""
import socket, subprocess, time, urllib.error, urllib.request

N_WORKERS = max(1, min(N_WORKERS, N_GPU))
PORTS = PORTS[:N_WORKERS]
print(f"{N_WORKERS} server (moi T4 mot server) | cong {PORTS}")

# lib CUDA: uu tien lib di kem llama.cpp, roi den CUDA runtime cua torch (tranh tai 594 MB vo ich)
_torch_lib = ""
try:
    import torch
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
except Exception as _e:
    print("khong import duoc torch (khong sao):", type(_e).__name__)
LD_PATH = ":".join(p for p in ([LLAMA_BIN_DIR] + CUDART_LIBS + [_torch_lib]
                               + [os.environ.get("LD_LIBRARY_PATH", "")]) if p)
print("LD_LIBRARY_PATH =", LD_PATH)


def _port_free(p):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", p))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _kill():
    subprocess.run(["pkill", "-f", "llama-server"])
    time.sleep(2)


def _health(p, timeout=1.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# tat server cu + chan chac chan cong da trong (neu khong: server moi chet, /health tra 200 cua server cu)
_kill()
for _p in PORTS:
    for _ in range(20):
        if _port_free(_p):
            break
        _kill()
        time.sleep(1)
    if not _port_free(_p):
        raise RuntimeError(f"cong {_p} van bi chiem sau pkill -f llama-server")

FLAG_SETS = [
    ["-fa", "on", "-sm", "layer", "--no-webui"],
    ["-fa", "on", "-sm", "layer"],
    ["-fa", "on", "--no-webui"],
    ["-fa", "on"],
    ["--no-webui"],
    [],
]
SERVER_OK, USED_FLAGS, procs = False, None, []
for _ai, _flags in enumerate(FLAG_SETS, 1):
    _kill()
    print(f"--- thu bo co {_ai}/{len(FLAG_SETS)}: {' '.join(_flags) or '(khong co)'} ---", flush=True)
    procs = []
    for _w in range(N_WORKERS):
        _log = f"{WORK}/llama-server.gpu{_w}.attempt{_ai}.log"
        _env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(_w), LD_LIBRARY_PATH=LD_PATH)
        _cmd = [LLAMA_SERVER, "-m", GGUF_PATH, "-ngl", "99",
                "-c", str(CTX), "--parallel", str(PARALLEL),
                "-b", str(BATCH_TOKENS), "-ub", str(UBATCH_TOKENS),
                "--host", "127.0.0.1", "--port", str(PORTS[_w]), "--jinja"] + _flags
        _fh = open(_log, "w")
        procs.append((subprocess.Popen(_cmd, stdout=_fh, stderr=subprocess.STDOUT, env=_env), _fh, _log))
    _t0 = time.time()
    _ready = False
    while time.time() - _t0 < 900:
        if all(_health(p) for p in PORTS):
            _ready = True
            break
        if any(pr.poll() is not None for pr, _f, _l in procs):
            break
        time.sleep(3)
    _dt = time.time() - _t0
    if _ready and _dt < 2:
        print(f"  CANH BAO: /health tra loi trong {_dt:.1f}s (nghi server cu giu cong)")
    if _ready:
        SERVER_OK, USED_FLAGS = True, _flags
        print(f"  SAN SANG sau {_dt:.0f}s")
        break
    print(f"  that bai sau {_dt:.0f}s; 4 dong cuoi moi log:")
    for _pr, _f, _log in procs:
        _f.close()
        _tail = subprocess.run(["tail", "-n", "4", _log], capture_output=True, text=True).stdout.strip()
        print(f"   {_log}:\n     " + _tail.replace("\n", "\n     ")[-500:])

if not SERVER_OK:
    raise RuntimeError("khong khoi dong duoc llama-server voi bat ky bo co nao -> thu FORCE_COMPILE=True")
PROCS = [pr for pr, _f, _l in procs]
print("dung bo co:", USED_FLAGS or "(khong co)")

# xac minh GPU: hoi driver, KHONG doc log
time.sleep(5)
_nv = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                      "--format=csv"], capture_output=True, text=True).stdout
print("=== tien trinh dang dung VRAM ===")
print(_nv.strip())
_on_gpu = {int(l.split(",")[0]) for l in _nv.splitlines()[1:]
           if l.split(",")[0].strip().isdigit()}
for _p in PROCS:
    if _p.pid in _on_gpu:
        print(f"OK: llama-server (pid {_p.pid}) DANG dung GPU")
    else:
        print(f"!!! llama-server (pid {_p.pid}) KHONG dung GPU -> dat FORCE_COMPILE = True o o 1")
""")

# ---------------------------------------------------------------- 6. QA + prompt + sinh
MD("""
## 6. QA, bảo vệ placeholder, và hàm sinh (HTTP tới `llama-server`)

Năm lớp QA cứng: **token** (multiset), **tên riêng**, **tiền tố người nói**, **cắt cụt**, **tag rỗng**.

Hai hàm sửa sentinel: model hay biến `}` thành `>`/`<` (`{0}` → `{0>`) hoặc đánh số lại
(`{0}` ở chỗ đáng lẽ `{2}`).

`gen_many` gửi **nhiều request đồng thời** tới **một** server; `llama-server` gộp chúng bằng
**continuous batching** (`--parallel`). Kèm **JSON schema** (`minItems`/`maxItems` = đúng số phần tử) để
output không thể sai cấu trúc.
""")
CO((r"""
import threading
import urllib.error, urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

# ---- lop bao ve placeholder: CUNG logic voi src/protect.py ----
RE_SPRITE   = re.compile(r"<sprite[^<>\n]{0,60}>")
RE_BRACE    = re.compile(r"\{[^{}]{0,24}\}")
RE_ANGLE    = re.compile(r"<[^<>\n]{1,60}>")
RE_OPTION   = re.compile(r"\[option\s[^\[\]\n]{0,60}?/?\]")
_STYLES = "@@STYLES@@"
RE_STYLE    = re.compile(r"\[/?(?:" + _STYLES + r")(?:\s[^\[\]\n]{0,40})?/?\]")
RES = [RE_SPRITE, RE_BRACE, RE_ANGLE, RE_OPTION, RE_STYLE]
ALL_TOK   = re.compile("|".join(r.pattern for r in RES))
EMPTY_TAG = re.compile(
    r"\[(?:" + _STYLES + r")\]\s*\[/"
    r"|<color=#[0-9A-Fa-f]{6}>\s*</color>")

NPC = @@NPC@@
RE_GLOSS = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in NPC) + r")(?![\w-])")


def glossary_hits(t):
    return RE_GLOSS.findall(t)


def _toks(t):
    o = []
    for rx in RES:
        o += rx.findall(t)
    return o


def bare(t):
    return ALL_TOK.sub(" ", t)


def qa_check(u, vi):
    a, b = Counter(_toks(u["en"])), Counter(_toks(vi))
    miss, extra = list((a - b).elements()), list((b - a).elements())
    names = [n for n in glossary_hits(u["en"]) if n not in vi]
    pbad = bool(u["prefix"]) and not vi.startswith(u["prefix"])
    be, bv = bare(u["en"]), bare(vi)
    trunc = len(be) > 60 and len(bv) < 0.50 * len(be)
    etag = bool(EMPTY_TAG.search(vi))
    return dict(miss=miss, extra=extra, names=names, prefix_bad=pbad,
                trunc=trunc, empty_tag=etag,
                ok=not (miss or extra or names or pbad or trunc or etag))


def needs_work(u, vi):
    # True neu ban dich cu khong dung lai duoc.
    if not str(vi).strip():
        return True
    return not qa_check(u, str(vi))["ok"]


def restore(maps, text):
    if not maps:
        return text
    pat = re.compile("|".join(re.escape(s) for s, _ in sorted(maps, key=lambda kv: -len(kv[0]))))
    d = dict(maps)
    return pat.sub(lambda m: d[m.group(0)], text)


# Model thinh thoang bien dau `}` cua sentinel thanh `>` hoac `<`: {0} -> {0> , {2} -> {2<}
_SENT_FIX = [re.compile(r"\{(\d+)\s*[<>]\s*\}"), re.compile(r"\{(\d+)\s*[<>]")]


def fix_sentinels(t):
    for rx in _SENT_FIX:
        t = rx.sub(r"{\1}", t)
    return t


def renumber_sentinels(u, raw):
    # Model doi khi DANH SO LAI sentinel. Doi chieu theo VI TRI, chi khi so luong khop.
    sent = [s for s, _ in u["maps"]]
    if not sent:
        return raw
    spans = list(re.finditer(r"\{\d+\s*[<>]?\s*\}?", raw))
    if len(spans) != len(sent):
        return raw
    out, prev = [], 0
    for k, m in enumerate(spans):
        out.append(raw[prev:m.start()])
        out.append(sent[k])
        prev = m.end()
    out.append(raw[prev:])
    return "".join(out)


def looks_like_credit(en):
    # Ten rieng / credit / tieu de: giu nguyen tieng Anh moi la DUNG.
    QUOTES = chr(34) + chr(39)
    core = ALL_TOK.sub(" ", en).strip()
    if not core:
        return True
    words = [w for w in re.split(r"[\s,;:]+", core) if w]
    if not words:
        return True
    for w in words:
        w = w.strip(QUOTES)
        if not w or re.match(r"^[\W_]+$", w):
            continue
        if len(w) <= 2:
            continue
        if not re.match(r"^[A-Z0-9\u4e00-\u9fff\uac00-\ud7af]", w):
            return False
    return True


def make_batches(items, max_count=BATCH, max_chars=MAX_BATCH_CHARS, sort_by_len=True):
    # Ghep theo CA so luong va tong ky tu: 12 don vi dai co the vuot ngan sach token.
    # SAP XEP THEO DO DAI truoc khi ghep: generate phai cho den khi ca lo xong, nen lo
    # tron don vi 40 ky tu voi don vi 2.336 ky tu se lang phi nang luc.
    if sort_by_len:
        items = sorted(items, key=lambda u: len(u["masked"]))
    out, cur, chars = [], [], 0
    for u in items:
        L = len(u["masked"])
        if cur and (len(cur) >= max_count or chars + L > max_chars):
            out.append(cur); cur, chars = [], 0
        cur.append(u); chars += L
    if cur:
        out.append(cur)
    return out


def split_blocks(items, n, block=None):
    # Chia theo BLOC ROUND-ROBIN. Hai muc tieu CUNG LUC:
    #   1. TRONG mot bloc: cac batch LIEN TIEP trong danh sach da sap xep => do dai dong nhat.
    #   2. GIUA cac bloc: chia luan phien => tai can bang.
    # Da thu va do duoc: `items[w::n]` can bang 1,00x NHUNG lang phi 32,6%; chia LIEN TIEP
    # thuan lang phi 24,7% NHUNG lech tai 8,93x => ca tien trinh bi worker cham nhat keo.
    if block is None:
        block = BATCH_PER_WORKER
    out = [[] for _ in range(n)]
    for k, i in enumerate(range(0, len(items), block)):
        out[k % n].extend(items[i:i + block])
    return out


def glossary_block(text):
    hits = sorted(set(glossary_hits(text)))
    if not hits:
        return ""
    return ("### Proper nouns that MUST stay in Latin script exactly as written\n"
            + ", ".join(hits) + "\n\n")


RULES = (
    "### Task\n"
    "Translate user-facing English text from @@GENRE@@ "
    "into natural Vietnamese. The input is a JSON array of strings.\n\n"
    "### Rules\n"
    "1. Return only a valid JSON array of strings. Do not include markdown, explanations, or notes.\n"
    "2. Preserve the input array's length and element order exactly.\n"
    "3. Preserve every placeholder exactly as written, including its position and formatting, "
    "such as {0}, {1}, {2}, {0:F0}, and {0:F1}.\n"
    "4. Keep all proper nouns from the list above unchanged and in Latin script. "
    "Do not translate or transliterate them.\n"
    "5. Keep all bracketed style tags unchanged: [info], [noun], [pos], [warn], [act], [smug], "
    "[/info], [/noun], [/pos], [/warn], [/act], [/smug], and similar. "
    "Do not translate, remove, or move them.\n"
    "6. Translate all other user-facing text into fluent, concise Vietnamese suitable for game UI.\n"
    "7. Leave standalone proper nouns, brands, studio credits, model codes, and numbers unchanged.\n"
    "8. Preserve JSON string escaping where needed; do not add or remove array elements.\n\n"
)


def build_prompt(masked_list):
    return (glossary_block(" ".join(masked_list))
            + RULES
            + "### Source Data\n" + json.dumps(masked_list, ensure_ascii=False)
            + "\n\n### Output\n")


def _chat_url(worker):
    return f"http://127.0.0.1:{PORTS[worker]}"


def _n_items(prompt):
    m = re.search(r"### Source Data\n(\[.*\])\n\n### Output", prompt, re.S)
    if not m:
        return None
    try:
        return len(json.loads(m.group(1)))
    except Exception:
        return None


_SCHEMA = [bool(USE_SCHEMA)]


def _post(worker, prompt, n, max_new_tokens):
    # JSON schema -> llama-server bien dich thanh GBNF grammar: output KHONG THE sai cau truc.
    # minItems/maxItems chan model tra thieu/thua phan tu.
    body = {"messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens, "temperature": 0.0, "stream": False}
    if _SCHEMA[0] and n:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "translations", "strict": True,
                            "schema": {"type": "array", "minItems": n, "maxItems": n,
                                       "items": {"type": "string"}}}}
    req = urllib.request.Request(_chat_url(worker) + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if _SCHEMA[0]:
            _SCHEMA[0] = False
            print("  server khong nhan response_format -> tat schema, chay tiep")
            return _post(worker, prompt, None, max_new_tokens)
        raise
    ch = j["choices"][0]
    u = j.get("usage") or {}
    tm = j.get("timings") or {}
    # DEM CA prompt_tokens VA thoi gian GPU that cua tung pha:
    #   prompt_n / prompt_ms  = prefill      predicted_n / predicted_ms = decode
    # Ban build nay KHONG tra usage.prompt_tokens (da kiem chung: token VAO/s = 0), nhung tra timings
    # o cap cao nhat => lay tu ca hai nguon. Tong thoi gian GPU / thoi gian wall = muc song song TB.
    return (ch["message"]["content"], ch.get("finish_reason"),
            int(u.get("completion_tokens") or tm.get("predicted_n") or 0),
            int(u.get("prompt_tokens") or tm.get("prompt_n") or 0),
            float(u.get("prompt_ms") or tm.get("prompt_ms") or 0.0),
            float(u.get("completion_ms") or tm.get("predicted_ms") or 0.0))


def gen_many(worker, prompts, max_new_tokens=MAX_NEW_TOKENS):
    # Gui NHIEU request DONG THOI toi MOT server. llama-server chay continuous batching
    # (--parallel): day la cach lam day GPU that su, khong phai nhieu luong cung goi generate.
    ns = [_n_items(p) for p in prompts]
    with ThreadPoolExecutor(max_workers=max(1, len(prompts))) as ex:
        out = list(ex.map(lambda kp: _post(worker, kp[1], ns[kp[0]], max_new_tokens),
                          list(enumerate(prompts))))
    # Co KHOA: cua so truot goi gen_many tu RAT nhieu luong cung luc; '+=' tren dict khong nguyen tu
    # nen thieu khoa la mat so lieu -> chinh phep do do phu slot o o 7 se sai.
    with _STATS_LOCK:
        STATS["gen_tok"] += sum(o[2] for o in out)
        STATS["prompt_tok"] += sum(o[3] for o in out)
        STATS["prompt_ms"] += sum(o[4] for o in out)
        STATS["gen_ms"] += sum(o[5] for o in out)
        # finish_reason == "length" nghia la bi cat vi tran token -> phai biet, khong duoc doan
        STATS["cap_hit"] += sum(1 for o in out if o[1] == "length")
    return [o[0] for o in out]


def _parse_json_array(txt, n):
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip()).strip()
    try:
        v = json.loads(s)
    except Exception:
        m = re.search(r"\[.*\]", s, re.S)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
        except Exception:
            return None
    if isinstance(v, list) and len(v) == n and all(isinstance(x, str) for x in v):
        return v
    return None


STATS = dict(batches=0, fallback=0, gen_tok=0, gen_pad=0, cap_hit=0, prompt_tok=0,
             prompt_ms=0.0, gen_ms=0.0)
_STATS_LOCK = threading.Lock()


def translate_group(worker, group):
    # group: list cac lo. Tra ve list ket qua cung do dai. JSON hong -> sinh lai TUNG don vi
    # nhung van theo lo (1 lan goi cho ca nhom).
    prompts = [build_prompt([u["masked"] for u in b]) for b in group]
    raws = gen_many(worker, prompts)
    with _STATS_LOCK:
        STATS["batches"] += len(group)
    results = [None] * len(group)
    retry, retry_pos = [], []
    for k, (b, raw) in enumerate(zip(group, raws)):
        got = _parse_json_array(raw, len(b))
        if got is not None:
            results[k] = got
        else:
            for j, u in enumerate(b):
                retry.append(u); retry_pos.append((k, j))
    if retry:
        with _STATS_LOCK:
            STATS["fallback"] += 1
        raws2 = gen_many(worker, [build_prompt([u["masked"]]) for u in retry])
        for (k, j), raw in zip(retry_pos, raws2):
            if results[k] is None:
                results[k] = [""] * len(group[k])
            g = _parse_json_array(raw, 1)
            results[k][j] = g[0] if g else ""
    return results


def best_translation(u, raw, retries=2):
    # Thu ban thuong; neu QA truot thi thu doi chieu vi tri. Chi nhan neu QA dat.
    # Neu ca hai deu truot, RETRY chuoi don (khong batch) toi da `retries` lan —
    # batching khac nhau co the cho ket qua khac (temperature=0 nhung composition khac).
    _raw = fix_sentinels((raw or "").strip())
    vi = u["prefix"] + restore(u["maps"], _raw)
    c = qa_check(u, vi)
    if not c["ok"]:
        _vi2 = u["prefix"] + restore(u["maps"], renumber_sentinels(u, _raw))
        _c2 = qa_check(u, _vi2)
        if _c2["ok"]:
            return _vi2, _c2
    # Both failed -> retry single unit (no batching) up to `retries` times.
    if not c["ok"]:
        for _ in range(retries):
            try:
                _raws = gen_many(0, [build_prompt([u["masked"]])])
                _r = fix_sentinels((_raws[0] or "").strip())
                _v = u["prefix"] + restore(u["maps"], _r)
                _cc = qa_check(u, _v)
                if _cc["ok"]:
                    return _v, _cc
                # try renumber on retry result
                _v2 = u["prefix"] + restore(u["maps"], renumber_sentinels(u, _r))
                _cc2 = qa_check(u, _v2)
                if _cc2["ok"]:
                    return _v2, _cc2
            except Exception:
                pass
    return vi, c


print("san sang:", len(RES), "lop token |", N_WORKERS, "server")
""").replace("@@STYLES@@", STYLE_PIPE).replace("@@NPC@@", NPC_SRC).replace("@@GENRE@@", GENRE))



# ---------------------------------------------------------------- 8. Chay that
MD("""
## 7. Chạy dịch

Chạy lại được nhiều lần. Kết quả ghi dần; đơn vị đã xong sẽ bỏ qua.
""")
CO(r"""
units = [json.loads(l) for l in open(UNITS_PATH, encoding="utf-8") if l.strip()]

if MODE == "failed":
    prev = {}
    for l in open(OUT_PATH, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); prev[r["uid"]] = r
    reuse, work = {}, []
    for u in units:
        r = prev.get(u["uid"])
        if u["skip"]:
            reuse[u["uid"]] = dict(uid=u["uid"], vi=u["en"], qa_ok=True, note="skipped")
        elif r is not None and "error" not in r and not needs_work(u, str(r["vi"])):
            reuse[u["uid"]] = dict(uid=u["uid"], vi=str(r["vi"]), qa_ok=True, note="reused_ok")
        else:
            work.append(u)
else:
    reuse = {u["uid"]: dict(uid=u["uid"], vi=u["en"], qa_ok=True, note="skipped")
             for u in units if u["skip"]}
    work = [u for u in units if not u["skip"]]

done = {}
if os.path.exists(OUT_PATH):
    for l in open(OUT_PATH, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); done[r["uid"]] = r
    # CHI loc "da co trong file" khi MODE=all.
    # MODE=failed da loc theo CHAT LUONG ban dich cu (needs_work/qa_check) va theo cot
    # "error" (don vi hong khi goi server, vi=en luon lot qua qa_check); neu loc them
    # lan nua thi khong bao gio sua duoc gi — vi lan chay truoc ghi ra DU 14.681 uid,
    # nen work se thanh rong.
    if MODE != "failed":
        work = [u for u in work if u["uid"] not in done]

print(f"Tong {len(units):,} | dung lai {len(reuse):,} | da xong {len(done):,} | CON DICH {len(work):,}")

batches = make_batches(work)
if batches:
    _lens = [sum(len(u["masked"]) for u in b) for b in batches]
    print(f"ghep lo: {len(batches):,} request | TB {sum(_lens)/len(_lens):.0f} ky tu | "
          f"max {max(_lens)} ky tu | toi da {BATCH} don vi")
else:
    print("Khong con don vi nao can dich (da xong het tu lan chay truoc).")

lock = threading.Lock()
fh = open(OUT_PATH, "a", encoding="utf-8")
frev = open(REVIEW_PATH, "a", encoding="utf-8")
stat = dict(ok=0, bad=0, err=0, n=0, chars=0)
_total_chars = sum(len(u["masked"]) for u in work)
t0 = time.time()
# Nhip in theo THOI GIAN: `MODE="failed"` co the chi con vai chuc dv (< moc 200) —
# khong co nhap thu thi cell in im long hang chu phut mau dau phai la "treo".
_PRINT_EVERY_S = 60.0
_last_print = [time.time()]
STATS = dict(batches=0, fallback=0, gen_tok=0, gen_pad=0, cap_hit=0, prompt_tok=0,
             prompt_ms=0.0, gen_ms=0.0)


def handle(chunk, outs):
    # Ghi ket qua 1 lo. Luon goi trong lock.
    for u, raw in zip(chunk, outs):
        try:
            vi, c = best_translation(u, raw)
        except Exception as e:
            vi, c = u["en"], dict(ok=False, err=f"{type(e).__name__}: {e}")
        rec = dict(uid=u["uid"], vi=vi, qa_ok=c["ok"], note="llamacpp")
        if vi.strip() == u["en"].strip():
            rec["still_en"] = True
        if c["ok"]:
            stat["ok"] += 1
        else:
            stat["bad"] += 1
            rec["problems"] = c
            frev.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done[u["uid"]] = rec
    stat["n"] += len(chunk)
    stat["chars"] += sum(len(u["masked"]) for u in chunk)


def progress():
    fh.flush()
    _last_print[0] = time.time()
    el = max(time.time() - t0, 1e-9)
    cps = stat["chars"] / el
    left = max(_total_chars - stat["chars"], 0)
    # 'don vi/s' KHONG cong bang: do dai don vi dao dong 40-2215 ky tu.
    # Chi so dang doc la ky tu/s, token RA/s va token VAO/s; ETA tinh theo KY TU CON LAI.
    print(f"  {stat['n']:,}/{len(work):,} dv | ok {stat['ok']:,} | loi {stat['bad']:,} "
          f"| fb {STATS['fallback']}/{STATS['batches']} "
          f"| {stat['n']/el:.1f} dv/s | {cps:.0f} ky tu/s "
          f"| {STATS['gen_tok']/el:.0f} tok ra/s + {STATS['prompt_tok']/el:.0f} tok vao/s "
          f"| con ~{left/max(cps,1)/60:.0f} phut (theo ky tu)", flush=True)


def worker_run(w, my_batches):
    # CUA SO TRUOT (PIPELINE): moi luong giu MOT request trong buffer do; request nao xong thi luong
    # do lay ngay batch ke tiep. Cach cu (chia lo roi cho ca lo xong) lam GPU tut ve 0 request o dau
    # moi lo va roi dan o cuoi lo: do duoc bang cot "chuoi sinh song song TB" (o 7).
    if not PIPELINE:
        for k in range(0, len(my_batches), BATCH_PER_WORKER):
            grp = my_batches[k:k + BATCH_PER_WORKER]
            try:
                outs_list = translate_group(w, grp)
            except Exception as e:
                with lock:
                    for b in grp:
                        _write_err(b, e)
                continue
            with lock:
                before = stat["n"]
                for b, outs in zip(grp, outs_list):
                    handle(b, outs)
                if stat["n"] // 200 != before // 200 or stat["n"] == len(work) \
                        or time.time() - _last_print[0] >= _PRINT_EVERY_S:
                    progress()
        return

    q = list(my_batches)
    cur = [0]
    qlock = threading.Lock()

    def one_thread():
        while True:
            with qlock:
                if cur[0] >= len(q):
                    return
                b = q[cur[0]]
                cur[0] += 1
            try:
                outs = translate_group(w, [b])
            except Exception as e:
                with lock:
                    _write_err(b, e)
                continue
            with lock:
                before = stat["n"]
                handle(b, outs[0])
                if stat["n"] // 200 != before // 200 or stat["n"] == len(work) \
                        or time.time() - _last_print[0] >= _PRINT_EVERY_S:
                    progress()

    ths = [threading.Thread(target=one_thread, daemon=True)
           for _ in range(max(1, min(BATCH_PER_WORKER, len(my_batches))))]
    for t in ths:
        t.start()
    for t in ths:
        t.join()


def _write_err(b, e):
    # Ghi nhan 1 lo hong khi goi model that bai. Luon goi trong lock.
    for u in b:
        stat["err"] += 1
        rec = dict(uid=u["uid"], vi=u["en"], qa_ok=False,
                   note="error", error=f"{type(e).__name__}: {e}")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done[u["uid"]] = rec
    stat["n"] += len(b)


if batches:
    # chia deu cho cac server; moi server chi goi MODEL cua no => khong tranh chap
    shards = split_blocks(batches, N_WORKERS)
    ths = [threading.Thread(target=worker_run, args=(w, shards[w]), daemon=True)
           for w in range(N_WORKERS) if shards[w]]
    for t in ths:
        t.start()
    for t in ths:
        t.join()

fh.flush(); fh.close(); frev.close()

# Ghi lai TOAN BO theo thu tu uid: don vi thieu duoc danh dau de thay, khong im lang bo qua
final = {}
for u in units:
    final[u["uid"]] = done.get(u["uid"]) or reuse.get(u["uid"]) or \
        dict(uid=u["uid"], vi=u["en"], qa_ok=False, note="missing_keep_en")
with open(OUT_PATH, "w", encoding="utf-8") as f:
    for u in units:
        f.write(json.dumps(final[u["uid"]], ensure_ascii=False) + "\n")
_el = max(time.time() - t0, 1e-9)
print(f"\nDa ghi {OUT_PATH} ({len(final):,} don vi)")
print(f"  {stat['n']:,} dv | {stat['chars']:,} ky tu | {stat['chars']/_el:.0f} ky tu/s "
      f"| {STATS['gen_tok']:,} token RA + {STATS['prompt_tok']:,} token VAO "
      f"trong {_el/60:.1f} phut")
if STATS["prompt_ms"] or STATS["gen_ms"]:
    print(f"  prefill {STATS['prompt_tok']/max(STATS['prompt_ms'],1e-9)*1e3:.0f} tok/s "
          f"({STATS['prompt_ms']/1e3:.0f}s GPU) | "
          f"decode {STATS['gen_tok']/max(STATS['gen_ms'],1e-9)*1e3:.0f} tok/s "
          f"({STATS['gen_ms']/1e3:.0f}s GPU) | "
          f"chay song song TB {(STATS['prompt_ms']+STATS['gen_ms'])/1e3/_el:.1f}x")
""")

# ---------------------------------------------------------------- 9. Bao cao
MD("## 8. Báo cáo")
CO(r"""
recs = [json.loads(l) for l in open(OUT_PATH, encoding="utf-8") if l.strip()]
notes = Counter(r.get("note") for r in recs)
bad = [r for r in recs if not r.get("qa_ok")]
byu = {u["uid"]: u for u in units}
print(f"Tong: {len(recs):,}")
for k, v in notes.most_common():
    print(f"  {str(k):16s} {v:>7,}")
print()
print(f"CON LOI (QA)  : {len(bad):,} ({100*len(bad)/max(len(recs),1):.2f}%)")
for k in ("miss", "extra", "names", "prefix_bad", "trunc", "empty_tag"):
    n = sum(1 for r in bad if r.get("problems", {}).get(k))
    if n:
        print(f"  {k:12s} {n:>6,}")

# "Van tieng Anh" KHONG dong nghia voi "loi": phan lon la CREDIT / TEN RIENG / TIEU DE.
# Model giu nguyen la DUNG.
still = [r for r in recs if r.get("still_en")]
credits = [r for r in still if looks_like_credit(byu[r["uid"]]["en"])]
need_tr = [r for r in still if not looks_like_credit(byu[r["uid"]]["en"])]
print()
print(f"Van tieng Anh : {len(still):,}")
print(f"  - {len(credits):,} la CREDIT / TEN RIENG / TIEU DE  (giu tieng Anh la DUNG)")
print(f"  - {len(need_tr):,} can XEM QUA (co the van la credit, vd username viet thuong)")
for r in need_tr[:8]:
    print("      " + repr(byu[r["uid"]]["en"][:80]))

print()
print("=== 10 vi du ===")
n = 0
for r in recs:
    u = byu[r["uid"]]
    if u["skip"] or n >= 10:
        continue
    n += 1
    print(f"  EN: {u['en'][:92]}")
    print(f"  VI: {r['vi'][:92]}   {'' if r.get('qa_ok') else '<-- CAN SUA'}")
""")

MD("""
## 9. Tải kết quả về

Tải `/kaggle/working/translations_hymt2.jsonl` (và `review_hymt2.jsonl` nếu còn lỗi), đặt vào
`local/<ten>/build/` của repo rồi chạy `python src/eval_translations.py`.
""")

nb = {"cells": CELLS,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11"}},
      "nbformat": 4, "nbformat_minor": 5}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

# kiem tra compile moi cell (bo qua dong magic !)
for i, c in enumerate(CELLS):
    if c["cell_type"] != "code":
        continue
    src = "\n".join("pass" if l.lstrip().startswith("!") else l
                    for l in "".join(c["source"]).split("\n"))
    compile(src, f"cell{i}", "exec")

# khong duoc de ba dau nhay kep lien nhau trong bat ky cell code nao
for i, c in enumerate(CELLS):
    if c["cell_type"] == "code" and '"""' in "".join(c["source"]):
        raise SystemExit(f"cell {i} chua ba dau nhay kep -> se pha chuoi raw cua generator")

print(f"da ghi {os.path.basename(OUT)} {os.path.getsize(OUT)} bytes, {len(CELLS)} cells — compile OK")




