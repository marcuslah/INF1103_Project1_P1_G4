"""io_manager.py — The ONLY module permitted to call print() / input().

Owners: Member 1:Marcus (Ingestion) & Member 2:Khant (Display).
Style: 100% procedural -- no ``class`` keyword anywhere.
"""

from __future__ import annotations

import logging
import os
import types
from datetime import datetime

_PYPDF_NOISE_TEXT = "Ignoring wrong pointing object"
_pypdf_log_filter_attached = False


def _attach_pypdf_log_filter() -> None:
    """Drop ONLY pypdf's benign 'Ignoring wrong pointing object' log records.

    pypdf emits these through ``logging.getLogger('pypdf._reader').warning(...)``
    for slightly malformed xref tables; they do not affect extraction.
    """
    global _pypdf_log_filter_attached
    if _pypdf_log_filter_attached:
        return

    def _keep(record: "logging.LogRecord") -> bool:
        try:
            return _PYPDF_NOISE_TEXT not in record.getMessage()
        except Exception:
            return True

    filterer = types.SimpleNamespace(filter=_keep)
    logging.getLogger("pypdf").addFilter(filterer)
    logging.getLogger("pypdf._reader").addFilter(filterer)
    _pypdf_log_filter_attached = True


MAIN_MENU_OPTIONS: tuple[tuple[str, str], ...] = (
    ("1", "View saved plans"),
    ("2", "Delete a plan"),
    ("3", "Search tasks by week"),
    ("4", "Search tasks by difficulty"),
    ("5", "Create new plan"),
    ("6", "Exit"),
)

PLAN_MENU_OPTIONS: tuple[tuple[str, str], ...] = (
    ("1", "View all tasks"),
    ("2", "View weekly schedule"),
    ("3", "View metrics"),
    ("4", "Edit task"),
    ("5", "Delete task"),
    ("6", "Back"),
)

BANNER_WIDTH: int = 60


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read(label: str) -> str:
    """Thin wrapper over input() that exits cleanly on EOF (non-interactive)."""
    try:
        return input(label)
    except EOFError:
        display_line("")
        raise SystemExit(0)


# --------------------------- Member:Khant and Marcus - Display ---------------------------

def display_line(text: str = "") -> None:
    print(text)


def banner(level: str, message: str) -> None:
    tag = str(level).strip().upper()
    if tag not in ("INFO", "WARN", "ERROR", "SUCCESS"):
        tag = "INFO"
    divider = "=" * BANNER_WIDTH
    print(divider)
    print(f"[{tag}] {message}")
    print(divider)


def render_table(headers: list[str], rows: list[list[str]], max_col_width: int = 30) -> str:
    """Render a plain-ASCII table as a string (caller decides how to display)."""
    header_cells = [str(h) for h in headers]
    column_count = len(header_cells)
    table_rows: list[list[str]] = []
    for row in rows:
        cells = ["" if cell is None else str(cell) for cell in row]
        if len(cells) < column_count:
            cells += [""] * (column_count - len(cells))
        table_rows.append(cells[:column_count])

    widths: list[int] = []
    for index in range(column_count):
        width = len(header_cells[index])
        for row in table_rows:
            width = max(width, len(row[index]))
        widths.append(min(width, max_col_width))

    def clip(text: str) -> str:
        if len(text) <= max_col_width:
            return text
        return text[: max(0, max_col_width - 3)] + "..."

    def render_row(cells: list[str]) -> str:
        padded = []
        for index, cell in enumerate(cells):
            padded.append(" " + clip(cell)[: widths[index]].ljust(widths[index]) + " ")
        return "|" + "|".join(padded) + "|"

    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [border, render_row(header_cells), border]
    for row in table_rows:
        lines.append(render_row(row))
    lines.append(border)
    return "\n".join(lines)


def render_task_table(tasks: list[dict]) -> str:
    rows = []
    for task in tasks:
        rows.append([
            task.get("task_id", ""),
            task.get("title", ""),
            task.get("deadline", ""),
            task.get("estimated_minutes", ""),
            str(task.get("difficulty", "")).capitalize(),
            str(task.get("priority", "")).capitalize(),
            str(task.get("category", "")).capitalize(),
            task.get("source_document", ""),
        ])
    return render_table(
        ["ID", "Task", "Deadline", "Est. (min)", "Difficulty", "Priority", "Category", "Source"],
        rows,
    )


