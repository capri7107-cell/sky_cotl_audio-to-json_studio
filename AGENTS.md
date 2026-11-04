# AGENTS.md — sky_cotl_mp3-to-json_studio

Hướng dẫn cho AI agent (VS Code / Copilot agent mode) khi làm việc trong repo này.
Đọc file này và `PLAN.md` trước khi viết code.

## 1. Dự án là gì

Ứng dụng desktop chuyển **tệp âm thanh hoặc YouTube → MIDI → JSON** để chơi nhạc trong *Sky: Children of the Light*.

Luồng xử lý (7 tầng, phụ thuộc một chiều từ trên xuống):

1. `gui` — Desktop GUI (PySide6): nhập MP3, cấu hình, theo dõi tiến trình, xuất kết quả
2. `pipeline` — điều phối các bước và quản lý trạng thái tác vụ
3. `audio` — kiểm tra âm thanh, tải YouTube, tiền xử lý
4. `ai` — Transkun (PyTorch, CUDA): MP3 → MIDI
5. `midi` — đọc MIDI, trích xuất nốt, hiệu chỉnh dữ liệu
6. `converter` — cao độ → Key 0–14, lượng tử hóa nhịp, hợp âm, timing
7. `exporters` — Sky Studio JSON một bè

Quy tắc phụ thuộc: tầng dưới **không** import tầng trên. `midi`, `converter`, `exporters`
phải chạy được không cần GUI, không cần GPU, không cần PyTorch.

Phạm vi xuất của dự án dừng ở Sky Studio JSON một bè; không làm VP Sheet hay 1KeyN.

## 2. Stack

- Python 3.11+
- PySide6-Essentials (GUI), PyTorch + Transkun (AI), `pytest` (test), `ruff` + `mypy` (lint, type)
- Đọc MIDI: dùng `mido` hoặc `pretty_midi`; nếu không có thì tự parse. Không giả định tempo cố định.
- Tách dependency: `requirements-core.txt` (midi/converter/exporters/test),
  `requirements-ai.txt` (torch, transkun), `requirements-gui.txt` (PySide6-Essentials)
  và `requirements-download.txt` (`yt-dlp[default]`).

## 3. Cấu trúc thư mục

```
sky_cotl_mp3-to-json_studio/
├─ AGENTS.md
├─ PLAN.md
├─ pyproject.toml
├─ src/sky_cotl_studio/
│  ├─ models.py          # Note, SkyNote, SongMeta (dataclass)
│  ├─ gui/
│  ├─ pipeline/
│  ├─ audio/
│  ├─ ai/
│  ├─ midi/
│  ├─ converter/
│  └─ exporters/
├─ tests/
└─ fixtures/
   ├─ test_output.mid     # đầu ra mẫu của Transkun
   └─ Summertime.json     # JSON đích mẫu (bản chép tay)
```

## 4. Mô hình dữ liệu

```python
@dataclass(frozen=True)
class Note:            # nốt thô từ MIDI
    time_ms: float
    duration_ms: float
    pitch: int         # MIDI note number
    velocity: int

@dataclass(frozen=True)
class SkyNote:         # nốt đã ánh xạ
    time_ms: int       # đã lượng tử hóa
    key: int           # 0..14
```

## 5. Định dạng JSON đích (Sky Studio JSON)

Rút ra từ `fixtures/Summertime.json` (file mẫu có thêm chữ số layer ở đầu key, dự án này bỏ qua). Gốc là **mảng chứa 1 object**:

```json
[
  {
    "name": "Summertime",
    "author": "…",
    "transcribedBy": "…",
    "isComposed": true,
    "bpm": 500,
    "bitsPerPage": 16,
    "pitchLevel": 2,
    "isEncrypted": false,
    "songNotes": [
      { "time": 0, "key": "Key11" },
      { "time": 240, "key": "Key11" },
      { "time": 480, "key": "Key9" }
    ]
  }
]
```

Quy tắc:

