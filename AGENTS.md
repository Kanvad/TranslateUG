# AGENTS.md

**TranslateUG** — bộ công cụ dịch game Unity bằng cách **ghi đè một locale có sẵn**. Đường ống 4 bước
(trích xuất → dịch trên Kaggle → đo/sửa → nạp vào game); `src/inject.py` là **cổng QA** ở cuối và
từ chối chạy khi bản dịch chưa đạt.

## Phân tầng luật (AGENTS.md lồng nhau)

- **File này chỉ chứa luật chung** áp cho mọi game trên máy.
- **Luật riêng từng game** nằm ở `local/<ten>/AGENTS.md`: OpenCode nạp tự động khi agent đọc file
  trong thư mục game đó (vd `local/doloctown/AGENTS.md`). Làm việc với một game cụ thể thì đọc,
  theo thứ tự: `local/<ten>/AGENTS.md` (nếu có) → `local/<ten>/SKILL.md` (số đo, nguồn văn bản,
  mối nguy — **đọc trước khi sửa bất cứ thứ gì trong đường ống**) → `local/<ten>/prompt_*.md`
  (nhật ký từng lượt). Không lặp lại lỗi đã ghi ở đó.

## Chỗ để dữ liệu

- **Máy móc chung** → `src/` và phần publish (`README.md`, `HUONG-DAN.md`, `AGENTS.md`, `SKILL.md`).
- **Dữ liệu riêng của game** → `local/<ten>/`, thứ **không** được đẩy lên GitHub: `game.py` (profile,
  kiểu cũ `local/games/<ten>.py` vẫn chạy), `build/` (đầu ra pipeline), `SKILL.md` + `prompt_*.md`,
  `AGENTS.md` (luật riêng), nhật ký, bản sao game vanilla (`aa_backup_*/`).
- Không đưa tên game / tên bundle / glossary / app id / tên asset vào phần publish. Mỗi game một
  thư mục con để thêm game thứ hai không bị nhầm dữ liệu.
- `src/paths.py` sở hữu mọi đường dẫn local — đừng ghép tay trong script.

## Luật chung (không đọc ra được từ code)

- **Byte-exact**: mọi TextAsset đã chọn phải tái tạo trùng từng byte. `src/formats.py` là nơi duy nhất
  sở hữu định dạng (tham số lấy từ profile); `src/verify_formats.py` kiểm chứng — FAIL thì chỉnh
  tham số của profile, không sửa serializer cho vừa một game.
- **Notebook không sửa tay**: sinh lại bằng `src/make_kaggle_llamacpp.py`, rồi **bắt buộc** chạy
  `src/test_notebook_kaggle.py` (exec code cell với tầng HTTP giả, đã bắt lỗi điều khiển luồng mà
  đọc code không thấy).
- **Cổng QA từng bước** — một bước chỉ coi là xong khi điều kiện của nó đạt:
  1. `extract_report.json` có `byte_exact` = `true` cho **mọi** asset cần dịch;
  2. ô báo cáo notebook in `CON LOI (QA)  : 0`;
  3. `eval/report.json` cho `diem.tong_hop` cao và **`con_nguyen_en` = 0** (nhóm
     `giu_en_theo_thiet_ke` là skip/still_en, không tính là lỗi); sửa bằng `src/repair_sentinels.py`
     (**không cần GPU**), hết khi `dat QA sau khi sua` đạt 100%;
  4. `inject.py` in `=> TAT CA OK` và `verify_catalog.py` OK.
- **Đo trước khi sửa**: `eval_translations.py` tách lỗi định dạng khỏi lỗi nội dung và phân nhóm;
  chỉ số đáng đọc là `diem.tong_hop`, không phải `qa.ty_le_dat` đơn thuần. Tốc độ chỉ đọc qua
  `ký tự/s` / `token/s` — độ dài đơn vị giữa các game dao động hàng chục lần, `đơn vị/s` không công bằng.
- **Catalog là bảng offset byte tuyệt đối**: tổng độ dài blob `m_ExtraDataString` không được đổi
  (cơ chế vá + vì sao treo game xem HUONG-DAN mục 7). Sai là crash loading, không liên quan CRC.
- **Vanilla**: nguồn của pipeline (bundle + catalog gốc trong `game_dir`) phải giữ vanilla; bản
  chuẩn để trong `local/<ten>/aa_backup_*/`. Apply mod chỉ nhắm **bản game đã cài**; luôn sao lưu
  `aa/` trước khi apply; nạp mod xong phải **xoá cache** `com.unity.addressables`.
- **Lời thoại Yarn tra bảng mono `_stringTable`, không tra TextAsset CSV**: bundle có các
  MonoBehaviour tên trùng `_LocaleCode` (`en`/`ru`/`de`…) mang bảng `{keys, values}` — game tra
  line-id Yarn ở **đây**; TextAsset CSV chỉ là bản chạy sẵn của editor, vá nó không có hiệu lực.
  `inject.py` phải vá cả hai và kiểm sau repack (`mono Loc 'en': KHOP VI N/N`). Trên game khác:
  dò MonoBehaviour có `_LocaleCode=='en'` + `_stringTable` trong bundle chứa bảng dialogue.
- **Môi trường máy**: `~/.cache/uv` read-only — mọi lệnh `uv` chạy kèm
  `export UV_CACHE_DIR=$PWD/.uv-cache TMPDIR=$PWD/.tmp`. `python3` mặc định là 3.14 (torch chưa
  hỗ trợ) — mọi script chạy bằng `.venv/bin/python` (3.12).
- **Bẫy khi chạy Kaggle / llama.cpp / llama-server** (tên asset build, cờ `-fa on`, cổng 8080,
  nvidia-smi, GBNF JSON schema, `MODE="failed"`…): xem HUONG-DAN.md — bổ sung bẫy mới vào đó,
  không nuôi lại chi tiết tooling ở file này.

## Nếu game cập nhật bản mới

- **Update lớn (new content)**: chạy lại pipeline từ đầu; MODE="all" tự resume, chỉ dịch units mới.
- **Update nhỏ (bug fix)**: thử apply mod cũ → `verify_catalog.py` OK thì dùng tiếp.
- **Update phá vỡ mod**: sao `aa/` lại → chạy lại pipeline. Steam ghi đè `aa/` khi update → mod
  mất tự động, nên luôn có backup.

Chi tiết: xem HUONG-DAN.md mục "Nếu game cập nhật bản mới".

## Đọc thêm

- **[README.md](README.md)** — bản cơ bản để chạy: quy trình 4 bước, kiểm thử, bảng file.
- **[HUONG-DAN.md](HUONG-DAN.md)** — chi tiết: nguồn văn bản, bẫy Kaggle/llama.cpp, catalog, porting
  sang game Unity khác (`src/discover_game.py`). Đọc khi **áp dụng cho game khác, đổi model, đổi
  tham số, hoặc cần biết vì sao một bước làm như vậy**.
- **[SKILL.md](SKILL.md)** — bản ngắn gọn cho agent: việc phải làm, thứ tự, bẫy.
