"""Configuration management for OpenZIM MCP server."""

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .defaults import CACHE, CONTENT, META, SEARCH, VALID_TOOL_MODES
from .exceptions import OpenZimMcpConfigurationError
from .rate_limiter import RateLimitConfig

__all__ = [
    "CacheConfig",
    "ContentConfig",
    "LoggingConfig",
    "MLConfig",
    "MetaConfig",
    "OpenZimMcpConfig",
    "QueryRewriteConfig",
    "RateLimitConfig",
    "RerankerConfig",
    "SearchConfig",
    "SynthesizeConfig",
]


class CacheConfig(BaseModel):
    """Cache configuration settings."""

    enabled: bool = True
    max_size: int = Field(default=CACHE.MAX_SIZE, ge=1, le=10000)
    # Soft byte cap. The count-based ``max_size`` remains a hard upper
    # bound; ``max_bytes`` adds an approximate-size eviction trigger so
    # a few large bundles can't pin hundreds of MB. Computed via
    # ``len(json.dumps(value))`` — cheap, deterministic, and accurate
    # enough for budgeting. ``0`` disables the byte cap entirely.
    max_bytes: int = Field(default=CACHE.MAX_BYTES, ge=0, le=8 * 1024 * 1024 * 1024)
    ttl_seconds: int = Field(default=CACHE.TTL_SECONDS, ge=60, le=86400)
    persistence_enabled: bool = Field(default=CACHE.PERSISTENCE_ENABLED)
    persistence_path: str = Field(default_factory=lambda: CACHE.PERSISTENCE_PATH)

    # Optional libzim reader cache tuning. These are independent of the
    # MCP-level response cache above; they size libzim's internal read
    # caches. ``None`` (default) leaves libzim's own defaults untouched.
    #
    # The cluster cache is sized in BYTES and is a PROCESS-GLOBAL setting
    # (libzim default 16 MiB). The dirent cache is sized as a COUNT of
    # dirents and is a per-archive property (libzim default 512). The two
    # units differ deliberately — see ``zim.archive.configure_libzim_caches``.
    libzim_cluster_cache_max_size_bytes: Optional[int] = Field(
        default=None,
        ge=0,
        le=4 * 1024 * 1024 * 1024,
        description=(
            "libzim cluster cache max size in bytes (process-global; "
            "None = use libzim default of 16 MiB)"
        ),
    )
    libzim_dirent_cache_max_count: Optional[int] = Field(
        default=None,
        ge=0,
        le=10_000_000,
        description=(
            "libzim dirent cache max size as a count of dirents (per-archive; "
            "None = use libzim default of 512)"
        ),
    )

    @field_validator("persistence_path")
    @classmethod
    def normalize_persistence_path(cls, v: str) -> str:
        """Normalize persistence_path to an absolute, tilde-expanded path.

        Without this, a CWD-relative default (or user-supplied relative
        path) lands in unpredictable locations under containers/systemd
        where the working directory is not the user's home.
        """
        return str(Path(v).expanduser().resolve())


class ContentConfig(BaseModel):
    """Content processing configuration."""

    max_content_length: int = Field(default=CONTENT.MAX_CONTENT_LENGTH, ge=100)
    snippet_length: int = Field(default=CONTENT.SNIPPET_LENGTH, ge=100)
    default_search_limit: int = Field(default=CONTENT.SEARCH_LIMIT, ge=1, le=100)
    table_row_threshold: int = Field(default=CONTENT.TABLE_ROW_THRESHOLD, ge=1)
    table_char_threshold: int = Field(default=CONTENT.TABLE_CHAR_THRESHOLD, ge=50)
    infobox_kv_limit: int = Field(default=CONTENT.INFOBOX_KV_LIMIT, ge=1, le=200)


class MetaConfig(BaseModel):
    """Configuration for the response `_meta` envelope (Phase A item #5)."""

    footer_enabled: bool = Field(default=META.FOOTER_ENABLED)
    tokenizer_encoding: str = Field(default=META.TOKENIZER_ENCODING)


