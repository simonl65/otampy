# Minification options

## Goal

Allow production deployments to be as small as practical without changing the
developer's source files or discouraging comments and readable code during
development.

## Recommended first implementation: safe source minification

Add `--minify` to `deploy`, `cp`, and `upd`.  For Python files, it should
create a temporary transformed copy, then upload that copy under the original
`.py` path.  It must never modify the project sources.

```bash
otampy deploy --minify
otampy cp --minify main.py lib/
otampy upd --minify
otampy upd --minify --all-files
```

Initially, minification should be deliberately conservative:

- remove comments and redundant blank lines;
- leave filenames, identifiers, string literals, and program structure intact;
- leave non-Python files unchanged;
- report the source path, deployed path, and size reduction clearly.

This works for `boot.py`, `main.py`, and ordinary modules because their device
paths do not change.  It is therefore suitable for the transactional `upd`
protocol as well as local `cp` and full filesystem `deploy`.

Use a shared staging function for all three commands.  It should produce a
source-to-staged-path mapping in a temporary directory, which each transfer
path consumes.  This avoids altering the user's working tree and ensures the
same source receives the same transformation regardless of command.

### Optional levels

If further source savings are wanted, make them explicit rather than silently
changing semantics:

- `--minify=comments` (the default behaviour above);
- `--minify=docs` additionally removes docstrings.

Removing docstrings can change a module, class, or function's `__doc__`, so it
should not be part of the default safe mode.

## Bytecode: a separate production option

OTAmpy already has `deploy --bytecode` / `--mpy`.  It asks the target for its
`.mpy` compatibility, builds target-matched portable bytecode for OTAmpy and
URST, and validates the result before deployment.  This is the stronger
production format for those libraries and should remain separate from source
minification.

It could later be extended to `cp` and `upd`, but it is not a straightforward
implementation of `--minify`:

- MicroPython imports `foo.py` before `foo.mpy`; updating a module to bytecode
  requires the old source to be removed or renamed as part of the transaction.
- `boot.py` and `main.py` need dedicated startup handling.
- `.mpy` files must be built for the target firmware's supported bytecode
  version and small-integer width.

For these reasons, introduce bytecode updates later as an explicit
`--bytecode` capability, with its own compatibility preflight and stale-source
cleanup semantics.  Do not overload `--minify` to mean both source stripping
and bytecode compilation.

## Aggressive minifiers

Tools that rename identifiers, fold expressions, or otherwise rewrite Python
can save more space, but cannot safely promise unchanged behaviour for all
MicroPython programs.  Dynamic imports, `getattr`, global-name lookups,
configuration by name, and debugging all make this riskier.

They are not appropriate for the default OTAmpy workflow.  If ever offered,
they should be opt-in, clearly labelled as aggressive, and have dedicated
compatibility tests.

## Frozen firmware

Freezing stable modules into a custom MicroPython firmware can eliminate their
filesystem footprint and may improve memory behaviour.  It is the most compact
option for stable production libraries, but is board- and firmware-specific,
so it belongs to a separate firmware-build workflow rather than `cp`, `upd`,
or ordinary `deploy`.

## Measurement and validation

Minification reduces source transfer bytes and filesystem use.  It does not by
itself establish equivalent runtime RAM savings, so measure source size,
filesystem allocation, import behaviour, and heap use on the actual target.

Tests should cover:

- comments and blank lines removed while executable behaviour is preserved;
- original source files unchanged after each command;
- `cp`, `upd`, and `deploy` all use the same staged representation;
- hashes, sizes, error handling, and transactional update behaviour reflect
  the staged file, not the source file;
- invalid source fails before any destructive deploy or device update action.
