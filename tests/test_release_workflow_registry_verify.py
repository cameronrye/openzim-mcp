"""Release-workflow guards for the ``publish-registry`` job.

``mcp-publisher status`` reads like a post-publish check but is a MUTATION
("Update the status of a server version"): the pinned v1.8.1 binary needs
``--status <active|deprecated|deleted>`` plus a server name, and with no
arguments prints ``Error: --status flag is required`` and exits 1. Under
``set -euo pipefail`` that turned ``publish-registry`` red on every release
— including the documented ``gh workflow run release.yml -f tag=vX.Y.Z``
backfill — even though ``mcp-publisher publish`` had just succeeded. The
job reads the version back from the registry API instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registry_job(workflow_text: str) -> Dict[str, Any]:
    return yaml.safe_load(workflow_text)["jobs"]["publish-registry"]


def _run_scripts(job: Dict[str, Any]) -> str:
    return "\n".join(step["run"] for step in job["steps"] if "run" in step)


def test_publish_registry_never_invokes_the_status_mutation(
    registry_job: Dict[str, Any],
) -> None:
    script = _run_scripts(registry_job)
    assert "./mcp-publisher publish" in script, script
    assert not re.search(r"mcp-publisher\s+status\b", script), script


def test_publish_registry_reads_the_published_version_back(
    registry_job: Dict[str, Any],
) -> None:
    """``publish``'s own exit code says nothing about what the registry
    serves, and docs/distribution.md sends maintainers to this job when the
    search API lags a release — so the verification has to be a real read."""
    script = _run_scripts(registry_job)
    assert "registry.modelcontextprotocol.io/v0/servers" in script, script
    # Whatever it asserts, it must compare against the released version
    # rather than merely proving the endpoint answers.
    assert "$VERSION" in script, script


def test_release_workflow_curls_pin_the_https_scheme(workflow_text: str) -> None:
    """Sonar's ``new_security_rating`` gate reds on any workflow ``curl``
    that lets the URL choose the scheme."""
    offenders = [
        line
        for line in workflow_text.splitlines()
        if re.search(r"\bcurl\b", line) and "--proto '=https'" not in line
    ]
    assert not offenders, offenders
