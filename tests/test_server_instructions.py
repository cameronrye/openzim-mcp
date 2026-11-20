"""Operator-supplied server instructions (#479).

The contract, as promised on the issue:

* ``OPENZIM_MCP_INSTRUCTIONS`` (the text) or ``OPENZIM_MCP_INSTRUCTIONS_PATH``
  (a file holding it). Setting both is an error.
* The operator's text replaces the built-in instructions; a ``{{default}}``
  token in it expands to the built-in text for the running tool mode, so an
  operator adds context without copying the routing guide.
* Neither set keeps today's behaviour byte for byte. A path that is set but
  missing, unreadable or empty stops the server at startup — it never falls
  back to the built-in text silently.

Most of what follows guards the "never silently" half. The deployments this
setting is for (a mounted file, a templated env block, a host's JSON config)
fail in ways that start a server serving the wrong text, so each such shape
either refuses to start or logs a line saying what it did.

Startup log records are read with ``_collected``, not ``caplog``: server
construction runs ``logging.basicConfig(force=True)``, which removes caplog's
root handler, and a "no warning" assertion over an empty capture would pass
vacuously. Every negative log assertion below therefore first finds the INFO
record the same start must have written.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional

import pydantic
import pytest

from openzim_mcp import instructions as instructions_module
from openzim_mcp import main as main_module
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpConfigurationError
from openzim_mcp.instructions import (
    ADVANCED_INSTRUCTIONS,
    DEFAULT_TOKEN,
    INSTRUCTIONS_ENV,
    INSTRUCTIONS_PATH_ENV,
    MAX_INSTRUCTIONS_BYTES,
    SIMPLE_INSTRUCTIONS,
    ServerInstructions,
    describe_instructions,
    instructions_for,
    misspelt_instruction_variables,
    near_miss_tokens,
    report_instructions,
    resolve_instructions,
    tool_name_findings,
    unrendered_escapes,
)
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.tools import TOOL_NAMES
from tests.test_stateless_http import _collected
from tests.test_v3_field_fixes_protocol import _client

REPO = Path(__file__).resolve().parent.parent
CONFIG_DOC = REPO / "website" / "src" / "content" / "docs" / "configuration.mdx"
TOOL_MODES = ("simple", "advanced")
LOGGER = "openzim_mcp.instructions"
LIMIT = "the limit is 16384 bytes (16 KiB)."
AS_SERVED = "as clients would receive it"


def _write(path: Path, data: bytes) -> Path:
    """Write exact bytes. ``write_text`` would use the locale encoding and
    translate newlines on Windows, which the decoding tests must not see."""
    path.write_bytes(data)
    return path


def _config(
    tmp_path: Path, tool_mode: str = "simple", **kwargs: Any
) -> OpenZimMcpConfig:
    return OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)], tool_mode=tool_mode, **kwargs
    )


def _server(
    tmp_path: Path, tool_mode: str = "simple", **kwargs: Any
) -> OpenZimMcpServer:
    return OpenZimMcpServer(_config(tmp_path, tool_mode, **kwargs))


def _messages(records: List[logging.LogRecord], level: int) -> List[str]:
    return [r.getMessage() for r in records if r.levelno == level]


def _report_lines(records: List[logging.LogRecord]) -> List[str]:
    """The INFO line every start writes; asserting on it first is what keeps
    the negative warning assertions from passing on an empty capture."""
    lines = [
        m
        for m in _messages(records, logging.INFO)
        if m.startswith("Server instructions: ")
    ]
    assert len(lines) == 1, lines
    return lines


def _unreadable(path: Path) -> bool:
    """True when chmod 000 really locks this process out (not root, not
    Windows, where the mode bits do not govern reads)."""
    return not os.access(path, os.R_OK)


def _report(
    resolved: ServerInstructions,
    tool_mode: str = "simple",
    environ: Optional[Dict[str, str]] = None,
) -> List[logging.LogRecord]:
    """``report_instructions`` on its own, with an environment of the test's
    choosing. The logger is held at INFO: without a server construction
    first, the process's root level would drop the INFO line."""
    target = logging.getLogger(LOGGER)
    previous = target.level
    target.setLevel(logging.INFO)
    try:
        with _collected(LOGGER) as records:
            report_instructions(
                resolved,
                tool_mode=tool_mode,
                registered_tools=(
                    ["zim_query"] if tool_mode == "simple" else list(TOOL_NAMES)
                ),
                environ=environ or {},
            )
    finally:
        target.setLevel(previous)
    _report_lines(records)
    return records


def _configmap(mount: Path) -> Path:
    """The layout kubelet mounts a ConfigMap key in: a symlink through
    ``..data`` into a timestamped directory that each update replaces."""
    stamped = mount / "..2026_11_19_10_00_00.000000001"
    stamped.mkdir(parents=True)
    _write(stamped / "instructions.md", b"From the ConfigMap.\n")
    try:
        (mount / "..data").symlink_to(stamped.name, target_is_directory=True)
        (mount / "instructions.md").symlink_to(Path("..data") / "instructions.md")
    except OSError:
        pytest.skip("symlinks unavailable")
    return mount / "instructions.md"


# ---------------------------------------------------------------------------
# Neither set: today's behaviour, byte for byte.
# ---------------------------------------------------------------------------


class TestUnsetKeepsTheBuiltInText:
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_server_serves_the_built_in_text(
        self, tmp_path: Path, tool_mode: str
    ) -> None:
        server = _server(tmp_path, tool_mode)
        assert server.mcp.instructions == instructions_for(tool_mode)
        assert server.mcp.instructions == (
            SIMPLE_INSTRUCTIONS if tool_mode == "simple" else ADVANCED_INSTRUCTIONS
        )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "\n",
            "\t\r\n",
            "\xa0",
            "\x0c",
            "\ufeff",
            "\ufeff\ufeff",
            " \ufeff ",
        ],
    )
    @pytest.mark.parametrize("variable", [INSTRUCTIONS_ENV, INSTRUCTIONS_PATH_ENV])
    def test_a_blank_value_counts_as_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        variable: str,
        value: str,
    ) -> None:
        """A template that renders an unset variable as ``""`` keeps the default.

        The path field needs this most: pydantic coerces ``""`` to
        ``Path(".")``, a directory, which would refuse to start.
        """
        monkeypatch.setenv(variable, value)
        config = _config(tmp_path, "advanced")
        assert config.instructions is None
        assert config.instructions_path is None
        assert OpenZimMcpServer(config).mcp.instructions == ADVANCED_INSTRUCTIONS

    def test_a_blank_inline_value_beside_a_path_is_not_both_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The templated-deploy case: one variable rendered empty, one set."""
        path = _write(tmp_path / "instructions.md", b"Archive notes.\n")
        monkeypatch.setenv(INSTRUCTIONS_ENV, "")
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, str(path))
        assert _server(tmp_path).mcp.instructions == "Archive notes.\n"


# ---------------------------------------------------------------------------
# Reading the two variables.
# ---------------------------------------------------------------------------


class TestTheVariables:
    def test_the_names_are_the_documented_ones(self) -> None:
        """The issue thread and the docs promise these two names. The other
        tests build their expectations from the constants, so they would
        follow a rename that broke every deployment."""
        assert INSTRUCTIONS_ENV == "OPENZIM_MCP_INSTRUCTIONS"
        assert INSTRUCTIONS_PATH_ENV == "OPENZIM_MCP_INSTRUCTIONS_PATH"
        assert DEFAULT_TOKEN == "{{default}}"

    def test_inline_text_is_read_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(INSTRUCTIONS_ENV, "Medical archives only.")
        server = _server(tmp_path)
        assert server.mcp.instructions == "Medical archives only.\n"

    def test_a_file_is_read_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write(tmp_path / "instructions.md", b"From a file.\n")
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, str(path))
        assert _server(tmp_path).mcp.instructions == "From a file.\n"

    def test_both_set_is_a_startup_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write(tmp_path / "instructions.md", b"From a file.\n")
        monkeypatch.setenv(INSTRUCTIONS_ENV, "Inline.")
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, str(path))
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            _config(tmp_path)
        # Whole: one name is a prefix of the other, so "both names appear"
        # also holds for a message that names the path variable twice.
        assert str(excinfo.value) == (
            f"{INSTRUCTIONS_ENV} and {INSTRUCTIONS_PATH_ENV} are both set; set "
            "only one: the text itself, or the path to a UTF-8 file holding it."
        )

    def test_the_resolver_refuses_both_even_past_the_config(self) -> None:
        """``model_copy`` and attribute assignment skip validators, and this
        repo's tests build servers that way, so the resolver checks itself."""
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="Inline.", path=Path("x.md"))
        assert str(excinfo.value).startswith(
            f"{INSTRUCTIONS_ENV} and {INSTRUCTIONS_PATH_ENV} are both set; "
        )

    @pytest.mark.parametrize("blank", ["", " \n", "\ufeff"])
    def test_the_resolver_lets_a_blank_beside_a_set_source_go(
        self, tmp_path: Path, blank: str
    ) -> None:
        """The validators' blank-is-unset rule, again past the config: a blank
        on either side is not the second of "both set"."""
        path = _write(tmp_path / "instructions.md", b"From the file.\n")
        assert resolve_instructions("simple", inline="Ours.", path=blank).text == (
            "Ours.\n"
        )
        assert resolve_instructions("simple", inline=blank, path=path).text == (
            "From the file.\n"
        )

    def test_a_path_of_the_wrong_type_is_pydantics_to_reject(
        self, tmp_path: Path
    ) -> None:
        """Code can pass anything; it gets a ValidationError, not a TypeError
        from inside the normaliser."""
        with pytest.raises(pydantic.ValidationError, match="instructions_path"):
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)], instructions_path=123)

    def test_surrounding_whitespace_in_the_path_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A YAML ``|`` block leaves a trailing newline on the value, and a
        file edited on Windows a CR."""
        path = _write(tmp_path / "instructions.md", b"Padded path.\n")
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, f"\t {path}\r\n")
        assert _config(tmp_path).instructions_path == path
        assert _server(tmp_path).mcp.instructions == "Padded path.\n"

    def test_a_tilde_in_the_path_is_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        home.mkdir()
        _write(home / "instructions.md", b"Home file.\n")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, "~/instructions.md")
        assert _config(tmp_path).instructions_path == home / "instructions.md"
        assert _server(tmp_path).mcp.instructions == "Home file.\n"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows expands ~user from the home directory's parent, never raises",
    )
    def test_an_unknown_user_in_the_path_names_the_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``expanduser`` raises RuntimeError, which pydantic does not wrap:
        unhandled, it reached main()'s generic "Server startup error" arm."""
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, "~no_such_user_479/x.md")
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            _config(tmp_path)
        assert INSTRUCTIONS_PATH_ENV in str(excinfo.value)
        assert "~no_such_user_479/x.md" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Replacing, and the {{default}} token.
