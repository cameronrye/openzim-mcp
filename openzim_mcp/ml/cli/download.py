"""`openzim-mcp download-models` — pre-stage ML model files.

Run once after `pip install openzim-mcp[reranker]` (or any other ML
extra) so the first MCP query doesn't hit a network call. Idempotent —
re-running checks the cache and only fetches missing files."""

from __future__ import annotations

import argparse
import logging
from typing import List, Optional

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect

logger = logging.getLogger(__name__)


def _stage_reranker(cfg: RerankerConfig) -> None:
    """Force-load the reranker model so FastEmbed's HuggingFace cache
    is populated. Raises on failure."""
    from openzim_mcp.ml.reranker import _load_model

    _load_model(cfg.model_id, cfg.cache_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openzim-mcp download-models",
        description=(
            "Pre-stage ML model files for installed extras. Run this once "
            "after installing an extra (e.g., `pip install "
            "openzim-mcp[reranker]`) on a machine with network access; "
            "the MCP server can then run offline without first-call "
            "download delays."
        ),
    )
    parser.add_argument(
        "--reranker-model-id",
        default=None,
        help=(
            f"Override the reranker model id "
            f"(default: {RerankerConfig().model_id})."
        ),
    )
    return parser


def download_models_main(argv: Optional[List[str]] = None) -> int:
    """Entry point. Returns process exit code (0 success, 1 failure)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    features = detect()
    if not features.reranker:
        print(
            "No ml extras installed. Re-run after `pip install "
            "openzim-mcp[reranker]` to pre-stage the reranker model.",
        )
        return 0

    print("Staging reranker model... ", end="", flush=True)
    cfg = RerankerConfig()
    if args.reranker_model_id:
        cfg = cfg.model_copy(update={"model_id": args.reranker_model_id})
    try:
        _stage_reranker(cfg)
        print("done.")
        return 0
    except Exception as exc:  # noqa: BLE001 — surface any underlying error
        print(f"failed: {exc}")
        return 1
