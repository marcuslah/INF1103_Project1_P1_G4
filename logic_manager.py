"""
logic_manager.py — Workload metrics, timeline-aware planning, decision engine.
To do: no console output or keyboard input belongs here > goes to io_manager.py
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any

WEEKLY_CAPACITY_HOURS: float = 20.0
WEEKLY_CAPACITY_MINUTES: int = 1200
COGNITIVE_LOAD_CAP: float = 100.0
COGNITIVE_SCALE: float = 5.0
CLASH_THRESHOLD_DAYS: int = 2
BURNOUT_FLAG_THRESHOLD: float = 80.0
IMMINENT_DAYS: int = 7
SINGLE_TASK_OVERLOAD_MINUTES: int = 720
TRIVIAL_MINUTES: int = 20

# --- planning / decomposition ---
SESSION_TARGET_MINUTES: int = 90
SESSION_MAX_MINUTES: int = 150
MAX_SESSIONS_PER_TASK_WEEK: int = 2
DEFAULT_HORIZON_WEEKS: int = 15

# Horizon fractions used to place undated module milestones / series.
MIDTERM_FRACTION: float = 0.5
LABTEST_FRACTION: float = 0.8
SERIES_START_FRACTION: float = 0.2
SERIES_END_OFFSET: int = 2

DIFFICULTY_WEIGHTS: dict[str, float] = {"easy": 0.8, "medium": 1.0, "hard": 1.3}
CATEGORY_WEIGHTS: dict[str, float] = {
    "exam": 1.5,
    "project": 1.3,
    "assignment": 1.0,
    "lab": 1.0,
    "tutorial": 0.9,
    "revision": 0.7,
    "reading": 0.5,
    "other": 0.8,
}
HIGH_IMPORTANCE_CATEGORIES: tuple[str, ...] = ("exam", "project")
PRIORITY_WEIGHTS: dict[str, float] = {"high": 1.0, "medium": 0.7, "low": 0.4}

_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")

# Timeline-hint patterns recovered from free-text task descriptions.
_WEEK_RANGE_RE = re.compile(r"weeks?\s+(\d{1,2})\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})", re.IGNORECASE)
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


# --------------------------- internal helpers ---------------------------

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_priority(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in PRIORITY_WEIGHTS else "medium"


def _norm_difficulty(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in DIFFICULTY_WEIGHTS else "medium"


def _norm_category(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in CATEGORY_WEIGHTS else "other"


def _clash_task_ids(clashes: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for clash in clashes:
        for tid in clash.get("task_ids", []):
            ids.add(str(tid))
    return ids


def _decision(task: dict[str, Any], decision: str, rule_id: str, reason: str) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id", "")),
        "decision": decision,
        "rule_id": rule_id,
        "reason": reason,
    }


def parse_date(value: Any) -> date | None:
    """Parse an ISO-ish date string. Returns ``None`` when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def compute_study_minutes(task: dict[str, Any]) -> int:
    """Effective study minutes = estimated minutes scaled by difficulty weight."""
    minutes = _to_float(task.get("estimated_minutes"))
    factor = DIFFICULTY_WEIGHTS.get(_norm_difficulty(task.get("difficulty")), 1.0)
    return int(round(minutes * factor))


def compute_study_hours(task: dict[str, Any]) -> float:
    """Convenience: effective study hours (minutes / 60)."""
    return round(compute_study_minutes(task) / 60.0, 2)


def compute_cognitive_load(tasks: list[dict[str, Any]]) -> float:
    """Sum of (hours x category-factor x scale), capped at ``COGNITIVE_LOAD_CAP``."""
    total = 0.0
    for task in tasks:
        hours = _to_float(task.get("estimated_minutes")) / 60.0
        factor = CATEGORY_WEIGHTS.get(_norm_category(task.get("category")), CATEGORY_WEIGHTS["other"])
        total += hours * factor * COGNITIVE_SCALE
    return round(min(COGNITIVE_LOAD_CAP, total), 2)


