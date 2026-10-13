"""data_manager.py — Flat-file JSON persistence with corruption resilience.

Owner: Member 6 (Data & DevOps Lead).
Style: 100% procedural -- no ``class`` keyword anywhere.
Boundary: no console output or keyboard input belongs here (see io_manager.py).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

DEFAULT_PLAN_PATH: str = os.getenv("PLAN_PATH", "data/study_plans.json")
SCHEMA_VERSION: str = "2.0"

REQUIRED_TASK_FIELDS: tuple[str, ...] = (
    "task_id",
    "title",
    "category",
    "deadline",
    "estimated_minutes",
    "difficulty",
    "priority",
    "source_document",
)

VALID_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
VALID_DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
VALID_CATEGORIES: tuple[str, ...] = (
    "assignment",
    "exam",
    "tutorial",
    "lab",
    "project",
    "reading",
    "revision",
    "other",
)
LEGACY_TASK_KEYS: tuple[str, ...] = (
    "course_code",
    "due_date",
    "estimated_hours",
    "weight_percent",
    "task_type",
    "source",
    "ai_confidence",
)


def now_iso() -> str:
    """Return the current UTC time as a compact ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_plan() -> dict[str, Any]:
    """Return a valid, empty plan container."""
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "plans": [],
    }


def ensure_parent_dir(path: str) -> bool:
    """Create the parent directory for *path* if needed. True on success."""
    parent = os.path.dirname(os.path.abspath(path))
    if not parent:
        return True
    try:
        os.makedirs(parent, exist_ok=True)
        return True
    except OSError:
        return False


def read_raw_file(path: str) -> tuple[str | None, str | None]:
    """Read a UTF-8 text file. Returns ``(text, error)``."""
    if not path:
        return None, "no path provided"
    if not os.path.exists(path):
        return None, f"file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(), None
    except OSError as exc:
        return None, f"could not read {path}: {exc}"


def parse_json_safe(raw: str | None) -> tuple[dict | None, str | None]:
    """Parse JSON text without ever raising. Returns ``(data, error)``."""
    if raw is None or not raw.strip():
        return None, "empty content"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "JSON root is not an object"
    return data, None


def backup_corrupt(path: str) -> str | None:
    """Copy a corrupt file aside. Returns the backup path, or None on failure."""
    if not os.path.exists(path):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base, ext = os.path.splitext(path)
    backup_path = f"{base}.corrupt.{stamp}{ext or '.json'}"
    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except OSError:
        return None


def _migrate_task(task: Any) -> Any:
    """Upgrade a legacy (v1) task dict to the v2 study-task shape, in place."""
    if not isinstance(task, dict):
        return task
    if "estimated_minutes" not in task and "estimated_hours" in task:
        try:
            task["estimated_minutes"] = int(round(float(task.get("estimated_hours") or 0) * 60))
        except (TypeError, ValueError):
            task["estimated_minutes"] = 0
    if not task.get("deadline") and task.get("due_date"):
        task["deadline"] = task.get("due_date")
    if not task.get("category") and task.get("task_type"):
        task["category"] = task.get("task_type")
    if not task.get("source_document") and task.get("course_code"):
        task["source_document"] = task.get("course_code")
    if not task.get("source_type") and task.get("source"):
        task["source_type"] = task.get("source")
    if "confidence" not in task and "ai_confidence" in task:
        task["confidence"] = task.get("ai_confidence")
    task.setdefault("task_id", "task")
    task.setdefault("title", "Untitled task")
    task.setdefault("description", "")
    task.setdefault("category", "other")
    task.setdefault("deadline", "")
    task.setdefault("estimated_minutes", 0)
    task.setdefault("difficulty", "medium")
    task.setdefault("priority", "medium")
    task.setdefault("dependencies", [])
    task.setdefault("source_document", "UNKNOWN")
    task.setdefault("source_type", "json")
    task.setdefault("confidence", 0.0)
    for key in LEGACY_TASK_KEYS:
        task.pop(key, None)
    return task


def validate_task(task: Any) -> tuple[bool, list[str]]:
    """Check a single task record. Returns ``(is_valid, problems)``."""
    problems: list[str] = []
    if not isinstance(task, dict):
        return False, ["task is not an object"]
    for field in REQUIRED_TASK_FIELDS:
        if field not in task:
            problems.append(f"missing field: {field}")
    if "task_id" in task and not str(task.get("task_id", "")).strip():
        problems.append("empty task_id")
    if "priority" in task and str(task.get("priority", "")).lower() not in VALID_PRIORITIES:
        problems.append(f"invalid priority: {task.get('priority')}")
    if "difficulty" in task and str(task.get("difficulty", "")).lower() not in VALID_DIFFICULTIES:
        problems.append(f"invalid difficulty: {task.get('difficulty')}")
    if "category" in task and str(task.get("category", "")).lower() not in VALID_CATEGORIES:
        problems.append(f"invalid category: {task.get('category')}")
    return (len(problems) == 0), problems


def validate_plan(plan: Any) -> tuple[bool, list[str]]:
    """Check a plan container. Returns ``(is_valid, problems)``."""
    problems: list[str] = []
    if not isinstance(plan, dict):
        return False, ["plan is not an object"]
    if not isinstance(plan.get("plans", []), list):
        problems.append("plans is not a list")
    return (len(problems) == 0), problems


