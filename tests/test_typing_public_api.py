"""Guard the public typing contract of ``ICModelController`` for consumers.

``ICModelController`` composes its domain mixins (``_mixins/``) *before* the
concrete ``ICBaseController`` in its base list. The mixins reach host-class
members (``send_cmd``, ``system_info``, ``_system_info``, the coercion helpers,
the request-coalescing entry point) through a ``TYPE_CHECKING``-only base defined
in ``_mixins/_base.py``.

If that base is an abstract ``typing.Protocol``, its empty-bodied members are
*implicitly abstract*, and because the base precedes ``ICBaseController`` in the
MRO that abstractness leaks out to **downstream** type-checkers -- they then
reject ``ICModelController(...)`` with ``[abstract]`` even though the runtime
class is perfectly concrete (see issue #35). The library's own ``mypy src`` does
*not* catch this, because nothing in ``src/`` instantiates the class outside
docstrings.

This test pins the contract from a consumer's perspective: a standalone module
that instantiates ``ICModelController`` must type-check cleanly.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# mypy is a dev/test dependency; skip cleanly if a runtime-only env lacks it.
pytest.importorskip("mypy")

_REPO_ROOT = Path(__file__).resolve().parent.parent

_CONSUMER_SOURCE = textwrap.dedent(
    """\
    \"\"\"Downstream-style consumer; must type-check without [abstract] errors.\"\"\"
    from __future__ import annotations

    from pyintellicenter import ICModelController, PoolModel


    def make_controller() -> ICModelController:
        return ICModelController("192.168.1.100", PoolModel())
    """
)


def test_model_controller_instantiable_for_consumers(tmp_path: Path) -> None:
    """A consumer instantiating ``ICModelController`` must pass mypy (issue #35)."""
    consumer = tmp_path / "consumer.py"
    consumer.write_text(_CONSUMER_SOURCE)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            str(consumer),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        "Downstream instantiation of ICModelController failed mypy -- the mixin "
        "typing scaffolding is leaking abstractness (issue #35).\n\n" + output
    )
    assert "[abstract]" not in output, output
