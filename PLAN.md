# PLAN.md — sky_cotl_mp3-to-json_studio

Làm tuần tự từng bước. Mỗi bước có tiêu chí hoàn thành và gợi ý prompt cho agent.
Thứ tự đi từ dưới lên: các phần kiểm chứng được bằng `fixtures/` làm trước, GUI và AI làm sau.

## Dữ kiện từ fixtures

**`fixtures/test_output.mid`** (đầu ra Transkun)
- Format 1, 960 ticks/beat, 2 track. Track 0 chỉ có meta tempo (500000 µs/beat = 120 BPM mặc định) và 4/4.
- Track 1: 650 note-on, kênh 0, pitch 40–83, velocity khoảng 80–98.
- Nốt đầu tại tick 12041 (≈ 6,27 s). Nốt cuối khoảng 163 s.
- Onset gần như nằm đúng lưới 120 ms, không phản ánh timing của Transkun thật
  (khoảng cách 458–463 ticks, ≈ 240 ms).

**`fixtures/Summertime.json`** (đích)
- 989 nốt, 515 thời điểm khác nhau, kéo dài đến khoảng 139,4 s, nốt đầu tại 2160 ms.
- Lưới 120 ms. Khoảng cách onset: 240 ms (450 lần), 480 ms (55), 120 ms (7).
- Kích thước hợp âm: 1 nốt (165 lần), 2 nốt (227), 3 nốt (122), 4 nốt (1).
- Key dạng `1KeyN`/`2KeyN` (có chữ số layer). Dự án bỏ qua chữ số này và chỉ dùng `N` (0..14).

---

## Bước 0 — Khung dự án

Làm: tạo cấu trúc thư mục theo `AGENTS.md`, `pyproject.toml`, `requirements-core.txt`,
`models.py` (Note, SkyNote), một test rỗng chạy được.

Xong khi: `pytest -q` và `ruff check .` chạy sạch.

Prompt: *"Đọc AGENTS.md. Thực hiện Bước 0 trong PLAN.md. Chỉ tạo khung dự án, chưa viết logic."*

## Bước 1 — Exporter (Sky Studio JSON)

Làm: `exporters/sky_studio.py` với `export(meta, sky_notes) -> str` và `load(path)` để đọc lại.
Ghi key dạng `Key{n}` (không layer). Khi đọc, chấp nhận cả `Key{n}` lẫn `{số}Key{n}` và bỏ chữ số đầu.
Sắp xếp theo `time`, khử trùng (time, key), giữ nguyên thứ tự trường như file mẫu.

Test:
- Đọc `Summertime.json` (bỏ layer, khử trùng) rồi ghi ra, rồi đọc lại: kết quả bằng nhau. Sau khi bỏ layer còn 987 nốt (file mẫu có 989, phần chênh là các cặp trùng cùng thời điểm và cùng chỉ số phím giữa hai layer).
- Chấp nhận `Key11` và `1Key11` khi đọc, ghi ra luôn là `Key11`.
- Từ chối `key` sai định dạng và `n` ngoài 0..14.
- Ghi đúng gốc là mảng chứa 1 object, ký tự Unicode (tiếng Trung trong `author`) không bị escape hỏng.

Prompt: *"Thực hiện Bước 1. Viết test trước. Không đụng đến thư mục midi hay converter."*

## Bước 2 — MIDI Processing

Làm: `midi/reader.py`
- `read_notes(path) -> list[Note]`: gộp mọi track, ghép note-on/note-off để có `duration_ms`.
- Đổi tick sang ms bằng **tempo map** (hỗ trợ đổi tempo giữa bài), không giả định 120 BPM.
- Lọc nốt quá ngắn (ngưỡng cấu hình, mặc định 30 ms) và nốt trùng.

`midi/cleanup.py`
- `trim_leading_silence(notes) -> (notes, offset_ms)`: đưa nốt đầu về 0 và trả về offset đã trừ.

Test với `test_output.mid`:
- Có 650 nốt (trước khi lọc), pitch trong 40..83.
- Nốt đầu ≈ 6271 ms trước khi trim, và = 0 sau khi trim.
- Test riêng cho tempo map bằng MIDI tổng hợp có đổi tempo.

Prompt: *"Thực hiện Bước 2. Không dùng PySide6 hay torch. Chạy test với fixtures/test_output.mid."*

## Bước 3 — Sky Converter

Chia thành các hàm nhỏ, mỗi hàm một test.

1. `converter/grid.py` — `estimate_grid(onsets_ms) -> float`
   Ước lượng bước lưới từ histogram khoảng cách onset. Mục tiêu với fixture: ≈ 240 ms (hoặc 120 ms nếu chia nhỏ hơn).
   `quantize(time_ms, grid_ms) -> int` làm tròn về lưới. Lưới cuối cùng là 120 ms hoặc ước lượng, cấu hình được.
2. `converter/scale.py` — thang âm 15 phím, Key0–Key14 = C4–C6 (đã xác nhận).
   `KEY0_MIDI_PITCH = 60`, `KEY_SEMITONE_OFFSETS = [0,2,4,5,7,9,11,12,14,16,17,19,21,23,24]`.
   Test: `Key0 → 60`, `Key7 → 72`, `Key14 → 84`.