# ---------------------------------------------------------------------------


class TestReplaceAndExpand:
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_custom_text_replaces_the_built_in_text(self, tool_mode: str) -> None:
        resolved = resolve_instructions(tool_mode, inline="Only this.")
        assert resolved.text == "Only this.\n"
        assert "zim_query" not in resolved.text
        assert resolved.expansions == 0

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_the_token_expands_to_the_running_modes_text(self, tool_mode: str) -> None:
        resolved = resolve_instructions(
            tool_mode, inline="Medical archives.\n\n{{default}}"
        )
        assert resolved.text == "Medical archives.\n\n" + instructions_for(tool_mode)
        assert resolved.expansions == 1
        # Each mode gets its own text, so the two must differ.
        other = "advanced" if tool_mode == "simple" else "simple"
        assert instructions_for(other) not in resolved.text

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    @pytest.mark.parametrize(
        "custom",
        ["{{default}}", "{{default}}\n", "\n{{default}}\n\n\n", "  {{default}}  "],
    )
    def test_every_token_only_form_is_the_built_in_text(
        self, tool_mode: str, custom: str
    ) -> None:
        """An editor saves ``{{default}}\\n``; an env value has no newline.
        Both mean "the default", so both must be byte-identical to it."""
        assert resolve_instructions(tool_mode, inline=custom).text == instructions_for(
            tool_mode
        )

    def test_the_built_in_texts_trailing_newline_does_not_pile_up(self) -> None:
        resolved = resolve_instructions("simple", inline="{{default}}\n\nThen ours.")
        assert resolved.text == SIMPLE_INSTRUCTIONS.rstrip("\n") + "\n\nThen ours.\n"
        assert "\n\n\n" not in resolved.text

    def test_a_token_mid_sentence_keeps_single_spacing(self) -> None:
        resolved = resolve_instructions(
            "simple", inline="Medical. {{default}} Prefer it."
        )
        assert resolved.text == (
            "Medical. " + SIMPLE_INSTRUCTIONS.rstrip("\n") + " Prefer it.\n"
        )

    def test_every_token_expands(self) -> None:
        resolved = resolve_instructions(
            "simple", inline="{{default}}\n---\n{{default}}"
        )
        assert resolved.text.count(SIMPLE_INSTRUCTIONS.rstrip("\n")) == 2
        assert resolved.expansions == 2

    def test_carriage_returns_become_newlines(self, tmp_path: Path) -> None:
        crlf = _write(tmp_path / "crlf.md", b"\xef\xbb\xbfOne.\r\nTwo.\rThree.\r\n")
        assert resolve_instructions("simple", path=crlf).text == "One.\nTwo.\nThree.\n"
        assert (
            resolve_instructions("simple", inline="One.\r\nTwo.").text == "One.\nTwo.\n"
        )

    @pytest.mark.parametrize("marks", [1, 2, 3], ids=["one", "doubled", "tripled"])
    def test_a_leading_byte_order_mark_is_dropped(
        self, tmp_path: Path, marks: int
    ) -> None:
        """Notepad saves UTF-8 with a BOM; ``$(cat file)`` carries it into env,
        and re-encoding a file that already had one doubles it."""
        bom = _write(tmp_path / "bom.md", b"\xef\xbb\xbf" * marks + b"Notes.\n")
        assert resolve_instructions("simple", path=bom).text == "Notes.\n"
        inline = "\ufeff" * marks + "Notes."
        assert resolve_instructions("simple", inline=inline).text == "Notes.\n"

    def test_a_byte_order_mark_anywhere_is_dropped(self, tmp_path: Path) -> None:
        """``cat a.md b.md`` of two Notepad files puts one mid-text, and one
        behind leading whitespace would otherwise start what clients get."""
        two = _write(
            tmp_path / "two.md", b"\xef\xbb\xbfA notes.\n\xef\xbb\xbfB notes.\n"
        )
        assert resolve_instructions("simple", path=two).text == "A notes.\nB notes.\n"
        hidden = _write(tmp_path / "hidden.md", b"\xef\xbb\xbf \xef\xbb\xbfHello\n")
        assert resolve_instructions("simple", path=hidden).text == "Hello\n"
        for inline in ("A\ufeffB", " \ufeffAB", "\n\ufeffAB"):
            assert resolve_instructions("simple", inline=inline).text == "AB\n"

    def test_the_resolver_treats_blank_inline_text_as_unset(self) -> None:
        for blank in ("", "  \n", "\xa0", "\ufeff", "\ufeff\ufeff", " \ufeff"):
            resolved = resolve_instructions("advanced", inline=blank)
            assert resolved.text == ADVANCED_INSTRUCTIONS
            assert resolved.source is None

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_the_warnings_get_the_operators_own_text(self, tool_mode: str) -> None:
        """``custom`` is what the startup checks scan: the operator's words,
        newlines normalised, before the token expands."""
        resolved = resolve_instructions(tool_mode, inline="Ours.\r\n{{default}}")
        assert resolved.custom == "Ours.\n{{default}}"
        assert resolved.text != resolved.custom

    def test_the_resolver_accepts_a_string_path(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "instructions.md", b"String path.\n")
        assert resolve_instructions("simple", path=str(path)).text == "String path.\n"


# ---------------------------------------------------------------------------
# A file that is set but unusable stops startup, naming what is wrong.
# ---------------------------------------------------------------------------


def _file_error(path: Path, tool_mode: str = "simple") -> str:
    with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
        resolve_instructions(tool_mode, path=path)
    message = str(excinfo.value)
    assert message.startswith(f"{INSTRUCTIONS_PATH_ENV}={str(path)!r}"), message
    return message