def detect_deadline_clashes(
    tasks: list[dict[str, Any]],
    threshold_days: int = CLASH_THRESHOLD_DAYS,
) -> list[dict[str, Any]]:
    """Group tasks whose due dates fall within ``threshold_days`` of each other."""
    dated: list[tuple[str, date]] = []
    for task in tasks:
        when = parse_date(task.get("deadline", ""))
        if when is not None:
            dated.append((str(task.get("task_id", "")), when))
    ids = [tid for tid, _ in dated]
    lookup = dict(dated)
    adjacency: dict[str, set[str]] = {tid: set() for tid in ids}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            first, second = ids[i], ids[j]
            if abs((lookup[first] - lookup[second]).days) <= threshold_days:
                adjacency[first].add(second)
                adjacency[second].add(first)
    clashes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in ids:
        if tid in seen or not adjacency[tid]:
            seen.add(tid)
            continue
        component: list[str] = []
        stack = [tid]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    stack.append(neighbour)
        if len(component) > 1:
            span = max(lookup[c] for c in component) - min(lookup[c] for c in component)
            clashes.append({"task_ids": sorted(component), "span_days": span.days})
    return clashes


def compute_burnout_index(weekly_minutes: float, cognitive_load: float, clash_count: int) -> float:
    """Weighted, clamped (0-100) burnout index.

    ``0.5 * peak_load_ratio + 0.3 * cognitive_ratio + 0.2 * clash_ratio``
    """
    capacity = WEEKLY_CAPACITY_MINUTES if WEEKLY_CAPACITY_MINUTES > 0 else 1
    load_ratio = min(max(_to_float(weekly_minutes), 0.0) / capacity, 1.0)
    cognitive_ratio = min(max(_to_float(cognitive_load), 0.0) / COGNITIVE_LOAD_CAP, 1.0)
    clash_ratio = min(max(int(clash_count), 0), 3) / 3.0
    index = 100.0 * (0.5 * load_ratio + 0.3 * cognitive_ratio + 0.2 * clash_ratio)
    return round(max(0.0, min(100.0, index)), 2)


# ------------------- timeline recovery + session decomposition -------------------

def extract_timeline_hints(text: str | None) -> dict[str, int | None]:
    """Recover relative timing from free text, e.g. "weeks 3-13", "week 8", "5 quizzes".

    Returns ``{"start_week", "due_week", "recurrence"}`` (``None`` where unknown).
    """
    result: dict[str, int | None] = {"start_week": None, "due_week": None, "recurrence": None}
    if not text:
        return result
    blob = str(text)
    match = _WEEK_RANGE_RE.search(blob) or _WEEK_OR_RE.search(blob)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        result["start_week"] = min(first, second)
        result["due_week"] = max(first, second)
    else:
        singles = [int(m.group(1)) for m in _WEEK_SINGLE_RE.finditer(blob)]
        if singles:
            result["start_week"] = min(singles)
            result["due_week"] = max(singles)
    recurrence = _RECURRENCE_RE.search(blob)
    if recurrence:
        count = int(recurrence.group(1))
        if 2 <= count <= 50:
            result["recurrence"] = count
    return result


def count_occurrences(task: dict[str, Any]) -> int:
    """How many repeating instances a task represents.

    Only tasks that span an **explicit week window** (e.g. "over weeks 3-13") are
    treated as recurring, so a standalone tutorial is never mistaken for 10 repeats.
    """
    text = f"{task.get('title', '')} {task.get('description', '')}"
    hints = extract_timeline_hints(text)
    start = hints.get("start_week")
    due = hints.get("due_week")
    if start is None or due is None or due <= start:
        return 1
    recurrence = hints.get("recurrence") or 1
    return max(1, min(int(recurrence), int(due) - int(start) + 1))


def _anchor_monday(today: date) -> date:
    """Monday of the week containing *today* -- week 1 starts here."""
    return today - timedelta(days=today.weekday())


def _week_dates(anchor: date, week_index: int) -> tuple[date, date]:
    start = anchor + timedelta(days=(week_index - 1) * 7)
    return start, start + timedelta(days=6)


def _week_index_for_date(target: date, today: date) -> int:
    anchor = _anchor_monday(today)
    return (target - anchor).days // 7 + 1


def _max_due_week(tasks: list[dict[str, Any]], today: date) -> int:
    """Highest week index referenced by any task (hints or deadline dates)."""
    best = 0
    for task in tasks:
        hints = extract_timeline_hints(f"{task.get('title', '')} {task.get('description', '')}")
        due = hints.get("due_week")
        deadline = parse_date(task.get("deadline", ""))
        if deadline is not None:
            mapped = _week_index_for_date(deadline, today)
            due = mapped if due is None else max(int(due), mapped)
        if due:
            best = max(best, int(due))
    return best