class SearchConfig(BaseModel):
    """Configuration for search-side knobs (Phase A items #4, #14)."""

    structured_suggestions_limit: int = Field(
        default=SEARCH.STRUCTURED_SUGGESTIONS_LIMIT, ge=1, le=20
    )
    fuzzy_title_min_query_len: int = Field(
        default=SEARCH.FUZZY_TITLE_MIN_QUERY_LEN, ge=2, le=20
    )
    fuzzy_title_score_penalty: float = Field(
        default=SEARCH.FUZZY_TITLE_SCORE_PENALTY, ge=0.0, le=1.0
    )
    # H22: wall-clock budget for ``search_all`` fan-out. The serial
    # per-archive search adds up — 10 ZIM files × 3 s ≈ 30 s in one
    # threadpool slot. When this budget elapses, the fan-out stops
    # iterating and the caller gets the partial result so the threadpool
    # slot frees up. ``0`` disables the timeout (legacy behavior).
    search_all_total_timeout_seconds: float = Field(
        default=20.0,
        ge=0.0,
        le=300.0,
        description="Aggregate timeout for search_all fan-out (seconds). 0 disables.",
    )


class SynthesizeConfig(BaseModel):
    """Phase C: tunables for `zim_query(synthesize=True)`.

    All knobs are advisory — the synthesize pipeline obeys these as
    soft budgets (e.g., output_char_budget truncates the *last* passage
    rather than refusing to include it).
    """

    top_n: int = Field(default=5, ge=1, le=50, description="Final passages returned.")
    per_archive_k: int = Field(
        default=10, ge=1, le=100, description="Top-K from each archive before fusion."
    )
    output_char_budget: int = Field(
        default=4800,
        ge=500,
        le=20000,
        description="Soft cap on answer_markdown chars (~1200 tokens).",
    )
    section_affinity_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum |query ∩ heading| / |heading| ratio before a "
            "section-attributed passage gets the affinity boost."
        ),
    )
    section_affinity_boost: float = Field(
        default=1.5,
        ge=1.0,
        le=10.0,
        description=(
            "Multiplier applied to a passage's score when its section "
            "heading affinity-matches the query. Conservative: won't "
            "dominate strong BM25 hits."
        ),
    )
    max_secondary_archive_hits: int = Field(
        default=2,
        ge=0,
        le=50,
        description=(
            "Cap on hits each NON-primary archive may contribute to the "
            "RRF-fused multi-archive result, bounding cross-archive flooding. "
            "0 = primary archive only."
        ),
    )
    cross_archive_min_overlap: int = Field(
        default=1,
        ge=1,
        le=10,
        description=(
            "Minimum query-token overlap a secondary-archive hit's entry path "
            "must have to survive the cross-archive relevance floor. RRF fuses "
            "by rank only (no BM25), so this lexical floor is the relevance bar "
            "on a default install. Primary-archive hits are exempt."
        ),
    )


class RerankerConfig(BaseModel):
    """Phase D sub-D-1: cross-encoder reranker config.

    Only applies when the `[reranker]` optional extra is installed.
    All knobs respect the kill switch in `ml_fallback` — if the model
    fails to load once, every subsequent search bypasses rerank for
    the rest of the process."""

    enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch. Set False (or env OPENZIM_RERANKER_DISABLE=1) "
            "to skip rerank even when the [reranker] extra is importable."
        ),
    )
    model_id: str = Field(
        default="BAAI/bge-reranker-base",
        description=(
            "FastEmbed model identifier. Default targets English-first "
            "archives. Multilingual archives can override via "
            "OPENZIM_RERANKER_MODEL env var (e.g., jina-reranker-v3)."
        ),
    )
    candidate_pool_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description=(
            "Xapian top-N to rerank. Larger pool = more recall, more "
            "rerank cost. 50 is the sweet spot per FastEmbed benchmarks."
        ),
    )
    final_top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Default response cap after rerank. Caller-supplied `limit` "
            "overrides this when smaller."
        ),
    )
    max_query_length: int = Field(default=256, ge=1, le=4096)
    max_passage_length: int = Field(default=512, ge=1, le=8192)
    min_query_tokens: int = Field(
        default=4,
        ge=0,
        le=64,
        description=(
            "Skip-on-short-query gate: queries with fewer than this many "
            "word tokens bypass rerank. Single-word entity queries (e.g., "
            "`Berlin`) already get a Xapian-score-1.0 canonical-title hit; "
            "the cross-encoder adds cost without value there. Set 0 to "
            "disable the gate."
        ),
    )
    first_call_timeout_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=120.0,
        description=(
            "Timeout for the first model load (covers HuggingFace download). "
            "When exceeded, the kill switch fires and search falls back to "
            "Xapian-only. Pre-stage with `openzim-mcp download-models` to "
            "avoid this path. Default sized for ONNX session creation on a "
            "warm cache (~7–10 s on modest hardware); raise for cold-cache "
            "downloads."
        ),
    )
    cache_dir: Path | None = Field(
        default=None,
        description=(
            "Override the FastEmbed model cache directory. None → "
            "$OPENZIM_MODEL_CACHE_DIR/fastembed, fallback "
            "~/.cache/openzim-mcp/models/fastembed."
        ),
    )


