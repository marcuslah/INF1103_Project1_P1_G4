"""repository.py — The storage contract every plan store must follow."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class StorageError(Exception):
    """Raised when plans cannot be read from or written to storage."""


class PlanRepository(ABC):
    """Interface for anything that stores study plans.
    A plan is passed as a dictionary in the stored shape (see StudyPlan.to_dict).
    Implementations raise StorageError when storage cannot be used.
    contains 7 storage methods, each of which is abstract and must be implemented by subclasses.
    """

    @property
    @abstractmethod
    def location(self) -> str:
        """Where the plans are stored, for messages shown to the user."""

    @abstractmethod
    def add(self, plan: dict[str, Any]) -> None:
        """Store a new plan."""

    @abstractmethod
    def get(self, plan_id: str) -> dict[str, Any] | None:
        """Return the plan with this id, or None when it does not exist."""

    @abstractmethod
    def list_all(self) -> list[dict[str, Any]]:
        """Return every stored plan, oldest first."""

    @abstractmethod
    def update(self, plan: dict[str, Any]) -> bool:
        """Replace the stored plan with the same plan_id. False when it does not exist."""

    @abstractmethod
    def delete(self, plan_id: str) -> bool:
        """Remove a plan. False when it does not exist."""

    @abstractmethod
    def find_tasks(
        self,
        difficulty: str | None = None,
        category: str | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return (plan_id, task) pairs across all plans that match the filters."""