def _weeks_needed(task: dict[str, Any], total_minutes: int | None = None) -> int:
    """How many weeks the task's OWN sessions need (never the whole semester)."""
    if total_minutes is None:
        total_minutes = compute_study_minutes(task)
        if total_minutes <= 0:
            total_minutes = int(round(_to_float(task.get("estimated_minutes"))))
    total = int(total_minutes)
    if total <= SESSION_MAX_MINUTES:
        sessions = 1
    else:
        sessions = max(1, ceil(total / SESSION_TARGET_MINUTES))
    return max(1, ceil(sessions / MAX_SESSIONS_PER_TASK_WEEK))


def _task_total(task: dict[str, Any]) -> int:
    total = compute_study_minutes(task)
    if total <= 0:
        total = int(round(_to_float(task.get("estimated_minutes"))))
    return total


def _ordinal(title: str) -> tuple[int, str] | None:
    """First ordinal token in a title, e.g. "Assignment 3B" -> (3, "b")."""
    match = _ORDINAL_RE.search(str(title or ""))
    if not match:
        return None
    return int(match.group(1)), (match.group(2) or "").lower()


def _series_key(title: str) -> str:
    """Normalise a title to a series key (ordinals/stopwords removed)."""
    text = _ORDINAL_RE.sub(" ", str(title or "").lower())
    text = re.sub(r"[^a-z]+", " ", text)
    return " ".join(word for word in text.split() if word not in _SERIES_STOPWORDS)


def _keyword_window(text: str, horizon: int) -> tuple[int, int] | None:
    """Default placement for undated module milestones, as horizon fractions."""
    low = str(text or "").lower()
    span = max(1, int(horizon))
    if "midterm" in low or "mid-term" in low:
        week = max(1, min(span, int(round(span * MIDTERM_FRACTION))))
        return week, week
    if "final" in low and ("exam" in low or "examination" in low):
        return max(1, span - 1), span
    if "lab test" in low or "proficiency" in low:
        week = max(1, min(span, int(round(span * LABTEST_FRACTION))))
        return week, week
    return None


def _document_week(task: dict[str, Any]) -> int | None:
    """Week declared in the source document id, e.g. "INF1103_Week3_Lab.pdf" -> 3."""
    match = _DOC_WEEK_RE.search(str(task.get("source_document", "")))
    return int(match.group(1)) if match else None


def _window_from_task(
    task: dict[str, Any],
    today: date,
    horizon: int,
    total_minutes: int,
) -> tuple[int, int] | None:
    """Explicit week/deadline/keyword/current-week window, or ``None`` if unknown."""
    text = f"{task.get('title', '')} {task.get('description', '')}"
    hints = extract_timeline_hints(text)
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
    deadline = parse_date(task.get("deadline", ""))
    if deadline is not None:
        due = max(1, min(_week_index_for_date(deadline, today), int(horizon)))
        lead = _weeks_needed(task, total_minutes) - 1
        return max(1, due - lead), due
    doc_week = _document_week(task)
    if doc_week is not None:
        week = max(1, min(doc_week, int(horizon)))
        return week, week
    keyword = _keyword_window(text, horizon)
    if keyword is not None:
        return keyword
    if _CURRENT_WEEK_RE.search(text):
        return 1, 1
    return None


