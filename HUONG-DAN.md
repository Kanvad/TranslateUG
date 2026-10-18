# TranslateUG — hướng dẫn chi tiết

Muốn chạy ngay: **[README.md](README.md)**. File này là phần giải thích và tra cứu — nguồn văn bản,
bẫy khi chạy Kaggle, và cách áp dụng cho game Unity khác.

## Nguồn văn bản cần dịch

Mỗi game có thể có nhiều nguồn chữ, nhưng thực tế thường gặp hai dạng — cả hai đều là TextAsset nằm
trong bundle Addressables:

| Dạng | Ví dụ | Trông thế nào |
|---|---|---|
| Bảng UI/item/email/mission | bảng config kiểu Luban | JSON mảng object `{"key","text"}` (hoặc tương tự) |
| Hội thoại | Yarn Spinner | CSV `language,id,text` |

Ngoài ra có thể có asset **dư thừa** (key đã nằm trong bảng chính) hoặc bảng locale **chỉ để đổi font**
(khai `translated=False`). Danh sách TextAsset thật của game đang dịch: xem `local/SKILL.md`.

## Model dịch (Hy-MT2-7B + llama.cpp)

| | |
|---|---|
| Kiến trúc | `hunyuan-dense` — llama.cpp hỗ trợ sẵn (`LLM_ARCH_HUNYUAN_DENSE`) |
| Tham số | 32 layer · 16 head · **4 KV head** · head_dim 128 · vocab 120.818 |
| KV cache | 64 KiB/token — chỉ 4 KV head nên rất nhẹ (4 GiB tại `-c 65536`) |
| Chat template | **nhúng sẵn** trong GGUF (596 ký tự) ⇒ `llama-server` dùng `--jinja` |
| Runtime | C++/CUDA, **continuous batching** (`--parallel`) — không tốn overhead Python mỗi bước |

**Hai server, mỗi T4 một server.** Chạy **2 tiến trình độc lập, ghim mỗi tiến trình một T4**
(`CUDA_VISIBLE_DEVICES`) để dùng cả hai GPU. Model 7B **chia qua 2 GPU** (`-sm layer`): chia model lớn ra
2 GPU qua PCIe.

## Chạy trên Kaggle: bẫy đã gặp

> ⚠️ **Không đoán tên asset llama.cpp.** Tên file là `llama-b11696-bin-ubuntu-cuda-12.8-x64.tar.gz`,
> **không** theo `tag`, và `/releases/latest` **bỏ qua** các bản `b…` vì chúng là *prerelease*. Notebook
> quét 40 release rồi khớp theo tên asset thật. Nếu binary không chạy được (driver cũ), đặt
> `FORCE_COMPILE = True` ở ô 1 — biên dịch **chỉ** target `llama-server` với `-DCMAKE_CUDA_ARCHITECTURES=75`.
>
> ⚠️ **Cú pháp cờ `llama-server`.** `--flash-attn` và `-sm` nhận *giá trị tuỳ chọn*: viết
> `--flash-attn --no-webui` thì nó **nuốt `--no-webui` làm giá trị** và server thoát. Phải dùng `-fa on`.
>
> ⚠️ **Cổng phải trống trước khi khởi động.** Server cũ còn giữ cổng 8080 thì server mới không bind được,
> nhưng `/health` vẫn trả 200 (của server cũ) ⇒ mọi phép đo **do cấu hình cũ phục vụ**. Notebook
> `pkill -f llama-server` rồi chờ cổng trống trước khi chạy.
>
> ⚠️ **Xác minh GPU bằng `nvidia-smi`, không bằng log.** llama.cpp đổi định dạng log theo từng bản và
> **lặng lẽ lùi về CPU** nếu thiếu CUDA runtime. Notebook hỏi
> `nvidia-smi --query-compute-apps=pid,process_name,used_memory` và báo rõ nếu PID của server không nằm
> trong danh sách.
>
> **JSON schema `minItems`/`maxItems`.** `llama-server` biên dịch `response_format` thành **GBNF grammar**
> nên output không thể sai cấu trúc. Nhưng `{"type":"array"}` **không chặn số phần tử** — phải ghi đúng
> số phần tử, nếu không model trả thiếu mục ⇒ bị coi là JSON hỏng ⇒ rơi vào đường dịch từng đơn vị.
>
> **Ghép lô theo ngân sách ký tự** (`MAX_BATCH_CHARS`), không chỉ theo số lượng: lô toàn đơn vị ngắn thì lọt,
> nhưng lô có đơn vị dài (hàng nghìn ký tự) vượt ngân sách token → bị cắt → JSON
> hỏng → rơi vào đường dịch từng đơn vị (chậm hơn nhiều lần).
>
> **Sắp xếp theo độ dài trước khi ghép lô** (`make_batches(sort_by_len=True)`). Cả lô phải chờ dãy dài
> nhất xong, nên lô trộn đơn vị ngắn với đơn vị dài khiến GPU chạy không cho các dãy ngắn.
> Miễn phí: kết quả ghi theo `uid` nên thứ tự xử lý không ảnh hưởng độ chính xác.
>
> **Đọc `ký tự/s`, `token RA/s` và `token VAO/s`, đừng đọc `đơn vị/s`.** Độ dài đơn vị trong một game
> thay đổi hàng chục lần nên `đơn vị/s` tụt dù tốc độ token không đổi. `token VAO/s` là **prefill**
> (khối luật lặp lại mỗi request), thứ mà `completion_tokens` che mất. ETA in **cả hai cách** — theo ký tự
> và theo token gồm prefill.
>
> **`MODE="failed"` để sửa đơn vị lỗi.** Nó lọc theo *chất lượng* bản dịch cũ và **không** lọc theo
> "uid đã có trong file" — nếu lọc thêm thì nó không bao giờ sửa được gì, vì lần chạy trước đã ghi ra
> đủ mọi uid.