class TestUnusableFiles:
    def test_a_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.md"
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} does not exist."
        )

    def test_a_relative_path_says_where_it_was_looked_for(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        message = _file_error(Path("nope.md"))
        assert "does not exist" in message
        assert repr(str(tmp_path / "nope.md")) in message

    def test_a_relative_path_keeps_its_dot_dot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collapsing ``..`` by hand, as ``os.path.abspath`` does, names a
        different file from the one opened when the directory before it is a
        symlink, so the message shows the path as the system will walk it."""
        sub = tmp_path / "sub"
        sub.mkdir()
        monkeypatch.chdir(sub)
        message = _file_error(Path("../nope.md"))
        assert repr(str(sub / ".." / "nope.md")) in message

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows cannot remove a working directory"
    )
    def test_a_relative_path_once_the_working_directory_is_gone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``Path.absolute()`` raises then. The message must still come out
        whole, or a raw OSError reaches main()'s generic error arm."""
        gone = tmp_path / "gone"
        gone.mkdir()
        monkeypatch.chdir(gone)
        gone.rmdir()
        assert _file_error(Path("instructions.md")) == (
            f"{INSTRUCTIONS_PATH_ENV}='instructions.md' does not exist."
        )

    def test_a_directory(self, tmp_path: Path) -> None:
        """What ``docker run -v`` leaves when the host file did not exist."""
        (tmp_path / "instructions.md").mkdir()
        message = _file_error(tmp_path / "instructions.md")
        assert "is a directory" in message

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
    def test_a_fifo_is_refused_without_blocking(self, tmp_path: Path) -> None:
        """``open()`` on a FIFO blocks until a writer appears; the type check
        has to come first or startup hangs.

        A regression would hang this test rather than fail it, and with no
        per-test timeout CI would only cancel the job. So a helper keeps
        opening the FIFO for writing until the resolve returns: each open
        frees a reader stuck in ``open()``, however many times the code
        opens the path, and records that one was stuck.
        """
        fifo = tmp_path / "instructions.fifo"
        os.mkfifo(fifo)
        released: List[bool] = []
        done = threading.Event()

        def _keep_freeing_stuck_readers() -> None:
            while not done.wait(0.5):
                try:
                    fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                except OSError:  # ENXIO: nobody is reading, as it should be
                    continue
                released.append(True)
                os.close(fd)

        helper = threading.Thread(target=_keep_freeing_stuck_readers, daemon=True)
        helper.start()
        try:
            message = _file_error(fifo)
        finally:
            done.set()
            helper.join()
        assert not released, "resolving blocked in open() until a writer came"
        assert message.endswith(
            "is not a regular file (it is a FIFO, socket or device)."
        )

    @pytest.mark.skipif(not Path("/dev/zero").exists(), reason="no /dev/zero")
    def test_a_device_is_refused(self) -> None:
        assert "not a regular file" in _file_error(Path("/dev/zero"))

    def test_a_dangling_symlink_is_missing(self, tmp_path: Path) -> None:
        """A link whose target was deleted reads as missing, not unreadable."""
        link = tmp_path / "instructions.md"
        try:
            link.symlink_to(tmp_path / "gone.md")
        except OSError:
            pytest.skip("symlinks unavailable")
        assert "does not exist" in _file_error(link)

    def test_a_symlink_loop_is_named(self, tmp_path: Path) -> None:
        """ELOOP has no arm of its own. It must still come out as a
        configuration error naming the variable, not reach main()'s generic
        "Server startup error" arm as a raw OSError."""
        link = tmp_path / "instructions.md"
        try:
            link.symlink_to(link)
        except OSError:
            pytest.skip("symlinks unavailable")
        assert " cannot be read: " in _file_error(link)

    def test_a_nul_in_a_path_set_in_code(self) -> None:
        """The environment cannot carry a NUL, but code can, and ``os.stat``
        raises ValueError for it, which no OSError arm catches."""
        message = _file_error(Path("instr\x00uctions.md"))
        assert " is not a usable path: " in message

    def test_a_nul_in_a_user_name_set_in_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POSIX looks ``~ro<NUL>ot`` up as a user and raises ValueError from
        there, so the config itself refuses it. Windows guesses another user's
        home from the current one's and ``os.stat`` raises instead; the guess
        is pinned here, since Windows gives up when the profile directory is
        not named after the user. Either way it is a configuration error."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "runner"))
        monkeypatch.setenv("USERNAME", "runner")
        value = "~ro\x00ot/x.md"
        if sys.platform != "win32":
            with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
                _config(tmp_path, instructions_path=value)
            assert str(excinfo.value) == (
                f"{INSTRUCTIONS_PATH_ENV}={value!r} is not a usable path: "
                "embedded null byte."
            )
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", path=value)
        assert str(excinfo.value).startswith(f"{INSTRUCTIONS_PATH_ENV}=")
        assert " is not a usable path: " in str(excinfo.value)

    def test_an_unreadable_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "instructions.md", b"Secret.\n")
        path.chmod(0)
        try:
            if not _unreadable(path):
                pytest.skip("chmod 000 does not lock this process out")
            assert _file_error(path) == (
                f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} cannot be read: Permission "
                "denied. The file, and every directory above it, must be readable "
                "by the user the server runs as."
            )
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_an_unsearchable_parent_directory(self, tmp_path: Path) -> None:
        """Python 3.12/3.13 ``Path.is_file()`` raises here and 3.14 returns
        False; either way the variable name was lost or the cause misread."""
        locked = tmp_path / "locked"
        locked.mkdir()
        path = _write(locked / "instructions.md", b"Behind a locked door.\n")
        locked.chmod(0)
        try:
            if os.access(path, os.R_OK):
                pytest.skip("chmod 000 does not lock this process out")
            assert _file_error(path).endswith(
                " cannot be read: Permission denied. The file, and every "
                "directory above it, must be readable by the user the server "
                "runs as."
            )
        finally:
            locked.chmod(stat.S_IRWXU)

    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"   \n\t\r\n",
            b"\xc2\xa0\n",  # a no-break space
            b"\x0c\n",  # a form feed
            b"\xef\xbb\xbf",
            b"\xef\xbb\xbf \n",
            b"\xef\xbb\xbf\xef\xbb\xbf",
            b"\xef\xbb\xbf \xef\xbb\xbf\n",
        ],
    )
    def test_an_empty_file(self, tmp_path: Path, data: bytes) -> None:
        path = _write(tmp_path / "instructions.md", data)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is empty (or holds only "
            "whitespace)."
        )

    @pytest.mark.parametrize(
        "bom", [b"\xff\xfe", b"\xfe\xff"], ids=["utf-16-le", "utf-16-be"]
    )
    def test_utf16_is_named(self, tmp_path: Path, bom: bytes) -> None:
        """Windows PowerShell 5.1's ``>`` writes UTF-16 with a BOM."""
        encoding = "utf-16-le" if bom == b"\xff\xfe" else "utf-16-be"
        path = _write(tmp_path / "instructions.md", bom + "Notes.".encode(encoding))
        message = _file_error(path)
        assert "UTF-16" in message and "save it as UTF-8" in message

    def test_a_nul_byte_is_refused(self, tmp_path: Path) -> None:
        """BOM-less UTF-16 of ASCII text is valid UTF-8, NULs and all, and
        ``/proc/<pid>/environ`` is NUL-separated: both must not be served."""
        path = _write(tmp_path / "instructions.md", "{{default}}".encode("utf-16-le"))
        message = _file_error(path)
        assert "NUL byte at offset 1" in message

    @pytest.mark.parametrize(
        ("data", "where"),
        [
            (b"First line.\nCaf\xe9 notes.\n", "byte 0xe9 at offset 15 (line 2)"),
            # Offsets count the BOM: it is in the file the operator opens.
            (b"\xef\xbb\xbfa\n\xe9", "byte 0xe9 at offset 5 (line 2)"),
        ],
        ids=["plain", "after-a-bom"],
    )
    def test_text_that_is_not_utf8_names_the_byte_and_line(
        self, tmp_path: Path, data: bytes, where: str
    ) -> None:
        path = _write(tmp_path / "instructions.md", data)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is not valid UTF-8: {where}; "
            "save it as UTF-8."
        )


class TestTheSizeCap:
    def test_the_cap_is_16_kib(self) -> None:
        assert MAX_INSTRUCTIONS_BYTES == 16 * 1024

    def test_a_file_exactly_at_the_cap_is_accepted(self, tmp_path: Path) -> None:
        body = b"x" * (MAX_INSTRUCTIONS_BYTES - 1) + b"\n"
        path = _write(tmp_path / "instructions.md", body)
        assert len(resolve_instructions("simple", path=path).text.encode()) == (
            MAX_INSTRUCTIONS_BYTES
        )

    def test_a_file_at_the_cap_without_a_final_newline_is_one_over(
        self, tmp_path: Path
    ) -> None:
        """The newline clients receive counts. The message says it measured
        that, since ``ls -l`` shows the file at exactly the limit."""
        path = _write(tmp_path / "instructions.md", b"x" * MAX_INSTRUCTIONS_BYTES)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is 16385 bytes {AS_SERVED} "
            f"(trimmed, with one final newline); {LIMIT}"
        )

    @pytest.mark.parametrize("size", [MAX_INSTRUCTIONS_BYTES + 1, 20_000])
    def test_a_larger_file_is_refused_with_its_real_size(
        self, tmp_path: Path, size: int
    ) -> None:
        """Checked on the raw bytes, and sized by ``fstat`` rather than by the
        bounded read, so 20000 does not come out as 16385."""
        path = _write(tmp_path / "instructions.md", b"x" * size)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is {size} bytes; {LIMIT}"
        )

    @pytest.mark.parametrize(
        "body",
        [
            b"x" * (MAX_INSTRUCTIONS_BYTES - 1) + b"\r\n",  # CRLF shrinks to LF
            b"\xef\xbb\xbf" + b"y" * (MAX_INSTRUCTIONS_BYTES - 2),  # a BOM goes
        ],
        ids=["crlf", "bom"],
    )
    def test_an_oversized_file_is_never_truncated_into_range(
        self, tmp_path: Path, body: bytes
    ) -> None:
        """One byte over as stored and under once decoded: the stored size
        decides. Checking only the decoded text let longer files start,
        serving their first 16 KiB cut off mid-line."""
        assert len(body) == MAX_INSTRUCTIONS_BYTES + 1
        path = _write(tmp_path / "instructions.md", body)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is 16385 bytes; {LIMIT}"
        )

    def test_the_read_stops_one_byte_past_the_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path pointed at an archive by mistake must not be read whole
        before it is refused. The refusal takes its size from ``fstat``, so
        only the read call itself shows the bound."""
        reads: List[int] = []
        real_open = open

        class _Recording:
            def __init__(self, handle: Any) -> None:
                self._handle = handle

            def __enter__(self) -> _Recording:
                return self

            def __exit__(self, *exc: object) -> None:
                self._handle.close()

            def read(self, size: int = -1) -> bytes:
                reads.append(size)
                return self._handle.read(size)

            def fileno(self) -> int:
                return self._handle.fileno()

        monkeypatch.setattr(
            instructions_module,
            "open",
            lambda *args, **kwargs: _Recording(real_open(*args, **kwargs)),
            raising=False,
        )
        path = _write(tmp_path / "archive.zim", b"z" * (4 * MAX_INSTRUCTIONS_BYTES))
        assert _file_error(path).endswith(f" is 65536 bytes; {LIMIT}")
        assert reads == [MAX_INSTRUCTIONS_BYTES + 1]

    def test_a_file_that_reports_no_size(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A /proc file reports size 0 however much it holds. The refusal says
        "more than" then, and the bytes read still decide: trusting the size
        would serve this CRLF file cut off at 16 KiB."""

        class _SizelessOs:
            def __getattr__(self, name: str) -> Any:
                return getattr(os, name)

            @staticmethod
            def fstat(fd: int) -> os.stat_result:
                real = os.fstat(fd)
                return os.stat_result((*real[:6], 0, *real[7:10]))

        monkeypatch.setattr(instructions_module, "os", _SizelessOs())
        path = _write(tmp_path / "instructions.md", b"line\r\n" * 3000)
        assert _file_error(path) == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is more than 16384 bytes; "
            f"{LIMIT}"
        )

    def test_an_oversized_non_ascii_file_is_reported_as_too_large(
        self, tmp_path: Path
    ) -> None:
        """A cut through a multi-byte character used to read as 'not UTF-8'."""
        path = _write(tmp_path / "instructions.md", ("é" * 9000).encode("utf-8"))
        message = _file_error(path)
        assert "the limit is" in message
        assert "UTF-8" not in message

    def test_the_expansion_counts_and_is_named(self, tmp_path: Path) -> None:
        """The same file can fit in simple mode and not in advanced mode, so
        the message says what each token adds, and in which mode."""
        filler = MAX_INSTRUCTIONS_BYTES - 1000
        path = _write(tmp_path / "instructions.md", b"z" * filler + b"\n{{default}}\n")
        assert resolve_instructions("simple", path=path).expansions == 1
        each = len(ADVANCED_INSTRUCTIONS.rstrip("\n").encode("utf-8"))
        assert _file_error(path, "advanced") == (
            f"{INSTRUCTIONS_PATH_ENV}={str(path)!r} is {filler + 1 + each + 1} "
            f"bytes {AS_SERVED}, once {DEFAULT_TOKEN} expands (once, to the "
            f"{each}-byte built-in advanced-mode text); {LIMIT}"
        )

    def test_two_expansions_are_counted(self) -> None:
        each = len(ADVANCED_INSTRUCTIONS.rstrip("\n").encode("utf-8"))
        filler = MAX_INSTRUCTIONS_BYTES - each
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions(
                "advanced", inline="z" * filler + "{{default}}{{default}}"
            )
        assert str(excinfo.value) == (
            f"{INSTRUCTIONS_ENV} is {filler + 2 * each + 1} bytes {AS_SERVED}, "
            f"once {DEFAULT_TOKEN} expands (2 times, to the {each}-byte built-in "
            f"advanced-mode text); {LIMIT}"
        )

    def test_inline_text_has_the_same_cap(self) -> None:
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="w" * (MAX_INSTRUCTIONS_BYTES + 1))
        assert str(excinfo.value) == (
            f"{INSTRUCTIONS_ENV} is 16386 bytes {AS_SERVED} (trimmed, with one "
            f"final newline); {LIMIT}"
        )

    def test_the_inline_cap_counts_the_final_newline(self) -> None:
        """16383 characters and the newline make 16384 bytes, which fits; one
        character more does not."""
        fits = resolve_instructions("simple", inline="w" * (MAX_INSTRUCTIONS_BYTES - 1))
        assert len(fits.text.encode("utf-8")) == MAX_INSTRUCTIONS_BYTES
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="w" * MAX_INSTRUCTIONS_BYTES)
        assert str(excinfo.value).startswith(f"{INSTRUCTIONS_ENV} is 16385 bytes ")

    def test_the_cap_counts_bytes_not_characters(self) -> None:
        """9000 two-byte characters are well under 16384 characters."""
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="é" * 9000)
        assert str(excinfo.value).startswith(f"{INSTRUCTIONS_ENV} is 18001 bytes ")


