from __future__ import annotations

import json
from datetime import UTC, datetime

from yebot.runtime.guardrails import AuditEvent
from yebot.runtime.release import (
    AuditLogWriter,
    ConfigBackup,
    MetricsSnapshot,
    RuntimeMetrics,
    redact_mapping,
)


def test_config_backup_round_trip_is_atomic(tmp_path) -> None:
    source = tmp_path / "config.json"
    source.write_text('{"enabled": true}\n', encoding="utf-8")
    backups = ConfigBackup(tmp_path / "backups")

    backup = backups.backup(source)
    source.write_text('{"enabled": false}\n', encoding="utf-8")
    backups.restore(backup, source)

    assert json.loads(source.read_text(encoding="utf-8")) == {"enabled": True}
    assert backups.list_backups() == (backup,)


def test_audit_writer_and_redaction_exclude_secrets(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    writer = AuditLogWriter(path)
    writer.append(
        AuditEvent(
            event_id="event-1",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            actor_id="42",
            group_id="100",
            tool_name="message.send",
            outcome="success",
            details={"api_key": "secret", "message_length": "4"},
        )
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["details"] == {"api_key": "[REDACTED]", "message_length": "4"}
    assert redact_mapping({"authorization": "Bearer secret"})["authorization"] == (
        "[REDACTED]"
    )


def test_runtime_metrics_are_redacted_counters() -> None:
    metrics = RuntimeMetrics()
    metrics.record_tool("message.send", "success")
    metrics.record_tool("group.kick_member", "quota_exceeded")
    metrics.record_job("completed")
    metrics.record_job("failed")

    snapshot = metrics.snapshot()
    assert isinstance(snapshot, MetricsSnapshot)
    assert snapshot.tool_calls == 2
    assert snapshot.tool_failures == 1
    assert snapshot.job_runs == 2
    assert snapshot.job_failures == 1
