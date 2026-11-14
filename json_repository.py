"""json_repository.py — Stores study plans in one JSON file, with corruption recovery."""

from __future__ import annotations
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any
from repository import PlanRepository, StorageError

class JsonPlanRepository(PlanRepository):
    """Flat-file JSON storage.
    Reading never raises: a missing file gives an empty store, and a corrupt file
    is copied to a backup before the store starts empty. Writing raises StorageError.
    """
    SCHEMA_VERSION: str = "2.0"
    DEFAULT_PATH: str = "data/study_plans.json"
    REQUIRED_TASK_FIELDS: tuple[str, ...] = (
        "task_id", "title", "category", "deadline", "estimated_minutes",
        "difficulty", "priority", "source_document",
    )
    VALID_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
    VALID_DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
    VALID_CATEGORIES: tuple[str, ...] = (
        "assignment", "exam", "tutorial", "lab", "project", "reading", "revision", "other",
    )
    LEGACY_TASK_KEYS: tuple[str, ...] = (
        "course_code", "due_date", "estimated_hours", "weight_percent",
        "task_type", "source", "ai_confidence",
    )

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self._path = path or self.DEFAULT_PATH
        self._warnings: list[str] = []
    # ----------------------------- interface ----------------------------
    @property
    def location(self) -> str:
        return self._path
    
    @property
    def warnings(self) -> list[str]:
        """Problems repaired during the most recent load (dropped tasks and so on)."""
        return list(self._warnings)
    
    def add(self, plan: dict[str, Any]) -> None:
        if not isinstance(plan, dict):
            raise StorageError("plan is not an object")
        container = self._load_container()
        container["plans"].append(plan)
        self._save_container(container)

    def get(self, plan_id: str) -> dict[str, Any] | None:
        target = str(plan_id)
        for entry in self._load_container()["plans"]:
            if str(entry.get("plan_id", "")) == target:
                return entry
        return None
    
    def list_all(self) -> list[dict[str, Any]]:
        return list(self._load_container()["plans"])
    
    def update(self, plan: dict[str, Any]) -> bool:
        if not isinstance(plan, dict):
            return False
        target = str(plan.get("plan_id", ""))
        container = self._load_container()
        for index, existing in enumerate(container["plans"]):
            if str(existing.get("plan_id", "")) == target:
                container["plans"][index] = plan
                self._save_container(container)
                return True
        return False
    
    def delete(self, plan_id: str) -> bool:
        target = str(plan_id)
        container = self._load_container()
        kept = [entry for entry in container["plans"] if str(entry.get("plan_id", "")) != target]
        if len(kept) == len(container["plans"]):
            return False
        container["plans"] = kept
        self._save_container(container)
        return True
    
    def find_tasks(
        self,
        difficulty: str | None = None,
        category: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        wanted_difficulty = str(difficulty).strip().lower() if difficulty else None
        wanted_category = str(category).strip().lower() if category else None
        matches: list[tuple[str, dict[str, Any]]] = []
        for entry in self._load_container()["plans"]:
            for task in entry.get("tasks", []):
                if wanted_difficulty and str(task.get("difficulty", "")).lower() != wanted_difficulty:
                    continue
                if wanted_category and str(task.get("category", "")).lower() != wanted_category:
                    continue
                matches.append((str(entry.get("plan_id", "")), task))
        return matches
    
    # ----------------------------- file handling ----------------------------
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    
    def _empty_container(self) -> dict[str, Any]:
        return {"schema_version": self.SCHEMA_VERSION, "updated_at": self._now_iso(), "plans": []}
    
    def _ensure_parent_dir(self) -> bool:
        parent = os.path.dirname(os.path.abspath(self._path))
        try:
            os.makedirs(parent, exist_ok=True)
            return True
        except OSError:
            return False
        
    def _backup_corrupt(self) -> str | None:
        """Copy a corrupt file aside. Returns the backup path, or None on failure."""
        if not os.path.exists(self._path):
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base, ext = os.path.splitext(self._path)
        backup_path = f"{base}.corrupt.{stamp}{ext or '.json'}"
        try:
            shutil.copy2(self._path, backup_path)
            return backup_path
        except OSError:
            return None
        
    def _load_container(self) -> dict[str, Any]:
        """Load the whole file, tolerating missing and corrupt files. Never raises."""
        self._warnings = []
        if not os.path.exists(self._path):
            self._ensure_parent_dir()
            return self._empty_container()
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            self._warnings.append(f"could not read {self._path}: {exc}")
            return self._empty_container()
        try:
            data = json.loads(raw) if raw.strip() else None
        except (json.JSONDecodeError, ValueError):
            data = None
        if not isinstance(data, dict):
            backup = self._backup_corrupt()
            self._warnings.append(f"corrupt plan file replaced (backup: {backup})")
            return self._empty_container()
        return self._repair(data)
    
    def _save_container(self, container: dict[str, Any]) -> None:
        if not self._ensure_parent_dir():
            raise StorageError(f"could not create directory for {self._path}")
        container["schema_version"] = container.get("schema_version", self.SCHEMA_VERSION)
        container["updated_at"] = self._now_iso()
        try:
            with open(self._path, "w", encoding="utf-8") as handle:
                json.dump(container, handle, indent=2, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            raise StorageError(f"could not write {self._path}: {exc}") from exc
        
    # ----------------------------- repair and migration ----------------------------
    def _migrate_task(self, task: Any) -> Any:
        """Upgrade an old-format task dictionary to the current shape, in place."""
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
        for key in self.LEGACY_TASK_KEYS:
            task.pop(key, None)
        return task
    
    def _task_problems(self, task: Any) -> list[str]:
        """Return what is wrong with a stored task (empty list when it is valid)."""
        if not isinstance(task, dict):
            return ["task is not an object"]
        problems: list[str] = []
        for field in self.REQUIRED_TASK_FIELDS:
            if field not in task:
                problems.append(f"missing field: {field}")
        if "task_id" in task and not str(task.get("task_id", "")).strip():
            problems.append("empty task_id")
        if "priority" in task and str(task.get("priority", "")).lower() not in self.VALID_PRIORITIES:
            problems.append(f"invalid priority: {task.get('priority')}")
        if "difficulty" in task and str(task.get("difficulty", "")).lower() not in self.VALID_DIFFICULTIES:
            problems.append(f"invalid difficulty: {task.get('difficulty')}")
        if "category" in task and str(task.get("category", "")).lower() not in self.VALID_CATEGORIES:
            problems.append(f"invalid category: {task.get('category')}")
        return problems
    
    def _repair(self, container: dict[str, Any]) -> dict[str, Any]:
        """Drop invalid plans and tasks, migrate old records, and note what changed."""
        entries = container.get("plans", [])
        if not isinstance(entries, list):
            self._warnings.append("plan file replaced: plans is not a list")
            return self._empty_container()
        cleaned: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                self._warnings.append("dropped a plan entry that was not an object")
                continue
            tasks = entry.get("tasks", [])
            if not isinstance(tasks, list):
                self._warnings.append(f"plan {entry.get('plan_id', '?')}: tasks is not a list")
                tasks = []
            good_tasks: list[dict[str, Any]] = []
            for task in tasks:
                task = self._migrate_task(task)
                problems = self._task_problems(task)
                if problems:
                    task_id = task.get("task_id", "?") if isinstance(task, dict) else "?"
                    self._warnings.append(f"dropped task {task_id}: {'; '.join(problems)}")
                else:
                    good_tasks.append(task)
            entry["tasks"] = good_tasks
            if "courses" in entry and "documents" not in entry:
                entry["documents"] = entry.pop("courses")
            entry.setdefault("documents", [])
            cleaned.append(entry)
        container["plans"] = cleaned
        container.setdefault("schema_version", self.SCHEMA_VERSION)
        return container