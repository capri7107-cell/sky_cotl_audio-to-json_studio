"""Qt-independent form validation and presentation helpers for the GUI."""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from sky_cotl_studio.audio.download import (
    DownloadError,
    safe_video_filename,
    validate_youtube_url,
)
from sky_cotl_studio.converter.convert import ConversionResult
from sky_cotl_studio.models import SongMeta
from sky_cotl_studio.pipeline.job import ConversionJobConfig, ConversionJobResult


@dataclass(frozen=True)
class ConversionForm:
    """Values collected by the desktop form before starting a conversion."""

    input_mp3: str
    output_json: str
    grid_mode: Literal["auto", "fixed"]
    grid_ms: str
    device: Literal["auto", "cuda", "cpu"]
    title: str
    author: str
    transcribed_by: str
    keep_midi: bool = False


def validate_form(form: ConversionForm) -> tuple[str, ...]:
    """Return all user-correctable form validation errors."""
    errors: list[str] = []
    input_source = form.input_mp3.strip()
    is_url = _looks_like_url(input_source)
    input_path = Path(input_source) if input_source and not is_url else None
    output_path = Path(form.output_json.strip()) if form.output_json.strip() else None

    if not input_source:
        errors.append("Chọn tệp âm thanh hoặc nhập liên kết YouTube.")
    elif is_url:
        try:
            validate_youtube_url(input_source)
        except DownloadError as error:
            errors.append(str(error))
    elif input_source.startswith("-"):
        errors.append("Đường dẫn tệp âm thanh không hợp lệ.")
    if (output_path is None and not is_url) or (
        output_path is not None and output_path.suffix.lower() != ".json"
    ):
        errors.append("Chọn nơi lưu có phần mở rộng .json.")
    if (
        input_path is not None
        and output_path is not None
        and input_path.resolve() == output_path.resolve()
    ):
        errors.append("Tệp MP3 và JSON đầu ra phải khác nhau.")
    if not form.title.strip() and not is_url:
        errors.append("Tên bài hát không được để trống.")
    if form.grid_mode not in ("auto", "fixed"):
        errors.append("Chế độ lưới không hợp lệ.")
    if form.grid_mode == "fixed":
        try:
            grid_ms = float(form.grid_ms)
        except ValueError:
            errors.append("Nhập chu kỳ lưới hợp lệ bằng mili giây.")
        else:
            if not math.isfinite(grid_ms) or grid_ms <= 0:
                errors.append("Chu kỳ lưới phải lớn hơn 0 ms.")
    if form.device not in ("auto", "cuda", "cpu"):
        errors.append("Thiết bị không hợp lệ.")
    return tuple(errors)


def build_job_config(form: ConversionForm) -> ConversionJobConfig:
    """Convert validated form values to the pipeline's immutable job config."""
    errors = validate_form(form)
    if errors:
        raise ValueError("\n".join(errors))

    input_source = form.input_mp3.strip()
    is_url = _looks_like_url(input_source)
    input_path = None if is_url else Path(input_source)
    output_path = (
        Path(form.output_json.strip())
        if form.output_json.strip()
        else Path.cwd() / "video.json"
    )
    return ConversionJobConfig(
        input_path=input_path,
        input_url=input_source if is_url else None,
        output_path_from_title=is_url and not form.output_json.strip(),
        output_path=output_path,
        metadata=SongMeta(
            name=form.title.strip(),
            author=form.author.strip(),
            transcribed_by=form.transcribed_by.strip(),
            is_composed=False,
            bpm=500,
            bits_per_page=16,
            pitch_level=2,
            is_encrypted=False,
        ),
        grid_mode=form.grid_mode,
        grid_ms=float(form.grid_ms) if form.grid_mode == "fixed" else 120.0,
        device=None if form.device == "auto" else form.device,
        keep_midi=form.keep_midi,
    )


