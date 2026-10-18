# SKILL.md — TranslateUG cho agent

Bộ công cụ dịch game Unity bằng cách **ghi đè một locale có sẵn**. Đường ống 4 bước; `src/inject.py` là
**cổng QA** chặn ở cuối. Đây là bản ngắn để agent làm việc nhanh; chạy nhanh ở [README.md](README.md),
chi tiết ở [HUONG-DAN.md](HUONG-DAN.md), luật bắt buộc + ràng buộc môi trường ở [AGENTS.md](AGENTS.md).

## Chỗ để dữ liệu

| Chỗ | Chứa gì |
|---|---|
| `src/`, `README.md`, `HUONG-DAN.md`, `AGENTS.md`, `SKILL.md` | máy móc chung — **được publish** |
| `local/` | **không publish**: `local/games/<ten>.py` (profile), `local/build/` (đầu ra), `local/SKILL.md` (số đo + runbook), nhật ký, bản sao vanilla |

Không đưa tên game / tên bundle / glossary / app id / tên asset của game vào phần publish.
Mọi đường dẫn local đi qua `src/paths.py` — đừng ghép tay.

## Chạy đường ống

```bash
export UV_CACHE_DIR=$PWD/.uv-cache TMPDIR=$PWD/.tmp
.venv/bin/python src/extract_units.py             # 1. trích xuất -> local/build/units.jsonl
.venv/bin/python src/make_kaggle_llamacpp.py      #    sinh local/kaggle_<ten>_llamacpp.ipynb -> chạy trên Kaggle
.venv/bin/python src/eval_translations.py         # 3. đo -> local/build/eval/report.json
.venv/bin/python src/inject.py                    # 4. QA cứng + đóng gói -> local/build/mod/
bash local/build/mod/apply.sh "<thư-mục-game>"    #    nạp (tự xoá cache) rồi chạy game
.venv/bin/python src/verify_catalog.py            #    kiểm chứng catalog sau khi vá
```

Xong khi: `extract_report.json` có `byte_exact` = `true`; notebook in `CON LOI (QA)  : 0`; `inject.py` in
`=> TAT CA OK`; `verify_catalog.py` báo blob catalog **giữ nguyên tổng độ dài**.

Notebook **không sửa tay** — sinh lại bằng `src/make_kaggle_llamacpp.py`, sau đó **bắt buộc** chạy
`src/test_notebook_kaggle.py` (exec code cell với tầng HTTP giả, không cần GPU).

## Thêm game mới

1. **Dò asset**: `.venv/bin/python src/discover_game.py "<thư-muc-game>"` → in mọi TextAsset + khung
   profile gợi ý.
2. **Tạo profile** `local/games/<ten>.py`:

```python
from games.profile import Asset, GameProfile

def build():
    return GameProfile(
        name="mygame",
        game_dir="~/Desktop/My Game",       # thư mục GỐC (chứa <Ten>_Data)
        data_subdir="MyGame_Data",
        assets=[
            Asset(textasset="ui_text_en", bundle="configs_assets_all_<hash>.bundle",
                  fmt="json", id_field="key", text_field="text",
                  dialogue=False, translated=True),
        ],
        style_ids=[...], entity_ids=[...], glossary=[...],   # nếu game có tag/tiền tố/tên riêng
        font_fix={...}, steam_appid="...", company="...", product="...",
        genre_desc="an action RPG",
    )
```

3. **Byte-exact trước khi dịch**: `src/extract_units.py --game <ten>` (in OK/FAIL từng asset) rồi
   `src/verify_formats.py --game <ten>`. FAIL thì chỉnh `json_opts` (`indent`, `newline`, `escape`) /
   `csv_header` cho khớp file gốc.
4. **Bảo vệ placeholder**: điền `style_ids` (tag dạng `[info]…[/info]`), `entity_ids` (tiền tố `name:`),
   `glossary` (tên riêng không dịch). Chỉ asset `dialogue=True` mới bật bảo vệ tag + cắt tiền tố.
5. **Font**: `src/check_fonts.py --game <ten>`; locale thiếu glyph thì khai `font_fix` trỏ sang font
   **đã có sẵn trong game**.
6. Chạy lại 4 bước ở trên (thêm `--game <ten>` nếu máy có nhiều profile).

## Bẫy phải nhớ

- **Byte-exact**: sai một byte là hỏng — luôn `verify_formats` trước khi dịch.
- **CRC Addressables**: đặt `m_Crc=0` + `m_UseCrcForCachedBundles=false` cho bundle đã sửa (tự động).
- **Catalog là bảng offset byte tuyệt đối**: blob không được đổi tổng độ dài (rút ngắn bao nhiêu ký tự
  thì chèn bấy nhiêu space); nguồn phải là bản **vanilla**.
- **`[...]` vừa là tag vừa là nội dung** → chỉ bảo vệ trong hội thoại.
- **Tiền tố người nói** `name:` (có hoặc không khoảng trắng) → cắt trước khi dịch, ghép lại sau.
- **Token nằm sát nhau** (`</color><color=…>`) phá sentinel → gộp thành một sentinel.
- **Sentinel hỏng** (`{0}` → `{0>`, hoặc đánh số lại): notebook sửa tại nguồn,
  `src/repair_sentinels.py` sửa trên file đã tải (**không cần GPU**).
- **Font TMP Static** thiếu glyph tiếng Việt → `font_fix`.
- **Xoá cache** `com.unity.addressables` trong `LocalLow/<company>/<product>/` trước khi chạy game.

## Đọc thêm

- `README.md` — bản cơ bản để chạy (4 bước, kiểm thử, bảng file).
- `HUONG-DAN.md` — chi tiết: nguồn văn bản, bẫy khi chạy Kaggle, porting sang game khác.
- `AGENTS.md` — luật bắt buộc, ràng buộc môi trường (uv cache, Python 3.12, cờ `llama-server`…).
- `local/SKILL.md` + `local/prompt_*.md` — số đo, runbook và nhật ký của game đang dịch.
  Đọc **trước khi sửa** bất cứ thứ gì trong đường ống.
