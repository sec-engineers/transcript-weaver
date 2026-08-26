import json
from datetime import datetime, timedelta, timezone

from transcript_weaver.artifacts import (
    disable_permission,
    enable_permission,
    permission_path,
    read_permission,
)


def test_permission_is_user_only_expires_and_can_be_disabled(tmp_path) -> None:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    permission = enable_permission(tmp_path, clock=now)
    path = permission_path(tmp_path)

    assert permission.expires_at == now + timedelta(hours=1)
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_permission(tmp_path, clock=now + timedelta(minutes=59)) == permission
    assert read_permission(tmp_path, clock=now + timedelta(hours=1)) is None
    assert disable_permission(tmp_path)
    assert not disable_permission(tmp_path)


def test_permission_record_remains_user_editable(tmp_path) -> None:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    enable_permission(tmp_path, clock=now)
    path = permission_path(tmp_path)
    value = json.loads(path.read_text())
    value["expires_at"] = "2099-01-01T00:00:00Z"
    path.write_text(json.dumps(value))

    assert read_permission(tmp_path, clock=now).expires_at.year == 2099
