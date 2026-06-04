"""Unit tests for the pure archive-type classifier (v2.5 #17)."""

from openzim_mcp.archive_types import detect_archive_type


class TestScraperSignal:
    def test_sotoki_is_stackexchange_high(self) -> None:
        assert detect_archive_type({"Scraper": "sotoki 2.1.0"}) == (
            "stackexchange",
            "high",
        )

    def test_ted2zim_is_ted_high(self) -> None:
        assert detect_archive_type({"Scraper": "ted2zim 3.0"}) == ("ted", "high")

    def test_mwoffliner_default_is_wikipedia_high(self) -> None:
        assert detect_archive_type({"Scraper": "mwoffliner 1.14.0"}) == (
            "wikipedia",
            "high",
        )

    def test_mwoffliner_with_wiktionary_name_is_wiktionary_high(self) -> None:
        meta = {"Scraper": "mwoffliner 1.14.0", "Name": "wiktionary_en_all"}
        assert detect_archive_type(meta) == ("wiktionary", "high")


class TestNameAndWeakSignals:
    def test_wikipedia_name_without_scraper_is_medium(self) -> None:
        assert detect_archive_type({"Name": "wikipedia_en_all_maxi"}) == (
            "wikipedia",
            "medium",
        )

    def test_superuser_host_is_stackexchange_medium(self) -> None:
        assert detect_archive_type({"Name": "superuser.com_en_all_2026-02"}) == (
            "stackexchange",
            "medium",
        )

    def test_stackexchange_subdomain_is_medium(self) -> None:
        assert detect_archive_type({"Name": "money.stackexchange.com_en_all"}) == (
            "stackexchange",
            "medium",
        )

    def test_tags_corroboration_is_medium(self) -> None:
        assert detect_archive_type({"Tags": "wikipedia;_category:foo"}) == (
            "wikipedia",
            "medium",
        )

    def test_wiktionary_name_without_scraper_is_medium(self) -> None:
        assert detect_archive_type({"Name": "wiktionary_en_all"}) == (
            "wiktionary",
            "medium",
        )

    def test_ted_name_prefix_is_medium(self) -> None:
        assert detect_archive_type({"Name": "ted_en_all"}) == ("ted", "medium")

    def test_creator_stack_exchange_is_medium(self) -> None:
        assert detect_archive_type({"Creator": "Stack Exchange"}) == (
            "stackexchange",
            "medium",
        )

    def test_tags_wiktionary_is_medium(self) -> None:
        assert detect_archive_type({"Tags": "wiktionary;_category:foo"}) == (
            "wiktionary",
            "medium",
        )


class TestGracefulFallback:
    def test_empty_dict_is_generic_none(self) -> None:
        assert detect_archive_type({}) == ("generic", "none")

    def test_unknown_scraper_is_generic_none(self) -> None:
        assert detect_archive_type({"Scraper": "some-random-tool"}) == (
            "generic",
            "none",
        )

    def test_non_string_values_do_not_raise(self) -> None:
        assert detect_archive_type({"Scraper": None, "Name": 123}) == (
            "generic",
            "none",
        )
