"""Background orchestration for the MP3-to-Sky-JSON conversion pipeline."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, TypeVar

from sky_cotl_studio.ai.transkun_runner import (
    Device,
    TranskunCancelledError,
    TranskunError,
    resolve_device,
    transcribe,
)
from sky_cotl_studio.audio.validate import AudioValidationError, validate_mp3
from sky_cotl_studio.converter.config import ConverterConfig
from sky_cotl_studio.converter.convert import ConversionResult, convert
from sky_cotl_studio.exporters.sky_studio import export
from sky_cotl_studio.midi.cleanup import trim_leading_silence
from sky_cotl_studio.midi.reader import read_notes
from sky_cotl_studio.models import SongMeta


class JobState(Enum):
    """Lifecycle state for a conversion job."""

    PENDING = "pending"
    VALIDATING = "validating"
    TRANSCRIBING = "transcribing"
    CONVERTING = "converting"
    EXPORTING = "exporting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConversionJobConfig:
    """Input, output, converter, device, and metadata settings for a job."""

    input_path: Path
    output_path: Path
    metadata: SongMeta
    grid_mode: Literal["auto", "fixed"] = "auto"
    grid_ms: float = 120
    device: Device | None = None
    keep_midi: bool = False
    midi_out: Path | None = None
    merge_ms: float = 40
    max_chord: int = 4

    def __post_init__(self) -> None:
        ConverterConfig(
            grid_mode=self.grid_mode,
            grid_ms=self.grid_ms,
            merge_ms=self.merge_ms,
            max_chord=self.max_chord,
        )
        if self.device not in (None, "cpu", "cuda"):
            raise ValueError("device must be 'cpu', 'cuda', or None")
        if self.midi_out is not None and _same_path(self.input_path, self.midi_out):
            raise ValueError("MIDI output path must differ from the MP3 input path")
        if _same_path(self.input_path, self.output_path):
            raise ValueError("JSON output path must differ from the MP3 input path")
        retained_midi_path = self.retained_midi_path
        if retained_midi_path is not None and _same_path(
            retained_midi_path,
            self.output_path,
        ):
            raise ValueError("MIDI and JSON output paths must differ")

    @property
    def retained_midi_path(self) -> Path | None:
        """Return the requested persistent MIDI path, if any."""
        if self.midi_out is not None:
            return self.midi_out
        if self.keep_midi:
            return self.output_path.with_suffix(".mid")
        return None


@dataclass(frozen=True)
class JobProgress:
    """A phase-aware progress event delivered from the worker thread."""

    phase: JobState
    message: str
    percentage: float | None = None


ProgressCallback = Callable[[JobProgress], None]


@dataclass(frozen=True)
class ConversionJobResult:
    """Published outputs and timing information from a successful job."""

    json_path: Path
    midi_path: Path | None
    conversion: ConversionResult
    device: Device
    phase_seconds: dict[str, float]
    leading_silence_ms: float


@dataclass(frozen=True)
class JobFailure:
    """User-facing failure summary and the separate technical cause."""

    user_message: str
    technical_cause: str


class ConversionJobError(Exception):
    """Raised by synchronous callers when a background job has failed."""

    def __init__(self, failure: JobFailure) -> None:
        super().__init__(failure.user_message)
        self.failure = failure


class ConversionJobCancelled(Exception):
    """Raised by synchronous callers when a job was cancelled."""


class _JobCancelled(Exception):
    pass


T = TypeVar("T")

_ACTIVE_JOB_LOCK = threading.Lock()
_ACTIVE_JOB: ConversionJob | None = None


class ConversionJob:
    """Run one conversion on a background thread and expose its state/result.

    Progress callbacks execute on the worker thread. A GUI must explicitly
    marshal callback events to its interface thread before updating widgets.
    """

    def __init__(
        self,
        config: ConversionJobConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self._progress_callback = progress_callback
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._state = JobState.PENDING
        self._thread: threading.Thread | None = None
        self._result: ConversionJobResult | None = None
        self._failure: JobFailure | None = None
        self._operation = "validate"

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    @property
    def result(self) -> ConversionJobResult | None:
        with self._lock:
            return self._result

    @property
    def failure(self) -> JobFailure | None:
        with self._lock:
            return self._failure

    def start(self) -> None:
        """Start the worker and return without waiting for conversion."""
        global _ACTIVE_JOB

        with _ACTIVE_JOB_LOCK:
            if _ACTIVE_JOB is not None:
                raise RuntimeError("A conversion job is already running")
            if self._thread is not None or self.state is not JobState.PENDING:
                raise RuntimeError("This conversion job has already been started")
            _ACTIVE_JOB = self
            self._thread = threading.Thread(
                target=self._run,
                name="sky-cotl-conversion",
                daemon=True,
            )
            try:
                self._thread.start()
            except BaseException:
                _ACTIVE_JOB = None
                self._thread = None
                raise

    def cancel(self) -> None:
        """Request cancellation; an active Transkun child is stopped by its runner."""
        if self.state not in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
            self._cancel_event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the background thread; return whether it has finished."""
        thread = self._thread
        if thread is None:
            return self.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED)
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        global _ACTIVE_JOB

        staged_midi: Path | None = None
        staged_json: Path | None = None
        try:
            phase_seconds: dict[str, float] = {}
            self._set_state(JobState.VALIDATING, "Validating MP3", 0)
            _check_cancel(self._cancel_event)
            audio_info, phase_seconds["validate"] = _measure(
                lambda: validate_mp3(self.config.input_path)
            )

            self._operation = "transcribe"
            self._set_state(JobState.TRANSCRIBING, "Transcribing MP3", 10)
            device = resolve_device(self.config.device)
            transcription_path = _temporary_path(
                self.config.output_path.parent,
                self.config.output_path.stem,
                ".mid",
            )
            staged_midi = transcription_path
            _, phase_seconds["transcribe"] = _measure(
                lambda: transcribe(
                    self.config.input_path,
                    transcription_path,
                    device=device,
                    progress_callback=self._transcription_progress,
                    cancel_event=self._cancel_event,
                    validated_audio=audio_info,
                )
            )
            _check_cancel(self._cancel_event)

            self._set_state(JobState.CONVERTING, "Reading generated MIDI", 45)
            self._operation = "read_midi"
            midi_notes, phase_seconds["read_midi"] = _measure(
                lambda: read_notes(transcription_path)
            )
            _check_cancel(self._cancel_event)
            self._operation = "trim"
            self._notify(
                JobProgress(JobState.CONVERTING, "Trimming leading silence", 50)
            )
            (trimmed_notes, _leading_silence_ms), phase_seconds["trim"] = _measure(
                lambda: trim_leading_silence(midi_notes)
            )
            _check_cancel(self._cancel_event)
            self._operation = "convert"
            self._notify(
                JobProgress(JobState.CONVERTING, "Converting MIDI notes", 60)
            )
            converter_config = ConverterConfig(
                grid_mode=self.config.grid_mode,
                grid_ms=self.config.grid_ms,
                merge_ms=self.config.merge_ms,
                max_chord=self.config.max_chord,
            )
            conversion, phase_seconds["convert"] = _measure(
                lambda: convert(trimmed_notes, converter_config)
            )

            self._operation = "export"
            self._set_state(JobState.EXPORTING, "Exporting JSON", 80)
            json_content, phase_seconds["export"] = _measure(
                lambda: export(self.config.metadata, conversion.sky_notes)
            )
            _check_cancel(self._cancel_event)
            staged_json = _temporary_path(
                self.config.output_path.parent,
                self.config.output_path.stem,
                ".json",
            )
            staged_json.write_text(json_content, encoding="utf-8")

            retained_midi_path = self.config.retained_midi_path
            if retained_midi_path is not None:
                retained_midi_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(transcription_path, retained_midi_path)
                staged_midi = None
            os.replace(staged_json, self.config.output_path)
            staged_json = None

            result = ConversionJobResult(
                json_path=self.config.output_path,
                midi_path=retained_midi_path,
                conversion=conversion,
                device=device,
                phase_seconds=phase_seconds,
                leading_silence_ms=_leading_silence_ms,
            )
            with self._lock:
                self._result = result
            self._set_state(JobState.DONE, "Conversion complete", 100)
        except _JobCancelled:
            self._set_terminal(JobState.CANCELLED, notify=True)
        except TranskunCancelledError as error:
            if self._cancel_event.is_set():
                self._set_terminal(JobState.CANCELLED, notify=True)
            else:
                self._record_failure(error)
        except BaseException as error:  # noqa: BLE001 - never leak errors from the worker thread
            self._record_failure(error)
        finally:
            cleanup_error: OSError | None = None
            for path in (staged_midi, staged_json):
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as error:
                        cleanup_error = error
            if cleanup_error is not None:
                self._record_failure(cleanup_error)
            with _ACTIVE_JOB_LOCK:
                if _ACTIVE_JOB is self:
                    _ACTIVE_JOB = None

    def _transcription_progress(self, message: str) -> None:
        self._notify(JobProgress(JobState.TRANSCRIBING, message, None))

    def _set_state(
        self,
        state: JobState,
        message: str,
        percentage: float,
    ) -> None:
        with self._lock:
            self._state = state
        self._notify(JobProgress(state, message, percentage))

    def _set_terminal(self, state: JobState, *, notify: bool) -> None:
        with self._lock:
            self._state = state
            failure = self._failure
        if notify:
            message = (
                failure.user_message
                if state is JobState.FAILED and failure is not None
                else "Conversion cancelled"
            )
            try:
                self._notify(JobProgress(state, message, None))
            except BaseException as error:  # noqa: BLE001 - keep callback errors in job state
                with self._lock:
                    prior_cause = (
                        f"{self._failure.technical_cause}; "
                        if self._failure is not None
                        else ""
                    )
                    self._failure = JobFailure(
                        user_message="The progress callback failed.",
                        technical_cause=(
                            f"{prior_cause}{type(error).__name__}: {error}"
                        ),
                    )
                    self._state = JobState.FAILED

    def _record_failure(self, error: BaseException) -> None:
        with self._lock:
            previous_failure = self._failure
            if previous_failure is None:
                failure = JobFailure(
                    user_message=_user_message(self._operation, error),
                    technical_cause=f"{type(error).__name__}: {error}",
                )
            else:
                failure = JobFailure(
                    user_message=previous_failure.user_message,
                    technical_cause=(
                        f"{previous_failure.technical_cause}; "
                        f"cleanup failed: {type(error).__name__}: {error}"
                    ),
                )
            self._failure = failure
        self._set_terminal(JobState.FAILED, notify=True)

    def _notify(self, event: JobProgress) -> None:
        callback = self._progress_callback
        if callback is not None:
            callback(event)


def _check_cancel(cancel_event: threading.Event) -> None:
    if cancel_event.is_set():
        raise _JobCancelled


def _measure(operation: Callable[[], T]) -> tuple[T, float]:
    start = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - start


def _temporary_path(directory: Path, stem: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{stem}.",
        suffix=suffix,
        dir=directory,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _same_path(first: str | Path, second: str | Path) -> bool:
    return Path(first).resolve() == Path(second).resolve()


def _user_message(stage: str, error: BaseException) -> str:
    if stage == "validate" or isinstance(error, AudioValidationError):
        return "The input MP3 could not be validated."
    if stage == "transcribe" or isinstance(error, TranskunError):
        return "The MP3 could not be transcribed."
    if stage == "read_midi":
        return "The generated MIDI could not be read."
    if stage == "convert":
        return "The notes could not be converted."
    if stage == "export":
        return "The output JSON could not be created."
    return "The generated MIDI could not be processed."