def render_weekly_table(weekly_plan: list[dict]) -> str:
    rows = []
    for week in weekly_plan:
        rows.append([
            week.get("week_index", ""),
            week.get("start_date", ""),
            week.get("end_date", ""),
            week.get("allocated_minutes", ""),
            ", ".join(str(t) for t in week.get("task_ids", [])),
        ])
    return render_table(["Week", "Start", "End", "Est. (min)", "Tasks"], rows)


def render_metrics(metrics: dict) -> str:
    rows = [
        ["Tasks", metrics.get("task_count", 0)],
        ["Total estimated minutes", metrics.get("total_estimated_minutes", 0)],
        ["Total weighted minutes", metrics.get("total_weighted_minutes", 0)],
        ["Peak weekly minutes", metrics.get("peak_weekly_minutes", 0)],
        ["Cognitive load index", metrics.get("cognitive_load_index", 0)],
        ["Burnout index", metrics.get("burnout_index", 0)],
        ["Deadline clashes", len(metrics.get("deadline_clashes", []))],
    ]
    return render_table(["metric", "value"], rows)


def render_decisions(decisions: list[dict]) -> str:
    rows = []
    for decision in decisions:
        rows.append([
            decision.get("task_id", ""),
            decision.get("decision", ""),
            decision.get("rule_id", ""),
            decision.get("reason", ""),
        ])
    return render_table(["task_id", "decision", "rule", "reason"], rows)


def render_summary(plan_entry: dict) -> str:
    metrics = plan_entry.get("metrics", {})
    courses = ", ".join(plan_entry.get("courses", [])) or "(none)"
    lines = [
        f"Plan {plan_entry.get('plan_id', '?')} created {plan_entry.get('created_at', '?')}",
        f"Courses: {courses}",
        f"Tasks: {metrics.get('task_count', len(plan_entry.get('tasks', [])))}",
        f"Peak weekly hours: {metrics.get('weekly_hours', 0)}",
        f"Burnout index: {metrics.get('burnout_index', 0)}",
        f"Cognitive load index: {metrics.get('cognitive_load_index', 0)}",
    ]
    for note in plan_entry.get("notes", []):
        lines.append(f"- {note}")
    return "\n".join(lines)


def show_main_menu() -> str:
    divider = "=" * 40
    display_line("")
    display_line(divider)
    display_line("        StudyPilot (AI STUDY PLANNER)")
    display_line(divider)
    for key, label in MAIN_MENU_OPTIONS:
        display_line(f"{key}. {label}")
    display_line("")
    return _read("Select an option: ").strip().lower()


def show_plan_menu(plan_id: str) -> str:
    display_line("")
    display_line("========== PLAN ==========")
    display_line(f"Plan: {plan_id}")
    for key, label in PLAN_MENU_OPTIONS:
        display_line(f"{key}. {label}")
    display_line("")
    return _read("Select an option: ").strip().lower()


def render_plans_index(entries: list[dict]) -> str:
    """Render the numbered list of saved plans with headline counts/workload."""
    lines: list[str] = []
    for index, entry in enumerate(entries):
        metrics = entry.get("metrics", {}) if isinstance(entry, dict) else {}
        documents = entry.get("documents", []) if isinstance(entry, dict) else []
        hours = round(_to_float(metrics.get("total_weighted_minutes", 0)) / 60.0, 1)
        lines.append(f"{index + 1}. {entry.get('plan_id', '?')}")
        lines.append(f"   Documents: {len(documents)}")
        lines.append(f"   Tasks: {metrics.get('task_count', len(entry.get('tasks', [])))}")
        lines.append(f"   Weeks: {metrics.get('weeks_span', 0)}")
        lines.append(f"   Total workload: {hours} hours")
        lines.append("")
    lines.append("0. Back")
    return "\n".join(lines)


def render_week_view(week_index: int, week: dict, tasks: list[dict]) -> str:
    """Render the tasks scheduled in a given week plus that week's total workload."""
    lines = [f"========== WEEK {week_index} ==========", ""]
    if not tasks:
        lines.append("(no tasks scheduled this week)")
        lines.append("")
    for index, task in enumerate(tasks):
        lines.append(f"{index + 1}. {task.get('source_document', '?')} - {task.get('title', '')}")
        lines.append(f"   Difficulty: {str(task.get('difficulty', '')).capitalize()}")
        lines.append(f"   Estimated: {task.get('estimated_minutes', 0)} min")
        if task.get("deadline"):
            lines.append(f"   Deadline: {task.get('deadline')}")
        lines.append("")
    minutes = int(week.get("allocated_minutes", 0)) if isinstance(week, dict) else 0
    lines.append(f"Total workload: {round(minutes / 60.0, 1)} hours")
    return "\n".join(lines)