def plan_windows(
    tasks: list[dict[str, Any]],
    today: date,
    horizon: int,
) -> dict[str, tuple[int, int]]:
    """Assign every task a (start_week, due_week) window.

    Explicit hints/deadlines/keywords win; undated sibling tasks that form an
    ordered series (e.g. "Assignment 1A..4B") are spread across a module window;
    a lone standalone task stays tight in the current week.
    """
    windows: dict[str, tuple[int, int]] = {}
    pending: list[dict[str, Any]] = []
    for task in tasks:
        tid = str(task.get("task_id", ""))
        window = _window_from_task(task, today, horizon, _task_total(task))
        if window is not None:
            windows[tid] = window
        else:
            pending.append(task)
    groups: dict[str, list[dict[str, Any]]] = {}
    for task in pending:
        groups.setdefault(_series_key(task.get("title", "")), []).append(task)
    series_start = max(1, int(round(horizon * SERIES_START_FRACTION)))
    series_end = max(series_start, int(horizon) - SERIES_END_OFFSET)
    for key, group in groups.items():
        ordinals = [o for o in (_ordinal(task.get("title", "")) for task in group) if o is not None]
        if key and len(group) >= 2 and len(set(ordinals)) >= 2:
            ordered = sorted(group, key=lambda task: _ordinal(task.get("title", "")) or (0, ""))
            count = len(ordered)
            span = series_end - series_start
            for position, task in enumerate(ordered):
                week = series_start + (int(round(position * span / (count - 1))) if count > 1 and span > 0 else 0)
                week = max(series_start, min(series_end, week))
                windows[str(task.get("task_id", ""))] = (week, week)
        else:
            for task in group:
                windows[str(task.get("task_id", ""))] = (1, max(1, min(_weeks_needed(task), int(horizon))))
    return windows


def resolve_window(
    task: dict[str, Any],
    today: date,
    horizon: int,
    total_minutes: int | None = None,
) -> tuple[int, int]:
    """Single-task window: explicit/keyword rules, else a tight task-local window."""
    total = total_minutes if total_minutes is not None else _task_total(task)
    window = _window_from_task(task, today, horizon, total)
    if window is not None:
        return window
    return 1, max(1, min(_weeks_needed(task, total), int(horizon)))


