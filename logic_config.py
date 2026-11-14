"""logic_config.py — Every threshold and weight the Logic Manager uses, in one object."""

from __future__ import annotations


class LogicConfig:
    """Configurable business-rule settings.

    The defaults are the Part 1 values. Pass different values to change how the
    rules, metrics and scheduler behave without editing their code.
    """

    DEFAULT_DIFFICULTY_WEIGHTS: dict[str, float] = {"easy": 0.8, "medium": 1.0, "hard": 1.3}
    DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
        "exam": 1.5,
        "project": 1.3,
        "assignment": 1.0,
        "lab": 1.0,
        "tutorial": 0.9,
        "revision": 0.7,
        "reading": 0.5,
        "other": 0.8,
    }

    def __init__(
        self,
        weekly_capacity_minutes: int = 1200,
        cognitive_load_cap: float = 100.0,
        cognitive_scale: float = 5.0,
        clash_threshold_days: int = 2,
        burnout_flag_threshold: float = 80.0,
        imminent_days: int = 7,
        single_task_overload_minutes: int = 720,
        trivial_minutes: int = 20,
        session_target_minutes: int = 90,
        session_max_minutes: int = 150,
        max_sessions_per_task_week: int = 2,
        default_horizon_weeks: int = 15,
        midterm_fraction: float = 0.5,
        labtest_fraction: float = 0.8,
        series_start_fraction: float = 0.2,
        series_end_offset: int = 2,
        high_importance_categories: tuple[str, ...] = ("exam", "project"),
        difficulty_weights: dict[str, float] | None = None,
        category_weights: dict[str, float] | None = None,
    ) -> None:
        self._weekly_capacity_minutes = int(weekly_capacity_minutes)
        self._cognitive_load_cap = float(cognitive_load_cap)
        self._cognitive_scale = float(cognitive_scale)
        self._clash_threshold_days = int(clash_threshold_days)
        self._burnout_flag_threshold = float(burnout_flag_threshold)
        self._imminent_days = int(imminent_days)
        self._single_task_overload_minutes = int(single_task_overload_minutes)
        self._trivial_minutes = int(trivial_minutes)
        self._session_target_minutes = int(session_target_minutes)
        self._session_max_minutes = int(session_max_minutes)
        self._max_sessions_per_task_week = int(max_sessions_per_task_week)
        self._default_horizon_weeks = int(default_horizon_weeks)
        self._midterm_fraction = float(midterm_fraction)
        self._labtest_fraction = float(labtest_fraction)
        self._series_start_fraction = float(series_start_fraction)
        self._series_end_offset = int(series_end_offset)
        self._high_importance_categories = tuple(high_importance_categories)
        self._difficulty_weights = dict(difficulty_weights or self.DEFAULT_DIFFICULTY_WEIGHTS)
        self._category_weights = dict(category_weights or self.DEFAULT_CATEGORY_WEIGHTS)

    # ----------------------------- capacity and risk -----------------------------

    @property
    def weekly_capacity_minutes(self) -> int:
        return self._weekly_capacity_minutes

    @property
    def weekly_capacity_hours(self) -> float:
        return self._weekly_capacity_minutes / 60.0

    @property
    def cognitive_load_cap(self) -> float:
        return self._cognitive_load_cap

    @property
    def cognitive_scale(self) -> float:
        return self._cognitive_scale

    @property
    def clash_threshold_days(self) -> int:
        return self._clash_threshold_days

    @property
    def burnout_flag_threshold(self) -> float:
        return self._burnout_flag_threshold

    @property
    def imminent_days(self) -> int:
        return self._imminent_days

    @property
    def single_task_overload_minutes(self) -> int:
        return self._single_task_overload_minutes

    @property
    def trivial_minutes(self) -> int:
        return self._trivial_minutes

    @property
    def high_importance_categories(self) -> tuple[str, ...]:
        return self._high_importance_categories

    # ----------------------------- scheduling -----------------------------

    @property
    def session_target_minutes(self) -> int:
        return self._session_target_minutes

    @property
    def session_max_minutes(self) -> int:
        return self._session_max_minutes

    @property
    def max_sessions_per_task_week(self) -> int:
        return self._max_sessions_per_task_week

    @property
    def default_horizon_weeks(self) -> int:
        return self._default_horizon_weeks

    @property
    def midterm_fraction(self) -> float:
        return self._midterm_fraction

    @property
    def labtest_fraction(self) -> float:
        return self._labtest_fraction

    @property
    def series_start_fraction(self) -> float:
        return self._series_start_fraction

    @property
    def series_end_offset(self) -> int:
        return self._series_end_offset

    # ----------------------------- weights -----------------------------

    def difficulty_weight(self, difficulty: str) -> float:
        return self._difficulty_weights.get(str(difficulty).lower(), 1.0)

    def category_weight(self, category: str) -> float:
        return self._category_weights.get(str(category).lower(), self._category_weights.get("other", 0.8))

    def resolve_capacity(self, weekly_capacity: float | None) -> int:
        """Use the given weekly capacity when it is a positive number, else the configured one."""
        try:
            value = float(weekly_capacity) if weekly_capacity is not None else 0.0
        except (TypeError, ValueError):
            value = 0.0
        return int(round(value)) if value > 0 else self._weekly_capacity_minutes
