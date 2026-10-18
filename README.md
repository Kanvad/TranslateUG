# TranslateUG — dịch game Unity sang tiếng Việt

**TranslateUG** là bộ công cụ 4 bước để Việt hoá game Unity: trích TextAsset → dịch bằng model
`Hy-MT2-7B` chạy `llama.cpp` trên Kaggle → đo và sửa chất lượng → đóng gói, **ghi đè một locale có sẵn**
(kèm vá CRC Addressables và thay font TMP thiếu glyph).

Vì sao phải ghi đè: game Unity đóng gói sẵn thường **không cho thêm locale mới** từ ngoài
(enum `LanguageID` nằm trong `Assembly-CSharp.dll`) ⇒ người chơi chọn ngôn ngữ gốc (thường `en`) sẽ đọc bản dịch.

> **Dữ liệu riêng của game KHÔNG nằm trong phần publish.** Game profile (tên game, bundle, glossary,
> app id) đặt ở `local/games/<ten>.py`. Repo này là quy trình mẫu áp dụng cho game; `src/games/` chứa khuôn mẫu profile. Mọi script đọc profile
> qua `--game <ten>` — không truyền thì dùng profile duy nhất tìm thấy.

**Đọc thêm:** [HUONG-DAN.md](HUONG-DAN.md) — nguồn văn bản, bẫy khi chạy Kaggle, áp dụng cho game khác
· [SKILL.md](SKILL.md) — bản ngắn cho agent · [AGENTS.md](AGENTS.md) — luật bắt buộc khi sửa repo.

## Quy trình 4 bước

```
[local]  extract_units.py                    →  units.jsonl
[Kaggle] local/kaggle_<ten>_llamacpp.ipynb   →  translations_hymt2.jsonl (GGUF + llama.cpp, 2×T4)
[local]  inject.py                           →  local/build/mod/         (QA 5 lớp + repack + vá CRC + fix font)
[local]  apply.sh                            →  copy vào game
```

Model dịch: **`tencent/Hy-MT2-7B-GGUF`** (Q4_K_M) chạy bằng **`llama-server`** (llama.cpp), 2 server mỗi
GPU T4. Chi tiết: xem [HUONG-DAN.md](HUONG-DAN.md). **Không** `transformers`, **không** PyTorch.

```bash
export UV_CACHE_DIR=$PWD/.uv-cache TMPDIR=$PWD/.tmp
.venv/bin/python src/extract_units.py          # 1. trích xuất
.venv/bin/python src/make_kaggle_llamacpp.py   # 2. sinh notebook → chạy trên Kaggle
.venv/bin/python src/eval_translations.py      # 3. đo + sửa
.venv/bin/python src/inject.py                 # 4. QA cứng + đóng gói
bash local/build/mod/apply.sh                  #    nạp vào game
```

> Thêm `--game <ten>` cho mọi script nếu máy có nhiều game profile. Bẫy đã gặp (asset llama.cpp, cờ `-fa on`,
> cổng 8080, JSON schema, ghép lô…) và cách chỉnh tốc độ: xem [HUONG-DAN.md](HUONG-DAN.md).

## Kiểm thử

```bash
.venv/bin/python src/verify_formats.py
.venv/bin/python src/test_notebook_kaggle.py
.venv/bin/python src/inject.py --identity
.venv/bin/python src/inject.py
.venv/bin/python src/verify_catalog.py
```

`inject.py` là cổng QA cuối: không đạt thì **từ chối** chạy. Danh sách lỗi ghi ở
`local/build/qa_canh_bao.json`.

## Cấu trúc

- `src/` — toàn bộ đường ống (máy móc chung).
- `local/` — **không publish**: profile, đầu ra pipeline, số đo/runbook, bản sao vanilla.
- `src/paths.py` — nơi duy nhất biết dữ liệu local nằm ở đâu.

Chi tiết file và quy trình porting sang game khác: xem [HUONG-DAN.md](HUONG-DAN.md) và [SKILL.md](SKILL.md).

## Credits

Đường ống này đứng trên vai các dự án sau:

- [llama.cpp](https://github.com/ggml-org/llama.cpp) — `llama-server` chạy model GGUF với
  continuous batching trên Kaggle.
- [Tencent Hy-MT2-7B](https://huggingface.co/tencent/Hy-MT2-7B-GGUF) — model dịch được dùng trong
  notebook (định dạng GGUF).
- [UnityPy](https://github.com/K0lb3/UnityPy) — đọc/ghi bundle Unity (TextAsset, font TMP, repack).
- Kaggle — môi trường chạy GPU T4 ×2 cho bước dịch.
- [Source Han Sans](https://github.com/adobe-fonts/source-han-sans) — font chèn thay font TMP thiếu
  glyph tiếng Việt.

Tool/asset của từng game cụ thể nằm trong `local/` — kiểm tra `local/games/<ten>.py` để thấy nguồn
font và asset nào được dùng cho game đó.