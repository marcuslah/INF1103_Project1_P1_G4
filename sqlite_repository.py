"""sqlite_repository.py — Stores study plans in a SQLite database (advanced feature)."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from typing import Any

from repository import PlanRepository, StorageError


class SqlitePlanRepository(PlanRepository):
    """Database storage with full create, read, update and delete.

    Two tables are used: ``plans`` (one row per plan) and ``tasks`` (one row per
    task, linked to its plan). Every database error is raised as StorageError.
    """

    DEFAULT_PATH: str = "data/study_plans.db"

    _TASK_COLUMNS: tuple[str, ...] = (
        "task_id", "title", "description", "category", "deadline", "estimated_minutes",
        "difficulty", "priority", "source_document", "source_type", "confidence",
    )
    _PLAN_JSON_COLUMNS: tuple[str, ...] = ("documents", "weekly_plan", "metrics", "decisions", "notes")
    _PLAN_JSON_DEFAULTS: dict[str, Any] = {
        "documents": [], "weekly_plan": [], "metrics": {}, "decisions": [], "notes": [],
    }

    def __init__(self, db_path: str = DEFAULT_PATH) -> None:
        self._db_path = db_path or self.DEFAULT_PATH
        self._create_tables()

    # ----------------------------- connection -----------------------------

    @property
    def location(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        try:
            parent = os.path.dirname(os.path.abspath(self._db_path))
            os.makedirs(parent, exist_ok=True)
            connection = sqlite3.connect(self._db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")     # needed for cascade delete
            return connection
        except (sqlite3.Error, OSError) as exc:
            raise StorageError(f"cannot open database {self._db_path}: {exc}") from exc

    def _create_tables(self) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS plans (
                        position    INTEGER PRIMARY KEY AUTOINCREMENT,
                        plan_id     TEXT NOT NULL UNIQUE,
                        created_at  TEXT,
                        semester    TEXT,
                        documents   TEXT,
                        weekly_plan TEXT,
                        metrics     TEXT,
                        decisions   TEXT,
                        notes       TEXT,
                        extra       TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        position          INTEGER PRIMARY KEY AUTOINCREMENT,
                        plan_id           TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                        task_id           TEXT NOT NULL,
                        title             TEXT,
                        description       TEXT,
                        category          TEXT,
                        deadline          TEXT,
                        estimated_minutes INTEGER,
                        difficulty        TEXT,
                        priority          TEXT,
                        source_document   TEXT,
                        source_type       TEXT,
                        confidence        REAL,
                        dependencies      TEXT,
                        extra             TEXT
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise StorageError(f"cannot prepare database {self._db_path}: {exc}") from exc

    # ----------------------------- row conversion -----------------------------

    def _plan_values(self, plan: dict[str, Any]) -> tuple:
        known = ("plan_id", "created_at", "semester", "tasks") + self._PLAN_JSON_COLUMNS
        extra = {key: value for key, value in plan.items() if key not in known}
        return (
            str(plan.get("plan_id", "")),
            plan.get("created_at", ""),
            plan.get("semester", "unspecified"),
            *(json.dumps(plan.get(column, self._PLAN_JSON_DEFAULTS[column])) for column in self._PLAN_JSON_COLUMNS),
            json.dumps(extra),
        )

    def _task_values(self, plan_id: str, task: dict[str, Any]) -> tuple:
        known = self._TASK_COLUMNS + ("dependencies",)
        extra = {key: value for key, value in task.items() if key not in known}
        return (
            plan_id,
            *(task.get(column) for column in self._TASK_COLUMNS),
            json.dumps(task.get("dependencies", [])),
            json.dumps(extra),
        )

    def _insert_tasks(self, connection: sqlite3.Connection, plan: dict[str, Any]) -> None:
        columns = ("plan_id",) + self._TASK_COLUMNS + ("dependencies", "extra")
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})"
        plan_id = str(plan.get("plan_id", ""))
        for task in plan.get("tasks", []) or []:
            connection.execute(sql, self._task_values(plan_id, task))

    def _row_to_task(self, row: sqlite3.Row) -> dict[str, Any]:
        task: dict[str, Any] = json.loads(row["extra"] or "{}")
        for column in self._TASK_COLUMNS:
            task[column] = row[column]
        task["dependencies"] = json.loads(row["dependencies"] or "[]")
        return task

    def _row_to_plan(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        plan: dict[str, Any] = json.loads(row["extra"] or "{}")
        plan["plan_id"] = row["plan_id"]
        plan["created_at"] = row["created_at"]
        plan["semester"] = row["semester"]
        for column in self._PLAN_JSON_COLUMNS:
            plan[column] = json.loads(row[column]) if row[column] else self._PLAN_JSON_DEFAULTS[column]
        task_rows = connection.execute(
            "SELECT * FROM tasks WHERE plan_id = ? ORDER BY position", (row["plan_id"],)
        ).fetchall()
        plan["tasks"] = [self._row_to_task(task_row) for task_row in task_rows]
        return plan

    # ----------------------------- interface -----------------------------

    def add(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict) or not str(plan.get("plan_id", "")).strip():
            raise StorageError("plan must be an object with a plan_id")
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO plans (plan_id, created_at, semester, documents, weekly_plan, "
                    "metrics, decisions, notes, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._plan_values(plan),
                )
                self._insert_tasks(connection, plan)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageError(f"could not save plan: {exc}") from exc

    def get(self, plan_id: str) -> dict[str, Any] | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM plans WHERE plan_id = ?", (str(plan_id),)
                ).fetchone()
                return self._row_to_plan(connection, row) if row is not None else None
        except (sqlite3.Error, ValueError) as exc:
            raise StorageError(f"could not read plan: {exc}") from exc

    def list_all(self) -> list[dict[str, Any]]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT * FROM plans ORDER BY position").fetchall()
                return [self._row_to_plan(connection, row) for row in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise StorageError(f"could not read plans: {exc}") from exc

    def update(self, plan: dict[str, Any]) -> bool:
        if not isinstance(plan, dict):
            return False
        plan_id = str(plan.get("plan_id", ""))
        try:
            with closing(self._connect()) as connection, connection:
                values = self._plan_values(plan)
                cursor = connection.execute(
                    "UPDATE plans SET created_at = ?, semester = ?, documents = ?, weekly_plan = ?, "
                    "metrics = ?, decisions = ?, notes = ?, extra = ? WHERE plan_id = ?",
                    values[1:] + (plan_id,),
                )
                if cursor.rowcount == 0:
                    return False
                connection.execute("DELETE FROM tasks WHERE plan_id = ?", (plan_id,))
                self._insert_tasks(connection, plan)
                return True
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise StorageError(f"could not update plan: {exc}") from exc

    def delete(self, plan_id: str) -> bool:
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute("DELETE FROM plans WHERE plan_id = ?", (str(plan_id),))
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise StorageError(f"could not delete plan: {exc}") from exc

    def find_tasks(
        self,
        difficulty: str | None = None,
        category: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        sql = "SELECT * FROM tasks"
        conditions: list[str] = []
        parameters: list[str] = []
        if difficulty:
            conditions.append("LOWER(difficulty) = ?")
            parameters.append(str(difficulty).strip().lower())
        if category:
            conditions.append("LOWER(category) = ?")
            parameters.append(str(category).strip().lower())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY position"
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(sql, parameters).fetchall()
                return [(row["plan_id"], self._row_to_task(row)) for row in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise StorageError(f"could not search tasks: {exc}") from exc
