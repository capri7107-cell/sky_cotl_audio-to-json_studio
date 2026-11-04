"""Download validated YouTube audio through the yt-dlp command-line module."""

from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.parse import parse_qs, urlsplit, urlunsplit

DEFAULT_YOUTUBE_DOMAINS = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
)
_PERCENTAGE_PATTERN = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)%")
_TITLE_MARKER = "SKYCOTL_TITLE="
_STREAM_END = object()


class DownloadError(Exception):
    """A yt-dlp failure with a stable category for user-facing translation."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        output: str = "",
        argv: tuple[str, ...] = (),
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.output = output
        self.argv = argv
        self.stderr = stderr


class InvalidYouTubeUrlError(DownloadError):
    """The source is not an allowed HTTP(S) YouTube URL."""

    def __init__(
        self,
        message: str = "Only YouTube links are supported.",
        *,
        category: str = "invalid_url",
    ) -> None:
        super().__init__(message, category=category)


class DownloadCancelledError(DownloadError):
    """The yt-dlp process tree was stopped at the user's request."""

    def __init__(self) -> None:
        super().__init__("The download was cancelled.", category="cancelled")


@dataclass(frozen=True)
class DownloadProgress:
    """One parsed yt-dlp output update."""

    percentage: float | None = None
    message: str = ""
    title: str | None = None
    stream: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    """Downloaded WAV path and the video title printed by yt-dlp."""

    audio_path: Path
    title: str
    argv: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""


def sanitize_video_title(title: str) -> str:
    """Remove control characters and cap a displayable title at 120 characters."""
    return "".join(character for character in title if character.isprintable()).strip()[
        :120
    ]


ProgressCallback = Callable[[DownloadProgress], None]


def build_download_command(
    url: str,
    temporary_directory: str | Path,
    *,
    max_duration_seconds: float = 900,
    allowed_domains: Iterable[str] = DEFAULT_YOUTUBE_DOMAINS,
) -> list[str]:
    """Build the exact yt-dlp argv used by the downloader."""
    validated_url = validate_youtube_url(url, allowed_domains)
    if max_duration_seconds <= 0 or not float(max_duration_seconds).is_integer():
        raise ValueError("max_duration_seconds must be a positive whole number")
    output_template = str(Path(temporary_directory) / "source.%(ext)s")
    return [
        _child_python_executable(),
        "-m",
        "yt_dlp",
        "--no-playlist",
        "-x",
        "--audio-format",
        "wav",
        "--newline",
        "--match-filter",
        f"!is_live & duration <= {max_duration_seconds:g}",
        "--no-simulate",
        "--progress",
        "--print",
        f"{_TITLE_MARKER}%(title)s",
        "-o",
        output_template,
        "--",
        validated_url,
    ]


