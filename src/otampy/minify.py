"""Conservative temporary source minification for deployment commands."""

from __future__ import annotations

import io
import tokenize
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

DISCARDED_TOKENS = (tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER)


def _character_offsets(text: str) -> list[int]:
    """Return the index in *text* at which each 1-based tokenizer row starts."""
    offsets = [0]
    for line in text.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    return offsets


def _compact_tokens(text: str) -> list[tuple[int, str]]:
    """Drop comments and blank lines, keeping each f-string verbatim.

    Since 3.12 an f-string tokenizes as a run of parts rather than one STRING,
    so ``untokenize``'s two-tuple compat mode pads inside replacement fields:
    ``{x!r}`` becomes ``{x !r }``. CPython accepts that, MicroPython rejects it.
    Re-emitting the run as one slice of the original source keeps it untouched.
    """
    offsets = _character_offsets(text)

    def index(position: tuple[int, int]) -> int:
        row, column = position
        return offsets[row - 1] + column

    compact: list[tuple[int, str]] = []
    depth = 0
    start = 0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.FSTRING_START:
            if depth == 0:
                start = index(token.start)
            depth += 1
        elif depth:
            if token.type == tokenize.FSTRING_END:
                depth -= 1
                if depth == 0:
                    compact.append(
                        (tokenize.STRING, text[start : index(token.end)])
                    )
        elif token.type not in DISCARDED_TOKENS:
            compact.append((token.type, token.string))
    return compact


def minify_python_source(source: bytes) -> bytes:
    """Remove comments and non-essential physical newlines from Python source."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    text = source.decode(encoding)
    return tokenize.untokenize(_compact_tokens(text)).encode(encoding)


def minify_python_file(source: Path, destination: Path) -> None:
    """Write a minified copy of *source* to *destination*."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(minify_python_source(source.read_bytes()))


def copy_minified_tree(source_root: Path, destination_root: Path) -> None:
    """Copy a tree, minifying Python files and preserving all other files."""
    for source in source_root.rglob("*"):
        if source.is_dir():
            continue
        destination = destination_root / source.relative_to(source_root)
        if source.suffix == ".py":
            minify_python_file(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())


@contextmanager
def staged_minified_files(
    files: Sequence[tuple[str, Path]],
) -> Iterator[list[tuple[str, Path]]]:
    """Yield upload mappings with Python files replaced by temporary artifacts."""
    with TemporaryDirectory(prefix="otampy-minify-") as temp_dir:
        staging_root = Path(temp_dir)
        staged = []
        for index, (target, source) in enumerate(files):
            if source.suffix != ".py":
                staged.append((target, source))
                continue
            destination = staging_root / f"{index}.py"
            minify_python_file(source, destination)
            staged.append((target, destination))
        yield staged
