# Installing pyintellicenter

## Requirements

- Python 3.13 or newer.
- Pentair IntelliCenter controller (i5P, i8P, i10P, or similar)
- Local network access to IntelliCenter

## Install from PyPI

```bash
pip install pyintellicenter
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add pyintellicenter
```

## Install from Source

```bash
git clone https://github.com/joyfulhouse/pyintellicenter.git
cd pyintellicenter
uv sync
```

This installs the package with its development dependencies into a local virtual
environment.

## Verify the Installation

```bash
python -c "import pyintellicenter; print(pyintellicenter.__version__)"
```

You should see the installed version printed with no import errors.

## Next Steps

See the [README](README.md#quick-start) for a quick-start example and usage
guide.
