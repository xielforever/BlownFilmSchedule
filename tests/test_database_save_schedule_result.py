from types import SimpleNamespace

import pytest

from src.database import DatabaseManager


def test_save_schedule_result_can_skip_schema_ensure_when_caller_already_did_it():
    manager = DatabaseManager()
    called = False

    def fail_if_called():
        nonlocal called
        called = True

    manager.ensure_planning_schema = fail_if_called
    result = SimpleNamespace(validation_errors=["invalid input"], status="INVALID")

    with pytest.raises(ValueError):
        manager.save_schedule_result(result, ensure_schema=False)

    assert called is False
