"""data_manager.py — Saves, loads and queries study plans.

The Data Manager is the only place where StudyPlan objects are turned into
dictionaries and back. It does not know whether the plans live in a JSON file
or a database; it only talks to a PlanRepository.
"""

from __future__ import annotations
from models import StudyPlan, Task
from repository import PlanRepository


class DataManager:
    """Persistence and querying for study plans."""

    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository      # aggregation: created outside and passed in

    @property
    def storage_location(self) -> str:
        return self._repository.location

    # ----------------------------- save and load ----------------------------
    def save_plan(self, plan: StudyPlan) -> None:
        """Store a new plan. Raises StorageError when it cannot be written."""
        self._repository.add(plan.to_dict())

    def update_plan(self, plan: StudyPlan) -> bool:
        """Replace a stored plan. Returns False when the plan is not in storage."""
        return self._repository.update(plan.to_dict())

    def delete_plan(self, plan_id: str) -> bool:
        return self._repository.delete(plan_id)

    def get_plan(self, plan_id: str) -> StudyPlan | None:
        data = self._repository.get(plan_id)
        return StudyPlan.from_dict(data) if data is not None else None

    def list_plans(self) -> list[StudyPlan]:
        return [StudyPlan.from_dict(data) for data in self._repository.list_all()]