## Byte-exact

`src/formats.py` tái tạo **nguyên byte** các TextAsset (đã kiểm chứng bằng `verify_formats.py`).
Mọi tham số định dạng (`indent`, `newline`, ký tự phải escape, `csv_header`) lấy từ profile:
- JSON: `ensure_ascii=False`, `indent` theo profile, escape riêng vài ký tự, newline theo profile,
  không BOM, không newline cuối
- CSV: header theo profile, `QUOTE_MINIMAL`, newline theo profile, UTF-8 không BOM

## Nếu game cập nhật bản mới

Mod bị ràng buộc với phiên bản game cụ thể (catalog.json, bundle hash, asset IDs). Khi game update:

### Sao lưu trước khi update
```bash
# Chỉ khi game dùng Addressables (có thư mục StreamingAssets/aa/). Đổi đường dẫn theo game của bạn.
cp -r "Game/Game_Data/StreamingAssets/aa" local/aa_backup_original
```

### Sau khi game update
1. Chạy lại pipeline từ đầu:
   - `extract_units.py` → trích xuất units mới (có thể có units mới từ content mới).
   - Kaggle: dịch với `MODE="all"` → **sẽ bỏ qua đơn vị đã dịch** (resume tự động), chỉ dịch units mới.
   - `eval_translations.py` → kiểm tra QA.
   - `inject.py` → `apply.sh` → `verify_catalog.py`.

2. **File dịch cũ vẫn dùng được**: `translations_hymt2.jsonl` giữ mọi đơn vị đã dịch. MODE="all" sẽ giữ nguyên những đơn vị unchanged và chỉ dịch đơn vị mới. Nếu game thêm 100 đơn vị mới, chỉ cần dịch 100.

3. **Nếu game chỉ sửa text cũ** (không thêm mới): extract_units sẽ tạo units.jsonl mới, và MODE="all" sẽ re-translate tất cả (vì uid có thể thay đổi). Trong trường hợp này, file dịch cũ ít hữu ích hơn.

### Lưu ý
- Luôn **sao lưu thư mục `aa/` gốc** trước khi apply mod. Khi game update, Steam sẽ ghi đè file trong `aa/` → mod bị xóa tự động. Bạn chỉ cần chạy lại pipeline.
- `extract_report.json` ghi sha256 của file gốc — dùng để kiểm tra game có thay đổi không.
- Nếu game update nhỏ (chỉ sửa bug), có thể thử apply mod cũ trước — nếu `verify_catalog.py` báo OK thì vẫn dùng được.

### Tóm tắt
| Tình huống | Hành động |
|---|---|
| Game update lớn (new content) | Chạy lại pipeline (MODE="all" sẽ reuse bản dịch cũ) |
| Game update nhỏ (bug fix) | Thử apply mod cũ → nếu verify_catalog OK thì dùng |
| Game update phá vỡ mod | Sao lưu aa/ → chạy lại pipeline |

## Áp dụng cho game Unity khác

