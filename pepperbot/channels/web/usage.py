"""Usage tracking for the web UI channel."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def append_usage(
    log_file: Path,
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    requests: int,
) -> None:
    """Append one usage record to the JSONL log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "requests": requests,
    }
    with log_file.open("a") as f:
        f.write(json.dumps(record) + "\n")


def get_usage_summary(log_file: Path) -> list[dict]:
    """
    Aggregate usage.jsonl by (provider, model) and return a list of dicts.

    Each dict has: provider, model, input_tokens, output_tokens, requests.
    """
    if not log_file.exists():
        return []

    totals: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"input_tokens": 0, "output_tokens": 0, "requests": 0}
    )
    with log_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                key = (r["provider"], r["model"])
                totals[key]["input_tokens"] += r.get("input_tokens", 0)
                totals[key]["output_tokens"] += r.get("output_tokens", 0)
                totals[key]["requests"] += r.get("requests", 0)
            except (json.JSONDecodeError, KeyError):
                continue

    return [
        {"provider": prov, "model": model, **data}
        for (prov, model), data in totals.items()
    ]