- `time` là số nguyên, đơn vị ms, tính từ nốt đầu của bài.
- `key` = `"Key{n}"`, `n` ∈ 0..14. **Không dùng layer**: đầu ra là một bè duy nhất.
- Khi **đọc** JSON có sẵn (như `Summertime.json`, key dạng `"1Key11"`, `"2Key3"`), bỏ chữ số đầu và chỉ lấy `n`.
- `songNotes` sắp xếp tăng dần theo `time`. Nốt cùng lúc là các phần tử riêng cùng `time`.
- Không có hai phần tử trùng cả `time` lẫn `key`. Khi gập quãng tám khiến hai nốt cùng thời điểm rơi vào cùng một phím thì chỉ giữ một.
- Không thêm trường lạ vào `songNotes`.

Đặc điểm của file mẫu (dùng để kiểm tra độ hợp lý):

- Lưới thời gian 120 ms. Khoảng cách giữa các onset chủ yếu là 240 ms, ít hơn là 480 và 120.
- Hợp âm thường 1–3 nốt, hiếm khi 4.
- `bpm`, `bitsPerPage`, `pitchLevel` là tham số có thể cấu hình. Ý nghĩa chính xác chưa được xác nhận,
  đừng tự suy diễn. Dùng giá trị mặc định của file mẫu và để người dùng sửa.
- Chỉ `fixtures/Summertime.json` là bản chép tay thật trong repo. Theo kết quả thử của người dùng,
  `bpm` không ảnh hưởng đến phát trong app.
- Các JSON khác trong `fixtures/local/` là đầu ra của ứng dụng, không dùng làm đáp án tham chiếu.

### Thang âm Sky (đã xác nhận)

`Key0`–`Key14` tương ứng **C4–C6**, 15 phím theo thang C trưởng (quy ước MIDI: C4 = 60, C6 = 84).

| Key | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nốt | C4 | D4 | E4 | F4 | G4 | A4 | B4 | C5 | D5 | E5 | F5 | G5 | A5 | B5 | C6 |
| MIDI | 60 | 62 | 64 | 65 | 67 | 69 | 71 | 72 | 74 | 76 | 77 | 79 | 81 | 83 | 84 |

Trong code: `KEY0_MIDI_PITCH = 60`, `KEY_SEMITONE_OFFSETS = [0,2,4,5,7,9,11,12,14,16,17,19,21,23,24]`.

Kiểm chứng trên fixtures: bảy nốt đầu của `Summertime.json` (G5 G5 E5 A5 G5 E5 C5) khớp với bảy nốt đầu của MIDI
khi dịch **−2 semitone** (bài gốc ở D trưởng, dịch về C trưởng). Chỉ lệch ở nốt thứ 6: MIDI cho 76, JSON ứng với 78.
Chưa rõ đó là lỗi của Transkun hay do bản chép tay.

## 6. Quyết định

Đã chốt:

- `grid_outliers="snap"` là mặc định. `keep` chỉ là tùy chọn dòng lệnh, không đưa lên GUI,
  vì thử nghe trên Imagine Dragons không phân biệt được hai chế độ.
- Ngưỡng “lệch quá 40 ms” trong `fidelity` chỉ là số liệu tham khảo, không dùng làm tiêu chí
  chọn chế độ lưới.
- Không thêm thuật toán lưới mới trừ khi có bằng chứng nghe được.

### Quyết định còn mở (đừng tự chốt, hãy để cấu hình được)

| Vấn đề | Cách xử lý tạm |
|---|---|
| Nốt ngoài thang âm | Đưa về nốt gần nhất, ghi vào danh sách cảnh báo trong kết quả. |
| Nốt ngoài C4–C6 (MIDI mẫu có khoảng 35% nốt thấp hơn C4 sau khi dịch) | Gập quãng tám vào C4–C6, vì không có layer để tách bè trầm. |
| Lưới thời gian | Mặc định `grid_mode="auto"` khớp bình phương tối thiểu chu kỳ và pha trên onset đã gộp; xét lưới 100–1000 ms, gồm nhịp và các ước số nhị phân 1/2, 1/4, 1/8. Chỉ nhận lưới mịn hơn khi bước ≥100 ms, RMS ≤25 ms, RMS không quá 0.75 lần lưới thô hơn, và có ít nhất 2 onset ở chỉ số lẻ cách lưới trong ±25 ms. Có thể đặt `grid_mode="fixed"` để dùng `grid_ms`. Giữ nguyên `bpm` vì ý nghĩa chưa xác nhận. Ngưỡng chỉ dựa trên hai fixture, phải xem lại khi có thêm MP3. |

