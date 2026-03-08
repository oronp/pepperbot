"""Tests for web UI usage tracking module."""
from pepperbot.channels.web.usage import append_usage, get_usage_summary


def test_append_and_read_single_entry(tmp_path):
    log = tmp_path / "usage.jsonl"
    append_usage(
        log_file=log,
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        requests=1,
    )
    summary = get_usage_summary(log)
    assert len(summary) == 1
    entry = summary[0]
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-4o"
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 50
    assert entry["requests"] == 1


def test_append_multiple_entries_same_provider(tmp_path):
    log = tmp_path / "usage.jsonl"
    append_usage(log, provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50, requests=1)
    append_usage(log, provider="openai", model="gpt-4o", input_tokens=200, output_tokens=80, requests=1)
    summary = get_usage_summary(log)
    assert len(summary) == 1
    assert summary[0]["input_tokens"] == 300
    assert summary[0]["output_tokens"] == 130
    assert summary[0]["requests"] == 2


def test_append_multiple_providers(tmp_path):
    log = tmp_path / "usage.jsonl"
    append_usage(log, provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50, requests=1)
    append_usage(log, provider="anthropic", model="claude-3", input_tokens=200, output_tokens=80, requests=1)
    summary = get_usage_summary(log)
    providers = {e["provider"] for e in summary}
    assert providers == {"openai", "anthropic"}


def test_empty_log_returns_empty_summary(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert get_usage_summary(log) == []


def test_missing_log_returns_empty_summary(tmp_path):
    log = tmp_path / "nonexistent.jsonl"
    assert get_usage_summary(log) == []