def format_summary(result: ConversionJobResult) -> str:
    """Create a concise Vietnamese summary of a completed conversion."""
    conversion = result.conversion
    grid_text = (
        f"{conversion.grid_ms:.1f} ms"
        if conversion.grid_ms is not None
        else "Không lượng tử hóa (giữ timing gốc)"
    )
    lines = [
        f"Số nốt đầu ra: {conversion.stats.output_note_count}",
        f"Lưới: {grid_text}",
        f"Dịch giọng: {conversion.transpose:+d} semitone",
        f"Nốt gập quãng tám: {conversion.stats.folded_count}",
        f"Nốt ngoài thang âm: {conversion.stats.out_of_scale_count}",
    ]
    warnings = [
        warning.message
        for warning in conversion.warnings
        if warning.kind in ("out_of_scale", "grid_fallback") and warning.message
    ]
    if warnings:
        lines.append("Cảnh báo:")
        lines.extend(f"• {warning}" for warning in warnings)
    lines.append("Thời gian từng giai đoạn:")
    lines.extend(
        f"• {phase}: {duration:.3f} s"
        for phase, duration in result.phase_seconds.items()
    )
    return "\n".join(lines)


def format_completion_status(conversion: ConversionResult) -> str:
    """Format the successful result as one concise status-bar line."""
    grid_text = (
        f"{conversion.grid_ms:.2f} ms".replace(".", ",")
        if conversion.grid_ms is not None
        else "dự phòng"
    )
    parts = [
        f"Hoàn tất: {conversion.stats.output_note_count} nốt",
        f"lưới {grid_text}",
    ]
    if conversion.stats.out_of_scale_count:
        parts.append(
            f"{conversion.stats.out_of_scale_count} nốt ngoài thang âm"
        )
    return ", ".join(parts)


def failure_message_vi(user_message: str) -> str:
    """Translate pipeline failure summaries into short Vietnamese UI messages."""
    messages = {
        "The input audio could not be validated.": "Không thể đọc hoặc kiểm tra tệp âm thanh.",
        "The audio could not be transcribed.": "Không thể phiên âm âm thanh thành MIDI.",
        "The generated MIDI could not be read.": "Không thể đọc MIDI được tạo.",
        "The notes could not be converted.": "Không thể chuyển đổi các nốt nhạc.",
        "The output JSON could not be created.": "Không thể tạo tệp JSON đầu ra.",
        "The generated MIDI could not be processed.": "Không thể xử lý MIDI được tạo.",
        "The YouTube URL is invalid.": "Liên kết YouTube không hợp lệ hoặc không được hỗ trợ.",
        "A network error interrupted the YouTube download.": "Không có mạng hoặc kết nối tải xuống bị gián đoạn.",
        "The YouTube video is private or unavailable.": "Video ở chế độ riêng tư hoặc đã bị gỡ.",
        "The YouTube video is age-restricted.": "Video bị giới hạn độ tuổi.",
        "The YouTube video exceeds the duration limit.": "Video vượt quá giới hạn thời lượng cho phép.",
        "Live streams are not supported.": "Không hỗ trợ video phát trực tiếp.",
        "Please update yt-dlp.": "Hãy cập nhật yt-dlp.",
        "No supported JavaScript runtime or video format was found.": "Thiếu JavaScript runtime hoặc không tìm thấy định dạng video hỗ trợ.",
        "The YouTube video could not be downloaded.": "Không thể tải âm thanh từ YouTube.",
    }
    return messages.get(user_message, "Không thể hoàn tất chuyển đổi.")


def grid_mode_from_label(label: str) -> Literal["auto", "fixed"]:
    """Map the user-visible grid-mode label to a typed mode."""
    if label == "Tự động":
        return "auto"
    if label == "Cố định":
        return "fixed"
    raise ValueError(f"Chế độ lưới không hợp lệ: {label}")


def grid_ms_enabled(grid_mode: Literal["auto", "fixed"]) -> bool:
    """Return whether the fixed-grid duration control should be enabled."""
    return grid_mode == "fixed"


def device_from_label(label: str) -> Literal["auto", "cuda", "cpu"]:
    """Map the user-visible device label to a typed device choice."""
    choices: dict[str, Literal["auto", "cuda", "cpu"]] = {
        "Tự động": "auto",
        "CUDA": "cuda",
        "CPU": "cpu",
    }
    try:
        return choices[label]
    except KeyError as error:
        raise ValueError(f"Thiết bị không hợp lệ: {label}") from error


def youtube_output_suggestion(title: str) -> str:
    """Return a safe JSON output path for a downloaded video title."""
    return str(Path.cwd() / f"{safe_video_filename(title)}.json")


def _looks_like_url(value: str) -> bool:
    if not value:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    return bool(urlsplit(value).scheme)
