"""Print yt-dlp help or inspect a YouTube download in a temporary directory."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sky_cotl_studio.audio.download import build_download_command


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--yt-dlp-help", action="store_true")
    args = parser.parse_args(argv)
    if args.yt_dlp_help:
        completed = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=_creation_flags(),
        )
        help_text = f"{completed.stdout}\n{completed.stderr}"
        for line in help_text.splitlines():
            if any(
                marker in line.casefold()
                for marker in (
                    "--print",
                    "--simulate",
                    "--progress",
                    "--progress-template",
                    "--newline",
                    "implies --quiet",
                )
            ):
                print(line)
        return completed.returncode

    if not args.url:
        parser.error("provide a URL or --yt-dlp-help")
    with tempfile.TemporaryDirectory(prefix="sky-cotl-download-debug-") as directory:
        command = build_download_command(args.url, Path(directory))
        print(f"argv: {subprocess.list2cmdline(command)}")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
            creationflags=_creation_flags(),
        )
        print(f"exit code: {completed.returncode}")
        print(f"stdout:\n{completed.stdout}")
        print(f"stderr:\n{completed.stderr}")
        print(f"files: {[path.name for path in Path(directory).iterdir()]}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
