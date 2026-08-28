"""A URL-shaped ``entry_path`` must come back readable, with guidance.

Passing ``https://iep.utm.edu/epistemo/`` as an ``entry_path`` is the most
natural wrong guess a client makes, and the server's own instructions say
entry paths are "archive-relative …, never URLs". The error it produced
said neither:

* the filesystem-path redactor matched the ``//iep.utm.edu/epistemo/`` tail
  of the caller's own URL as a POSIX absolute path and collapsed it, so the
  message read ``Path: https:<path-hidden>`` — the caller could not even
  see which value was rejected, and the redactor's contract of keeping the
  basename visible failed too (a trailing slash leaves an empty basename);
* nothing mentioned that the scheme and host have to go.

Redaction of *real* filesystem paths is unaffected: paths rooted at a
configured directory are collapsed by the literal-prefix pass that runs
first, whatever punctuation precedes them.
"""

from __future__ import annotations

from openzim_mcp.security import redact_paths_in_message


class TestUrlsSurviveRedaction:
    def test_https_url_is_not_treated_as_a_filesystem_path(self):
        out = redact_paths_in_message(
            "Entry not found: 'https://iep.utm.edu/epistemo/'."
        )
        assert "https://iep.utm.edu/epistemo/" in out
        assert "<path-hidden>" not in out

    def test_http_url_survives(self):
        out = redact_paths_in_message("Path: http://example.org/wiki/Aspirin")
        assert "http://example.org/wiki/Aspirin" in out

    def test_absolute_path_after_a_space_is_still_redacted(self):
        out = redact_paths_in_message("Failed to open /home/user/data/wikipedia.zim")
        assert "/home/user/data" not in out
        assert "wikipedia.zim" in out

    def test_labelled_absolute_path_is_still_redacted(self):
        out = redact_paths_in_message("Path: /home/user/secret/wikipedia.zim")
        assert "/home/user/secret" not in out
        assert "wikipedia.zim" in out


class TestMaskCannotBeForged:
    """Caller text must not be able to impersonate the internal mask.

    ``entry_path`` is echoed into the message verbatim, so a caller who
    embeds the mask token can otherwise have it substituted for a URL of
    their choosing — rewriting the error the next reader sees.
    """

    def test_forged_mask_token_is_not_substituted(self):
        out = redact_paths_in_message(
            "Entry not found: 'A/x\x00u0\x00 and https://real.example/b'."
        )
        assert "https://real.example/b" in out
        # The forged token must not have been filled with the stashed URL.
        assert out.count("https://real.example/b") == 1

    def test_forged_token_alone_is_inert(self):
        out = redact_paths_in_message("Entry not found: 'A/x\x00u7\x00'.")
        assert "\x00u7\x00" not in out


class TestSchemePrefixIsNotARedactionBypass:
    """An empty authority means the tail is a path, not a host — redact it.

    ``file:///home/user/secret/wiki.zim`` and any invented ``x:///home/...``
    would otherwise ride the URL exemption and carry an absolute filesystem
    path through unredacted.
    """

    def test_authority_less_scheme_still_redacts(self):
        out = redact_paths_in_message("file:///home/user/secret/wikipedia.zim")
        assert "/home/user/secret" not in out
        assert "wikipedia.zim" in out

    def test_invented_authority_less_scheme_still_redacts(self):
        out = redact_paths_in_message("x:///home/user/secret/wikipedia.zim")
        assert "/home/user/secret" not in out


class TestRedactionStaysLinear:
    """The URL exemption must not reintroduce quadratic work.

    Two separate ways this went quadratic, both reachable from a
    caller-supplied long ``entry_path`` — a shape this module is hardened
    against elsewhere (see ``sanitize_for_log``):

    * an unanchored, unbounded scheme pattern rescans the tail from every
      offset (25s on 200k characters);
    * restoring the stashed URLs with one ``str.replace`` per URL rescans
      the whole message once per URL (~53s on 200KB of small URLs).
    """

    def test_many_urls_restore_promptly(self):
        import time

        message = "Entry not found: " + " ".join(
            f"https://h/{index}" for index in range(20_000)
        )
        started = time.monotonic()
        redact_paths_in_message(message)
        assert time.monotonic() - started < 2.0

    def test_long_token_redacts_promptly(self):
        import time

        message = "Entry not found: " + ("a" * 200_000)
        started = time.monotonic()
        redact_paths_in_message(message)
        assert time.monotonic() - started < 2.0

    def test_long_path_like_token_redacts_promptly(self):
        import time

        message = "Failed to open /home/user/" + ("b" * 200_000) + ".zim"
        started = time.monotonic()
        redact_paths_in_message(message)
        assert time.monotonic() - started < 2.0


class TestNonUrlColonPathsStillCollapse:
    """The exemption keys on ``scheme://``, not on a colon.

    ``archive:/home/user/secret/x.zim`` is a labelled filesystem path, not a
    URL, and must keep redacting — a blanket "ignore anything after a colon"
    rule would have opened a hole here.
    """

    def test_labelled_path_without_a_scheme_is_redacted(self):
        out = redact_paths_in_message("archive:/home/user/secret/wikipedia.zim")
        assert "/home/user/secret" not in out
        assert "wikipedia.zim" in out

    def test_windows_drive_path_is_still_redacted(self):
        out = redact_paths_in_message(r"Failed to open C:\Users\jo\data\wiki.zim")
        assert "Users" not in out
        assert "wiki.zim" in out
