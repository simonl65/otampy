"""Transfer progress reporting for ``otampy upd``.

A single OTA update is dominated by its largest file: at the 128-byte
transfer chunk size, a ~34 kB ``main.py`` is ~268 chunks, and every chunk is
an ack round-trip over the radio. Announcing a file and then saying nothing
until the next one begins makes the longest part of an update look like a
hang, both in a terminal and in anything capturing the output.

Two renderings, chosen from whether the console is a terminal:

* Terminal -- a live Rich progress bar, redrawn in place.
* Not a terminal (piped into a dashboard, a log, CI) -- plain lines at fixed
  completion steps. A redrawn bar is meaningless once captured, and Rich's
  own control codes would just be litter in whatever reads it.

``--no-progress`` restores exactly the output this replaced: one plain
``Transferring <path> (<n> bytes)...`` line per file.
"""

from __future__ import annotations

from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

# Completion steps reported when output is captured rather than drawn: 25%
# gives three intermediate lines for a large file, enough to show the
# transfer moving without burying the per-file announcements it sits between.
PROGRESS_STEP_FRACTION = 0.25

__all__ = ["PROGRESS_STEP_FRACTION", "TransferProgress"]


class TransferProgress:
    """Reports per-file and within-file progress across one update."""

    def __init__(
        self,
        console: Console,
        total_files: int,
        total_bytes: int,
        enabled: bool = True,
    ) -> None:
        self._console = console
        self._total_files = total_files
        self._total_bytes = total_bytes
        self._enabled = enabled
        # Rich decides this from the real stream, so a captured or redirected
        # console reports False and gets the plain rendering automatically.
        self._live = enabled and console.is_terminal
        self._progress: Progress | None = None

    def __enter__(self) -> TransferProgress:
        if self._live:
            self._progress = Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=self._console,
                transient=False,
            )
            self._progress.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        # Stopping restores the terminal, so it has to happen even when the
        # transfer raises -- an aborted update must not leave the cursor
        # parked inside a half-drawn bar.
        if self._progress is not None:
            self._progress.stop()
            self._progress = None

    @contextmanager
    def file(self, index: int, target_path: str, size: int):
        """Reports one file, yielding a callable to advance it by n bytes."""
        if not self._enabled:
            self._console.print(f"Transferring {target_path} ({size} bytes)...")
            yield lambda _advanced: None
            return

        label = f"[{index}/{self._total_files}] {target_path}"
        if self._progress is not None:
            task = self._progress.add_task(label, total=max(size, 1))
            progress = self._progress
            try:
                yield lambda advanced: progress.advance(task, advanced)
            finally:
                # Leave the row showing a completed file rather than frozen
                # at wherever the last chunk landed.
                progress.update(task, completed=max(size, 1))
            return

        self._console.print(f"{label} ({size} bytes)")
        yield from self._stepped(target_path, size)

    def _stepped(self, target_path: str, size: int):
        """Plain-line rendering: one line per completion step."""
        sent = 0
        # 100% is deliberately absent: the next file's announcement, or the
        # commit line, already says this one finished.
        pending = []
        if size > 0:
            step = PROGRESS_STEP_FRACTION
            fraction = step
            while fraction < 1.0:
                pending.append(fraction)
                fraction += step

        def advance(advanced: int) -> None:
            nonlocal sent
            sent = min(sent + advanced, size)
            # Only the furthest step crossed is reported. One chunk can carry
            # a small file past several at once, and printing 25/50/75% with
            # the same byte count against each is noise, not progress.
            crossed = None
            while pending and size and sent >= pending[0] * size:
                crossed = pending.pop(0)
            # Nothing to say once the file is done: the next announcement,
            # or the commit line, already carries that.
            if crossed is None or sent >= size:
                return
            self._console.print(
                f"       {target_path}: {round(crossed * 100)}% "
                f"({sent}/{size} bytes)"
            )

        yield advance
