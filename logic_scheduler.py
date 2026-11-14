"""logic_scheduler.py — Timeline recovery and the weekly study schedule."""

from __future__ import annotations

import re
from datetime import date, timedelta
from math import ceil

from logic_config import LogicConfig
from logic_metrics import WorkloadEstimator
from models import Task, WeekSchedule


class TimelineParser:
    """Recovers timing information from the free text of a task."""

    _WEEK_RANGE_RE = re.compile(r"weeks?\s+(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})", re.IGNORECASE)
    _WEEK_OR_RE = re.compile(r"weeks?\s+(\d{1,2})\s*(?:or|/|and)\s*(\d{1,2})", re.IGNORECASE)
    _WEEK_SINGLE_RE = re.compile(r"week\s+(\d{1,2})", re.IGNORECASE)
    _RECURRENCE_RE = re.compile(
        r"(?<![\w-])(\d{1,2})\s+(?:[a-z]+\s+)?"
        r"(assignments|quizzes|readings|exercises|tasks|labs|tutorials|reports)\b",
        re.IGNORECASE,
    )
    _CURRENT_WEEK_RE = re.compile(
        r"\bthis week\b|\bcurrent week\b|\bby (mon|tue|wed|thu|fri|sat|sun)",
        re.IGNORECASE,
    )
    _ORDINAL_RE = re.compile(r"\b(\d{1,2})([a-z]?)\b", re.IGNORECASE)
    _DOC_WEEK_RE = re.compile(r"week\s*(\d{1,2})", re.IGNORECASE)
    _SERIES_STOPWORDS: frozenset[str] = frozenset({
        "complete", "submit", "write", "and", "the", "a", "an", "for", "of", "to",
        "with", "part", "as", "in", "on", "your", "all", "selected", "questions",
    })

    def __init__(self, config: LogicConfig) -> None:
        self._config = config

    def extract_hints(self, text: str | None) -> dict[str, int | None]:
        """Find relative timing such as "weeks 3-13", "week 8" or "5 quizzes".

        Returns ``{"start_week", "due_week", "recurrence"}`` with None where unknown.
        """
        result: dict[str, int | None] = {"start_week": None, "due_week": None, "recurrence": None}
        if not text:
            return result
        blob = str(text)
        match = self._WEEK_RANGE_RE.search(blob) or self._WEEK_OR_RE.search(blob)
        if match:
            first, second = int(match.group(1)), int(match.group(2))
            result["start_week"] = min(first, second)
            result["due_week"] = max(first, second)
        else:
            singles = [int(m.group(1)) for m in self._WEEK_SINGLE_RE.finditer(blob)]
            if singles:
                result["start_week"] = min(singles)
                result["due_week"] = max(singles)
        recurrence = self._RECURRENCE_RE.search(blob)
        if recurrence:
            count = int(recurrence.group(1))
            if 2 <= count <= 50:
                result["recurrence"] = count
        return result

    def count_occurrences(self, task: Task) -> int:
        """How many repeating instances a task represents.

        Only tasks with an explicit week window (for example "over weeks 3-13")
        count as recurring, so a standalone tutorial is never mistaken for 10 repeats.
        """
        hints = self.extract_hints(task.text)
        start = hints.get("start_week")
        due = hints.get("due_week")
        if start is None or due is None or due <= start:
            return 1
        recurrence = hints.get("recurrence") or 1
        return max(1, min(int(recurrence), int(due) - int(start) + 1))

    def ordinal(self, title: str) -> tuple[int, str] | None:
        """First ordinal token in a title, for example "Assignment 3B" gives (3, "b")."""
        match = self._ORDINAL_RE.search(str(title or ""))
        if not match:
            return None
        return int(match.group(1)), (match.group(2) or "").lower()

    def series_key(self, title: str) -> str:
        """Reduce a title to its series name (numbers and filler words removed)."""
        text = self._ORDINAL_RE.sub(" ", str(title or "").lower())
        text = re.sub(r"[^a-z]+", " ", text)
        return " ".join(word for word in text.split() if word not in self._SERIES_STOPWORDS)

    def keyword_window(self, text: str, horizon: int) -> tuple[int, int] | None:
        """Default placement for undated milestones such as midterms and finals."""
        low = str(text or "").lower()
        span = max(1, int(horizon))
        if "midterm" in low or "mid-term" in low:
            week = max(1, min(span, int(round(span * self._config.midterm_fraction))))
            return week, week
        if "final" in low and ("exam" in low or "examination" in low):
            return max(1, span - 1), span
        if "lab test" in low or "proficiency" in low:
            week = max(1, min(span, int(round(span * self._config.labtest_fraction))))
            return week, week
        return None

    def document_week(self, task: Task) -> int | None:
        """Week named in the source document, for example "INF1103_Week3_Lab.pdf" gives 3."""
        match = self._DOC_WEEK_RE.search(task.source_document)
        return int(match.group(1)) if match else None

    def mentions_current_week(self, text: str) -> bool:
        return bool(self._CURRENT_WEEK_RE.search(str(text or "")))