class TestInlineEncoding:
    @pytest.mark.parametrize("byte", [0x80, 0xE9, 0xFF])
    def test_an_undecodable_byte_is_a_named_startup_error(self, byte: int) -> None:
        """``os.environ`` decodes a byte that is not UTF-8 (cp1252's euro sign,
        Latin-1's e-acute or y-diaeresis) to a lone surrogate between U+DC80 and
        U+DCFF. Left in, it crashed the stdio writer on the first
        ``initialize``."""
        stand_in = chr(0xDC00 + byte)
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline=f"Archives: caf{stand_in} recipes")
        assert str(excinfo.value) == (
            f"{INSTRUCTIONS_ENV} is not valid UTF-8: it holds the undecodable "
            f"byte 0x{byte:02x} at character 14 (line 1). Set it from UTF-8 text, "
            f"or put the text in a UTF-8 file and set {INSTRUCTIONS_PATH_ENV}."
        )

    def test_the_position_counts_lines(self) -> None:
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="one\ntwo\ncaf\udce9")
        assert " the undecodable byte 0xe9 at character 12 (line 3). " in str(
            excinfo.value
        )

    def test_a_position_counts_the_byte_order_marks_too(self) -> None:
        """BOMs are dropped after the check, so a position is in the value as
        it was set."""
        value = chr(0xFEFF) + "caf" + chr(0xDCE9)
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline=value)
        assert " the undecodable byte 0xe9 at character 5 (line 1). " in str(
            excinfo.value
        )

    def test_a_lone_surrogate_from_code_is_not_called_a_byte(self) -> None:
        """Only code can pass a surrogate outside surrogateescape's range,
        and it does not stand for a byte."""
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            resolve_instructions("simple", inline="x\ud800y")
        assert " it holds the lone surrogate U+D800 at character 2 (line 1). " in (
            str(excinfo.value)
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX environ bytes")
    def test_the_same_byte_through_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # os.environ re-encodes the surrogate as the original 0xe9 byte.
        monkeypatch.setenv(INSTRUCTIONS_ENV, "caf\udce9")
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            _server(tmp_path)
        assert str(excinfo.value).startswith(f"{INSTRUCTIONS_ENV} is not valid UTF-8: ")


# ---------------------------------------------------------------------------
# The server wiring, and what a client receives.
# ---------------------------------------------------------------------------


class TestServerWiring:
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_the_server_serves_the_resolved_text(
        self, tmp_path: Path, tool_mode: str
    ) -> None:
        server = _server(tmp_path, tool_mode, instructions="Ours.\n\n{{default}}")
        assert server.mcp.instructions == "Ours.\n\n" + instructions_for(tool_mode)
        assert server.server_instructions.text == server.mcp.instructions

    def test_a_bad_file_fails_before_the_cache_is_built(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail fast: a typo'd path must not first load a persistence file."""
        import openzim_mcp.server as server_module

        def _no_cache(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("the cache was built before instructions resolved")

        monkeypatch.setattr(server_module, "OpenZimMcpCache", _no_cache)
        config = _config(tmp_path, instructions_path=tmp_path / "missing.md")
        with pytest.raises(OpenZimMcpConfigurationError, match="does not exist"):
            OpenZimMcpServer(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_mode", TOOL_MODES)
@pytest.mark.parametrize("modern", [False, True], ids=["initialize", "discover"])
async def test_both_protocol_eras_receive_the_custom_text(
    tmp_path: Path, tool_mode: str, modern: bool
) -> None:
    """``initialize`` and ``server/discover`` must carry the same string."""
    expected = "Medical archives.\n\n" + instructions_for(tool_mode)
    server = _server(
        tmp_path, tool_mode, instructions="Medical archives.\n\n{{default}}"
    )
    async with _client(tmp_path, modern=modern, server=server) as session:
        if modern:
            result = await session.discover()
            # The docs tell operators a 2026-07-28 client may keep the text
            # for up to an hour; that is this hint.
            assert result.ttl_ms == 60 * 60 * 1000
            assert result.cache_scope == "private"
        else:
            result = await session.initialize()
    assert result.instructions == expected


# ---------------------------------------------------------------------------
# What startup says about the text it is serving.
# ---------------------------------------------------------------------------


class TestStartupReport:
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_the_built_in_case_is_logged_too(
        self, tmp_path: Path, tool_mode: str
    ) -> None:
        """A variable that never reached the process is silent otherwise."""
        with _collected(LOGGER) as records:
            _server(tmp_path, tool_mode)
        (line,) = _report_lines(records)
        size = len(instructions_for(tool_mode).encode("utf-8"))
        assert line == (
            f"Server instructions: built-in, for {tool_mode} mode ({size} bytes)"
        )
        assert not _messages(records, logging.WARNING)

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_a_file_with_the_token(self, tmp_path: Path, tool_mode: str) -> None:
        path = _write(tmp_path / "instructions.md", b"Notes.\n\n{{default}}\n")
        with _collected(LOGGER) as records:
            server = _server(tmp_path, tool_mode, instructions_path=path)
        (line,) = _report_lines(records)
        text = server.mcp.instructions
        # The path appears as repr() writes it, so a Windows path shows every
        # backslash doubled; the expectation is built the same way.
        assert line == (
            f"Server instructions: custom, from {INSTRUCTIONS_PATH_ENV}="
            f"{str(path)!r} ({len(text.encode('utf-8'))} bytes, {len(text)} "
            f"characters); the built-in {tool_mode}-mode guidance is included via "
            "{{default}}"
        )

    def test_inline_text_without_the_token_says_the_guidance_is_gone(
        self, tmp_path: Path
    ) -> None:
        """A template engine that ate ``{{default}}`` leaves only this line."""
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions="Use me for medicine.")
        (line,) = _report_lines(records)
        assert line.startswith(
            f"Server instructions: custom, from {INSTRUCTIONS_ENV} ("
        )
        assert line.endswith(
            "; the built-in guidance is not included (no {{default}} token)"
        )
        # The text itself is the operator's business, not the log's.
        assert "Use me for medicine" not in line

    def test_two_tokens_are_counted(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions="{{default}}\n{{default}}")
        (line,) = _report_lines(records)
        assert line.endswith("guidance is included 2 times via {{default}}")

    def test_a_configmap_mount_is_logged_as_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resolving the key's symlink would put the timestamped directory,
        which every update replaces, in the config, its hash and this line."""
        path = _configmap(tmp_path / "config")
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, str(path))
        config = _config(tmp_path)
        assert config.instructions_path == path
        with _collected(LOGGER) as records:
            server = OpenZimMcpServer(config)
        assert server.mcp.instructions == "From the ConfigMap.\n"
        (line,) = _report_lines(records)
        assert line.startswith(
            f"Server instructions: custom, from {INSTRUCTIONS_PATH_ENV}="
            f"{str(path)!r} ("
        )

    def test_a_relative_configmap_path_is_not_followed_either(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mount = tmp_path / "config"
        _configmap(mount)
        monkeypatch.chdir(mount)
        resolved = resolve_instructions("simple", path="instructions.md")
        assert describe_instructions(resolved, "simple").startswith(
            f"Server instructions: custom, from {INSTRUCTIONS_PATH_ENV}="
            "'instructions.md' (resolved against the working directory: "
            f"{str(mount / 'instructions.md')!r}) ("
        )


class TestToolNameWarnings:
    def test_simple_mode_warns_about_tools_it_does_not_register(
        self, tmp_path: Path
    ) -> None:
        """Simple is the default mode, and the requester adds context: text
        that names ``zim_search`` describes a tool the client cannot call."""
        with _collected(LOGGER) as records:
            _server(
                tmp_path,
                "simple",
                instructions="Use zim_search, then `zim_get`, then zim_search.",
            )
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions name zim_search, zim_get, which simple mode does "
            "not register; clients are offered only zim_query. Set "
            "OPENZIM_MCP_TOOL_MODE=advanced (or pass --mode advanced), or remove "
            "those names."
        )

    def test_one_unregistered_name_reads_as_one(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(tmp_path, "simple", instructions="Use zim_search.")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning.startswith("Server instructions name zim_search, which ")
        assert warning.endswith(", or remove that name.")

    def test_the_mode_hint_names_a_flag_the_cli_takes(self, tmp_path: Path) -> None:
        """The warning tells operators what to type, so the parser must take
        it; a flag renamed in one place only fails here."""
        with _collected(LOGGER) as records:
            _server(tmp_path, "simple", instructions="Use zim_search.")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        found = re.search(r"\(or pass (--[\w-]+) advanced\)", warning)
        assert found, warning
        parser = main_module._build_arg_parser()
        args = parser.parse_args([found.group(1), "advanced", str(tmp_path)])
        assert args.mode == "advanced"

    def test_advanced_mode_registers_them(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(
                tmp_path, "advanced", instructions="Use zim_search, then `zim_get`."
            )
        _report_lines(records)
        assert not _messages(records, logging.WARNING)

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_the_expanded_default_is_never_scanned(
        self, tmp_path: Path, tool_mode: str
    ) -> None:
        """Only the operator's words are theirs to fix. A near-miss after the
        token is reported on the operator's own line, not one shifted by the
        built-in text's lines, so the scan did not run on the expansion."""
        with _collected(LOGGER) as records:
            _server(tmp_path, tool_mode, instructions="{{default}}\nSee {{ default }}.")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning.startswith(
            "Server instructions contain '{{ default }}' (line 2), "
        )

    def test_a_close_misspelling_gets_a_suggestion(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(tmp_path, "advanced", instructions="Try zim_serach first.")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions name zim_serach (did you mean zim_search?), which "
            "is not a tool on this server."
        )

    def test_a_suggestion_simple_mode_lacks_says_so(self, tmp_path: Path) -> None:
        """Fixing the spelling alone would earn a second warning next start."""
        with _collected(LOGGER) as records:
            _server(tmp_path, "simple", instructions="Try zim_serach first.")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions name zim_serach (did you mean zim_search? It is "
            "registered in advanced mode only.), which is not a tool on this "
            "server."
        )

    def test_two_misspellings_are_named_together(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(
                tmp_path, "advanced", instructions="Try zim_serach or zim_gett first."
            )
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions name zim_serach (did you mean zim_search?), "
            "zim_gett (did you mean zim_get?), which are not tools on this server."
        )

    def test_a_suggestion_this_mode_lacks_says_so(self) -> None:
        unregistered, typos = tool_name_findings("Try zim_serach.", ["zim_query"])
        assert unregistered == []
        assert typos == [("zim_serach", "zim_search", False)]

    @pytest.mark.parametrize(
        ("typo", "tool"),
        [
            ("zim_gte", "zim_get"),  # 0.857: one letter off in the shortest tool
            ("zim_qry", "zim_query"),  # 0.875
            ("zim_qeury", "zim_query"),  # 0.889: a transposition
            ("zim_query2", "zim_query"),  # digits are part of the name
            ("zim_get_sections", "zim_get_section"),  # longer than any tool
        ],
    )
    def test_typos_close_to_a_tool_get_a_suggestion(self, typo: str, tool: str) -> None:
        unregistered, typos = tool_name_findings(f"Use {typo}.", ["zim_query"])
        assert (unregistered, typos) == ([], [(typo, tool, tool == "zim_query")])

    @pytest.mark.parametrize(
        "word",
        [
            "zim_section",  # 0.846 against zim_get_section
            "zim_list",  # 0.824 against zim_links
            "zim_data",  # 0.8: a volume name
        ],
    )
    def test_words_further_off_are_left_alone(self, word: str) -> None:
        """Where the 0.85 cutoff sits: below the closest typo (0.857) and
        above the closest words that are not one."""
        assert tool_name_findings(f"Mount the {word} volume.", ["zim_query"]) == (
            [],
            [],
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Pass zim_file_path to pick an archive.",
            "This openzim_mcp server holds medicine.",
            "my_zim_archive is the main one.",
            "Errors such as zim_path_not_found mean the path is wrong.",
            "The backup is zim_backup.zim.",
            "Mount the zim_data volume, or zim_meta, or zim_queries.",
            # Each of these holds a real tool name, which simple mode would
            # report as unregistered if the rule it exercises let it through.
            "Call tools.zim_search for terms.",
            "Archives live in /srv/zim_search and /srv/zim_data/.",
            "Files are in C:\\archives\\zim_search",
            "Mirror it to backup-zim_search nightly.",
            "See zim_links.md for the link policy.",
            "Put archives under zim_search/wiki.zim",
            "The zim_search/ directory holds them.",
            "The zim_search-2024 share is read-only.",
            "The zim_searchAPI wrapper.",
            "zim_search\\wiki.zim holds it.",
            "See https://example.com/zim_search for more.",
            "The .zim_search file is hidden.",  # only trailing dots go
            "Logs go to /var/log/mcp__zim_search",  # a path, '__' tail or not
            "Logs go to C:\\logs\\mcp__zim_search",
            # A Latin letter against a name makes it part of a longer word.
            "La table zim_get_sección.",
            "Le café_zim_search est fermé.",
            # So does an underscore against a letter of another script, on
            # one side or both.
            "Поле кафе_zim_search в таблице.",
            "Колонка zim_get_раздел.",
            "Колонка кафе_zim_search_раздел.",
            # A hyphen after a space is not a prefix.
            "Use -zim_search here.",
        ],
    )
    def test_names_that_are_not_tools_are_left_alone(self, text: str) -> None:
        assert tool_name_findings(text, ["zim_query"]) == ([], [])

    @pytest.mark.parametrize(
        "letter",
        [chr(0xC0), chr(0xF6), chr(0xF8), chr(0x1CE), chr(0x301), chr(0x1E01)],
        ids=[
            "a-grave",
            "o-diaeresis",
            "o-stroke",
            "a-caron",
            "combining-acute",
            "a-ring-below",
        ],
    )
    def test_a_latin_letter_continues_the_word(self, letter: str) -> None:
        """One letter from each range of the run class: a name glued to it is
        part of a longer word, as ``zim_get_sección`` is."""
        assert tool_name_findings(f"Use zim_search{letter}.", ["zim_query"]) == (
            [],
            [],
        )

    @pytest.mark.parametrize(
        "mark",
        [chr(0xD7), chr(0xF7), chr(0x434), chr(0x3B1), chr(0x5D0)],
        ids=["times-sign", "division-sign", "cyrillic", "greek", "hebrew"],
    )
    def test_anything_else_ends_the_name(self, mark: str) -> None:
        """The two signs inside the Latin-1 letters, and every other script."""
        assert tool_name_findings(f"Use zim_search{mark}2.", ["zim_query"]) == (
            ["zim_search"],
            [],
        )

    @pytest.mark.parametrize(
        ("text", "named"),
        [
            ("Use __zim_search__ for exact terms.", ["zim_search"]),
            ("Use _zim_search_ here.", ["zim_search"]),
            ("Use **zim_search** and `zim_get`.", ["zim_search", "zim_get"]),
            ("End on zim_search.", ["zim_search"]),
            ("Use zim_search... then zim_get.", ["zim_search", "zim_get"]),
            # Prettier writes italics with the full stop inside the marker.
            ("_Then call zim_get._", ["zim_get"]),
            ("__Never call zim_health.__", ["zim_health"]),
            ("_Always start with zim_query_, the one tool here.", []),
        ],
    )
    def test_markdown_around_a_name_is_not_part_of_it(
        self, text: str, named: List[str]
    ) -> None:
        """The docs keep the text in a Markdown file; emphasis around a correct
        name must not turn it into a "did you mean" about itself."""
        assert tool_name_findings(text, ["zim_query"]) == (named, [])

    @pytest.mark.parametrize(
        ("text", "named"),
        [
            ("그다음 _zim_get_으로 읽으세요.", ["zim_get"]),
            ("需要某一节时，用_zim_get_section_。", ["zim_get_section"]),
            ("Prefer _zim_search_\u00b9 for terms.", ["zim_search"]),
        ],
        ids=["korean-particle-after", "chinese-word-before", "footnote-after"],
    )
    def test_emphasis_glued_on_one_side_is_still_emphasis(
        self, text: str, named: List[str]
    ) -> None:
        """Underscores at both ends with one side free are emphasis, which
        these scripts and footnote marks glue to the other side."""
        assert tool_name_findings(text, ["zim_query"]) == (named, [])

    def test_a_typo_inside_emphasis_is_still_a_typo(self) -> None:
        assert tool_name_findings("__Then try zim_serach.__", ["zim_query"]) == (
            [],
            [("zim_serach", "zim_search", False)],
        )

    @pytest.mark.parametrize(
        "text",
        [
            "请优先使用zim_search检索词条，再用zim_get读取。",
            "まずzim_searchで検索し、zim_getで記事を読みます。",
            "먼저 zim_search를 사용하고, 그다음 zim_get으로 읽으세요.",
            "השתמש ב-zim_search ואז ב-zim_get.",
        ],
        ids=["chinese", "japanese", "korean", "hebrew"],
    )
    def test_names_in_text_without_spaces_around_them(self, text: str) -> None:
        """Chinese and Japanese put no space around a Latin word, Korean
        attaches particles to it and Hebrew a prefix with a hyphen; none of
        that may join the name."""
        assert tool_name_findings(text, ["zim_query"]) == (
            ["zim_search", "zim_get"],
            [],
        )
        assert tool_name_findings("zim_serach를 사용하세요.", ["zim_query"]) == (
            [],
            [("zim_serach", "zim_search", False)],
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Call mcp__openzim__zim_search for terms.",
            "Call mcp__openzim-mcp-local__zim_search for terms.",
            "Call mcp__zim__zim_search for terms.",
        ],
    )
    def test_client_qualified_names_count(self, text: str) -> None:
        assert tool_name_findings(text, ["zim_query"]) == (["zim_search"], [])

    @pytest.mark.parametrize(
        "text",
        [
            "Use zim_get/zim_get_section for articles.",
            "Use _zim_get/zim_get_section_ for articles.",
            "Use __zim_get/zim_get_section__.",
        ],
    )
    def test_names_joined_by_a_slash_are_alternatives(self, text: str) -> None:
        assert tool_name_findings(text, ["zim_query"]) == (
            ["zim_get", "zim_get_section"],
            [],
        )

    def test_a_doubled_underscore_is_a_typo_not_a_qualifier(self) -> None:
        assert tool_name_findings("Try zim__search.", ["zim_query"]) == (
            [],
            [("zim__search", "zim_search", False)],
        )

    def test_a_repeated_name_is_reported_once(self) -> None:
        assert tool_name_findings(
            "zim_search, zim_search, zim_serach, zim_serach", ["zim_query"]
        ) == (["zim_search"], [("zim_serach", "zim_search", False)])

    def test_every_identifier_the_server_publishes_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        """Parameter, resource and template names are real and must not warn.

        Read off a live advanced server, so a new argument or resource that
        happens to look like a misspelt tool fails here by name.
        """
        server = _server(tmp_path, "advanced")
        names = set(server.mcp.registered_tool_names())
        for tool in server.mcp._tool_manager.list_tools():
            names.update(tool.parameters.get("properties", {}))
        names.update(r.name for r in server.mcp._resource_manager.list_resources())
        names.update(t.name for t in server.mcp._resource_manager.list_templates())
        zim_names = sorted(n for n in names if n.startswith("zim_"))
        assert "zim_file_path" in zim_names
        text = " ".join(zim_names)
        assert tool_name_findings(text, server.mcp.registered_tool_names()) == ([], [])


def _scan(text: str) -> None:
    near_miss_tokens(text)
    unrendered_escapes(text)
    tool_name_findings(text, ["zim_query"])


def _cheapest(call: Callable[[], object], repeats: int = 7) -> float:
    """The least noisy estimate of a cost on a shared runner."""
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - start)
    return best


