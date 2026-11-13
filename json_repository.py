"""json_repository.py — Stores study plans in one JSON file, with corruption recovery."""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any
from repository import PlanRepository, StorageError

class JsonPlanRepository(PlanRepository):
    """Flat-file JSON storage.
    Reading never raises: a missing or unreadable file gives an empty store.
    Writing raises StorageError.
    """
    SCHEMA_VERSION: str = "2.0"
    DEFAULT_PATH: str = "data/study_plans.json"

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
        if not isinstance(data, dict) or not isinstance(data.get("plans"), list):
            self._warnings.append(f"unreadable plan file ignored: {self._path}")
            return self._empty_container()
        return data
    
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
