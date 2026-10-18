# AGENTS.md

**TranslateUG** — bộ công cụ dịch game Unity bằng cách **ghi đè một locale có sẵn**. Đường ống 4 bước;
`src/inject.py` là **cổng QA** ở cuối và từ chối chạy khi bản dịch chưa đạt.

Hai quy tắc về chỗ để dữ liệu:

- **Máy móc chung** → `src/` và phần publish (`README.md`, `HUONG-DAN.md`, `AGENTS.md`, `SKILL.md`).
- **Dữ liệu riêng của game** → `local/`, thứ **không** được đẩy lên GitHub: `local/games/<ten>.py`
  (profile), `local/build/` (đầu ra pipeline), `local/SKILL.md` (số đo + runbook), nhật ký, bản sao game
  vanilla. Không đưa tên game / tên bundle / glossary / app id vào phần publish.

`src/paths.py` sở hữu mọi đường dẫn local — đừng ghép tay trong script.

## Chạy đường ống

**1. Trích xuất** — `.venv/bin/python src/extract_units.py`

Xong khi `local/build/extract_report.json` có `byte_exact` = `true` cho **mọi** asset cần dịch.

**2. Dịch** — mở `local/kaggle_<ten>_llamacpp.ipynb` trên Kaggle (Internet On, Accelerator GPU T4 ×2),
chạy hết. Model là `tencent/Hy-MT2-7B-GGUF` (`Hy-MT2-7B-Q4_K_M.gguf`) chạy bằng **`llama-server`**
(continuous batching) — **không** `transformers`, **không** PyTorch. Hai server, mỗi T4 một server.
Notebook do `src/make_kaggle_llamacpp.py` sinh ra — **không sửa tay** file `.ipynb`.

Xong khi tải `translations_hymt2.jsonl` về `local/build/translations_hymt2.jsonl` (giữ nguyên tên; các
script tự tìm file), và ô báo cáo in `CON LOI (QA)  : 0`.

**3. Đo và sửa** — `.venv/bin/python src/eval_translations.py`

Xong khi `report.json` cho `diem.tong_hop` cao và `noi_dung.theo_nhom` không còn `rong`. Còn lỗi sentinel
thì `.venv/bin/python src/repair_sentinels.py local/build/translations_hymt2.jsonl` (không cần GPU), xong
khi dòng `dat QA sau khi sua` đạt 100%.

**4. Nạp vào game** — `.venv/bin/python src/inject.py` (sinh ra `local/build/mod/` gồm `catalog.json`,
các bundle và `apply.sh`) rồi `bash local/build/mod/apply.sh "<thư-mục-cài-game>"`
(script tự xoá cache `com.unity.addressables` trong `LocalLow/<company>/<product>/` rồi chạy game qua Steam).

Xong khi `inject.py` in `QA cung: N/N dat | loi cung: 0` và `=> TAT CA OK`, đồng thời
`src/verify_catalog.py` báo chỉ đổi đúng entry cần thiết và blob catalog **giữ nguyên tổng độ dài**
(lệch là treo game — xem "Catalog là bảng offset byte tuyệt đối" bên dưới). Số cụ thể, log in-game và
bằng chứng chạy thật của game đang dịch: `local/SKILL.md`.

**Bị cổng QA chặn:** đọc chi tiết 5 lớp lỗi nó in ra, sửa bản dịch, chạy lại. Danh sách lỗi nằm ở
`local/build/qa_canh_bao.json`.

## Ràng buộc không đọc ra được từ code

- **Cache uv**: `~/.cache/uv` là read-only. Mọi lệnh `uv` chạy kèm
  `export UV_CACHE_DIR=$PWD/.uv-cache TMPDIR=$PWD/.tmp`.
- **Python**: `python3` mặc định là 3.14, torch chưa hỗ trợ. Mọi script chạy bằng `.venv/bin/python` (3.12).
- **Byte-exact**: mọi TextAsset đã chọn phải tái tạo trùng từng byte. `src/formats.py` là nơi duy nhất
  sở hữu định dạng (tham số lấy từ profile); `src/verify_formats.py` kiểm chứng.
