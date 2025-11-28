"""Tests for version consistency."""

import tomllib
from pathlib import Path

import pyintellicenter


class TestVersion:
    """Tests for version consistency between pyproject.toml and __init__.py."""

    def test_version_matches_pyproject(self):
        """Ensure __init__.py version matches pyproject.toml."""
        # Read pyproject.toml
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)

        pyproject_version = pyproject["project"]["version"]
        init_version = pyintellicenter.__version__

        assert init_version == pyproject_version, (
            f"Version mismatch: __init__.py has '{init_version}' "
            f"but pyproject.toml has '{pyproject_version}'"
        )

    def test_version_is_valid_semver(self):
        """Ensure version follows semantic versioning pattern."""
        version = pyintellicenter.__version__

        # Basic semver pattern: X.Y.Z or X.Y.Z-suffix
        parts = version.split(".")
        assert len(parts) >= 3, f"Version '{version}' should have at least 3 parts (X.Y.Z)"

        # First two parts should be integers
        assert parts[0].isdigit(), f"Major version '{parts[0]}' should be a number"
        assert parts[1].isdigit(), f"Minor version '{parts[1]}' should be a number"

        # Third part can have suffix like "0a1" or "0-alpha"
        patch = parts[2].split("-")[0].split("a")[0].split("b")[0].split("rc")[0]
        assert patch.isdigit(), f"Patch version '{patch}' should be a number"
