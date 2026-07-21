"""Conservative temporary source minification for deployment commands."""

from __future__ import annotations

import io
import tokenize
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


def minify_python_source(source: bytes) -> bytes:
    """Remove comments and non-essential physical newlines from Python source."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
    text = source.decode(encoding)
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    compact_tokens = [
        (token.type, token.string)
        for token in tokens
        if token.type not in (tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER)
    ]
    return tokenize.untokenize(compact_tokens).encode(encoding)


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