- **Sentinel**: placeholder và tag được thay bằng `{0}`, `{1}`… trước khi dịch. Model hay làm hỏng
  (`{0}` → `{0>`) hoặc đánh số lại (`{0}` ở chỗ đáng lẽ `{2}`). Hai hàm `fix_sentinels` và
  `renumber_sentinels` trong notebook xử lý tại nguồn; `src/repair_sentinels.py` làm điều tương tự
  trên file đã tải, **không cần GPU**.
- **llama.cpp + GGUF**: notebook tải **binary CUDA build sẵn** của llama.cpp. **Không đoán tên file** —
  quét danh sách release và khớp theo tên asset thật (`llama-b11696-bin-ubuntu-cuda-12.8-x64.tar.gz`);
  `/releases/latest` bỏ qua các bản `b…` vì chúng là *prerelease*. Nếu binary không chạy, đặt
  `FORCE_COMPILE=True`: biên dịch **chỉ** target `llama-server` với `-DCMAKE_CUDA_ARCHITECTURES=75`.
  Model `hunyuan-dense` có **chat template nhúng sẵn** trong GGUF nên `llama-server` dùng `--jinja`.
- **Cờ `llama-server`**: dùng `-fa on` — **không** viết `--flash-attn --no-webui` vì cờ này nhận giá trị
  tuỳ chọn nên **nuốt luôn cờ sau** làm giá trị và server thoát. Model 7B dùng `-sm layer` (chia 2 GPU):
  chia model nhỏ ra 2 GPU qua PCIe làm hai GPU chạy nối tiếp, chậm hơn. Notebook chạy **2 server độc lập**,
  mỗi cái ghim một T4 qua `CUDA_VISIBLE_DEVICES`.
- **Kiểm tra cổng trước khi khởi động server**: server cũ còn giữ cổng 8080 thì server mới không bind được
  mà `/health` vẫn trả 200 (của server cũ) → mọi phép đo do cấu hình cũ phục vụ. Phải `pkill -f llama-server`
  và chờ cổng trống.
- **Xác minh GPU bằng `nvidia-smi`, không bằng log**: llama.cpp đổi định dạng log theo từng bản và lặng lẽ
  lùi về CPU nếu thiếu CUDA runtime. Hỏi `nvidia-smi --query-compute-apps=pid,process_name,used_memory`.
- **JSON schema `minItems`/`maxItems`**: `llama-server` biên dịch `response_format` thành **GBNF grammar**,
  output không thể sai cấu trúc. Nhưng `{"type":"array"}` **không chặn số phần tử** — phải ghi đúng
  số phần tử, nếu không model trả thiếu mục và bị coi là JSON hỏng.
- **Đơn vị/s không công bằng**: độ dài đơn vị trong một game dao động hàng chục lần, nên chỉ số đáng đọc
  là `ký tự/s` và `token/s`; ETA trong notebook tính theo ký tự còn lại.
- **`MODE="failed"` không được lọc resume**: nó đã lọc theo *chất lượng* bản dịch cũ. Lọc thêm theo
  "uid đã có trong file" sẽ khiến nó không bao giờ sửa được gì, vì lần chạy trước ghi ra đủ mọi uid.
- **Catalog là bảng offset byte tuyệt đối** (`patch_catalog` trong `src/inject.py`): `m_EntryDataString` /
  `m_BucketDataString` lưu **offset byte tuyệt đối** trỏ vào blob `m_ExtraDataString` (blob gồm nhiều entry
  JSON, UTF-16LE). Sửa entry làm **đổi tổng độ dài blob** → mọi entry sau lệch offset → game treo loading
  với `RemoteProviderException : Invalid path in AssetBundleProvider: ''` (không liên quan CRC/size — chỉ
  cần blob dài khác là hỏng, đã chứng minh bằng A/B test thật). Phép: rút ngắn bao nhiêu ký tự thì
  **chen đúng bấy nhiêu space vào JSON của entry** (space là whitespace hợp lệ); `patch_catalog` tự làm và
  từ chối chạy nếu entry dài hơn vanilla. Nạp mod xong phải **xoá cache** `com.unity.addressables`.