def render_difficulty_view(difficulty: str, tasks: list[dict], weeks_by_task: dict) -> str:
    """Render all tasks of a given difficulty with their week(s) and workload total."""
    lines = [f"========== DIFFICULTY: {str(difficulty).upper()} ==========", ""]
    total_minutes = 0
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id", ""))
        weeks = weeks_by_task.get(task_id, [])
        week_text = ",".join(str(week) for week in weeks) if weeks else "-"
        estimated = int(task.get("estimated_minutes", 0) or 0)
        total_minutes += estimated
        lines.append(f"{index + 1}. Week: {week_text} | {task.get('source_document', '?')} - {task.get('title', '')}")
        lines.append(f"   Estimated: {estimated} min")
        lines.append("")
    lines.append(f"Matching tasks: {len(tasks)}")
    lines.append(f"Total workload: {round(total_minutes / 60.0, 1)} hours")
    return "\n".join(lines)


def render_task_index(tasks: list[dict]) -> str:
    """Render a numbered list of tasks for selection."""
    lines: list[str] = []
    for index, task in enumerate(tasks):
        lines.append(
            f"{index + 1}. {task.get('task_id', '?')} | {task.get('title', '')} "
            f"({str(task.get('difficulty', '?')).capitalize()}, {task.get('estimated_minutes', 0)} min)"
        )
    lines.append("0. Back")
    return "\n".join(lines)


def prompt_index(label: str, count: int, allow_zero: bool = True) -> int:
    """Prompt for a selection in ``low..count`` (``0..count`` when allow_zero). Returns the int."""
    low = 0 if allow_zero else 1
    while True:
        raw = _read(f"{label}: ").strip()
        try:
            value = int(raw)
        except ValueError:
            display_line("  ! Please enter a number.")
            continue
        if low <= value <= count:
            return value
        display_line(f"  ! Enter a number between {low} and {count}.")


