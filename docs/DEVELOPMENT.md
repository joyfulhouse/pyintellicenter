# Development

How to set up a development environment for pyintellicenter.

## Prerequisites

- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/).

## Setup

```bash
git clone https://github.com/joyfulhouse/pyintellicenter.git
cd pyintellicenter
uv sync --extra dev
```

## Quality Checks

```bash
uv run pytest                              # tests
uv run pytest --cov=src/pyintellicenter   # tests with coverage
uv run ruff check                          # lint
uv run ruff format                         # format
uv run mypy src/pyintellicenter            # type check
```

Full validation (run before every pull request):

```bash
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/pyintellicenter && uv run pytest tests/
```

See
[CONTRIBUTING](https://github.com/joyfulhouse/.github/blob/main/CONTRIBUTING.md)
for the contribution workflow.

## Testing Against Real Hardware

A live integration test helper lives in `scripts/test_discovery_live.py`. Set
your controller's IP in the script (or pass it as an argument) and run:

```bash
uv run python scripts/test_discovery_live.py
```

## Releasing

1. Bump the version in `pyproject.toml`.
2. Update `CHANGELOG.md` — move `[Unreleased]` items under a new versioned section,
   add the date, and update the compare links footer.
3. Commit and tag: `git tag v<version> && git push --tags`.
4. The `publish.yml` GitHub Actions workflow publishes to PyPI on tag push.
