"""test_sqlite_repository.py — SQLite-only tests.

The shared interface tests in test_data_manager.py also run against SQLite
once "sqlite" is added to BACKENDS there.
"""

from __future__ import annotations

import sqlite3

import pytest

from data_manager import DataManager
from models import StudyPlan, Task
from repository import StorageError
from sqlite_repository import SqlitePlanRepository
from test_data_manager import sample_plan, sample_task


@pytest.fixture
def repo(tmp_path) -> SqlitePlanRepository:
    return SqlitePlanRepository(str(tmp_path / "plans.db"))


def count_rows(repo: SqlitePlanRepository, table: str) -> int:
    connection = sqlite3.connect(repo.location)
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


def test_tables_are_created(repo) -> None:
    assert count_rows(repo, "plans") == 0
    assert count_rows(repo, "tasks") == 0


def test_tasks_are_stored_as_rows(repo) -> None:
    repo.add(sample_plan("p1", tasks=[sample_task("A"), sample_task("B")]))
    assert count_rows(repo, "plans") == 1
    assert count_rows(repo, "tasks") == 2


def test_deleting_a_plan_removes_its_tasks(repo) -> None:
    repo.add(sample_plan("p1", tasks=[sample_task("A"), sample_task("B")]))
    repo.add(sample_plan("p2", tasks=[sample_task("C")]))
    assert repo.delete("p1") is True
    assert count_rows(repo, "tasks") == 1
    assert [plan["plan_id"] for plan in repo.list_all()] == ["p2"]


def test_update_does_not_leave_old_task_rows(repo) -> None:
    repo.add(sample_plan("p1", tasks=[sample_task("A"), sample_task("B")]))
    repo.update(sample_plan("p1", tasks=[sample_task("C")]))
    assert count_rows(repo, "tasks") == 1


def test_duplicate_plan_id_raises_storage_error(repo) -> None:
    repo.add(sample_plan("p1"))
    with pytest.raises(StorageError):
        repo.add(sample_plan("p1"))
    assert count_rows(repo, "plans") == 1


def test_plan_without_id_is_rejected(repo) -> None:
    with pytest.raises(StorageError):
        repo.add({"tasks": []})


def test_nested_plan_data_round_trips(repo) -> None:
    plan = sample_plan("p1")
    plan["weekly_plan"] = [{"week_index": 1, "allocations": [{"task_id": "T1", "minutes": 120}]}]
    plan["decisions"] = [{"task_id": "T1", "decision": "ACCEPT", "rule_id": "R7", "reason": "ok"}]
    plan["custom"] = {"owner": "team"}
    repo.add(plan)
    assert repo.get("p1") == plan


def test_sql_injection_text_is_stored_as_plain_data(repo) -> None:
    nasty = "x'); DROP TABLE tasks; --"
    repo.add(sample_plan("p1", tasks=[sample_task("A", title=nasty)]))
    assert repo.get("p1")["tasks"][0]["title"] == nasty
    assert repo.find_tasks(difficulty=nasty) == []
    assert count_rows(repo, "tasks") == 1


def test_bad_database_path_raises_storage_error(tmp_path) -> None:
    with pytest.raises(StorageError):
        SqlitePlanRepository(str(tmp_path))       # a directory, not a file


def test_file_that_is_not_a_database_raises_storage_error(tmp_path) -> None:
    path = tmp_path / "plans.db"
    path.write_text("this is not a database, it is plain text " * 20, encoding="utf-8")
    with pytest.raises(StorageError):
        SqlitePlanRepository(str(path)).list_all()


def test_data_manager_works_on_sqlite(repo) -> None:
    data = DataManager(repo)
    data.save_plan(StudyPlan(plan_id="p1", tasks=[Task("A", "Revise", difficulty="hard")]))
    assert data.get_plan("p1").tasks[0].difficulty == "hard"
    assert [task.task_id for _plan_id, task in data.find_tasks(difficulty="hard")] == ["A"]
