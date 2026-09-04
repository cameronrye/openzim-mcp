"""Guards against a release being public before it has anything in it.

On 2026-09-04 v3.3.0 was tagged and PUBLISHED at 02:15:45 by release-please the
moment the release PR merged, ``release.yml`` then went red on its "Test before
release" job at 02:18:50, and Build / Publish to PyPI / Publish to MCP Registry
/ Create GitHub Release all skipped. For 11m17s — and indefinitely, had nobody
re-run it — ``v3.3.0`` was a public, tagged, completely empty release while PyPI
still served 3.2.5. The assets only landed at 02:27:02 on a manual re-run.

The pipeline is a handshake across three files and the invariants that keep the
window shut are not visible in any one of them:

* ``release-please-config.json`` must hand over an *unpublished* (draft) release
  shell, because ``release.yml`` is what publishes it — after the assets are on.
* A draft release does not create its git tag (GitHub cuts the tag when a
  release is published), so ``force-tag-creation`` has to put the tag there
  instead, or every job that checks the tag out has nothing to check out.
* ``release.yml`` must publish strictly after attaching assets, and must refuse
  to publish nothing.

Each test below derives its requirement from the workflows rather than asserting
a literal, so removing the machinery relaxes the rule instead of silently
passing. The publish step is exercised for real: its shell is lifted out of the
YAML and run against a stubbed ``gh``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - runs the workflow's own shell against a gh stub
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS / "release.yml"
RELEASE_PLEASE_YML = WORKFLOWS / "release-please.yml"
RELEASE_PLEASE_CONFIG = ROOT / "release-please-config.json"

# The one expression the publish step interpolates. Rendering is deliberately
# strict: a newly added ``${{ }}`` fails the render instead of silently
# evaluating to the empty string and testing a different script than CI runs.
EXPRESSIONS = {"steps.tag.outputs.tag_name": "v9.9.9"}


@pytest.fixture(scope="module")
def release_yml() -> Dict[str, Any]:
    return yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def release_please_yml() -> Dict[str, Any]:
    return yaml.safe_load(RELEASE_PLEASE_YML.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def release_please_package() -> Dict[str, Any]:
    config = json.loads(RELEASE_PLEASE_CONFIG.read_text(encoding="utf-8"))
    return config["packages"]["."]


def _steps(workflow: Dict[str, Any], job: str) -> List[Dict[str, Any]]:
    return workflow["jobs"][job]["steps"]


def _index_of_run(steps: List[Dict[str, Any]], needle: str) -> int:
    """Index of the single step whose ``run`` script contains ``needle``."""
    hits = [i for i, step in enumerate(steps) if needle in str(step.get("run", ""))]
    assert len(hits) == 1, f"expected exactly one step running {needle!r}, found {hits}"
    return hits[0]


def _run_script(steps: List[Dict[str, Any]], needle: str) -> str:
    return str(steps[_index_of_run(steps, needle)]["run"])


def _checkouts_of_the_release_tag(workflow: Dict[str, Any]) -> List[str]:
    """Jobs whose checkout resolves to the release tag by *name*.

    These are the jobs that cannot run at all unless ``refs/tags/<tag>`` already
    exists on the remote — the dispatch path, where ``github.ref`` is a branch
    and the tag has to be named explicitly.
    """
    found: List[str] = []
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if not str(step.get("uses", "")).startswith("actions/checkout"):
                continue
            ref = str((step.get("with") or {}).get("ref", ""))
            if "tag_name" in ref or "inputs.tag" in ref:
                found.append(job_name)
    return found


def test_release_please_hands_over_an_unpublished_release(
    release_yml: Dict[str, Any], release_please_package: Dict[str, Any]
) -> None:
    """The GitHub release must not go public when the release PR merges.

    ``release.yml`` owns publication: it builds, uploads and only then flips the
    draft. If release-please publishes the shell itself, that final flip is a
    no-op and the release is public and empty for the whole length of the
    pipeline — every minute of which is a chance for it to stay that way.
    """
    steps = _steps(release_yml, "create-release")
    publishers = [
        i for i, s in enumerate(steps) if "--draft=false" in str(s.get("run", ""))
    ]
    assert publishers, (
        "release.yml's create-release job no longer publishes the release. "
        "With release-please handing over a draft, nothing else ever makes it "
        "public — revisit this invariant before removing that step."
    )
    assert release_please_package.get("draft") is True, (
        "release-please-config.json publishes the GitHub release the instant the "
        "release PR merges, minutes before release.yml has built a single "
        "artifact. Any failure in between leaves a public, tagged, empty release "
        "(v3.3.0, 2026-09-04). Hand over a draft and let release.yml publish it."
    )


def test_a_draft_release_shell_still_gets_its_tag(
    release_yml: Dict[str, Any],
    release_please_yml: Dict[str, Any],
    release_please_package: Dict[str, Any],
) -> None:
    """A draft release creates no tag, so release-please has to create one.

    GitHub only cuts ``refs/tags/<tag>`` when a release is *published*. Flipping
    release-please to ``draft: true`` on its own therefore removes the tag that
    the whole downstream pipeline addresses itself by, and every consumer found
    below dies on "couldn't find remote ref". ``force-tag-creation`` pushes the
    ref at the release commit before creating the release, restoring the tag
    without restoring the visibility.
    """
    consumers = _checkouts_of_the_release_tag(release_yml)
    consumers += _checkouts_of_the_release_tag(release_please_yml)
    prepare = _steps(release_yml, "validate-and-prepare")
    hard_failures = [
        s
        for s in prepare
        if "does not exist and create_tag is false" in str(s.get("run", ""))
    ]
    assert consumers, (
        "nothing checks the release tag out by name any more — the draft/tag "
        "interaction below may no longer apply, so re-derive it before editing."
    )
    assert hard_failures, (
        "validate-and-prepare no longer refuses a missing tag; re-derive this "
        "invariant rather than assuming the dispatch path tolerates one."
    )
    assert (
        release_please_package.get("draft") is not True
        or release_please_package.get("force-tag-creation") is True
    ), (
        "release-please creates a draft release, which does not create a tag, "
        f"but {sorted(set(consumers))} check that tag out by name and "
        "validate-and-prepare hard-fails without it. Set "
        '"force-tag-creation": true so the ref is pushed at the release commit.'
    )


def test_release_please_still_creates_the_release_shell(
    release_please_yml: Dict[str, Any], release_please_package: Dict[str, Any]
) -> None:
    """``skip-github-release`` would strand the release before it starts.

    ``release_created`` is only set when release-please actually creates a
    GitHub release. Skipping release creation leaves the jobs below permanently
    skipped and nothing tagged — the v1.0.1 symptom, a release PR merged into
    silence.
    """
    gated = [
        name
        for name, job in release_please_yml["jobs"].items()
        if "outputs.release_created" in str(job.get("if", ""))
    ]
    assert gated, "no job depends on release_created any more — re-derive this rule"
    assert release_please_package.get("skip-github-release") is False, (
        f"{sorted(gated)} are gated on release-please's release_created output, "
        "which is never set when skip-github-release is true."
    )


def test_the_release_is_published_only_after_its_assets_are_attached(
    release_yml: Dict[str, Any],
) -> None:
    """Ordering is the whole mechanism: draft, then assets, then publish.

    It keeps a half-finished release invisible, and on a repo with immutable
    releases enabled it is the only order that can attach assets at all —
    publishing locks the asset list. rc0 and rc1 both shipped with empty
    Releases pages when the create step published in one shot.
    """
    steps = _steps(release_yml, "create-release")
    upload = _index_of_run(steps, "gh release upload")
    publish = _index_of_run(steps, "--draft=false")
    created = [
        i
        for i, s in enumerate(steps)
        if str(s.get("uses", "")).startswith("softprops/action-gh-release")
    ]
    assert len(created) == 1, f"expected one release-creating step, found {created}"
    assert steps[created[0]]["with"]["draft"] is True, (
        "the manual-tag path creates a published release in one shot, so its "
        "asset upload has nothing to attach to under immutable releases."
    )
    assert publish > upload, (
        f"publish step (index {publish}) runs before the asset upload "
        f"(index {upload}) — that publishes an empty release."
    )
    assert publish > created[0], (
        f"publish step (index {publish}) runs before the draft is created "
        f"(index {created[0]})."
    )


# --------------------------------------------------------------------------
# The publish step's shell, executed for real against a stubbed ``gh``.
# --------------------------------------------------------------------------

pytestmark_bash = pytest.mark.skipif(
    sys.platform == "win32",
    reason="release.yml only ever runs on ubuntu-latest; its shell needs a POSIX bash",
)


def _render(script: str) -> str:
    def substitute(match: "re.Match[str]") -> str:
        expression = match.group(1).strip()
        if expression not in EXPRESSIONS:
            raise AssertionError(
                f"publish step interpolates {expression!r}, which this test does not "
                "know how to render; add it to EXPRESSIONS so the executed script "
                "stays the one CI runs."
            )
        return EXPRESSIONS[expression]

    return re.sub(r"\$\{\{(.+?)\}\}", substitute, script)


def _gh_stub(directory: Path, *, is_draft: Optional[str], asset_count: int) -> Path:
    """A ``gh`` that answers the publish step's two reads and logs every call.

    ``is_draft=None`` makes the isDraft read exit non-zero, standing in for a
    ``gh``/API failure.
    """
    if is_draft is None:
        is_draft_body = 'echo "boom" >&2; exit 1'
    else:
        is_draft_body = f"echo {is_draft}"
    stub = directory / "gh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
        'case "$*" in\n'
        f"  *'--json isDraft'*) {is_draft_body} ;;\n"
        f'  *"--json assets"*) echo {asset_count} ;;\n'
        '  "release edit "*) exit 0 ;;\n'
        '  *) echo "unexpected gh invocation: $*" >&2; exit 127 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _run_publish_step(
    release_yml: Dict[str, Any],
    tmp_path: Path,
    *,
    is_draft: Optional[str],
    asset_count: int,
) -> "subprocess.CompletedProcess[str]":
    script = _render(
        _run_script(_steps(release_yml, "create-release"), "--draft=false")
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "gh-calls.log"
    calls.touch()
    _gh_stub(bindir, is_draft=is_draft, asset_count=asset_count)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["GH_CALLS"] = str(calls)
    result = subprocess.run(  # nosec B603 B607 - fixed argv, stubbed PATH, temp dir
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    result.stderr = (
        f"{result.stderr}\n--- gh calls ---\n{calls.read_text(encoding='utf-8')}"
    )
    return result


def _published(result: "subprocess.CompletedProcess[str]") -> bool:
    return "--draft=false" in result.stderr.split("--- gh calls ---", 1)[1]


@pytestmark_bash
def test_publish_step_publishes_a_draft_that_has_assets(
    release_yml: Dict[str, Any], tmp_path: Path
) -> None:
    result = _run_publish_step(release_yml, tmp_path, is_draft="true", asset_count=4)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _published(result), result.stdout + result.stderr


@pytestmark_bash
def test_publish_step_refuses_to_publish_a_release_with_no_assets(
    release_yml: Dict[str, Any], tmp_path: Path
) -> None:
    """The empty-release failure shape, caught at the last possible moment.

    Every asset-producing job has to have succeeded for this step to run, so
    zero assets means something upstream produced nothing and stayed green.
    Publishing that is exactly what happened to v3.3.0; staying a draft keeps it
    invisible and re-dispatchable.
    """
    result = _run_publish_step(release_yml, tmp_path, is_draft="true", asset_count=0)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not _published(result), result.stdout + result.stderr
    assert "no assets" in (result.stdout + result.stderr)


@pytestmark_bash
def test_publish_step_is_a_no_op_on_an_already_published_release(
    release_yml: Dict[str, Any], tmp_path: Path
) -> None:
    """Re-dispatching a finished tag must not touch it — see the asset-clobber
    guard in ``check-release``."""
    result = _run_publish_step(release_yml, tmp_path, is_draft="false", asset_count=4)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not _published(result), result.stdout + result.stderr


@pytestmark_bash
def test_publish_step_fails_loudly_when_it_cannot_read_the_release(
    release_yml: Dict[str, Any], tmp_path: Path
) -> None:
    """A ``gh`` failure must not be mistaken for "already published".

    Piping the isDraft read into ``grep -q`` swallowed a failed read into the
    no-op branch. That was survivable while release-please published the release
    itself; now that this step is the only publisher, silently skipping it
    strands the release as a draft nobody can see.
    """
    result = _run_publish_step(release_yml, tmp_path, is_draft=None, asset_count=4)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not _published(result), result.stdout + result.stderr


# --------------------------------------------------------------------------
# The prose has to agree with the config
# --------------------------------------------------------------------------

_CONTRIBUTING_DRAFT_RE = re.compile(
    r"`release-please-config\.json`\s+sets\s+`\"draft\":\s*(true|false)`"
)


def test_contributing_states_the_draft_setting_the_config_actually_has(
    release_please_package: Dict[str, Any],
) -> None:
    """CONTRIBUTING's release walkthrough must not describe the old flow.

    This is the half that rots silently. The workflow change is enforced by the
    tests above, but the page a contributor reads to understand the release is
    plain prose, and it spent this PR's whole review claiming the release is
    "published immediately" while the config had already stopped doing that.
    Pin the one machine-checkable claim it makes -- the ``draft`` value it
    quotes -- to the value the config actually carries.
    """
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    stated = _CONTRIBUTING_DRAFT_RE.search(text)
    assert stated, (
        "CONTRIBUTING.md no longer quotes release-please-config.json's `draft` "
        "setting in the form this gate reads. If the walkthrough was reworded, "
        "reword this regex with it -- do not delete the gate: the claim it "
        "guards is the one that went stale."
    )
    claimed = stated.group(1) == "true"
    actual = release_please_package.get("draft")
    assert claimed is actual, (
        f"CONTRIBUTING.md says the release is created with draft={claimed}, but "
        f"release-please-config.json sets draft={actual}. One of them is lying "
        "to whoever reads it next."
    )
