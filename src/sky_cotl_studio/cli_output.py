"""Console output helpers that tolerate GUI interpreters without stdout."""

import builtins
import sys


def safe_print(message: object) -> None:
    """Print one CLI message when the current process has a stdout stream."""
    output = sys.stdout
    if output is not None:
        builtins.print(message, file=output)
