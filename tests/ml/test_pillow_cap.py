"""The exit condition of the pillow block in ``.github/pip-audit-ignore.txt``.

That block accepts pillow 12.x advisories only because fastembed, the sole
route pillow takes into this project, requires ``pillow<13`` and the fixes are
in 13.0.0. Whether that still holds is a property of the installed fastembed,
which ``uv.lock`` does not record, so this runs in the ML job, where the
``[reranker]`` extra is installed.
"""

from __future__ import annotations

import importlib.metadata

import pytest
from packaging.requirements import Requirement
from packaging.version import Version


@pytest.mark.requires_reranker
def test_fastembed_still_caps_pillow_below_13() -> None:
    """Fail the day fastembed admits the patched pillow."""
    fastembed = importlib.metadata.version("fastembed")
    pillow_specs = [
        Requirement(raw)
        for raw in importlib.metadata.requires("fastembed") or []
        if Requirement(raw).name.lower() == "pillow"
    ]
    applicable = [r for r in pillow_specs if r.marker is None or r.marker.evaluate()]
    assert applicable, f"fastembed {fastembed} no longer requires pillow at all"
    assert all(Version("13.0.0") not in r.specifier for r in applicable), (
        f"fastembed {fastembed} admits pillow 13 ({applicable}). Delete the "
        "pillow block in .github/pip-audit-ignore.txt and run `uv lock "
        "--upgrade-package fastembed --upgrade-package pillow`."
    )
