"""R-POL-6: no patching of imported modules and no access to the provenance recorder.

Each bypass attempt below must be rejected by the static policy before anything runs, so the
trace stays the simulator's own record (R-TRACE-3).
"""

import textwrap

import pytest

from simagent.policy import PHOTONSIM_API, RECORDER_NAMES, check

HEADER = "import photonsim as ps\nimport simagent_io\nimport numpy as np\n"


def _rejected(body: str) -> list[str]:
    result = check(HEADER + textwrap.dedent(body))
    assert not result.ok, f"should be rejected:\n{body}"
    return [v.message for v in result.violations]


@pytest.mark.parametrize(
    "body",
    [
        # assignment to attributes of imported modules, direct and through aliases
        "ps.simulate = lambda *a, **k: None\n",
        "import photonsim\nphotonsim.sweep = None\n",
        "import photonsim as p2\np2.simulate = print\n",
        "np.random.default_rng = None\n",
        "ps.simulate.__defaults__ = (1,)\n",
        "ps.Layer.material = 'lead'\n",
        "from photonsim import Slab\nSlab.layers = []\n",
        "from photonsim import simulate as s\ns.cache = 1\n",
        "r = np.random\nr.default_rng = None\n",
        "a = np.random\nb = a\nb.seed = 3\n",
        "ps.simulate += 1\n",
        "ps.simulate: int = 1\n",
        "del ps.simulate\n",
        "for ps.simulate in [1]:\n    pass\n",
        "x = [0 for ps.sweep in [1]]\n",
        "a, ps.simulate = 1, 2\n",
        "[*ps.simulate] = [1]\n",
        # setattr / delattr on imported names
        "setattr(ps, 'simulate', print)\n",
        "delattr(ps, 'simulate')\n",
        "setattr(np.random, 'seed', print)\n",
        # modules may not be stored, aliased or passed around (to patch them elsewhere)
        "q = ps\n",
        "def patch(m):\n    m.simulate = None\npatch(ps)\n",
        "mods = [ps]\n",
        "f = lambda: np\n",
    ],
)
def test_patching_is_rejected(body: str) -> None:
    """Covers R-POL-6 and R-TRACE-3: every way of patching an imported module is rejected."""
    messages = _rejected(body)
    assert any(
        "may not be patched" in m or "may only be used as" in m or "not part of" in m
        for m in messages
    ), messages


@pytest.mark.parametrize(
    "body",
    [
        "from photonsim import _provenance\n",
        "import photonsim._provenance\n",
        "from photonsim._provenance import RECORDER\n",
        "ps._provenance.RECORDER.calls.clear()\n",
        "x = ps._provenance\n",
        "getattr(ps, '_provenance')\n",
        "from photonsim import engine\n",
        "ps.engine.run_simulation(None, 1.0, 1)\n",
        "from photonsim.engine import run_simulation\n",
        "res = ps.transport.transport\n",
        "getattr(ps, 'engine')\n",
        "run_simulation = 1\n",
        "import photonsim.engine as e\n",
    ],
)
def test_recorder_and_unrecorded_paths_are_rejected(body: str) -> None:
    """Covers R-POL-6: the recorder's internals and non-API (unrecorded) entry points."""
    _rejected(body)


def test_reference_style_scripts_still_pass() -> None:
    """Legitimate code is unaffected: public API, local objects, item assignment, plotting."""
    code = textwrap.dedent(
        """
        import math
        import matplotlib
        import matplotlib.pyplot as plt
        import numpy as np
        import photonsim as ps
        import simagent_io
        from photonsim import Layer, Slab, simulate

        matplotlib.use("Agg")
        plt.rcParams["font.size"] = 9
        rng = np.random.default_rng(1)
        fig, ax = plt.subplots()
        ax.set_title("T")
        results = {}
        results["lead"] = simulate(Slab([Layer("lead", 1.0)]), 1.0, 100, seed=1).transmitted
        curve = ps.sweep(lambda t: ps.Slab([ps.Layer("water", t)]), [1, 2], 1.0, 100, seed=1)
        lo, hi = ps.energy_range("lead")
        names = ps.list_materials()

        class Box:
            pass

        box = Box()
        box.value = math.sqrt(4)
        simagent_io.submit(results["lead"], curve=[[x, r.transmitted] for x, r in curve])
        """
    )
    result = check(code)
    assert result.ok, result.feedback()


def test_api_and_recorder_lists() -> None:
    assert {"simulate", "sweep", "Slab", "Layer"} <= PHOTONSIM_API
    assert "run_simulation" not in PHOTONSIM_API
    assert "_provenance" in RECORDER_NAMES


def test_messages_tell_the_model_what_to_do() -> None:
    (msg,) = check("import photonsim as ps\nps.simulate = None\n").violations
    assert "may not be patched" in msg.message
    (api,) = check("from photonsim import engine\n").violations
    assert "use only: Layer, Result, Slab" in api.message
