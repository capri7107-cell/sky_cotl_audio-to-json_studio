# Sky CotL audio to JSON Studio

Ứng dụng Windows chuyển tệp âm thanh hoặc video YouTube thành MIDI bằng Transkun, sau đó
chuyển các nốt thành **Sky Studio JSON một bè** để chơi trong *Sky: Children of the Light*.

## Tính năng

- Giao diện desktop để chọn tệp âm thanh hoặc liên kết YouTube, xem tiến trình và hủy tác vụ.
- Phiên âm âm thanh sang MIDI bằng Transkun, rồi xuất JSON theo định dạng Sky Studio.
- Tệp âm thanh đầu vào trong GUI: MP3, WAV, M4A, FLAC, OGG, OPUS, AAC và WMA.
- Chọn CPU hoặc CUDA; CUDA là tùy chọn.
- Tự ước lượng lưới thời gian hoặc đặt lưới cố định.
- Tùy chỉnh thông tin bài hát trước khi xuất.

## Phạm vi và giới hạn

- Đầu ra chỉ gồm một bè theo thang C trưởng, từ C4 đến C6 (Key0–Key14); không xuất VP Sheet
  hoặc 1KeyN.
- Nốt ngoài C4–C6 được gập quãng tám vào khoảng này. Nốt ngoài thang C trưởng được đưa về
  phím gần nhất và được báo trong kết quả.
- Lưới hiện dùng các phân chia nhị phân, chưa xử lý tốt nhịp ba hoặc chùm ba. Ngưỡng nhận
  diện lưới hiện được hiệu chỉnh trên số fixture còn hạn chế.
- Chất lượng phiên âm phụ thuộc vào Transkun và bản ghi đầu vào.
- Các trường `bpm`, `bitsPerPage` và `pitchLevel` được xuất với giá trị mặc định có thể cấu
  hình trong giao diện; ý nghĩa của chúng chưa được xác nhận.

## Yêu cầu

- Windows và PowerShell.
- Python 3.11 trở lên trong môi trường mà `scripts/dev.ps1` sử dụng.
- `ffmpeg` và `ffprobe` có trong `PATH` để kiểm tra/giải mã âm thanh.
- Các gói chạy GUI và phiên âm AI: PySide6-Essentials, PyTorch và Transkun. CUDA chỉ cần nếu
  muốn chạy bằng GPU.
- `yt-dlp[default]` để tải âm thanh từ YouTube; cần kết nối Internet.

Lệnh `install` bên dưới cài dependency core, công cụ phát triển và yt-dlp. Nó không cài
PySide6, PyTorch hoặc Transkun; các gói GUI/AI cần có sẵn trong môi trường Python cấu hình.
Danh sách dependency tương ứng nằm trong `requirements-gui.txt` và
`requirements-ai.lock.txt`.

## Cài đặt dependency

Mở PowerShell tại thư mục dự án và chạy:

```powershell
.\scripts\dev.ps1 install
```

Script dùng interpreter được cấu hình trong `scripts/dev.ps1` và kiểm tra dependency sau khi
cài. Nếu báo không tìm thấy interpreter, cần cấu hình môi trường Python đó trước khi dùng
các lệnh của dự án.

## Chạy giao diện

Chạy `Chạy ứng dụng.vbs` để mở GUI không có cửa sổ console. Để xem lỗi khởi động trực tiếp:

```powershell
.\scripts\dev.ps1 app
```

Trong GUI, chọn **Audio file** hoặc **YouTube link**. Tệp âm thanh có thể được chọn bằng hộp
thoại hoặc kéo thả. Chọn thư mục lưu qua **Change…**; thư mục được ghi nhớ trong
`settings.json`, mặc định là `output/`. GUI không ghi đè JSON hoặc MIDI đã tồn tại mà thêm
hậu tố như `(2)` hoặc `(3)`.

Liên kết YouTube phải thuộc `youtube.com`, `youtube-nocookie.com` hoặc `youtu.be`. Playlist,
livestream và video dài hơn 15 phút không được hỗ trợ.

GUI ghi đè nhật ký lần chạy gần nhất tại `logs/last_run.log` và ghi lỗi ngoài dự kiến vào
`logs/app_error.log`.

## Dòng lệnh

### Âm thanh MP3 sang JSON

```powershell
.\scripts\dev.ps1 mp3 .\input.mp3 .\output.json
```

Có thể chọn thiết bị và giữ MIDI trung gian:

```powershell
.\scripts\dev.ps1 mp3 .\input.mp3 .\output.json --device cpu --keep-midi
```

Các tùy chọn:

- `--device cpu|cuda`: chọn thiết bị; mặc định tự chọn.
- `--grid-mode auto|fixed`: tự ước lượng lưới (mặc định) hoặc dùng lưới cố định.
- `--grid-ms MS`: độ dài lưới tính bằng mili giây khi dùng `--grid-mode fixed`.
- `--grid-outliers snap|keep`: đưa onset lệch lưới về lưới (`snap`, mặc định) hoặc giữ lại
  onset lệch quá ngưỡng.
- `--outlier-ms MS`: ngưỡng lệch lưới, mặc định 40 ms.
- `--keep-midi`: giữ MIDI trung gian cạnh tệp JSON.
- `--midi-out PATH`: lưu MIDI trung gian tại đường dẫn chỉ định; tùy chọn này cũng giữ MIDI.

### MIDI sang JSON

```powershell
.\scripts\dev.ps1 convert .\input.mid .\output.json
```

Lệnh này cũng nhận các tùy chọn `--grid-mode`, `--grid-ms`, `--grid-outliers` và
`--outlier-ms`.

### Tải YouTube để chẩn đoán

Để cập nhật yt-dlp:

```powershell
.\scripts\dev.ps1 update-ytdlp
```

Để kiểm tra tải một liên kết và xem thông tin tiến trình:

```powershell
.\scripts\dev.ps1 debug-download "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Kiểm tra chất lượng

```powershell
.\scripts\dev.ps1 test
.\scripts\dev.ps1 lint
.\scripts\dev.ps1 types
```

Chạy cả ba bước bằng một lệnh:

```powershell
.\scripts\dev.ps1 all
```

Kiểm thử GPU tùy chọn:

```powershell
.\scripts\dev.ps1 test-gpu
```