- **Nguồn pipeline phải giữ vanilla**: `src/inject.py` đọc bundle + catalog gốc từ `game_dir` trong
  profile — nếu bản copy đó đang bị mod thì repack dựng trên file đã sửa (mất chuẩn vanilla, offset lệch).
  Bản vanilla chuẩn để trong `local/aa_backup_*/`. Nạp mod (apply) chỉ nhắm **bản game đã cài**, không để
  mod nằm lại trong thư mục nguồn của pipeline.

## Đọc thêm

- **[README.md](README.md)** — bản cơ bản để chạy: cấu trúc repo, quy trình 4 bước, kiểm thử, bảng file.
- **[HUONG-DAN.md](HUONG-DAN.md)** — hướng dẫn chi tiết: nguồn văn bản, bẫy khi chạy Kaggle, và cách
  chuyển sang **game Unity khác** (game profile trong
  `local/games/<ten>.py`, mọi script nhận `--game <ten>`; dò TextAsset bằng `src/discover_game.py`).
  Đọc khi **áp dụng cho game khác, đổi model, đổi tham số, hoặc cần biết vì sao một bước làm như vậy**.
- **[SKILL.md](SKILL.md)** — bản ngắn gọn cho agent: việc phải làm, thứ tự, bẫy.
- `local/SKILL.md` + `local/prompt_*.md` — số đo, runbook và nhật ký của game đang dịch. Đọc **trước khi
  sửa bất cứ thứ gì trong đường ống** để không lặp lại lỗi cũ. Hai file này **không được đẩy lên GitHub**
  (nằm trong `local/`).

## Nếu game cập nhật bản mới

Mod bị ràng buộc với phiên bản game (catalog.json, bundle hash). Khi game update:

- **Game update lớn (new content)**: chạy lại pipeline từ đầu. `MODE="all"` sẽ **bỏ qua đơn vị đã dịch**
  (resume tự động), chỉ dịch units mới. File dịch cũ vẫn dùng được.
- **Game update nhỏ (bug fix)**: thử apply mod cũ → nếu `verify_catalog.py` báo OK thì vẫn dùng.
- **Game update phá vỡ mod**: sao lưu `aa/` gốc → chạy lại pipeline.

Luôn sao lưu `<game_dir>/<data_subdir>/StreamingAssets/aa/` trước khi apply mod. Khi game update,
Steam ghi đè file trong `aa/` → mod bị xóa tự động.

Chi tiết: xem HUONG-DAN.md mục "Nếu game cập nhật bản mới".

## Kiểm thử

```bash
.venv/bin/python src/verify_formats.py        # mọi TextAsset byte-exact
.venv/bin/python src/test_notebook_kaggle.py  # notebook Kaggle với hàm sinh GIẢ, không cần GPU
.venv/bin/python src/eval_translations.py     # điểm + biểu đồ -> local/build/eval/ (chỉ đọc, không sửa gì)
.venv/bin/python src/inject.py --identity     # chạy hết đường ống -> local/build/mod_identity/
```

Sinh lại notebook bằng `.venv/bin/python src/make_kaggle_llamacpp.py`; **không sửa tay** file `.ipynb`.
`test_notebook_kaggle.py` **bắt buộc chạy** sau mỗi lần sinh: nó exec đúng code cell với `gen_many` giả
(mô phỏng tầng HTTP tới `llama-server`) và đã bắt được lỗi điều khiển luồng mà đọc code không thấy
(ví dụ `MODE="failed"` bị lọc resume).

`eval_translations.py` là nơi **đo trước khi sửa**: nó tách lỗi định dạng khỏi lỗi nội dung và phân
nhóm nội dung (`da_dich`, `giu_en_theo_thiet_ke`, `khong_dau_nghi_chua_dich`, `rong`), nên chỉ số
đáng đọc là `diem.tong_hop` chứ không phải `qa.ty_le_dat` đơn thuần.
