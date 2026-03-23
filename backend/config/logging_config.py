"""Structured logging configuration for AgentOS.

Supports two formats:
  - "text": Human-readable for development (default)
  - "json": Machine-parseable for production (set LOG_FORMAT=json)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOG_FORMAT_ENV = os.environ.get("LOG_FORMAT", "text").lower()


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production — compatible with ELK/CloudWatch/Datadog."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the entire application."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)

    if _LOG_FORMAT_ENV == "json":
        handler.setFormatter(JSONFormatter())
    else:
        text_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        handler.setFormatter(logging.Formatter(text_format, datefmt=LOG_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.addHandler(handler)

    # Reduce noise from libraries
    for noisy in ("httpx", "httpcore", "urllib3", "sqlalchemy.engine", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("agentos").setLevel(numeric_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