def validate_youtube_url(
    url: str,
    allowed_domains: Iterable[str] = DEFAULT_YOUTUBE_DOMAINS,
) -> str:
    """Validate a URL against the configured scheme and exact hostname allowlist."""
    candidate = _trim_url_wrapping(url)
    if not candidate or candidate.startswith("-"):
        raise InvalidYouTubeUrlError
    if (
        not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", candidate)
        and _looks_like_domain_prefix(candidate)
    ):
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise InvalidYouTubeUrlError(
            "This link is not formatted correctly.",
            category="invalid_format",
        ) from error
    if parsed.scheme.lower() not in ("http", "https"):
        raise InvalidYouTubeUrlError
    if not hostname:
        raise InvalidYouTubeUrlError(
            "This link is not formatted correctly.",
            category="invalid_format",
        )
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise InvalidYouTubeUrlError(
            "This link is not formatted correctly.",
            category="invalid_format",
        )
    normalized_host = hostname.lower().rstrip(".")
    normalized_domains = {
        domain.strip().lower().rstrip(".") for domain in allowed_domains
    }
    if not _is_allowed_youtube_host(normalized_host, normalized_domains):
        raise InvalidYouTubeUrlError

    video_id = _video_id(parsed.path, parsed.query, normalized_host)
    if video_id is None:
        raise InvalidYouTubeUrlError(
            "This link has no video ID.",
            category="missing_video_id",
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        raise InvalidYouTubeUrlError(
            "This link is not formatted correctly.",
            category="invalid_format",
        )
    netloc = normalized_host if port is None else f"{normalized_host}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _trim_url_wrapping(url: str) -> str:
    candidate = url.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
        candidate = candidate[1:-1].strip()
    return candidate


def _looks_like_domain_prefix(value: str) -> bool:
    known_youtube_host = re.match(
        r"^(?:[A-Za-z0-9-]+\.)*(?:youtube\.com|youtube-nocookie\.com|youtu\.be)(?:[/:?#]|$)",
        value,
        flags=re.IGNORECASE,
    )
    generic_domain_with_path = re.match(
        r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}[/:?#]",
        value,
        flags=re.IGNORECASE,
    )
    return known_youtube_host is not None or generic_domain_with_path is not None


def _is_allowed_youtube_host(hostname: str, domains: set[str]) -> bool:
    if hostname == "youtu.be":
        return "youtu.be" in domains
    for domain in ("youtube.com", "youtube-nocookie.com"):
        if domain in domains and (
            hostname == domain or hostname.endswith(f".{domain}")
        ):
            return True
    for domain in domains - {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return True
    return False


def _video_id(path: str, query: str, hostname: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    query_values = parse_qs(query, keep_blank_values=True)
    if hostname == "youtu.be":
        return segments[0] if segments else None
    if not segments and query_values.get("v"):
        return query_values["v"][0] or None
    if segments == ["watch"]:
        values = query_values.get("v")
        return values[0] or None if values else None
    if segments and segments[0].lower() in ("shorts", "embed", "live", "v"):
        return segments[1] if len(segments) > 1 else None
    if not segments or segments == ["watch"]:
        return None
    raise InvalidYouTubeUrlError(
        "This link is not formatted correctly.",
        category="invalid_format",
    )


def parse_download_percentage(line: str) -> float | None:
    """Extract a yt-dlp percentage from one output line, if present."""
    match = _PERCENTAGE_PATTERN.search(line)
    if match is None:
        return None
    percentage = float(match.group(1))
    return percentage if 0.0 <= percentage <= 100.0 else None


def download_youtube(
    url: str,
    temporary_directory: str | Path,
    *,
    max_duration_seconds: float = 900,
    allowed_domains: Iterable[str] = DEFAULT_YOUTUBE_DOMAINS,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> DownloadResult:
    """Download a YouTube URL as WAV into a caller-owned temporary directory."""
    command = build_download_command(
        url,
        temporary_directory,
        max_duration_seconds=max_duration_seconds,
        allowed_domains=allowed_domains,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError

    directory = Path(temporary_directory)
    directory.mkdir(parents=True, exist_ok=True)
    output_path = directory / "source.wav"
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        if progress_callback is not None:
            progress_callback(
                DownloadProgress(
                    message=f"yt-dlp argv: {subprocess.list2cmdline(command)}",
                    stream="command",
                )
            )
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            creationflags=_creation_flags(),
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        raise DownloadError(
            f"Could not launch yt-dlp: {error}",
            category="process_start",
            output=str(error),
            argv=tuple(command),
        ) from error

    try:
        output, title, stdout, stderr = _read_process_output(
            process,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        return_code = process.wait()
        if return_code != 0:
            category = _classify_download_failure(output)
            raise DownloadError(
                f"yt-dlp exited with code {return_code}.",
                category="process_exit" if category == "unknown" else category,
                output=output,
                argv=tuple(command),
                stderr=stderr,
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise DownloadError(
                "yt-dlp finished but no audio file was created.",
                category="missing_output",
                output=output,
                argv=tuple(command),
                stderr=stderr,
            )
        return DownloadResult(
            audio_path=output_path,
            title=title.strip(),
            argv=tuple(command),
            stdout=stdout,
            stderr=stderr,
        )
    except DownloadCancelledError:
        _terminate_process_tree(process)
        _remove_partial_downloads(directory)
        raise
    except BaseException:
        _terminate_process_tree(process)
        _remove_partial_downloads(directory)
        raise


def _read_process_output(
    process: subprocess.Popen[str],
    *,
    progress_callback: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[str, str, str, str]:
    messages: queue.Queue[tuple[str, str] | tuple[str, object]] = queue.Queue()
    streams: tuple[tuple[str, IO[str] | None], ...] = (
        ("stdout", process.stdout),
        ("stderr", process.stderr),
    )

    def read_stream(name: str, stream: IO[str]) -> None:
        try:
            for line in stream:
                messages.put((name, line.rstrip("\r\n")))
        finally:
            messages.put((name, _STREAM_END))

    readers = [
        threading.Thread(
            target=read_stream,
            args=(name, stream),
            daemon=True,
        )
        for name, stream in streams
        if stream is not None
    ]
    for reader in readers:
        reader.start()

    lines: list[str] = []
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    title = ""
    ended_streams = 0
    while ended_streams < len(readers):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError
        try:
            stream_name, line_or_end = messages.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None and not any(reader.is_alive() for reader in readers):
                break
            continue
        if line_or_end is _STREAM_END:
            ended_streams += 1
            continue
        line = str(line_or_end)
        if line:
            lines.append(line)
            if stream_name == "stderr":
                stderr_lines.append(line)
            else:
                stdout_lines.append(line)
        parsed_title = ""
        if stream_name == "stdout" and line.startswith(_TITLE_MARKER):
            parsed_title = sanitize_video_title(line[len(_TITLE_MARKER) :].strip())
            if parsed_title and not title:
                title = parsed_title
        percentage = parse_download_percentage(line)
        if progress_callback is not None and (line or parsed_title):
            progress_callback(
                DownloadProgress(
                    percentage=percentage,
                    message=line,
                    title=parsed_title or None,
                    stream=stream_name,
                )
            )
    for reader in readers:
        reader.join(timeout=1)
    return (
        "\n".join(lines),
        title,
        "\n".join(stdout_lines),
        "\n".join(stderr_lines),
    )


def _classify_download_failure(output: str) -> str:
    message = output.casefold()
    if "outdated" in message or "update yt-dlp" in message:
        return "outdated"
    if (
        "no supported javascript runtime could be found" in message
        or "no video formats found" in message
        or "no formats found" in message
        or "no playable formats" in message
        or "requested format is not available" in message
        or "requested format is unavailable" in message
    ):
        return "javascript_runtime"
    if "age-restricted" in message or "age restricted" in message or "sign in to confirm your age" in message:
        return "age_restricted"
    if "private video" in message or "has been removed" in message or "video unavailable" in message:
        return "unavailable"
    if "livestream" in message or "live stream" in message or "is_live" in message:
        return "livestream"
    if "duration" in message and (
        "filter" in message or "too long" in message or "exceeds" in message
    ):
        return "too_long"
    if any(
        phrase in message
        for phrase in (
            "unable to download webpage",
            "unable to connect",
            "urlopen error",
            "network is unreachable",
            "connection timed out",
            "name or service not known",
            "temporary failure in name resolution",
            "http error 5",
        )
    ):
        return "network"
    return "unknown"


def _child_python_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.casefold() == "pythonw.exe":
        return str(executable.with_name("python.exe"))
    return sys.executable


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
                creationflags=_creation_flags(),
            )
            if result.returncode != 0 and process.poll() is None:
                process.kill()
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        kill_process_group = getattr(os, "killpg", None)
        if kill_process_group is None:
            process.terminate()
        else:
            try:
                kill_process_group(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            kill_process_group = getattr(os, "killpg", None)
            if kill_process_group is None:
                process.kill()
            else:
                try:
                    kill_process_group(
                        process.pid,
                        getattr(signal, "SIGKILL", signal.SIGTERM),
                    )
                except ProcessLookupError:
                    pass
        process.wait()


def _remove_partial_downloads(directory: Path) -> None:
    for path in directory.glob("source*"):
        if path.is_file():
            path.unlink(missing_ok=True)


__all__ = [
    "DEFAULT_YOUTUBE_DOMAINS",
    "DownloadCancelledError",
    "DownloadError",
    "DownloadProgress",
    "DownloadResult",
    "InvalidYouTubeUrlError",
    "download_youtube",
    "parse_download_percentage",
    "sanitize_video_title",
    "validate_youtube_url",
]
