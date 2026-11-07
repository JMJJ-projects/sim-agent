"""Tests for the static policy."""

import pytest

from simagent.policy import ALLOWED_MODULES, check

GOOD = """\
import math
import json
import itertools
import statistics
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import photonsim as ps
import simagent_io
from photonsim import Layer, Slab, simulate


def main() -> None:
    res = simulate(Slab([Layer("lead", 2.0)]), 1.0, 1000, seed=1)
    x = getattr(res, "transmitted")
    simagent_io.submit(x, mean=float(np.mean([x, math.e])), name=type(res).__name__)


if __name__ == "__main__":
    main()
"""


def test_typical_script_passes() -> None:
    result = check(GOOD)
    assert result.ok, result.feedback()
    assert result.feedback() == "no policy violations"


@pytest.mark.parametrize("module", sorted(ALLOWED_MODULES))
def test_each_allowed_module(module: str) -> None:
    """Covers R-POL-2."""
    assert check(f"import {module}\n").ok
    assert check(f"from {module} import x\n").ok


@pytest.mark.parametrize(
    "module", ["os", "sys", "subprocess", "socket", "pathlib", "shutil", "urllib.request", "ctypes"]
)
def test_disallowed_imports(module: str) -> None:
    """Covers R-POL-2 and R-POL-4 (message lists the allowed modules)."""
    result = check(f"import {module}\n")
    assert not result.ok
    msg = result.feedback()
    assert f"import of `{module}` is not allowed" in msg
    assert "allowed modules are" in msg
    assert "photonsim" in msg


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        ("from os import path\n", "import from `os`"),
        ("import numpy.f2py\n", "import of `numpy.f2py`"),
        ("from . import x\n", "relative imports"),
        ("from numpy import *\n", "import *"),
        ("from numpy import load\n", "importing `load`"),
        ("eval('1')\n", "`eval()`"),
        ("exec('x=1')\n", "`exec()`"),
        ("compile('1', 'f', 'eval')\n", "`compile()`"),
        ("__import__('os')\n", "`__import__()`"),
        ("open('/etc/passwd')\n", "`open()`"),
        ("globals()\n", "`globals()`"),
        ("vars()\n", "`vars()`"),
        ("input()\n", "`input()`"),
        ("f = eval\n", "use of `eval`"),
        ("x = (1).__class__\n", "dunder attribute `__class__`"),
        ("().__class__.__bases__[0].__subclasses__()\n", "`__subclasses__`"),
        ("getattr(x, '__class__')\n", "`getattr()` on `__class__`"),
        ("setattr(x, '__dict__', 1)\n", "`setattr()` on `__dict__`"),
        ("getattr(x, name)\n", "literal attribute name"),
        ("g = getattr\n", "use of `getattr`"),
        ("print(__builtins__)\n", "use of `__builtins__`"),
        ("__loader__()\n", "use of `__loader__`"),
        ("import numpy as np\nnp.save('x', 1)\n", "`.save`"),
        ("import numpy as np\nnp.ctypeslib\n", "`.ctypeslib`"),
        ("'{0.__class__}'.format(1)\n", "format strings"),
    ],
)
def test_forbidden_patterns(code: str, fragment: str) -> None:
    """Covers R-POL-3."""
    result = check(code)
    assert not result.ok
    assert fragment in result.feedback()


def test_open_hint_points_to_submit() -> None:
    assert "simagent_io.submit" in check("open('x', 'w')\n").feedback()


def test_syntax_error_has_line_number() -> None:
    """Covers R-POL-1."""
    result = check("x = 1\ny = (\n")
    assert not result.ok
    assert result.violations[0].line is not None
    assert "SyntaxError" in result.feedback()
    assert "line" in result.feedback()


def test_null_bytes_reported() -> None:
    result = check("x = 1\x00\n")
    assert not result.ok
    assert result.violations


def test_violations_are_sorted_and_deduplicated() -> None:
    result = check("import os\nimport os\nimport sys\n")
    lines = [v.line for v in result.violations]
    assert lines == sorted(lines)
    assert len(result.violations) == 3
    assert str(result.violations[0]).startswith("line 1:")