def confirm(prompt: str) -> bool:
    while True:
        answer = _read(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        display_line("  ! Please answer y or n.")

#---------------------------Member: Marcus insertion -----------------------------#

def prompt_line(label: str, allow_empty: bool = False) -> str:
    while True:
        value = _read(f"{label}: ").strip()
        if value or allow_empty:
            return value
        display_line("  ! Input cannot be empty.")


def prompt_float(label: str, minimum: float = 0.0, maximum: float = 1000.0) -> float:
    while True:
        raw = _read(f"{label}: ").strip()
        try:
            value = float(raw)
        except ValueError:
            display_line("  ! Please enter a number.")
            continue
        if minimum <= value <= maximum:
            return value
        display_line(f"  ! Value must be between {minimum} and {maximum}.")


def prompt_int(label: str, minimum: int = 0, maximum: int = 100) -> int:
    while True:
        raw = _read(f"{label}: ").strip()
        try:
            value = int(raw)
        except ValueError:
            display_line("  ! Please enter a whole number.")
            continue
        if minimum <= value <= maximum:
            return value
        display_line(f"  ! Value must be between {minimum} and {maximum}.")


def prompt_date(label: str, fmt: str = "%Y-%m-%d") -> str:
    while True:
        raw = _read(f"{label} ({fmt}): ").strip()
        try:
            datetime.strptime(raw, fmt)
            return raw
        except ValueError:
            display_line(f"  ! Invalid date, expected {fmt}.")


def prompt_choice(label: str, choices: list[str]) -> str:
    display_line(f"{label} [{'/'.join(choices)}]")
    lowered = [choice.lower() for choice in choices]
    while True:
        raw = _read("> ").strip().lower()
        if raw in lowered:
            return raw
        display_line("  ! Choose one of: " + ", ".join(choices))


def prompt_yes_no(label: str) -> bool:
    return confirm(label)


def extract_pdf_text(path: str) -> tuple[str | None, str | None]:
    """Extract text from a PDF using pypdf. Returns ``(text, error)``. Never raises."""
    if not path:
        return None, "no path provided"
    if not os.path.exists(path):
        return None, f"file not found: {path}"
    try:
        from pypdf import PdfReader  # lazy import keeps non-PDF use dependency-free
    except ImportError:
        return None, "PDF support requires the 'pypdf' package (pip install pypdf)"
    _attach_pypdf_log_filter()
    try:
        reader = PdfReader(path)
    except Exception as exc:  # malformed / unreadable PDF
        return None, f"could not open PDF {path}: {exc}"
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            return None, f"{path}: PDF is encrypted and could not be opened"
        if getattr(reader, "is_encrypted", False):
            return None, f"{path}: PDF is encrypted and requires a password"
    try:
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        joined = "\n".join(parts).strip()
    except Exception as exc:  # extraction failure on a page
        return None, f"could not extract text from {path}: {exc}"
    if not joined:
        return None, f"{path}: no extractable text (image-only PDF? OCR is not supported)"
    return joined, None


def read_syllabus_file(path: str) -> tuple[str | None, str | None]:
    """Read a document as text (.pdf is extracted, others read as UTF-8). Returns ``(text, error)``."""
    if not path:
        return None, "no path provided"
    if not os.path.exists(path):
        return None, f"file not found: {path}"
    if path.lower().endswith(".pdf"):
        return extract_pdf_text(path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(), None
    except UnicodeDecodeError:
        return None, f"{path}: not UTF-8 text (binary file?)"
    except OSError as exc:
        return None, f"could not read {path}: {exc}"


def discover_syllabi(inputs_dir: str = "inputs") -> list[str]:
    """Return candidate document files inside ``inputs_dir``."""
    if not inputs_dir or not os.path.isdir(inputs_dir):
        return []
    found = []
    for name in sorted(os.listdir(inputs_dir)):
        if name.lower().endswith((".json", ".txt", ".md", ".pdf")):
            found.append(os.path.join(inputs_dir, name))
    return found


def _is_valid_date(value: str, fmt: str = "%Y-%m-%d") -> bool:
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False


def ingest_interactive_tasks(source_name: str) -> list[dict]:
    """Prompt the user for study tasks until they leave the title blank."""
    display_line(f"Entering tasks for {source_name}. Leave the title blank to finish.")
    tasks: list[dict] = []
    counter = 1
    while True:
        title = prompt_line("Task title (blank to finish)", allow_empty=True)
        if not title:
            break
        description = prompt_line("Description", allow_empty=True)
        category = prompt_choice(
            "Category",
            ["assignment", "exam", "tutorial", "lab", "project", "reading", "revision", "other"],
        )
        deadline = prompt_line("Deadline YYYY-MM-DD (blank = none)", allow_empty=True)
        while deadline and not _is_valid_date(deadline):
            display_line("  ! Invalid date, expected YYYY-MM-DD.")
            deadline = prompt_line("Deadline YYYY-MM-DD (blank = none)", allow_empty=True)
        minutes = prompt_int("Estimated minutes", 0, 100000)
        difficulty = prompt_choice("Difficulty", ["easy", "medium", "hard"])
        priority = prompt_choice("Priority", ["low", "medium", "high"])
        tasks.append({
            "task_id": f"manual-{counter}",
            "title": title,
            "description": description,
            "category": category,
            "deadline": deadline,
            "estimated_minutes": minutes,
            "difficulty": difficulty,
            "priority": priority,
            "dependencies": [],
            "source_document": source_name,
            "source_type": "manual",
            "confidence": 1.0,
        })
        counter += 1
    return tasks


def render_document_index(paths: list[str]) -> str:
    """Render a numbered list of selectable documents (basename shown)."""
    lines: list[str] = []
    for index, path in enumerate(paths):
        lines.append(f"{index + 1}. {os.path.basename(path)}")
    lines.append("")
    lines.append("Tip: enter numbers like 1,3 or a range like 1-3; type 'all' or leave blank for every document; 0 cancels.")
    return "\n".join(lines)


def prompt_indices(label: str, count: int) -> list[int]:
    """Prompt for one or more selections in ``1..count``.

    Accepts comma/space separated numbers and ranges (e.g. ``1-3``);
    ``all`` (or blank) selects everything; ``0`` cancels. Returns a sorted,
    de-duplicated list of 1-based indices (empty list when cancelled).
    """
    while True:
        raw = _read(f"{label}: ").strip().lower()
        if raw in ("", "all", "a"):
            return list(range(1, count + 1))
        if raw == "0":
            return []
        picked: set[int] = set()
        valid = True
        for token in raw.replace(",", " ").split():
            if "-" in token:
                low_text, _, high_text = token.partition("-")
                if not (low_text.isdigit() and high_text.isdigit()):
                    valid = False
                    break
                low, high = int(low_text), int(high_text)
                if low < 1 or high > count or low > high:
                    valid = False
                    break
                picked.update(range(low, high + 1))
            elif token.isdigit():
                value = int(token)
                if value < 1 or value > count:
                    valid = False
                    break
                picked.add(value)
            else:
                valid = False
                break
        if valid and picked:
            return sorted(picked)
        display_line(f"  ! Enter numbers between 1 and {count}, a range like 1-3, or 'all'.")