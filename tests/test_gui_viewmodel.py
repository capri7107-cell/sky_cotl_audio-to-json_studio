from pathlib import Path

from sky_cotl_studio.audio.download import safe_video_filename
from sky_cotl_studio.converter.convert import ConversionResult, ConversionStats
from sky_cotl_studio.converter.mapping import MappingWarning
from sky_cotl_studio.gui.viewmodel import (
    ConversionForm,
    build_job_config,
    failure_message_vi,
    format_completion_status,
    format_summary,
    grid_ms_enabled,
    validate_form,
)
from sky_cotl_studio.models import SkyNote
from sky_cotl_studio.pipeline.job import ConversionJobResult


def _form(**overrides: object) -> ConversionForm:
    values: dict[str, object] = {
        "input_mp3": "song.mp3",
        "output_json": "song.json",
        "grid_mode": "auto",
        "grid_ms": "",
        "device": "auto",
        "title": "Bài hát",
        "author": "Tác giả",
        "transcribed_by": "Người chép",
        "keep_midi": False,
    }
    values.update(overrides)
    return ConversionForm(**values)  # type: ignore[arg-type]


def test_validate_form_requires_files_metadata_and_fixed_grid() -> None:
    assert validate_form(_form()) == ()
    assert "Chọn tệp âm thanh hoặc nhập liên kết YouTube." in validate_form(
        _form(input_mp3="", output_json="")
    )
    assert any(
        "lưới" in message.lower()
        for message in validate_form(_form(grid_mode="fixed", grid_ms="bad"))
    )


def test_youtube_form_allows_automatic_output_and_empty_video_title() -> None:
    errors = validate_form(
        _form(
            input_mp3="https://youtu.be/example",
            output_json="",
            title="",
        )
    )

    assert errors == ()
    config = build_job_config(
        _form(
            input_mp3="https://youtu.be/example",
            output_json="",
            title="",
        )
    )
    assert config.input_url == "https://youtu.be/example"
    assert config.output_path_from_title
    assert config.metadata.name == ""


def test_video_title_is_made_safe_for_a_windows_filename() -> None:
    assert safe_video_filename('Vết Mưa: "Live"') == "Vết Mưa_ _Live_"
    assert safe_video_filename("...") == "youtube-video"


def test_youtube_failures_are_translated_to_short_vietnamese_messages() -> None:
    expected_messages = {
        "The YouTube URL is invalid.": "Liên kết YouTube không hợp lệ hoặc không được hỗ trợ.",
        "A network error interrupted the YouTube download.": "Không có mạng hoặc kết nối tải xuống bị gián đoạn.",
        "The YouTube video is private or unavailable.": "Video ở chế độ riêng tư hoặc đã bị gỡ.",
        "The YouTube video is age-restricted.": "Video bị giới hạn độ tuổi.",
        "The YouTube video exceeds the duration limit.": "Video vượt quá giới hạn thời lượng cho phép.",
        "Live streams are not supported.": "Không hỗ trợ video phát trực tiếp.",
        "Please update yt-dlp.": "Hãy cập nhật yt-dlp.",
        "No supported JavaScript runtime or video format was found.": "Thiếu JavaScript runtime hoặc không tìm thấy định dạng video hỗ trợ.",
    }

    for user_message, translated in expected_messages.items():
        assert failure_message_vi(user_message) == translated


def test_build_job_config_maps_form_values_to_job_configuration() -> None:
    config = build_job_config(
        _form(
            input_mp3="audio.mp3",
            output_json="exports/song.json",
            grid_mode="fixed",
            grid_ms="187.5",
            device="cuda",
            keep_midi=True,
        )
    )

    assert config.input_path == Path("audio.mp3")
    assert config.output_path == Path("exports/song.json")
    assert config.grid_mode == "fixed"
    assert config.grid_ms == 187.5
    assert config.device == "cuda"
    assert config.keep_midi
    assert config.metadata.name == "Bài hát"


def test_summary_includes_conversion_metrics_warnings_and_phase_durations() -> None:
    conversion = ConversionResult(
        sky_notes=[SkyNote(time_ms=0, key=1), SkyNote(time_ms=120, key=2)],
        transpose=-2,
        grid_ms=187.2,
        warnings=[
            MappingWarning(
                kind="out_of_scale",
                message="MIDI pitch 66 mapped from 66 to 67",
            )
        ],
        stats=ConversionStats(
            input_note_count=4,
            merged_onset_count=2,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=2,
            distinct_time_count=2,
            max_chord_size=1,
            folded_count=1,
            out_of_scale_count=1,
        ),
    )
    result = ConversionJobResult(
        json_path=Path("song.json"),
        midi_path=None,
        conversion=conversion,
        device="cpu",
        phase_seconds={"validate": 0.1, "transcribe": 2.5, "convert": 0.2},
        leading_silence_ms=30,
    )

    summary = format_summary(result)

    assert "2" in summary
    assert "187.2 ms" in summary
    assert "-2" in summary
    assert "1" in summary
    assert "MIDI pitch 66 mapped from 66 to 67" in summary
    assert "transcribe: 2.500 s" in summary


def test_summary_handles_no_detected_grid() -> None:
    result = ConversionJobResult(
        json_path=Path("song.json"),
        midi_path=None,
        conversion=ConversionResult(
            sky_notes=[],
            transpose=0,
            grid_ms=None,
            warnings=[
                MappingWarning(
                    kind="grid_fallback",
                    message="Không tìm thấy lưới ổn định.",
                )
            ],
            stats=ConversionStats(
                input_note_count=0,
                merged_onset_count=0,
                deduplicated_count=0,
                chord_trimmed_count=0,
                output_note_count=0,
                distinct_time_count=0,
                max_chord_size=0,
                folded_count=0,
                out_of_scale_count=0,
            ),
        ),
        device="cpu",
        phase_seconds={},
        leading_silence_ms=0,
    )

    assert "Không lượng tử hóa" in format_summary(result)


def test_fixed_grid_ms_must_be_positive() -> None:
    errors = validate_form(_form(grid_mode="fixed", grid_ms="0"))

    assert errors


def test_grid_ms_enabled_only_for_fixed_mode() -> None:
    assert grid_ms_enabled("fixed")
    assert not grid_ms_enabled("auto")


def test_completion_status_formats_grid_and_out_of_scale_count() -> None:
    conversion = ConversionResult(
        sky_notes=[SkyNote(time_ms=0, key=1)],
        transpose=0,
        grid_ms=119.99,
        warnings=[],
        stats=ConversionStats(
            input_note_count=1,
            merged_onset_count=1,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=649,
            distinct_time_count=1,
            max_chord_size=1,
            folded_count=0,
            out_of_scale_count=18,
        ),
    )

    assert format_completion_status(conversion) == (
        "Hoàn tất: 649 nốt, lưới 119,99 ms, 18 nốt ngoài thang âm"
    )


def test_completion_status_reports_grid_fallback() -> None:
    conversion = ConversionResult(
        sky_notes=[],
        transpose=0,
        grid_ms=None,
        warnings=[],
        stats=ConversionStats(
            input_note_count=0,
            merged_onset_count=0,
            deduplicated_count=0,
            chord_trimmed_count=0,
            output_note_count=0,
            distinct_time_count=0,
            max_chord_size=0,
            folded_count=0,
            out_of_scale_count=0,
        ),
    )

    assert format_completion_status(conversion) == (
        "Hoàn tất: 0 nốt, lưới dự phòng"
    )
