# Sky CotL MP3 to JSON Studio

Ứng dụng desktop chuyển tệp âm thanh hoặc video YouTube thành MIDI bằng Transkun, rồi chuyển
MIDI thành Sky Studio JSON một bè để chơi trong Sky: Children of the Light.

## Yêu cầu

- Windows.
- Python trong môi trường `pytorch-env` của dự án.
- `ffmpeg` và `ffprobe` có trong `PATH`.
- `yt-dlp` (cài từ `requirements-download.txt`) để tải âm thanh YouTube.
- GPU CUDA là tùy chọn; có thể chạy bằng CPU.

## Cài đặt

Mở PowerShell tại thư mục dự án và chạy:

```powershell
.\scripts\dev.ps1 install
```

## Mở ứng dụng

Chạy `Chạy ứng dụng.vbs` ở thư mục gốc để mở ứng dụng không có cửa sổ console.
Để gỡ lỗi và xem lỗi khởi động trực tiếp, chạy `.\scripts\dev.ps1 app` trong PowerShell.
Nhật ký lần chạy gần nhất được ghi đè tại `logs/last_run.log`; lỗi ngoài dự kiến được ghi
thêm vào `logs/app_error.log`.

## Dòng lệnh

Script `scripts/mp3_to_json.py` nhận đường dẫn MP3 đầu vào và JSON đầu ra. Có thể chạy qua
wrapper của dự án:

```powershell
.\scripts\dev.ps1 mp3 .\input.mp3 .\output.json --device cpu --grid-mode auto
```

Các tùy chọn hiện có:

- `--device cpu|cuda`: chọn thiết bị; mặc định tự chọn.
- `--grid-mode auto|fixed` và `--grid-ms MS`: chọn lưới tự động hoặc lưới cố định.
- `--grid-outliers snap|keep` và `--outlier-ms MS`: mặc định snap các onset về lưới; `keep`
  giữ onset lệch lưới quá ngưỡng đã đặt.
- `--keep-midi`: giữ MIDI trung gian cạnh JSON.
- `--midi-out PATH`: lưu MIDI trung gian tại đường dẫn chỉ định.

Có thể nhập URL YouTube vào ô nguồn của GUI. Mặc định chỉ chấp nhận `youtube.com`,
`music.youtube.com` và `youtu.be`; playlist, livestream và video dài hơn 15 phút không được tải.
Để cập nhật yt-dlp, chạy `.\scripts\dev.ps1 update-ytdlp`.

Ví dụ dùng CUDA và giữ MIDI:

```powershell
.\scripts\dev.ps1 mp3 .\input.mp3 .\output.json --device cuda --keep-midi
```

## Kiểm tra

```powershell
.\scripts\dev.ps1 all
```

## Hạn chế đã biết

- Đầu ra chỉ là một bè Sky Studio JSON.
- Nốt ngoài thang C trưởng được kéo về nốt gần nhất.
- Lưới nhị phân chưa phù hợp với nhịp ba hoặc chùm ba.
- Transkun hiện chạy trên Python 3.14 và có cảnh báo `torch.jit`.
- Chất lượng phiên âm phụ thuộc vào Transkun.
