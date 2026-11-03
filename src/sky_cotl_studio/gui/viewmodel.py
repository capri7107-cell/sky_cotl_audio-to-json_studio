"""Qt-independent form validation and presentation helpers for the GUI."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    input_path = Path(form.input_mp3.strip()) if form.input_mp3.strip() else None
    output_path = Path(form.output_json.strip()) if form.output_json.strip() else None

    if input_path is None or input_path.suffix.lower() != ".mp3":
        errors.append("Chọn tệp MP3 hợp lệ.")
    if output_path is None or output_path.suffix.lower() != ".json":
        errors.append("Chọn nơi lưu có phần mở rộng .json.")
    if (
        input_path is not None
        and output_path is not None
        and input_path.resolve() == output_path.resolve()
    ):
        errors.append("Tệp MP3 và JSON đầu ra phải khác nhau.")
    if not form.title.strip():
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

    input_path = Path(form.input_mp3.strip())
    output_path = Path(form.output_json.strip())
    return ConversionJobConfig(
        input_path=input_path,
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


def grid_mode_from_label(label: str) -> Literal["auto", "fixed"]:
    """Map the user-visible grid-mode label to a typed mode."""
    if label == "Tự động":
        return "auto"
    if label == "Cố định":
        return "fixed"
    raise ValueError(f"Chế độ lưới không hợp lệ: {label}")


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
