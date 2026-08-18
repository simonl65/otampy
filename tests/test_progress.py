"""Transfer progress reporting for ``otampy upd``."""

import re

import pytest
from rich.console import Console

from otampy.progress import PROGRESS_STEP_FRACTION, TransferProgress


def _console(width=100, force_terminal=False):
    """A Console that records output instead of writing to a real stream."""
    return Console(
        record=True,
        width=width,
        force_terminal=force_terminal,
        highlight=False,
        no_color=True,
    )


def _lines(console):
    return [
        line.rstrip()
        for line in console.export_text().splitlines()
        if line.strip()
    ]


def _transfer(console, files, enabled=True):
    """Drives a whole transfer, sending every file one chunk at a time."""
    total_bytes = sum(size for _, size in files)
    with TransferProgress(
        console, len(files), total_bytes, enabled=enabled
    ) as progress:
        for index, (name, size) in enumerate(files, start=1):
            with progress.file(index, name, size) as advance:
                sent = 0
                while sent < size:
                    step = min(128, size - sent)
                    sent += step
                    advance(step)
    # Only a recording console has a buffer to read back; the two terminal
    # tests below drive a real stream and read stdout instead.
    return _lines(console) if console.record else []


def test_announces_each_file_with_its_position_in_the_manifest():
    lines = _transfer(_console(), [("boot.py", 256), ("main.py", 512)])

    assert any(
        re.search(r"\[1/2\].*boot\.py.*256 bytes", line) for line in lines
    )
    assert any(
        re.search(r"\[2/2\].*main\.py.*512 bytes", line) for line in lines
    )


# The reason this feature exists: main.py is ~34 kB, which is ~268 chunks,
# each an ack round-trip over the radio. Before this there was one line at
# the start of the file and nothing until the next file began, so the
# longest silence in an update was its largest file.
def test_reports_intermediate_progress_within_a_single_large_file():
    lines = _transfer(_console(), [("main.py", 34188)])

    progress_lines = [line for line in lines if "%" in line]
    assert len(progress_lines) >= 3
    for line in progress_lines:
        assert "main.py" in line
        assert "34188" in line


def test_reports_progress_at_the_configured_fraction():
    lines = _transfer(_console(), [("main.py", 34188)])

    percentages = [
        int(match.group(1))
        for line in lines
        if (match := re.search(r"(\d+)%", line))
    ]
    step = int(PROGRESS_STEP_FRACTION * 100)
    assert percentages == list(range(step, 100, step))


# 100% is redundant: the next file's announcement, or the commit line,
# already says this one finished.
def test_does_not_report_a_hundred_percent_step():
    lines = _transfer(_console(), [("main.py", 34188)])

    assert not any("100%" in line for line in lines)


# A small file arrives in a single chunk, which crosses every step at once.
# Reporting 25/50/75% with the same byte count against each is noise.
def test_a_file_that_completes_in_one_chunk_reports_no_intermediate_progress():
    lines = _transfer(_console(), [("boot.py", 64)])

    assert not any("%" in line for line in lines)
    assert any("boot.py" in line for line in lines)


def test_reports_only_the_furthest_step_crossed_by_one_chunk():
    console = _console()
    with (
        TransferProgress(console, 1, 1000, enabled=True) as progress,
        progress.file(1, "main.py", 1000) as advance,
    ):
        advance(600)  # crosses 25% and 50% together
        advance(200)  # then 75% on its own, still short of the end
        advance(200)

    percentages = [
        int(match.group(1))
        for line in _lines(console)
        if (match := re.search(r"(\d+)%", line))
    ]
    assert percentages == [50, 75]


# --no-progress must leave exactly the output that existed before this
# feature: one plain line per file, no counter, no percentages.
def test_disabled_falls_back_to_the_original_per_file_line():
    lines = _transfer(
        _console(), [("boot.py", 256), ("main.py", 34188)], enabled=False
    )

    assert lines == [
        "Transferring boot.py (256 bytes)...",
        "Transferring main.py (34188 bytes)...",
    ]


def test_disabled_reports_no_percentages_even_for_a_large_file():
    lines = _transfer(_console(), [("main.py", 34188)], enabled=False)

    assert not any("%" in line for line in lines)


def test_advancing_past_the_declared_size_does_not_exceed_a_hundred_percent():
    console = _console()
    with (
        TransferProgress(console, 1, 100, enabled=True) as progress,
        progress.file(1, "main.py", 100) as advance,
    ):
        advance(1000)

    percentages = [
        int(match.group(1))
        for line in _lines(console)
        if (match := re.search(r"(\d+)%", line))
    ]
    assert all(value <= 100 for value in percentages)


# A zero-byte file is legitimate (an empty __init__.py) and must not divide
# by zero.
def test_handles_an_empty_file():
    lines = _transfer(_console(), [("__init__.py", 0)])

    assert any("__init__.py" in line for line in lines)


# Rich draws a live bar straight to the stream rather than through the
# console's recording buffer, so these two read real stdout.
def test_uses_a_live_progress_bar_on_a_terminal(capsys):
    _transfer(Console(force_terminal=True, width=100), [("main.py", 34188)])

    # The bar renders block-drawing glyphs; the piped form never does.
    assert "━" in capsys.readouterr().out


def test_uses_plain_lines_when_not_a_terminal(capsys):
    _transfer(Console(force_terminal=False, width=100), [("main.py", 34188)])

    out = capsys.readouterr().out
    assert "━" not in out
    assert "main.py: 25% (8576/34188 bytes)" in out


def test_reraises_the_transfer_error_and_still_closes_cleanly():
    console = _console()
    with (
        pytest.raises(RuntimeError, match="chunk failed"),
        TransferProgress(console, 1, 100, enabled=True) as progress,
        progress.file(1, "main.py", 100),
    ):
        raise RuntimeError("chunk failed")