# Each of the first seven is quadratic under some form of the patterns: a
# brace run, and braces before "default", under a near-miss pattern without
# its lookbehind; "{{" and spaces under the natural greedy form of that
# pattern (\s*\.?\s* in the middle); a zim_ run under a tool pattern that can
# start a match inside a word; and the "__"-joined runs under one that let a
# match start after every "__". The escape openers have no such history and
# keep a broadening of that pattern honest.
_SCAN_SHAPES: Dict[str, Callable[[int], str]] = {
    "brace-run": lambda n: "{" * n,
    "brace-then-spaces": lambda n: "{{" + " " * n,
    "braces-then-default": lambda n: "{" * (n // 2) + "default" + " " * (n // 2),
    "zim-run-then-slash": lambda n: "zim_" * (n // 4) + "/",
    "qualified-run-then-slash": lambda n: "__zim_" * (n // 6) + "/",
    "underscored-run-then-capital": lambda n: "_zim_" * (n // 5) + "X",
    "doubled-run-then-dot": lambda n: "zim__" * (n // 5) + ".x",
    "helm-escape-openers": lambda n: '{{ "' * (n // 4),
    "helm-escape-then-spaces": lambda n: '{{"{{default}}"' + " " * n,
    "raw-escape-openers": lambda n: "{% raw %}" * (n // 9),
    "raw-tag-then-spaces": lambda n: "{%" + " " * n,
    "raw-tag-name-then-spaces": lambda n: "{% raw" + " " * n,
    "raw-blocks": lambda n: "{% raw %}x{% endraw %}" * (n // 22),
}
# Four times the text: about four times the time when linear, sixteen when
# quadratic. Both sides are timed in one process, so the bound holds on any
# machine (#474 replaced an absolute budget that failed on a slow runner).
_GROWTH_BOUND = 10.0


class TestTokenWarnings:
    @pytest.mark.parametrize(
        "near_miss",
        [
            "{{ default }}",
            "{{DEFAULT}}",
            "{default}",
            "{{defaults}}",
            "{{{default}}}",
            "{{default}}}",
            "${default}",
            "{{ .Default }}",
        ],
    )
    def test_near_misses_are_reported_with_their_line(self, near_miss: str) -> None:
        text = f"Line one.\nLine two.\n{near_miss} here."
        assert near_miss_tokens(text) == [(near_miss, 3)]

    @pytest.mark.parametrize(
        "text",
        [
            "{{default}}",
            "Plain {{default}} use.",
            'JSON like {"default": true}.',
            "the {default: true} flag",
            "by default}} weird",
            "Use the defaults.",
        ],
    )
    def test_everything_else_is_quiet(self, text: str) -> None:
        assert near_miss_tokens(text) == []

    def test_each_near_miss_is_reported_once_on_its_own_line(self) -> None:
        """Lines run on from one match to the next, across a near-miss that
        itself spans lines; a repeat is reported where it first appears."""
        text = (
            "Intro.\n{{ default }}\nMore.\n{{\ndefault\n}}\n"
            "And {default} here.\n{{ default }} again."
        )
        assert near_miss_tokens(text) == [
            ("{{ default }}", 2),
            ("{{\ndefault\n}}", 4),
            ("{default}", 7),
        ]

    def test_the_warning_is_logged(self, tmp_path: Path) -> None:
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions="Ours.\n{{ default }}")
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions contain '{{ default }}' (line 2), which is not "
            "the {{default}} token: only the exact text {{default}} is replaced, "
            "and anything else is sent to clients as written."
        )

    def test_two_near_misses_share_one_warning(self) -> None:
        records = _report(
            resolve_instructions("simple", inline="Ours.\n{{ default }}\n{default}")
        )
        (warning,) = _messages(records, logging.WARNING)
        assert warning.startswith(
            "Server instructions contain '{{ default }}' (line 2), '{default}' "
            "(line 3), which are not the {{default}} token: "
        )

    def test_the_token_inside_extra_braces_expands_and_is_said_to(
        self, tmp_path: Path
    ) -> None:
        """The startup line says the guidance is included, so the warning
        must not say this went out as written."""
        with _collected(LOGGER) as records:
            server = _server(tmp_path, instructions="Notes.\n{{{default}}}")
        (line,) = _report_lines(records)
        assert line.endswith("guidance is included via {{default}}")
        assert server.mcp.instructions == (
            "Notes.\n{" + SIMPLE_INSTRUCTIONS.rstrip("\n") + "}\n"
        )
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions contain '{{{default}}}' (line 2): the {{default}} "
            "inside expands, but the characters around it are sent to clients as "
            "written."
        )

    def test_both_kinds_of_near_miss_are_told_apart(self) -> None:
        """Each warning lists only its own spellings and counts only them."""
        records = _report(
            resolve_instructions("simple", inline="Ours.\n{{ default }}\n{{{default}}}")
        )
        assert _messages(records, logging.WARNING) == [
            "Server instructions contain '{{ default }}' (line 2), which is not "
            "the {{default}} token: only the exact text {{default}} is replaced, "
            "and anything else is sent to clients as written.",
            "Server instructions contain '{{{default}}}' (line 3): the {{default}} "
            "inside expands, but the characters around it are sent to clients as "
            "written.",
        ]

    @pytest.mark.parametrize("source", ["inline", "file"])
    def test_lines_count_from_the_operators_first_line(
        self, tmp_path: Path, source: str
    ) -> None:
        """Leading blank lines are trimmed from what clients get, but not
        from what the warnings count: the operator's editor shows them."""
        text = "\n\nSee {{ default }}."
        if source == "file":
            path = _write(tmp_path / "instructions.md", text.encode("utf-8"))
            kwargs: Dict[str, Any] = {"instructions_path": path}
        else:
            kwargs = {"instructions": text}
        with _collected(LOGGER) as records:
            server = _server(tmp_path, **kwargs)
        assert server.mcp.instructions == "See {{ default }}.\n"
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning.startswith(
            "Server instructions contain '{{ default }}' (line 3), "
        )

    @pytest.mark.parametrize(
        ("escape", "quoted"),
        [
            # Helm escapes are quoted whole.
            ('{{ "{{default}}" }}', None),
            ("{{ '{{default}}' }}", None),
            ("{{`{{default}}`}}", None),
            ('{{- "{{default}}" -}}', None),
            ('{{\t"{{default}}"\t}}', None),
            ('{{\n  "{{default}}"\n}}', None),  # a Go action may span lines
            # A Jinja raw block by its opening tag, however its text is laid out.
            ("{% raw %}{{default}}{% endraw %}", "{% raw %}"),
            ("{%- raw -%}{{default}}{%- endraw -%}", "{%- raw -%}"),
            ("{%+ raw %}{{default}}{%+ endraw %}", "{%+ raw %}"),
            ("{% raw %} {{default}} {% endraw %}", "{% raw %}"),
            ("{% raw %}\n{{default}}\n{% endraw %}", "{% raw %}"),
            ("{% raw %}\nMedical.\n\n{{default}}\n{% endraw %}\n", "{% raw %}"),
            # The docs' own form, quoted whole in a code span.
            ("`{% raw %}{{default}}{% endraw %}`", "{% raw %}"),
            # Raw blocks do not nest: the first tag opens the block.
            ("{% raw %}{%- raw -%}{{default}}{% endraw %}", "{% raw %}"),
        ],
    )
    def test_an_unrendered_template_escape_is_found(
        self, escape: str, quoted: Optional[str]
    ) -> None:
        """The escapes the docs teach, when no template engine ran: the
        token inside still expands, inside the escape."""
        text = f"Line one.\n\n{escape}"
        assert unrendered_escapes(text) == [(quoted or escape, 3)]
        assert near_miss_tokens(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            "{{default}}",
            'Write "{{default}}" in the file.',
            "{% raw %}",
            "{{ \"{{default}}' }}",  # the quotes do not match
            "{% raw %}x{% endraw %} {{default}}",  # the token is outside
            "{% raw %}{{default}}",  # never closed, so never rendered either way
            # Prose about the syntax, each tag in a code span of its own.
            "In Jinja, `{% raw %}` starts a literal block.\n\n{{default}}\n\n"
            "A literal block ends with `{% endraw %}`.",
        ],
    )
    def test_no_escape_no_escape_warning(self, text: str) -> None:
        assert unrendered_escapes(text) == []

    def test_each_escape_is_listed_once_on_its_line(self) -> None:
        """In the order they appear, across both kinds, a repeat dropped."""
        text = (
            '{{ "{{default}}" }}\n\n{% raw %}{{default}}{% endraw %}\n\n'
            "{{ '{{default}}' }}\n\n"
            '{{ "{{default}}" }}'
        )
        assert unrendered_escapes(text) == [
            ('{{ "{{default}}" }}', 1),
            ("{% raw %}", 3),
            ("{{ '{{default}}' }}", 5),
        ]

    @pytest.mark.parametrize("source", ["inline", "file"])
    def test_the_escape_warning_is_logged(self, tmp_path: Path, source: str) -> None:
        """A values file or a copied file is where the docs say this happens."""
        text = 'Ours.\n{{ "{{default}}" }}'
        if source == "file":
            path = _write(tmp_path / "instructions.md", text.encode("utf-8"))
            kwargs: Dict[str, Any] = {"instructions_path": path}
        else:
            kwargs = {"instructions": text}
        with _collected(LOGGER) as records:
            server = _server(tmp_path, **kwargs)
        (line,) = _report_lines(records)
        assert line.endswith("guidance is included via {{default}}")
        assert server.mcp.instructions == (
            'Ours.\n{{ "' + SIMPLE_INSTRUCTIONS.rstrip("\n") + '" }}\n'
        )
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            "Server instructions contain '{{ \"{{default}}\" }}' (line 2): a "
            "{{default}} inside a template escape that was never rendered still "
            "expands, but the escape around it is sent to clients as written."
        )

    @pytest.mark.parametrize("shape", sorted(_SCAN_SHAPES))
    def test_the_scans_stay_linear(self, shape: str) -> None:
        small = _SCAN_SHAPES[shape](MAX_INSTRUCTIONS_BYTES)
        large = _SCAN_SHAPES[shape](4 * MAX_INSTRUCTIONS_BYTES)
        # One pass at the cap first: a pattern gone quadratic takes most of a
        # second there and a minute or more at four times the size, so stop
        # early. Linear scans take a millisecond or two, and under coverage
        # and full CPU load at most about 40 ms.
        start = time.perf_counter()
        _scan(small)
        assert time.perf_counter() - start < 0.5, f"{shape}: slow at the cap"
        growth = _cheapest(lambda: _scan(large)) / _cheapest(lambda: _scan(small))
        assert growth < _GROWTH_BOUND, f"{shape}: 4x the text took {growth:.1f}x"


class TestMisconfigurationWarnings:
    @pytest.mark.parametrize(
        "variable",
        [
            "OPENZIM_MCP_INSTRUCTIONS__PATH",
            "OPENZIM_MCP_INSTRUCTIONS_FILE",
            "OPENZIM_MCP_INSTRUCTION",
            "OPENZIM_MCP_INSTRUCTION_PATH",
        ],
    )
    def test_a_misspelt_variable_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
    ) -> None:
        """pydantic-settings ignores names it does not know, so these start
        the server on the built-in text with no other signal."""
        monkeypatch.setenv(variable, "/config/instructions.md")
        with _collected(LOGGER) as records:
            _server(tmp_path)
        (line,) = _report_lines(records)
        assert line.startswith("Server instructions: built-in")
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            f"{variable} is not a setting and is ignored: the server reads "
            f"{INSTRUCTIONS_ENV} (the text itself) and {INSTRUCTIONS_PATH_ENV} (a "
            "file holding it)."
        )

    def test_misspellings_are_found_in_any_case(self) -> None:
        """The settings model reads names case-insensitively, so it ignores a
        lower-case misspelling just as silently."""
        environ = {"openzim_mcp_instructions_file": "x", "Openzim_Mcp_Instruction": "y"}
        assert misspelt_instruction_variables(environ) == [
            "Openzim_Mcp_Instruction",
            "openzim_mcp_instructions_file",
        ]

    def test_the_real_names_in_any_case_are_not_misspelt(self) -> None:
        environ = {
            "OPENZIM_MCP_INSTRUCTIONS": "x",
            "openzim_mcp_instructions_path": "y",
            "OPENZIM_MCP_TOOL_MODE": "simple",
        }
        assert misspelt_instruction_variables(environ) == []

    def test_two_misspelt_variables_share_one_warning(self) -> None:
        records = _report(
            resolve_instructions("simple"),
            environ={
                "OPENZIM_MCP_INSTRUCTION": "x",
                "OPENZIM_MCP_INSTRUCTIONS_FILE": "y",
            },
        )
        (warning,) = _messages(records, logging.WARNING)
        assert warning.startswith(
            "OPENZIM_MCP_INSTRUCTION, OPENZIM_MCP_INSTRUCTIONS_FILE are not "
            "settings and are ignored: "
        )

    @pytest.mark.parametrize(
        "name",
        [
            "OPENZIM_MCP_INSTRUCTIONS_FILE\n2026-11-19 10:00:00 - INFO - forged",
            "OPENZIM_MCP_INSTRUCTIONS_FILE\rINFO - forged",
            "OPENZIM_MCP_INSTRUCTIONS_FILE\x1b[2K",
            "OPENZIM_MCP_INSTRUCTIONS ",
            "OPENZIM_MCP_INSTRUCTIONS PATH",
        ],
        ids=[
            "newline",
            "carriage-return",
            "escape-sequence",
            "trailing-space",
            "inner-space",
        ],
    )
    def test_a_name_that_would_mislead_the_log_is_quoted(self, name: str) -> None:
        """POSIX allows control characters in a variable name, and logged raw
        they start or overwrite a line that reads as the server's own. cmd.exe's
        ``set NAME = value`` keeps the space, which would read as the real
        name."""
        records = _report(resolve_instructions("simple"), environ={name: "x"})
        (warning,) = _messages(records, logging.WARNING)
        assert warning.isprintable()
        assert warning.startswith(f"{name!r} is not a setting and is ignored: ")

    # The inline values; ``{home}`` is the test's home directory, and the
    # warning quotes the value, or _QUOTED_AS's form of it. The files under
    # ``{home}`` are real; every other path is missing, and each one is
    # written so that only the rule its group names can make it warn.
    _FILE_PATHS: Dict[str, str] = {
        # Files that exist, found by looking: spaced and with no extension.
        "spaced-absolute": "{home}/My Notes/instructions",
        "spaced-home-relative": "~/My Notes/instructions",
        "spaced-relative": "My Notes/instructions",
        # A file name or a relative path, ending in a text-file extension.
        "a-file-name": "notes.md",
        "a-relative-file": "config/notes.md",
        "a-cyrillic-file-name": "\u0438\u043d\u0441\u0442\u0440.md",
        "a-hebrew-file-name": "\u05d4\u05d5\u05e8\u05d0.md",
        "an-at-file-reference": "@/config/instructions.md",
        "a-stray-quote": "'/srv/notes.md",
        # Each way a path starts, with no extension.
        "root": "/config/instructions",
        "home": "~/config/instructions",
        "another-users-home": "~someone/config/instructions",
        "dot": "./config/instructions",
        "dot-dot": "../config/instructions",
        "drive": "C:\\Users\\me\\instructions",
        "drive-with-forward-slashes": "C:/Users/me/instructions",
        "unc-share": "\\\\server\\share\\instructions",
        "unexpanded-variable": "$HOME/config/instructions",
        "unexpanded-variable-in-braces": "${HOME}/config/instructions",
        "unexpanded-kubernetes-variable": "$(HOME)/config/instructions",
        "unexpanded-windows-variable": "%USERPROFILE%\\config\\instructions",
        # A path start with spaces, kept for its extension, in any case.
        "spaced-markdown": "/Users/me/Library/Application Support/Claude/notes.md",
        "spaced-long-markdown": "/srv/My Docs/notes.markdown",
        "spaced-text": "/srv/My Docs/notes.txt",
        "spaced-upper-case": "/Users/me/My Docs/NOTES.MD",
        # What comes off first.
        "absolute": "{home}/instructions.md",
        "trailing-newline": "{home}/instructions.md\n",
        "double-quoted": '"{home}/instructions.md"',
        "single-quoted": "'{home}/instructions.md'",
        "curly-quoted": "\u201c{home}/instructions.md\u201d",
        "polish-quoted": "\u201e/config/instructions.md\u201d",
        "swedish-quoted": "\u201d/config/instructions.md\u201d",
        "danish-quoted": "\u00bb/config/instructions.md\u00ab",
        "german-single-quoted": "\u201a/config/instructions.md\u2018",
        "padded-inside-quotes": '" {home}/instructions.md "',
        "command-substitution": "$(cat /config/instructions.md)",
        "quoted-command-substitution": '$(cat "/config/instructions.md")',
        "redirect-substitution": "$(< /config/instructions.md)",
        "backquoted-substitution": "`cat /config/instructions.md`",
    }
    _QUOTED_AS = {
        "trailing-newline": "{home}/instructions.md",
        "double-quoted": "{home}/instructions.md",
        "single-quoted": "{home}/instructions.md",
        "curly-quoted": "{home}/instructions.md",
        "polish-quoted": "/config/instructions.md",
        "swedish-quoted": "/config/instructions.md",
        "danish-quoted": "/config/instructions.md",
        "german-single-quoted": "/config/instructions.md",
        "padded-inside-quotes": "{home}/instructions.md",
        "command-substitution": "/config/instructions.md",
        "quoted-command-substitution": "/config/instructions.md",
        "redirect-substitution": "/config/instructions.md",
        "backquoted-substitution": "/config/instructions.md",
    }

    @pytest.mark.parametrize("shape", sorted(_FILE_PATHS))
    def test_inline_text_that_is_a_file_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
    ) -> None:
        """The likeliest mix-up between the two variables: a path set where
        the text belongs is served to every client as the instructions."""
        home = tmp_path / "home"
        (home / "My Notes").mkdir(parents=True)
        _write(home / "instructions.md", b"Notes.\n")
        _write(home / "My Notes" / "instructions", b"Notes.\n")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.chdir(home)
        template = self._FILE_PATHS[shape]
        value = template.replace("{home}", str(home))
        quoted = self._QUOTED_AS.get(shape, template)
        named = quoted.replace("{home}", str(home))
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions=value)
        _report_lines(records)
        (warning,) = _messages(records, logging.WARNING)
        assert warning == (
            f"{INSTRUCTIONS_ENV} looks like a file path ({named!r}); clients "
            "receive it as the instructions text. To load the file, set "
            f"{INSTRUCTIONS_PATH_ENV} instead."
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Medicine.",
            "Prefer MedlinePlus for clinical questions.",
            "/help lists the commands",
            "~no_such_user_479",
            "~no_such_user_479 and friends",
            "x" * 300,
            "archives",
            # Starts like a path and ends in a file name, but is two lines.
            "/srv/zim holds the archives.\nSee notes.md",
            "See docs/notes.md for the rules.",
            "Follow the rules in notes.md",
            "/srv/a\tb",
            "https://example.org/medical",
            "$5/hour",
            "$(echo /config/instructions.md)",
            "~a\x00b",
            # A sentence in a script written without spaces is not one word.
            "回答请使用中文，参见说明.md",
            "詳しくはREADME.md",
            "\u0e14\u0e39\u0e23\u0e32\u0e22README.md",
        ],
        ids=[
            "a-word",
            "a-sentence",
            "a-leading-slash",
            "an-unknown-user",
            "an-unknown-user-with-spaces",
            "too-long-for-a-file-name",
            "a-directory",
            "two-lines",
            "a-path-inside-a-sentence",
            "a-sentence-ending-in-a-file-name",
            "a-tab-between-words",
            "a-url",
            "a-dollar-amount",
            "a-command-that-is-not-cat",
            "a-nul-from-code",
            "a-chinese-sentence",
            "a-japanese-sentence",
            "a-thai-sentence",
        ],
    )
    def test_text_that_only_resembles_a_path_is_fine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
    ) -> None:
        """Including what makes the file check itself raise (an unknown
        ``~user``, a name too long for the file system, a NUL from code): a
        check that only warns must never stop startup."""
        (tmp_path / "archives").mkdir()
        monkeypatch.chdir(tmp_path)
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions=text)
        _report_lines(records)
        assert not _messages(records, logging.WARNING)

    @pytest.mark.parametrize(
        "letter",
        [
            chr(0x0E14),
            chr(0x0EC0),
            chr(0x1000),
            chr(0x1798),
            chr(0x304F),
            chr(0x30AB),
            chr(0x3400),
            chr(0x8A73),
            chr(0xF900),
        ],
        ids=[
            "thai",
            "lao",
            "myanmar",
            "khmer",
            "hiragana",
            "katakana",
            "han-extension-a",
            "han",
            "han-compatibility",
        ],
    )
    def test_one_word_in_a_script_without_spaces_can_be_a_sentence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, letter: str
    ) -> None:
        """One letter from each block of those scripts: a name ending in a
        file name is no path there unless the file exists."""
        monkeypatch.chdir(tmp_path)
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions=f"{letter}README.md")
        _report_lines(records)
        assert not _messages(records, logging.WARNING)

    def test_a_file_holding_a_path_is_not_second_guessed(self, tmp_path: Path) -> None:
        """The check is about the inline variable: an operator who set the
        path variable has already chosen a file."""
        other = _write(tmp_path / "other.md", b"Notes.\n")
        holder = _write(tmp_path / "holder.md", f"{other}\n".encode("utf-8"))
        with _collected(LOGGER) as records:
            _server(tmp_path, instructions_path=holder)
        _report_lines(records)
        assert not _messages(records, logging.WARNING)