Đường ống này **~80% là máy chung**, chỉ ~20% là cấu hình riêng của từng game. Phần riêng gom vào
**một file profile**: `local/games/<ten>.py`; mọi script đọc profile qua cờ `--game <ten>` (máy chỉ có
một profile thì không cần truyền). Đầu ra của mọi game vẫn nằm trong `local/build/` (`src/paths.py` là
nơi duy nhất biết; muốn tách riêng từng game thì sửa ở đó). Bản ngắn gọn cho agent: **[SKILL.md](SKILL.md)**.

### 0. Bản đồ: chung vs riêng

| Chung (không đụng khi sang game khác) | Riêng (nằm trong `local/games/<ten>.py`) |
|---|---|
| `formats.py` — serializer byte-exact (tham số hoá) | path game, tên bundle, tên TextAsset + định dạng |
| Lõi `protect.py` — sentinel, gộp token, cắt/ghép tiền tố, QA | `style_ids`, `entity_ids`, `glossary` |
| `extract_units.py` vòng lặp asset (đọc profile) | `font_fix` (đổi font cho locale thiếu glyph) |
| `inject.py` — repack + `patch_catalog` + `apply.sh` | `steam_appid`, `company/product` |
| `eval_translations.py`, `repair_sentinels.py`, `verify_formats.py` | `genre_desc`, `notebook_name` |
| Notebook Kaggle (sinh bởi `make_kaggle_llamacpp.py`) | |

### 1. Dò game mới

```bash
.venv/bin/python src/discover_game.py "~/Desktop/My Game"
```

In ra: thư mục Addressables, các thư mục bundle, và **mọi TextAsset** kèm kích thước + định dạng đoán
được (`JSON indent=… newline=…`, `CSV cot=…`, hoặc `TEXT`), cùng **khung profile gợi ý**. Chỉ những asset
JSON/CSV *có chữ thật* mới được đề xuất — bạn tự quyết cái nào cần dịch.

Gợi ý: chạy `--bundle <một phần tên bundle>` để thu hẹp; nếu game có nhiều bundle, quét cả
`StandaloneWindows64` rồi lọc.

### 2. Viết profile

Tạo `local/games/<ten>.py`:

```python
from games.profile import Asset, GameProfile

def build():
    return GameProfile(
        name="mygame",
        game_dir="~/Desktop/My Game",      # thư mục GỐC (chứa <Ten>_Data)
        data_subdir="MyGame_Data",
        bundle_subdir="StandaloneWindows64",
        assets=[
            Asset(textasset="text_en", bundle="configs_assets_all_<hash>.bundle",
                  fmt="json", id_field="key", text_field="text",
                  dialogue=False, translated=True),
        ],
        style_ids=[...], entity_ids=[...], glossary=[...],
        font_fix={...}, steam_appid="...", company="...", product="...",
        genre_desc="an action RPG",
    )
```

#### `Asset` — mỗi TextAsset chứa chữ

| Trường | Ý nghĩa |
|---|---|
| `textasset` | tên TextAsset (script ghi `local/build/raw/<textasset>.json\|.csv`) |
| `bundle` | tên file bundle chứa nó |
| `fmt` | `"json"` (mảng object) hoặc `"csv"` (có header) |
| `id_field` / `text_field` | tên khoá/cột định danh và chứa chữ |
| `dialogue` | `True` = hội thoại → bảo vệ style tag + cắt tiền tố người nói; `False` = bảng UI |
| `translated` | `False` = chỉ lưu raw (vd bảng font), không tạo đơn vị dịch |

#### Các trường còn lại

| Trường | Khi nào cần |
|---|---|
| `game_dir`, `data_subdir`, `bundle_subdir`, `catalog_name` | luôn |
| `json_opts` (`indent`, `newline`, `escape`), `csv_header` | khi định dạng game khác mặc định (xem mục 3) |
| `style_ids` | game có tag style dạng `[info]…[/info]` |
| `entity_ids` | tiền tố người nói dạng `name: text` |
| `glossary` | tên riêng KHÔNG dịch (nhân vật, địa danh) |
| `font_fix` | font TMP của locale thiếu glyph tiếng Việt (xem mục 5) |
| `steam_appid`, `company`, `product` | để `apply.sh` in đúng lệnh xoá cache |
| `genre_desc`, `display_name`, `notebook_name` | cho prompt notebook + đường dẫn/tên file |

### 3. Định dạng byte-exact

Đây là **điều kiện sống còn**: game đọc TextAsset theo byte, tái tạo sai một byte là hỏng.
`formats.py` tham số hoá qua `json_opts` / `csv_header`:

