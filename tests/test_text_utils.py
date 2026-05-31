"""Tests for openzim_mcp.text_utils.tokenize_for_relevance."""

import pytest

from openzim_mcp.text_utils import RELEVANCE_TOKEN_MIN_LEN, tokenize_for_relevance


def test_basic_tokenization():
    result = tokenize_for_relevance("Berlin Culture 2024")
    assert result == {"berlin", "culture", "2024"}


def test_short_tokens_dropped():
    result = tokenize_for_relevance("a of to xyz")
    assert result == {"xyz"}


def test_casing_lowered():
    result = tokenize_for_relevance("Python JAVA Rust")
    assert result == {"python", "java", "rust"}


def test_punctuation_splits():
    result = tokenize_for_relevance("hello, world! foo-bar")
    assert result == {"hello", "world", "foo", "bar"}


def test_unicode_non_alnum_splits():
    # Non-ASCII characters are not [a-z0-9], so they act as separators.
    result = tokenize_for_relevance("café résumé")
    # "caf" and "r" and "sum" and "e" - let's verify: "café" → "caf" + "e"
    # "résumé" → "r" (dropped <3) + "sum" + "e" (dropped <3)
    assert result == {"caf", "sum"}


def test_empty_string():
    assert tokenize_for_relevance("") == set()


def test_returns_set():
    result = tokenize_for_relevance("the quick brown fox")
    assert isinstance(result, set)


def test_duplicates_deduplicated():
    result = tokenize_for_relevance("fox fox fox")
    assert result == {"fox"}


def test_digits_included():
    result = tokenize_for_relevance("v1 abc123 99")
    # "v1" len=2 → dropped, "abc123" len=6 → kept, "99" len=2 → dropped
    assert result == {"abc123"}


def test_default_min_len_constant():
    assert RELEVANCE_TOKEN_MIN_LEN == 3


def test_custom_min_len():
    result = tokenize_for_relevance("a to the fox", min_len=2)
    assert result == {"to", "the", "fox"}


def test_only_short_tokens():
    assert tokenize_for_relevance("a b c") == set()