class MLConfig(BaseModel):
    """Phase D umbrella config. Sized to today's scope (sub-D-1 only);
    deferred sub-Ds add their sub-configs when they ship."""

    reranker: RerankerConfig = Field(default_factory=RerankerConfig)


class QueryRewriteConfig(BaseModel):
    """Phase D sub-D-2: Tier 1 rule-based query rewriting config.

    Always in the base install — no opt-in extras required. Four
    idempotent rules run before the intent regex chain. See the
    sub-D-2 design spec for per-rule behavior."""

    enabled: bool = Field(
        default=True,
        description=(
            "Master switch. False short-circuits all four rules; "
            "queries pass through to the regex chain unchanged."
        ),
    )
    misspelling_map_path: Path | None = Field(
        default=None,
        description=(
            "Override the bundled misspellings.txt path. None = use "
            "the package-bundled default."
        ),
    )
    misspelling_exclusion_path: Path | None = Field(
        default=None,
        description=(
            "Override the bundled exclusions list. None = use the "
            "package-bundled default."
        ),
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(default="INFO")
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()


class OpenZimMcpConfig(BaseSettings):
    """Main configuration for OpenZIM MCP server."""

    # Directory settings
    allowed_directories: List[str] = Field(default_factory=list)

    # Component configurations
    cache: CacheConfig = Field(default_factory=CacheConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    query_rewrite: QueryRewriteConfig = Field(default_factory=QueryRewriteConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    meta: MetaConfig = Field(default_factory=MetaConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    synthesize: SynthesizeConfig = Field(default_factory=SynthesizeConfig)

    # Server settings
    server_name: str = "openzim-mcp"
    tool_mode: Literal["advanced", "simple"] = Field(
        default="simple",
        description=(
            "Tool registration mode. "
            "'simple' (default) registers only zim_query — the NL entry point. "
            "'advanced' registers the full 8-tool Phase F surface: zim_query, "
            "zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, "
            "zim_links, zim_health."
        ),
    )
    transport: Literal["stdio", "http", "sse"] = Field(
        default="stdio",
        description=(
            "Transport protocol: 'stdio' (default), 'http' (streamable HTTP), "
            "or 'sse' (legacy SSE — no auth middleware, intended for local use)"
        ),
    )
    host: str = Field(
        default="127.0.0.1",
        description="HTTP bind host (only used when transport='http' or 'sse')",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="HTTP bind port (only used when transport='http' or 'sse')",
    )
    auth_token: Optional[SecretStr] = Field(
        default=None,
        description=(
            "Bearer token for HTTP transport. Loaded from env var "
            "OPENZIM_MCP_AUTH_TOKEN. Never set this in a config file."
        ),
    )
    insecure_disable_auth: bool = Field(
        default=False,
        description=(
            "Operator-acknowledged escape hatch: allow --transport http to "
            "bind a non-loopback host without OPENZIM_MCP_AUTH_TOKEN. "
            "Intended for closed networks (Docker bridge, Tailscale-only, "
            "isolated LAN) where the network itself is the trust boundary. "
            "Logs a WARNING naming the bound host on every startup. "
            "Does not apply to --transport sse — SSE has no auth middleware "
            "to reason about and remains localhost-only."
        ),
    )
    cors_origins: List[str] = Field(
        default_factory=list,
        description=(
            "CORS allow-list. Wildcard '*' is rejected. Default is empty "
            "(no CORS headers emitted)."
        ),
    )
    allowed_hosts: List[str] = Field(
        default_factory=list,
        description=(
            "Public-facing hostnames the HTTP transport accepts in the "
            "Host header (e.g. ['mcp.example.com']). Loopback values "
            "('127.0.0.1', 'localhost', '[::1]') are always allowed; this "
            "setting extends them when openzim-mcp sits behind a reverse "
            "proxy or Tailscale serve, which preserve the original Host. "
            "Entries may be exact ('mcp.example.com') or include the "
            "':*' wildcard-port suffix ('mcp.example.com:*'). Wildcard "
            "'*' alone is rejected. Honored only when transport='http'."
        ),
    )
    watch_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Polling interval for resource subscriptions (seconds).",
    )
    subscriptions_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for resource subscriptions. When False, the "
            "polling task is not started and subscribe calls succeed but "
            "never fire updates."
        ),
    )
    presets_override_path: Optional[Path] = Field(
        default=None,
        description=(
            "Path to an operator TOML that overrides archive-type presets "
            "(deep-merged per type) and defines per-archive pins. Loaded from "
            "OPENZIM_MCP_PRESETS_OVERRIDE_PATH. Absent => bundled defaults only."
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="OPENZIM_MCP_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @field_validator("allowed_directories")
    @classmethod
    def validate_directories(cls, v: List[str]) -> List[str]:
        """Validate that all directories exist and are accessible."""
        if not v:
            raise OpenZimMcpConfigurationError(
                "At least one allowed directory must be specified"
            )

        validated_dirs = []
        for dir_path in v:
            path = Path(dir_path).expanduser().resolve()
            if not path.exists():
                raise OpenZimMcpConfigurationError(f"Directory does not exist: {path}")
            if not path.is_dir():
                raise OpenZimMcpConfigurationError(f"Path is not a directory: {path}")
            validated_dirs.append(str(path))

        return validated_dirs

    @field_validator("tool_mode")
    @classmethod
    def validate_tool_mode(cls, v: str) -> str:
        """Validate tool mode."""
        if v not in VALID_TOOL_MODES:
            raise OpenZimMcpConfigurationError(
                f"Invalid tool mode: {v}. Must be one of {VALID_TOOL_MODES}"
            )
        return v

    @field_validator("cors_origins")
    @classmethod
    def reject_cors_wildcard(cls, v: List[str]) -> List[str]:
        """Reject wildcard '*' in CORS origins (footgun prevention).

        Strips each origin before comparing so whitespace-padded variants
        like ``" * "`` cannot bypass the check.
        """
        if any(origin.strip() == "*" for origin in v):
            raise OpenZimMcpConfigurationError(
                "CORS wildcard '*' is not allowed. List origins explicitly "
                "(e.g. ['http://localhost:5173'])."
            )
        return v

    @field_validator("allowed_hosts")
    @classmethod
    def reject_allowed_hosts_wildcard(cls, v: List[str]) -> List[str]:
        """Reject wildcard '*' in allowed_hosts (footgun prevention).

        DNS rebinding protection is the whole point of the allow-list;
        accepting '*' would defeat it. Whitespace-padded variants are
        normalized before comparison.
        """
        if any(host.strip() == "*" for host in v):
            raise OpenZimMcpConfigurationError(
                "allowed_hosts wildcard '*' is not allowed. List hostnames "
                "explicitly (e.g. ['mcp.example.com'])."
            )
        return v

    def setup_logging(self) -> None:
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.logging.level),
            format=self.logging.format,
            force=True,
        )

    def get_config_hash(self) -> str:
        """
        Generate a hash fingerprint of the current configuration.

        This hash is used to detect configuration conflicts between
        multiple server instances. Only configuration elements that
        affect server behavior are included in the hash.

        Returns:
            SHA-256 hash of the configuration as a hex string
        """
        # Create a normalized configuration dict for hashing
        config_for_hash = {
            "allowed_directories": sorted(
                self.allowed_directories
            ),  # Sort for consistency
            "cache_enabled": self.cache.enabled,
            "cache_max_size": self.cache.max_size,
            "cache_ttl_seconds": self.cache.ttl_seconds,
            "libzim_cluster_cache_bytes": (
                self.cache.libzim_cluster_cache_max_size_bytes
            ),
            "libzim_dirent_cache_count": self.cache.libzim_dirent_cache_max_count,
            "content_max_length": self.content.max_content_length,
            "content_snippet_length": self.content.snippet_length,
            "search_default_limit": self.content.default_search_limit,
            "server_name": self.server_name,
            "tool_mode": self.tool_mode,
            "transport": self.transport,
            "host": self.host,
            "port": self.port,
            "cors_origins": sorted(self.cors_origins),
            "allowed_hosts": sorted(self.allowed_hosts),
            "watch_interval_seconds": self.watch_interval_seconds,
            "subscriptions_enabled": self.subscriptions_enabled,
            "rate_limit_enabled": self.rate_limit.enabled,
            "rate_limit_rps": self.rate_limit.requests_per_second,
            "rate_limit_burst": self.rate_limit.burst_size,
        }

        # Convert to JSON string with sorted keys for consistent hashing
        config_json = json.dumps(config_for_hash, sort_keys=True, separators=(",", ":"))

        # Generate SHA-256 hash
        return hashlib.sha256(config_json.encode("utf-8")).hexdigest()