- `json_opts["indent"]`: 2 hoặc 4 (đoán bằng `discover_game.py`).
- `json_opts["newline"]`: `"\r\n"` (Windows) hay `"\n"`.
- `json_opts["escape"]`: ký tự serializer gốc escape dù `ensure_ascii=False`
  (vài serializer escape `U+00A0`, `U+2003` → `\uXXXX`). Nếu game khác, tự so khớp.
- `csv_header`: đúng thứ tự cột trong file gốc.

Kiểm tra:

```bash
.venv/bin/python src/extract_units.py --game <ten>   # BUOC 2 in OK/FAIL từng asset
.venv/bin/python src/verify_formats.py --game <ten>  # tất cả phải OK
```

Nếu FAIL, chỉnh `json_opts`/`csv_header` cho tới khi OK rồi mới đi tiếp.

### 4. Bảo vệ placeholder / glossary

- `style_ids`: quét asset style của game để lấy id tag.
- `entity_ids`: quét asset entity (tiền tố người nói) để lấy id.
- `glossary`: gom tên nhân vật/địa danh xuất hiện trong bản dịch phải giữ nguyên.

Chỉ `dialogue=True` mới bật bảo vệ style tag + cắt tiền tố (bài học: trong bảng UI, `[...]`
vẫn có thể là **nội dung thật**, không phải tag).

### 5. Font tiếng Việt

TMP FontAsset atlas ở chế độ Static sẽ hiển thị ô vuông với ký tự thiếu. Kiểm tra:

```bash
.venv/bin/python src/check_fonts.py --game <ten>
```

Nếu locale đang dùng font thiếu glyph, khai báo `font_fix` trỏ sang font đủ glyph (phải là font
**đã có sẵn trong game**):

```python
font_fix={"<textasset bang locale>": {"en": {"tmp_font": "<ten font du glyph>"}}}
```

`inject.py` sẽ đổi `tmp_font.url` cho entry đó (giữ nguyên độ dài nếu chỉ đổi tên cùng độ dài —
nhớ kiểm tra blob catalog sau khi vá).

### 6. Chạy đường ống

```bash
# 1) Trích xuất
.venv/bin/python src/extract_units.py --game <ten>

# 2) Sinh notebook + chạy trên Kaggle (Internet On, GPU T4 x2)
.venv/bin/python src/make_kaggle_llamacpp.py --game <ten>
#    -> local/kaggle_<ten>_llamacpp.ipynb ; tải translations_hymt2.jsonl về local/build/

# 3) Đo + sửa
.venv/bin/python src/eval_translations.py --game <ten> --no-plots
.venv/bin/python src/repair_sentinels.py local/build/translations_hymt2.jsonl --game <ten>

# 4) Nạp
.venv/bin/python src/inject.py --game <ten>
bash local/build/mod/apply.sh
```

`inject.py` là cổng QA cuối: QA cứng không đạt thì nó **từ chối** chạy.

### 7. Catalog là bảng offset byte tuyệt đối

`patch_catalog` trong `inject.py` xử lý việc này **chung cho mọi game Addressables**:
`m_ExtraDataString` là blob nhiều entry JSON (UTF-16LE), còn `m_EntryDataString` /
`m_BucketDataString` lưu **offset byte tuyệt đối** vào blob. Sửa entry làm **đổi tổng độ dài entry** là
mọi offset sau lệch → game treo loading. Vì vậy khi vá, nếu entry bị rút ngắn bao nhiêu ký tự thì chèn
đúng bấy nhiêu dấu cách; nếu entry dài hơn vanilla thì **từ chối**. Điều kiện: file gốc phải là
**vanilla** (không đang bị mod).

Kiểm chứng sau khi nạp:

```bash
.venv/bin/python src/verify_catalog.py --game <ten>
```

Luôn **xoá cache** `com.unity.addressables` trong `LocalLow/<company>/<product>/` trước khi chạy game.

### 8. Bẫy chung (giữ nguyên khi đổi game)

- **Byte-exact**: sai một byte là hỏng; luôn chạy `verify_formats` trước khi dịch.
- **CRC Addressables**: đặt `m_Crc=0` + `m_UseCrcForCachedBundles=false` cho bundle đã sửa (đã tự động).
- **`[...]` vừa là tag vừa là nội dung**: chỉ bảo vệ trong file hội thoại.
- **Tiền tố người nói** để nguyên thì model dịch luôn → phải cắt trước, ghép sau.
- **Token nằm sát nhau** (`</color><color=…>`) phá sentinel → gộp token liền kề.
- **Sentinel bị model làm hỏng** (`{0}`→`{0>`): notebook sửa tại nguồn, hoặc `repair_sentinels.py`
  (không cần GPU).