3. `converter/transpose.py` — `best_transpose(pitches) -> int`
   Thử −11..+11 semitone, chọn mức có nhiều nốt nằm trong thang âm C trưởng nhất.
   Nếu hòa, ưu tiên mức có nhiều nốt nằm trong C4–C6 hơn, rồi mới đến mức dịch nhỏ nhất.
   Trên `test_output.mid`: −2 và +10 hòa nhau (632/650 nốt trong thang âm), nhưng −2 có 420 nốt trong C4–C6
   còn +10 chỉ có 181, nên kết quả đúng là **−2**. Đây là test bắt buộc.
4. `converter/mapping.py` — `pitch_to_key(pitch, transpose) -> (key, tuple[MappingWarning, ...])`
   Gập quãng tám khi ngoài C4–C6 (60–84). Nốt ngoài thang âm đưa về nốt gần nhất.
   Cảnh báo có kiểu: `folded` chỉ được đếm; `out_of_scale` giữ thông điệp.
   Với MIDI mẫu sau khi dịch −2: 0 nốt cao hơn C6, nhưng 230/650 nốt thấp hơn C4 (thấp nhất là 38), nên gập quãng tám
   là bắt buộc chứ không phải trường hợp hiếm.
   Test: 7 nốt đầu của MIDI mẫu (81,81,78,83,81,76,74) sau khi dịch −2 phải ra Key 11,11,9,12,11,8,7.
   Sau khi gập, hai nốt cùng thời điểm có thể rơi vào cùng một phím (ví dụ bè trầm cách giai điệu đúng quãng tám). Khi đó chỉ giữ một nốt.
5. `converter/chords.py` — gộp nốt cùng thời điểm, khử trùng, giới hạn số nốt/hợp âm (cấu hình, mặc định 4,
   giữ nốt cao nhất và thấp nhất khi phải cắt). Các onset cách nhau dưới `merge_ms` được gộp về trung vị.
6. `converter/convert.py` — ghép tất cả: `convert(notes, config) -> ConversionResult`
   với `ConversionResult(sky_notes, transpose, grid_ms, warnings, stats)`. Cấu hình mặc định:
   `grid_ms=120`, `merge_ms=40`, `max_chord=4`. `warnings` chỉ chứa cảnh báo `out_of_scale`;
   `stats` đếm riêng `folded_count` và `out_of_scale_count`.

Xong khi: `test_output.mid` chuyển ra JSON hợp lệ qua exporter của Bước 1, nhập được vào Sky Studio.

Prompt: *"Thực hiện Bước 3, từng hàm một, theo thứ tự 1 đến 6. Dừng sau mỗi hàm để chạy test."*

## Bước 4 — So sánh với bản chép tay

Làm: `tools/compare.py` (hoặc `tests/test_golden.py`).

Cách so sánh (vì hai bản không khớp tuyệt đối):
1. Căn offset: trừ nốt đầu của mỗi bên, hoặc tìm offset tốt nhất bằng tương quan onset.
2. Ghép nốt theo `time` trong dung sai ±60 ms.
3. Báo cáo: precision, recall, F1 của onset; tỷ lệ cùng `key` trong số nốt đã ghép;
   chênh lệch số nốt; chênh lệch độ dài bài.

Ngưỡng ban đầu: chỉ **ghi số liệu**, chưa fail test. Sau khi có số liệu thật thì đặt ngưỡng tối thiểu
để chống thụt lùi (regression). Lưu ý bản MIDI có 650 nốt còn JSON có 989 nốt,
nên recall được dự đoán thấp hơn precision.

Prompt: *"Thực hiện Bước 4. Chỉ in báo cáo số liệu, chưa đặt ngưỡng fail."*

## Bước 5 — Audio và AI Engine

Làm:
- `audio/validate.py`: kiểm tra MP3 (đọc được, độ dài, sample rate), lỗi rõ ràng.
- `ai/transkun_runner.py`: chạy Transkun, tự chọn CUDA hoặc CPU, trả về đường dẫn MIDI.
  Hỗ trợ hủy giữa chừng và báo tiến trình qua callback.
- Phần này tách khỏi `requirements-core.txt`, test bằng mock nên CI không cần GPU.

Xong khi: một MP3 ngắn đi qua cả chuỗi ra MIDI, rồi ra JSON, không crash.

## Bước 6 — Pipeline layer và GUI

Làm:
- `pipeline/job.py`: trạng thái tác vụ (`pending → validating → transcribing → converting → exporting → done|failed|cancelled`),
  chạy nền, phát tín hiệu tiến trình.
- `gui/`: chọn MP3, cấu hình (transpose tự động hoặc thủ công, lưới, metadata),
  thanh tiến trình, nút hủy, xuất kết quả, hiển thị cảnh báo của converter.

Xong khi: chạy end-to-end từ GUI, GUI không bị đơ khi chạy AI.

## Bước 7 — Định dạng xuất khác

Làm: `exporters/vp_sheet.py` và `exporters/one_key_n.py` dùng cùng `list[SkyNote]`.
Cần mẫu đầu ra của từng định dạng trước khi viết. Nếu chưa có thì hỏi lại, đừng đoán.

---

## Danh sách kiểm tra cuối mỗi bước

- [ ] `pytest -q` xanh
- [ ] `ruff check .` và `mypy src` sạch
- [ ] Không import ngược tầng
- [ ] Không sửa `fixtures/`
- [ ] Cập nhật mục "Quyết định còn mở" trong `AGENTS.md` nếu có thông tin mới