def build_sessions(
    task: dict[str, Any],
    window: tuple[int, int],
    total_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """Split a task into study sessions (``<= SESSION_MAX_MINUTES`` each)."""
    if total_minutes is None:
        total_minutes = compute_study_minutes(task)
        if total_minutes <= 0:
            total_minutes = int(round(_to_float(task.get("estimated_minutes"))))
    total = int(total_minutes)
    if total <= 0:
        return []
    task_id = str(task.get("task_id", ""))
    if total <= SESSION_MAX_MINUTES:
        return [{"task_id": task_id, "minutes": total, "window": window}]
    count = max(1, ceil(total / SESSION_TARGET_MINUTES))
    base = total // count
    remainder = total - base * count
    sessions: list[dict[str, Any]] = []
    for index in range(count):
        minutes = base + (1 if index < remainder else 0)
        sessions.append({"task_id": task_id, "minutes": minutes, "window": window})
    return sessions


# ------------------- spread scheduling over a semester timeline -------------------

def _empty_week(index: int) -> dict[str, Any]:
    return {
        "week_index": index,
        "start_date": "",
        "end_date": "",
        "allocated_minutes": 0,
        "task_ids": [],
        "allocations": [],
    }


def _plan_items(
    tasks: list[dict[str, Any]],
    today: date,
    horizon: int,
) -> list[dict[str, Any]]:
    """Turn tasks into session items, expanding recurring tasks across their window."""
    items: list[dict[str, Any]] = []
    windows = plan_windows(tasks, today, horizon)
    for task in tasks:
        tid = str(task.get("task_id", ""))
        total = _task_total(task)
        if total <= 0:
            continue
        window = windows.get(tid) or resolve_window(task, today, horizon, total)
        occurrences = count_occurrences(task)
        if occurrences >= 2:
            per = max(1, int(round(total / occurrences)))
            start, end = window
            span = max(0, end - start)
            for index in range(occurrences):
                week = start + (int(round(index * span / (occurrences - 1))) if span > 0 else 0)
                week = max(start, min(end, week))
                items.extend(build_sessions(task, (week, week), per))
        else:
            items.extend(build_sessions(task, window, total))
    return items


def _place_item(
    item: dict[str, Any],
    weeks: list[dict[str, Any]],
    per_task_week: dict[tuple[str, int], int],
    capacity: int,
    horizon: int,
) -> None:
    """Place one session into the least-loaded week within its window."""
    task_id = item["task_id"]
    minutes = item["minutes"]
    start, end = item["window"]
    start = max(1, min(int(start), horizon))
    end = max(start, min(int(end), horizon))
    best_week = None
    best_score = None
    for week in range(start, end + 1):
        data = weeks[week - 1]
        if data["allocated_minutes"] + minutes > capacity:
            continue
        if per_task_week.get((task_id, week), 0) >= MAX_SESSIONS_PER_TASK_WEEK:
            continue
        score = (data["allocated_minutes"], week)  # least loaded, then earliest
        if best_score is None or score < best_score:
            best_score = score
            best_week = week
    if best_week is None:
        candidates = list(range(start, end + 1)) or [horizon]
        best_week = min(candidates, key=lambda w: weeks[w - 1]["allocated_minutes"])
    data = weeks[best_week - 1]
    data["allocated_minutes"] += minutes
    data["allocations"].append({"task_id": task_id, "minutes": minutes})
    per_task_week[(task_id, best_week)] = per_task_week.get((task_id, best_week), 0) + 1


def build_weekly_plan(
    tasks: list[dict[str, Any]],
    weekly_capacity: int = WEEKLY_CAPACITY_MINUTES,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Spread decomposed sessions across a semester timeline (week 1 = this week)."""
    if not tasks:
        return []
    if not isinstance(today, date):
        today = date.today()
    capacity = weekly_capacity if weekly_capacity and weekly_capacity > 0 else WEEKLY_CAPACITY_MINUTES
    horizon = max(DEFAULT_HORIZON_WEEKS, _max_due_week(tasks, today))
    anchor = _anchor_monday(today)
    weeks = [_empty_week(index + 1) for index in range(horizon)]
    per_task_week: dict[tuple[str, int], int] = {}
    for item in _plan_items(tasks, today, horizon):
        _place_item(item, weeks, per_task_week, capacity, horizon)
    result: list[dict[str, Any]] = []
    for week in weeks:
        start, end = _week_dates(anchor, week["week_index"])
        week["start_date"] = start.isoformat()
        week["end_date"] = end.isoformat()
        seen: set[str] = set()
        ids: list[str] = []
        for allocation in week["allocations"]:
            tid = allocation["task_id"]
            if tid not in seen:
                seen.add(tid)
                ids.append(tid)
        week["task_ids"] = ids
        result.append(week)
    return result


def _population_stddev(values: list[int]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round(variance ** 0.5, 2)


def compute_metrics(
    tasks: list[dict[str, Any]],
    weekly_capacity: int = WEEKLY_CAPACITY_MINUTES,
    today: date | None = None,
) -> dict[str, Any]:
    """Aggregate headline metrics, including how well load spreads over time."""
    if not isinstance(today, date):
        today = date.today()
    total_estimated = int(round(sum(_to_float(t.get("estimated_minutes")) for t in tasks)))
    total_weighted = int(sum(compute_study_minutes(t) for t in tasks))
    cognitive = compute_cognitive_load(tasks)
    clashes = detect_deadline_clashes(tasks, CLASH_THRESHOLD_DAYS)
    weekly_plan = build_weekly_plan(tasks, weekly_capacity, today)
    used = [week for week in weekly_plan if week["allocated_minutes"] > 0]
    peak = max((week["allocated_minutes"] for week in weekly_plan), default=0)
    weeks_span = len(used)
    avg_weekly = int(round(total_weighted / weeks_span)) if weeks_span else 0
    load_spread = _population_stddev([week["allocated_minutes"] for week in used])
    sessions_per_task: dict[str, int] = {}
    for week in weekly_plan:
        for allocation in week["allocations"]:
            tid = allocation["task_id"]
            sessions_per_task[tid] = sessions_per_task.get(tid, 0) + 1
    capacity = weekly_capacity if weekly_capacity and weekly_capacity > 0 else WEEKLY_CAPACITY_MINUTES
    cramming = peak > capacity
    burnout = compute_burnout_index(peak, cognitive, len(clashes))
    return {
        "task_count": len(tasks),
        "total_estimated_minutes": total_estimated,
        "total_weighted_minutes": total_weighted,
        "peak_weekly_minutes": peak,
        "avg_weekly_minutes": avg_weekly,
        "weeks_span": weeks_span,
        "load_spread": load_spread,
        "sessions_per_task": sessions_per_task,
        "cramming_flag": bool(cramming),
        "cognitive_load_index": cognitive,
        "burnout_index": burnout,
        "deadline_clashes": clashes,
    }