class StudySession:
    """One block of study time for a task, to be placed inside a window of weeks."""

    def __init__(self, task_id: str, minutes: int, window: tuple[int, int]) -> None:
        self._task_id = str(task_id)
        self._minutes = int(minutes)
        self._window = (int(window[0]), int(window[1]))

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def minutes(self) -> int:
        return self._minutes

    @property
    def window(self) -> tuple[int, int]:
        return self._window


class Scheduler:
    """Splits tasks into study sessions and spreads them across the semester."""

    def __init__(self, config: LogicConfig, estimator: WorkloadEstimator) -> None:
        self._config = config
        self._estimator = estimator
        self._timeline = TimelineParser(config)       # composition: owned by the scheduler

    @property
    def timeline(self) -> TimelineParser:
        return self._timeline

    # ----------------------------- calendar helpers -----------------------------

    @staticmethod
    def _anchor_monday(today: date) -> date:
        """Monday of the week containing today. Week 1 starts here."""
        return today - timedelta(days=today.weekday())

    @staticmethod
    def _week_dates(anchor: date, week_index: int) -> tuple[date, date]:
        start = anchor + timedelta(days=(week_index - 1) * 7)
        return start, start + timedelta(days=6)

    def _week_index_for_date(self, target: date, today: date) -> int:
        return (target - self._anchor_monday(today)).days // 7 + 1

    def _max_due_week(self, tasks: list[Task], today: date) -> int:
        """Highest week number mentioned by any task (text hints or deadline dates)."""
        best = 0
        for task in tasks:
            due = self._timeline.extract_hints(task.text).get("due_week")
            deadline = task.deadline_date
            if deadline is not None:
                mapped = self._week_index_for_date(deadline, today)
                due = mapped if due is None else max(int(due), mapped)
            if due:
                best = max(best, int(due))
        return best

    def _weeks_needed(self, task: Task, total_minutes: int | None = None) -> int:
        """How many weeks the task's own sessions need (never the whole semester)."""
        total = int(total_minutes) if total_minutes is not None else self._estimator.task_total(task)
        if total <= self._config.session_max_minutes:
            sessions = 1
        else:
            sessions = max(1, ceil(total / self._config.session_target_minutes))
        return max(1, ceil(sessions / self._config.max_sessions_per_task_week))

    # ----------------------------- windows -----------------------------

    def _window_from_task(
        self,
        task: Task,
        today: date,
        horizon: int,
        total_minutes: int,
    ) -> tuple[int, int] | None:
        """Window from explicit weeks, a deadline, the document name or keywords. None if unknown."""
        hints = self._timeline.extract_hints(task.text)
        start_week = hints.get("start_week")
        due_week = hints.get("due_week")
        if start_week or due_week:
            start = int(start_week if start_week is not None else due_week)
            end = int(due_week if due_week is not None else start_week)
            start = max(1, min(start, int(horizon)))
            end = max(1, min(end, int(horizon)))
            if end < start:
                start, end = end, start
            return start, end
        deadline = task.deadline_date
        if deadline is not None:
            due = max(1, min(self._week_index_for_date(deadline, today), int(horizon)))
            lead = self._weeks_needed(task, total_minutes) - 1
            return max(1, due - lead), due
        doc_week = self._timeline.document_week(task)
        if doc_week is not None:
            week = max(1, min(doc_week, int(horizon)))
            return week, week
        keyword = self._timeline.keyword_window(task.text, horizon)
        if keyword is not None:
            return keyword
        if self._timeline.mentions_current_week(task.text):
            return 1, 1
        return None

    def plan_windows(self, tasks: list[Task], today: date, horizon: int) -> dict[str, tuple[int, int]]:
        """Give every task a (start_week, due_week) window.

        Explicit hints, deadlines and keywords win. Undated tasks that form an
        ordered series (for example "Assignment 1A..4B") are spread across the
        module. A lone undated task stays in the current week.
        """
        windows: dict[str, tuple[int, int]] = {}
        pending: list[Task] = []
        for task in tasks:
            window = self._window_from_task(task, today, horizon, self._estimator.task_total(task))
            if window is not None:
                windows[task.task_id] = window
            else:
                pending.append(task)
        groups: dict[str, list[Task]] = {}
        for task in pending:
            groups.setdefault(self._timeline.series_key(task.title), []).append(task)
        series_start = max(1, int(round(horizon * self._config.series_start_fraction)))
        series_end = max(series_start, int(horizon) - self._config.series_end_offset)
        for key, group in groups.items():
            ordinals = [o for o in (self._timeline.ordinal(task.title) for task in group) if o is not None]
            if key and len(group) >= 2 and len(set(ordinals)) >= 2:
                ordered = sorted(group, key=lambda task: self._timeline.ordinal(task.title) or (0, ""))
                count = len(ordered)
                span = series_end - series_start
                for position, task in enumerate(ordered):
                    offset = int(round(position * span / (count - 1))) if count > 1 and span > 0 else 0
                    week = max(series_start, min(series_end, series_start + offset))
                    windows[task.task_id] = (week, week)
            else:
                for task in group:
                    windows[task.task_id] = (1, max(1, min(self._weeks_needed(task), int(horizon))))
        return windows

    def resolve_window(
        self,
        task: Task,
        today: date,
        horizon: int,
        total_minutes: int | None = None,
    ) -> tuple[int, int]:
        """Window for a single task: explicit rules first, otherwise a tight local window."""
        total = total_minutes if total_minutes is not None else self._estimator.task_total(task)
        window = self._window_from_task(task, today, horizon, total)
        if window is not None:
            return window
        return 1, max(1, min(self._weeks_needed(task, total), int(horizon)))

    # ----------------------------- sessions -----------------------------

    def build_sessions(
        self,
        task: Task,
        window: tuple[int, int],
        total_minutes: int | None = None,
    ) -> list[StudySession]:
        """Split a task into study sessions no longer than the configured maximum."""
        total = int(total_minutes) if total_minutes is not None else self._estimator.task_total(task)
        if total <= 0:
            return []
        if total <= self._config.session_max_minutes:
            return [StudySession(task.task_id, total, window)]
        count = max(1, ceil(total / self._config.session_target_minutes))
        base = total // count
        remainder = total - base * count
        return [
            StudySession(task.task_id, base + (1 if index < remainder else 0), window)
            for index in range(count)
        ]

    def _plan_sessions(self, tasks: list[Task], today: date, horizon: int) -> list[StudySession]:
        """Turn tasks into sessions, expanding recurring tasks across their window."""
        sessions: list[StudySession] = []
        windows = self.plan_windows(tasks, today, horizon)
        for task in tasks:
            total = self._estimator.task_total(task)
            if total <= 0:
                continue
            window = windows.get(task.task_id) or self.resolve_window(task, today, horizon, total)
            occurrences = self._timeline.count_occurrences(task)
            if occurrences >= 2:
                per = max(1, int(round(total / occurrences)))
                start, end = window
                span = max(0, end - start)
                for index in range(occurrences):
                    offset = int(round(index * span / (occurrences - 1))) if span > 0 else 0
                    week = max(start, min(end, start + offset))
                    sessions.extend(self.build_sessions(task, (week, week), per))
            else:
                sessions.extend(self.build_sessions(task, window, total))
        return sessions

    def _place_session(
        self,
        session: StudySession,
        weeks: list[WeekSchedule],
        capacity: int,
        horizon: int,
    ) -> None:
        """Put one session into the least-loaded week inside its window."""
        start, end = session.window
        start = max(1, min(int(start), horizon))
        end = max(start, min(int(end), horizon))
        best_week = None
        best_score = None
        for week_number in range(start, end + 1):
            week = weeks[week_number - 1]
            if week.allocated_minutes + session.minutes > capacity:
                continue
            if week.session_count(session.task_id) >= self._config.max_sessions_per_task_week:
                continue
            score = (week.allocated_minutes, week_number)      # least loaded, then earliest
            if best_score is None or score < best_score:
                best_score = score
                best_week = week_number
        if best_week is None:
            candidates = list(range(start, end + 1)) or [horizon]
            best_week = min(candidates, key=lambda number: weeks[number - 1].allocated_minutes)
        weeks[best_week - 1].add_allocation(session.task_id, session.minutes)

    # ----------------------------- public scheduling -----------------------------

    def build_weekly_plan(
        self,
        tasks: list[Task],
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> list[WeekSchedule]:
        """Spread study sessions across the semester. Week 1 is the current week."""
        if not tasks:
            return []
        if not isinstance(today, date):
            today = date.today()
        capacity = self._config.resolve_capacity(weekly_capacity)
        horizon = max(self._config.default_horizon_weeks, self._max_due_week(tasks, today))
        anchor = self._anchor_monday(today)
        weeks: list[WeekSchedule] = []
        for index in range(1, horizon + 1):
            start, end = self._week_dates(anchor, index)
            weeks.append(WeekSchedule(index, start.isoformat(), end.isoformat()))
        for session in self._plan_sessions(tasks, today, horizon):
            self._place_session(session, weeks, capacity, horizon)
        return weeks

    def rebalance(
        self,
        tasks: list[Task],
        weekly_capacity: float | None = None,
        today: date | None = None,
    ) -> tuple[list[WeekSchedule], list[str]]:
        """Build the schedule and describe how the load was spread."""
        capacity = self._config.resolve_capacity(weekly_capacity)
        weekly_plan = self.build_weekly_plan(tasks, capacity, today)
        first_week: dict[str, int] = {}
        for week in weekly_plan:
            for task_id in week.task_ids:
                first_week.setdefault(task_id, week.week_index)
        deferred_low = [
            task for task in tasks
            if task.priority == "low" and first_week.get(task.task_id, 1) >= 2
        ]
        notes: list[str] = []
        if deferred_low:
            notes.append(
                f"Spread {len(deferred_low)} low-priority task(s) beyond week 1 to respect the "
                f"{capacity} min weekly cap"
            )
        used = [week for week in weekly_plan if week.allocated_minutes > 0]
        if len(used) > 1:
            notes.append(f"Schedule spans {len(used)} weeks")
        return weekly_plan, notes