def repair_records(plan: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop invalid plans/tasks and collect human-readable warnings."""
    warnings: list[str] = []
    if not isinstance(plan, dict):
        return empty_plan(), ["plan replaced: not an object"]
    entries = plan.get("plans", [])
    if not isinstance(entries, list):
        return empty_plan(), ["plan replaced: plans is not a list"]
    cleaned_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            warnings.append("dropped a plan entry that was not an object")
            continue
        tasks = entry.get("tasks", [])
        if not isinstance(tasks, list):
            warnings.append(f"plan {entry.get('plan_id', '?')}: tasks is not a list")
            tasks = []
        good_tasks: list[dict[str, Any]] = []
        for task in tasks:
            task = _migrate_task(task)
            ok, problems = validate_task(task)
            if ok:
                good_tasks.append(task)
            else:
                tid = task.get("task_id", "?") if isinstance(task, dict) else "?"
                warnings.append(f"dropped task {tid}: {'; '.join(problems)}")
        entry["tasks"] = good_tasks
        if "courses" in entry and "documents" not in entry:
            entry["documents"] = entry.pop("courses")
        entry.setdefault("documents", [])
        cleaned_entries.append(entry)
    plan["plans"] = cleaned_entries
    plan.setdefault("schema_version", SCHEMA_VERSION)
    return plan, warnings


def load_plans(path: str = DEFAULT_PLAN_PATH) -> dict[str, Any]:
    """Load the plan container, tolerating missing/corrupt files. Never raises."""
    if not path:
        path = DEFAULT_PLAN_PATH
    if not os.path.exists(path):
        ensure_parent_dir(path)
        return empty_plan()
    raw, error = read_raw_file(path)
    if error is not None:
        return empty_plan()
    data, parse_error = parse_json_safe(raw)
    if parse_error is not None:
        backup_corrupt(path)
        return empty_plan()
    data, _warnings = repair_records(data)
    return data


def save_plans(plan: dict[str, Any], path: str = DEFAULT_PLAN_PATH) -> tuple[bool, str | None]:
    """Persist the plan container. Returns ``(success, error)``."""
    if not path:
        path = DEFAULT_PLAN_PATH
    if not isinstance(plan, dict):
        return False, "plan is not an object"
    if not ensure_parent_dir(path):
        return False, f"could not create directory for {path}"
    plan["schema_version"] = plan.get("schema_version", SCHEMA_VERSION)
    plan["updated_at"] = now_iso()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=2, ensure_ascii=False)
        return True, None
    except OSError as exc:
        return False, f"could not write {path}: {exc}"


def append_plan_entry(
    plan: dict[str, Any],
    entry: dict[str, Any],
    path: str = DEFAULT_PLAN_PATH,
) -> tuple[bool, str | None]:
    """Append a plan entry to the container and persist it."""
    if not isinstance(plan, dict):
        plan = empty_plan()
    if not isinstance(entry, dict):
        return False, "entry is not an object"
    plan.setdefault("schema_version", SCHEMA_VERSION)
    if not isinstance(plan.get("plans"), list):
        plan["plans"] = []
    plan["plans"].append(entry)
    return save_plans(plan, path)


def list_plan_entries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the plan entries inside a container (never raises)."""
    if not isinstance(plan, dict):
        return []
    entries = plan.get("plans", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def get_plan_entry(plan: dict[str, Any], plan_id: str) -> dict[str, Any] | None:
    """Return the plan entry with ``plan_id``, or ``None`` if not found."""
    target = str(plan_id)
    for entry in list_plan_entries(plan):
        if str(entry.get("plan_id", "")) == target:
            return entry
    return None


def delete_plan_entry(plan: dict[str, Any], plan_id: str) -> bool:
    """Remove the plan entry with ``plan_id`` (does not save). True if removed."""
    if not isinstance(plan, dict) or not isinstance(plan.get("plans"), list):
        return False
    target = str(plan_id)
    kept = [
        entry
        for entry in plan["plans"]
        if not (isinstance(entry, dict) and str(entry.get("plan_id", "")) == target)
    ]
    removed = len(kept) != len(plan["plans"])
    plan["plans"] = kept
    return removed


def update_plan_entry(plan: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Replace the plan entry whose ``plan_id`` matches ``entry`` (does not save)."""
    if not isinstance(plan, dict) or not isinstance(plan.get("plans"), list) or not isinstance(entry, dict):
        return False
    target = str(entry.get("plan_id", ""))
    for index, existing in enumerate(plan["plans"]):
        if isinstance(existing, dict) and str(existing.get("plan_id", "")) == target:
            plan["plans"][index] = entry
            return True
    return False


def find_task(entry: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    """Return the task with ``task_id`` inside a plan entry, or ``None``."""
    if not isinstance(entry, dict):
        return None
    tasks = entry.get("tasks", [])
    if not isinstance(tasks, list):
        return None
    target = str(task_id)
    for task in tasks:
        if isinstance(task, dict) and str(task.get("task_id", "")) == target:
            return task
    return None