## 7. Quy tắc làm việc

- Mỗi lần chỉ làm **một bước** trong `PLAN.md`. Xong bước nào thì chạy test của bước đó rồi dừng.
- Viết test trước hoặc cùng lúc với code. Không merge code của `midi`, `converter`, `exporters`
  nếu chưa có test.
- Hàm thuần (pure function) cho `midi`, `converter`, `exporters`: nhận dữ liệu, trả dữ liệu,
  không đọc/ghi file ngầm.
- Đơn vị thời gian trong code là **ms (float)** cho đến bước lượng tử hóa, sau đó là **int ms**.
- Không hard-code tempo 120 BPM. Tempo trong MIDI của Transkun chỉ là mặc định, không phản ánh bài hát.
- Việc nặng (AI, đọc file lớn) không được chạy trên thread của GUI.
- Có type hint cho mọi hàm công khai. `ruff` và `mypy` phải sạch.
- Không thêm dependency mới nếu chưa nói rõ lý do trong mô tả thay đổi.
- Không sửa file trong `fixtures/`.

## 8. Môi trường Python

- Interpreter duy nhất: `D:\My Folder\Environment\pytorch-env\Scripts\python.exe`.
- Không gọi `py`, `python`, `pip` trần. Mọi lệnh chạy qua `scripts/dev.ps1`:
  `./scripts/dev.ps1 install | test | lint | types | all`
- Không dùng `pip install --upgrade` trong môi trường này, ngoại trừ lệnh `update-ytdlp`
  trong `scripts/dev.ps1` để chạy `pip install -U yt-dlp[default]`. Sau khi cài/cập nhật gói,
  lệnh wrapper chạy `pip check`.
- Các dependency được chia theo nhóm trong `requirements-core.txt`, `requirements-dev.txt`,
  `requirements-ai.txt`, `requirements-gui.txt` và `requirements-download.txt`.

### GUI, nhật ký và tiến trình con

- `Chạy ứng dụng.vbs` mở GUI ở chế độ im lặng qua `scripts/dev.ps1 app-silent`;
  `scripts/dev.ps1 app` giữ console để gỡ lỗi. Không thêm interpreter path thứ hai vào launcher.
- GUI ghi lần chạy gần nhất vào `logs/last_run.log` (ghi đè) và lỗi ngoài dự kiến vào
  `logs/app_error.log`; không đưa nhật ký kỹ thuật lên widget giao diện.
- Các subprocess ffprobe, ffmpeg và Transkun phải dùng `CREATE_NO_WINDOW` trên Windows.
  Khi runner được khởi chạy bằng `pythonw.exe`, tiến trình Transkun phải dùng `python.exe`
  cùng thư mục để stdout/stderr có thể được đọc.
- Mọi đầu ra console phải bỏ qua việc in khi `sys.stdout is None`; không gắn `StreamHandler`
  trực tiếp vào `sys.stdout` trong các chế độ chạy GUI.
- Không import `yt_dlp` trong code; chỉ gọi `sys.executable -m yt_dlp` bằng subprocess trong
  `audio/download.py`. Khi interpreter là `pythonw.exe`, dùng `python.exe` cùng thư mục.

## 9. Những điều không được làm

- Không import `PySide6` hay `torch` bên trong `midi`, `converter`, `exporters`.
- Không coi `Summertime.json` là đáp án chính xác từng nốt. Đó là bản chép tay và có khác biệt
  so với kết quả MIDI. Chỉ so sánh có dung sai (xem `PLAN.md`, bước 4).
- Không bịa ý nghĩa cho `pitchLevel`, `bitsPerPage`, `bpm`.
