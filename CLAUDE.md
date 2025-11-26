# PyIntelliCenter - Claude Code Instructions

## Project Overview

Python library for communicating with Pentair IntelliCenter pool control systems. Provides async TCP communication, equipment state management, and automatic reconnection handling.

## Development Environment

- **Package Manager**: Use `uv` for all Python operations
- **Python Version**: 3.13+
- **Test Runner**: pytest with pytest-asyncio

## Common Commands

```bash
# Install dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/

# Run tests with coverage
uv run pytest tests/ --cov=src/pyintellicenter --cov-report=term-missing

# Linting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy src/pyintellicenter

# Full validation (run before commits)
uv run ruff check --fix . && uv run ruff format . && uv run mypy src/pyintellicenter && uv run pytest tests/
```

## Project Structure

```
src/pyintellicenter/
├── __init__.py          # Public API exports
├── connection.py        # TCP connection handling
├── controller.py        # Controller classes (Base, Model, Handler)
├── model.py             # PoolModel and PoolObject
├── discovery.py         # mDNS/Zeroconf discovery
├── exceptions.py        # Exception hierarchy
├── types.py             # Type definitions
└── attributes/          # Attribute constants
    ├── __init__.py
    ├── constants.py     # HeaterType enum, object types
    ├── body.py          # Body (pool/spa) attributes
    ├── circuit.py       # Circuit attributes
    ├── equipment.py     # Pump, heater, chem attributes
    ├── schedule.py      # Schedule attributes
    ├── system.py        # System attributes
    └── misc.py          # Miscellaneous attributes
```

## Key Classes

- `ICConnection` - Low-level async TCP connection
- `ICBaseController` - Basic command handling
- `ICModelController` - State management with PoolModel
- `ICConnectionHandler` - Auto-reconnection wrapper
- `PoolModel` / `PoolObject` - Equipment state tracking

## Testing

- Unit tests in `tests/test_*.py`
- Integration tests use `MockIntelliCenterServer` from `tests/mock_server.py`
- Target: 90%+ code coverage
- All tests must pass before release

## Release Checklist

**IMPORTANT: Always update CHANGELOG.md before any release!**

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`:
   - Move items from [Unreleased] to new version section
   - Add release date
   - Update comparison links at bottom
3. Run full validation suite
4. Create git tag matching version
5. Push to trigger GitHub Actions publish workflow

## Code Style

- Follow ruff linting rules (see pyproject.toml)
- Use type hints everywhere
- Prefer async/await over callbacks
- Keep public API minimal and well-documented