# ---------------------------------------------------------------------------
# The entry point: what an operator sees when startup refuses.
# ---------------------------------------------------------------------------


class TestEntryPoint:
    def test_main_prints_a_configuration_error_and_exits_1(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The real server class: patching it out would never run the
        resolver. ``run`` is patched so a regression fails instead of
        serving stdio for ever."""

        def _must_not_run(self: OpenZimMcpServer) -> None:
            raise AssertionError("main() reached run() with a missing file")

        monkeypatch.setattr(OpenZimMcpServer, "run", _must_not_run)
        missing = tmp_path / "missing.md"
        monkeypatch.setenv(INSTRUCTIONS_PATH_ENV, str(missing))
        monkeypatch.setattr(sys, "argv", ["openzim-mcp", str(tmp_path)])
        with pytest.raises(SystemExit) as excinfo:
            main_module.main()
        assert excinfo.value.code == 1
        # Log lines share stderr; the verdict is the last line. The prefix is
        # the point: main() exits 1 from a generic "Server startup error"
        # arm too, which a resolver leaking an OSError would reach.
        last = capsys.readouterr().err.splitlines()[-1]
        assert last.startswith(
            f"Configuration error: {INSTRUCTIONS_PATH_ENV}={str(missing)!r}"
        ), last
        assert last.endswith("does not exist.")

    def test_a_real_process_refuses_to_start(self, tmp_path: Path) -> None:
        """Through the environment, the way an operator sets it; stdout is
        the JSON-RPC channel and must stay empty."""
        env = dict(os.environ)
        env[INSTRUCTIONS_PATH_ENV] = str(tmp_path / "missing.md")
        proc = subprocess.run(
            [sys.executable, "-m", "openzim_mcp", str(tmp_path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=env,
            timeout=120,
        )
        assert proc.returncode == 1, proc.stderr
        assert proc.stdout == b""
        assert b"Configuration error: " + INSTRUCTIONS_PATH_ENV.encode() in proc.stderr

    def test_a_real_process_serves_the_file(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "instructions.md", b"Medical archives.\n\n{{default}}\n"
        )
        env = dict(os.environ)
        env[INSTRUCTIONS_PATH_ENV] = str(path)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "instructions-test", "version": "1"},
            },
        }
        proc = subprocess.run(
            [sys.executable, "-m", "openzim_mcp", str(tmp_path)],
            input=(json.dumps(request) + "\n").encode(),
            capture_output=True,
            env=env,
            timeout=120,
        )
        # A server that never answered would otherwise fail on the index
        # below with nothing of its stderr shown.
        assert proc.returncode == 0 and proc.stdout.strip(), proc.stderr.decode(
            errors="replace"
        )
        answer = json.loads(proc.stdout.splitlines()[0])
        assert answer["result"]["instructions"] == (
            "Medical archives.\n\n" + SIMPLE_INSTRUCTIONS
        )
        assert b"Server instructions: custom, from" in proc.stderr


# ---------------------------------------------------------------------------
# Supporting pieces.
# ---------------------------------------------------------------------------


def test_the_tool_catalogue_is_the_advanced_registry(tmp_path: Path) -> None:
    """The warnings check names against this list; it must not drift."""
    server = _server(tmp_path, "advanced")
    assert list(TOOL_NAMES) == server.mcp.registered_tool_names()
    assert set(TOOL_NAMES) == set(server.mcp._tool_manager._tools)


def test_the_config_hash_tells_the_texts_apart(tmp_path: Path) -> None:
    base = _config(tmp_path).get_config_hash()
    assert _config(tmp_path, instructions="  ").get_config_hash() == base
    one = _config(tmp_path, instructions="One.").get_config_hash()
    two = _config(tmp_path, instructions="Two.").get_config_hash()
    path = _config(tmp_path, instructions_path=tmp_path / "x.md").get_config_hash()
    # Same file name, another directory: a different file.
    elsewhere = _config(
        tmp_path, instructions_path=tmp_path / "other" / "x.md"
    ).get_config_hash()
    assert len({base, one, two, path, elsewhere}) == 5


def _docs_section() -> str:
    page = CONFIG_DOC.read_text(encoding="utf-8")
    return page.split("## Server instructions", 1)[1].split("\n## ", 1)[0]


def _fenced(section: str, language: str) -> str:
    """The body of the section's first ``language`` code fence."""
    found = re.search(rf"^```{language}\n(.*?)^```$", section, re.M | re.S)
    assert found, f"no {language} fence"
    return found.group(1)


def test_the_docs_quote_the_lines_the_code_writes(tmp_path: Path) -> None:
    """The three example startup lines, rendered here from the code: the
    built-in text, the page's own example file at the page's own path, and
    an 80-byte inline text. A reworded built-in text or line format changes
    the byte counts or the words, and the page has to follow."""
    section = _docs_section()
    documented = re.search(r"OPENZIM_MCP_INSTRUCTIONS_PATH=(\S+)", section)
    assert documented
    example = _write(
        tmp_path / "instructions.md", _fenced(section, "markdown").encode("utf-8")
    )
    from_file = dataclasses.replace(
        resolve_instructions("simple", path=example),
        # POSIX on every OS: the page shows a POSIX path.
        path=PurePosixPath(documented.group(1)),
    )
    assert _fenced(section, "text").splitlines() == [
        describe_instructions(resolve_instructions("simple"), "simple"),
        describe_instructions(from_file, "simple"),
        describe_instructions(
            resolve_instructions("simple", inline="x" * 79), "simple"
        ),
    ]


def test_the_docs_describe_what_the_code_does() -> None:
    """The variables, the token and the cap, as the section states them."""
    page = CONFIG_DOC.read_text(encoding="utf-8")
    section = _docs_section()
    for fragment in (
        INSTRUCTIONS_ENV,
        INSTRUCTIONS_PATH_ENV,
        f"`{DEFAULT_TOKEN}`",
        "Server instructions: built-in",
        "Server instructions: custom, from",
        "is included via {{default}}",
        "is not included (no {{default}} token)",
        f"{MAX_INSTRUCTIONS_BYTES} bytes",
    ):
        assert fragment in section, fragment
    assert "16 KiB" in section
    for row in ("| `instructions` |", "| `instructions_path` |"):
        assert row in page, row
