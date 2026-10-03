"""Logging setup.

Two sinks:
  * stdlib logging -> rich console (human-readable)
  * structlog -> JSONL file (machine-readable audit trail)

The JSONL file is the source of truth for "why did the agent do X
at time T". Never delete it; rotate by date in production.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog
from rich.logging import RichHandler


def setup_logging(level: str = "INFO", jsonl_path: str = "./data/logs/decisions.jsonl") -> None:
    Path(jsonl_path).parent.mkdir(parents=True, exist_ok=True)

    # stdlib console -> rich
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )

    # structlog -> JSONL file (separate file handler)
    file_handler = logging.FileHandler(jsonl_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_logger = logging.getLogger("polyagent.audit")
    file_logger.handlers.clear()
    file_logger.addHandler(file_handler)
    file_logger.setLevel(level)
    file_logger.propagate = False

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "polyagent"):
    return structlog.get_logger(name)


def get_audit_logger():
    """Logger that writes ONLY to the JSONL audit file."""
    return structlog.get_logger("polyagent.audit")


# Make sure stderr gets a default handler if setup_logging hasn't run yet,
# so import-time errors aren't swallowed.
logging.basicConfig(level="WARNING", stream=sys.stderr)
