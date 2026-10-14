"""main.py — Orchestration for the AI Academic Workload Planner.
24 functions
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import date

import ai_manager
import data_manager
import io_manager
import logic_manager

DEFAULT_INPUTS_DIR = "inputs"

EDIT_FIELD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("title", "Task name"),
    ("difficulty", "Difficulty"),
    ("estimated_minutes", "Estimated time"),
    ("deadline", "Deadline"),
)
EDIT_FIELD_LABELS: dict[str, str] = dict(EDIT_FIELD_OPTIONS)


# Read the weekly study-hour limit from the environment and convert it to minutes.
# If the setting is missing or invalid, use the default from logic_manager.
def _weekly_capacity_minutes() -> int:
    raw = os.getenv("STUDY_WEEKLY_CAPACITY", str(logic_manager.WEEKLY_CAPACITY_HOURS))
    try:
        hours = float(raw)
    except ValueError:
        return logic_manager.WEEKLY_CAPACITY_MINUTES
    return int(round(hours * 60)) if hours > 0 else logic_manager.WEEKLY_CAPACITY_MINUTES


# Create a short, unique ID so each saved study plan can be identified.
def _new_plan_id() -> str:
    return "plan-" + uuid.uuid4().hex[:10]

# Prepare the weekly capacity and current date that logic_manager needs.
# Supplied constraints override the normal defaults, which also helps with testing.
def build_context(constraints: dict | None = None) -> dict:
    """Assemble the constraints/context passed into logic_manager."""
    constraints = constraints or {}
    capacity = int(constraints.get("weekly_capacity_minutes", _weekly_capacity_minutes()))
    today = constraints.get("today", date.today())
    return {"weekly_capacity_minutes": capacity, "today": today}

# Read an input file and turn it into a consistent list of tasks.
# Use existing JSON tasks directly; otherwise ask ai_manager to extract them.
def load_or_extract(path: str) -> tuple[list[dict], list[str]]:
    """Ingest one document: structured JSON is used directly, otherwise call the AI."""
    source_name = os.path.basename(path) or path
    text, error = io_manager.read_syllabus_file(path)
    if error is not None:
        return [], [f"{path}: {error}"]
    parsed, _parse_error = data_manager.parse_json_safe(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("tasks"), list):
        source = str(parsed.get("course_code") or parsed.get("source_document") or source_name)
        return ai_manager.normalize_tasks(parsed["tasks"], source, source="json"), []
    result = ai_manager.extract_tasks(text, source_name)
    if result.get("status") != "ok":
        code = result.get("error_code", "error")
        message = result.get("message", "unknown error")
        return [], [f"{path}: AI extraction failed ({code}: {message})"]
    return result.get("tasks", []), []

# Package analyzed tasks, schedule, metrics and metadata into one record.
# data_manager can then store the complete study plan.
def _build_plan_entry(result: dict, tasks: list[dict]) -> dict:
    documents = sorted({str(task.get("source_document", "UNKNOWN")) for task in tasks})
    return {
        "plan_id": _new_plan_id(),
        "created_at": data_manager.now_iso(),
        "semester": "unspecified",
        "documents": documents,
        "tasks": tasks,
        "weekly_plan": result.get("weekly_plan", []),
        "metrics": result.get("metrics", {}),
        "decisions": result.get("decisions", []),
        "notes": result.get("notes", []),
    }


# Pass the collected tasks to logic_manager, show the results using io_manager,
# and save the finished plan through data_manager.
def analyze_and_persist(tasks: list[dict], warnings: list[str] | None = None) -> int:
    """Run the logic engine, display the results, and persist the plan."""
    warnings = list(warnings or [])
    if not tasks:
        io_manager.banner("WARN", "No tasks to analyze.")
        for note in warnings:
            io_manager.banner("WARN", note)
        return 1

    result = logic_manager.run_logic(tasks, build_context())
    entry = _build_plan_entry(result, result.get("tasks", tasks))

    io_manager.display_line(io_manager.render_task_table(tasks))
    io_manager.display_line(io_manager.render_metrics(result.get("metrics", {})))
    io_manager.display_line(io_manager.render_decisions(result.get("decisions", [])))
    io_manager.display_line(io_manager.render_weekly_table(result.get("weekly_plan", [])))

    plan = data_manager.load_plans()
    saved, error = data_manager.append_plan_entry(plan, entry)
    if saved:
        io_manager.banner("SUCCESS", f"Plan saved to {data_manager.DEFAULT_PLAN_PATH}")
    else:
        io_manager.banner("ERROR", f"Could not save plan: {error}")
    for note in warnings:
        io_manager.banner("WARN", note)
    return 0 if saved else 1


# Collect tasks from selected files and optionally from manual user input.
# Keep any file-reading or AI-extraction warnings for later display.
def ingest_phase(paths: list[str], interactive: bool) -> tuple[list[dict], list[str]]:
    """Collect tasks from files and (optionally) manual prompts."""
    tasks: list[dict] = []
    warnings: list[str] = []
    for path in paths:
        found, problems = load_or_extract(path)
        tasks.extend(found)
        warnings.extend(problems)
    if interactive:
        source = io_manager.prompt_line("Source label for manual tasks", allow_empty=True) or "MANUAL"
        tasks.extend(io_manager.ingest_interactive_tasks(source))
    return tasks, warnings

# Coordinate the non-menu workflow: discover input files, collect tasks,
# analyze them and save the resulting study plan.
def run_pipeline(args: dict) -> int:
    """Non-interactive pipeline: ingest -> analyze -> persist."""
    paths: list[str] = []
    for path in args.get("files") or []:
        if path:
            paths.append(path)
    if args.get("inputs"):
        paths.extend(io_manager.discover_syllabi(args["inputs"]))
    if not paths and not args.get("interactive"):
        paths.extend(io_manager.discover_syllabi(DEFAULT_INPUTS_DIR))
        if not paths:
            io_manager.banner("WARN", "No documents found. Provide --file, --inputs or --interactive.")
            return 1
    tasks, warnings = ingest_phase(paths, bool(args.get("interactive")))
    return analyze_and_persist(tasks, warnings)


# --------------------------- interactive flows ---------------------------

# Save edits to an existing plan and inform the user whether saving worked.
def _persist_entry(plan: dict, entry: dict) -> None:
    """Replace and save a plan entry, reporting the outcome."""
    if data_manager.update_plan_entry(plan, entry):
        saved, error = data_manager.save_plans(plan)
        if saved:
            io_manager.banner("SUCCESS", f"Plan updated: {entry.get('plan_id')}")
        else:
            io_manager.banner("ERROR", f"Could not save plan: {error}")
    else:
        io_manager.banner("ERROR", "Plan not found; nothing saved.")

# List existing plans and let the user choose one, or return to the menu.
def _select_plan(plan: dict) -> dict | None:
    """Show saved plans and prompt for one. Returns the entry, or None (back/empty)."""
    entries = data_manager.list_plan_entries(plan)
    if not entries:
        io_manager.banner("WARN", "No saved plans yet.")
        return None
    io_manager.display_line(io_manager.render_plans_index(entries))
    choice = io_manager.prompt_index("Select a plan (0 to go back)", len(entries))
    if choice == 0:
        return None
    return entries[choice - 1]


# Find the selected task, validate the new value through logic_manager,
# then recalculate the plan so its schedule and metrics stay consistent.
def apply_task_edit(
    entry: dict,
    task_id: str,
    field: str,
    value,
    constraints: dict | None = None,
) -> tuple[bool, str]:
    """Validate, apply, and recompute a plan entry after a task field edit."""
    task = data_manager.find_task(entry, task_id)
    if task is None:
        return False, f"task not found: {task_id}"
    ok, normalized, error = logic_manager.validate_task_edit(field, value)
    if not ok:
        return False, error or "invalid value"
    task[str(field).strip().lower()] = normalized
    logic_manager.recalculate_plan_entry(entry, constraints or build_context())
    label = EDIT_FIELD_LABELS.get(str(field).strip().lower(), field)
    return True, f"Updated {label} on task {task_id}."


# Remove a task by ID and recalculate the plan after the deletion.
# Return a message if the task or task list cannot be found.
def remove_task(entry: dict, task_id: str, constraints: dict | None = None) -> tuple[bool, str]:
    """Remove a task from a plan entry and recompute the schedule/metrics/decisions."""
    tasks = entry.get("tasks", [])
    if not isinstance(tasks, list):
        return False, "plan has no tasks"
    target = str(task_id)
    kept = [task for task in tasks if str(task.get("task_id", "")) != target]
    if len(kept) == len(tasks):
        return False, f"task not found: {task_id}"
    entry["tasks"] = kept
    logic_manager.recalculate_plan_entry(entry, constraints or build_context())
    return True, f"Deleted task {task_id}."


# Display the tasks in one plan and ask the user which task to work on.
def _pick_task_id(entry: dict) -> str | None:
    tasks = entry.get("tasks", [])
    if not tasks:
        io_manager.banner("WARN", "This plan has no tasks.")
        return None
    io_manager.display_line(io_manager.render_task_index(tasks))
    choice = io_manager.prompt_index("Select a task (0 to go back)", len(tasks))
    if choice == 0:
        return None
    return str(tasks[choice - 1].get("task_id", ""))

# Guide the user through choosing a task and editing one of its fields.
# Save the plan only after the edit passes validation.
def _edit_task_flow(plan: dict, entry: dict) -> None:
    task_id = _pick_task_id(entry)
    if task_id is None:
        return
    io_manager.display_line("")
    io_manager.display_line("What would you like to edit?")
    for index, (_, label) in enumerate(EDIT_FIELD_OPTIONS, start=1):
        io_manager.display_line(f"{index}. {label}")
    io_manager.display_line("0. Back")
    choice = io_manager.prompt_index("Select an option", len(EDIT_FIELD_OPTIONS))
    if choice == 0:
        return
    field = EDIT_FIELD_OPTIONS[choice - 1][0]
    if field == "difficulty":
        value = io_manager.prompt_choice("New difficulty", ["Easy", "Medium", "Hard"])
    elif field == "estimated_minutes":
        task = data_manager.find_task(entry, task_id)
        current = int(task.get("estimated_minutes", 0) or 0) if task else 0
        io_manager.display_line(f"Current estimated time: {current} minutes")
        value = io_manager.prompt_int("New estimated time in minutes", 1, 100000)
    elif field == "deadline":
        value = io_manager.prompt_line("New deadline YYYY-MM-DD (blank = none)", allow_empty=True)
    else:
        value = io_manager.prompt_line("New task name")
    ok, message = apply_task_edit(entry, task_id, field, value)
    if ok:
        _persist_entry(plan, entry)
    io_manager.banner("INFO" if ok else "ERROR", message)

# Ask for confirmation before removing a task from a saved plan.
# Recalculate and persist changes only when deletion succeeds.
def _delete_task_flow(plan: dict, entry: dict) -> None:
    task_id = _pick_task_id(entry)
    if task_id is None:
        return
    if not io_manager.confirm(f"Delete task {task_id}?"):
        io_manager.display_line("Cancelled.")
        return
    ok, message = remove_task(entry, task_id)
    if ok:
        _persist_entry(plan, entry)
    io_manager.banner("INFO" if ok else "ERROR", message)

# Display the submenu for one plan, including viewing, editing and deleting tasks.
def _plan_menu_flow(plan: dict, entry: dict) -> None:
    """Submenu for a single selected plan."""
    while True:
        choice = io_manager.show_plan_menu(str(entry.get("plan_id", "?")))
        if choice == "1":
            io_manager.display_line(io_manager.render_task_table(entry.get("tasks", [])))
        elif choice == "2":
            io_manager.display_line(io_manager.render_weekly_table(entry.get("weekly_plan", [])))
        elif choice == "3":
            io_manager.display_line(io_manager.render_metrics(entry.get("metrics", {})))
        elif choice == "4":
            _edit_task_flow(plan, entry)
        elif choice == "5":
            _delete_task_flow(plan, entry)
        elif choice == "6":
            return
        else:
            io_manager.banner("WARN", "Unknown option.")

# Let the user select a saved plan, then open its submenu.
def _view_plans_flow(plan: dict) -> None:
    entry = _select_plan(plan)
    if entry is None:
        return
    _plan_menu_flow(plan, entry)

# Select a whole plan, confirm the deletion, and save the updated storage.
def _delete_plan_flow(plan: dict) -> None:
    entry = _select_plan(plan)
    if entry is None:
        return
    plan_id = str(entry.get("plan_id", "?"))
    if not io_manager.confirm(f"Delete plan {plan_id}?"):
        io_manager.display_line("Cancelled.")
        return
    if data_manager.delete_plan_entry(plan, plan_id):
        saved, error = data_manager.save_plans(plan)
        if saved:
            io_manager.banner("SUCCESS", f"Deleted plan {plan_id}.")
        else:
            io_manager.banner("ERROR", f"Could not save changes: {error}")
    else:
        io_manager.banner("ERROR", "Plan not found.")

# Show tasks scheduled for a chosen week using logic_manager filtering.
def _search_week_flow(plan: dict) -> None:
    entry = _select_plan(plan)
    if entry is None:
        return
    week = io_manager.prompt_int("Week number", 1, 1000)
    weekly_plan = entry.get("weekly_plan", [])
    tasks = logic_manager.filter_tasks_by_week(entry.get("tasks", []), weekly_plan, week)
    week_entry = next((w for w in weekly_plan if int(w.get("week_index", -1)) == week), {})
    io_manager.display_line(io_manager.render_week_view(week, week_entry, tasks))

# Find tasks of the requested difficulty and display their scheduled weeks.
def _search_difficulty_flow(plan: dict) -> None:
    entry = _select_plan(plan)
    if entry is None:
        return
    difficulty = io_manager.prompt_choice("Difficulty", ["Easy", "Medium", "Hard"])
    tasks = logic_manager.filter_tasks_by_difficulty(entry.get("tasks", []), difficulty)
    weeks_by_task = logic_manager.task_week_map(entry.get("weekly_plan", []))
    io_manager.display_line(io_manager.render_difficulty_view(difficulty, tasks, weeks_by_task))

# List documents in the inputs folder and let the user select which to analyze.
def _create_plan_from_inputs() -> None:
    """Discover documents in inputs/, let the user pick one or more, and plan only those."""
    paths = io_manager.discover_syllabi(DEFAULT_INPUTS_DIR)
    if not paths:
        io_manager.banner("WARN", f"No documents found in {DEFAULT_INPUTS_DIR}/.")
        return
    io_manager.display_line("")
    io_manager.display_line(f"Documents available in {DEFAULT_INPUTS_DIR}/:")
    io_manager.display_line(io_manager.render_document_index(paths))
    chosen = io_manager.prompt_indices("Select documents", len(paths))
    if not chosen:
        io_manager.display_line("Cancelled.")
        return
    selected = [paths[index - 1] for index in chosen]
    run_pipeline({"files": selected})

# Offer three ways to create a plan: chosen documents, a file path,
# or tasks entered manually.
def _create_plan_flow() -> None:
    """Create a new independent plan, reusing the existing ingestion pipeline."""
    io_manager.display_line("")
    io_manager.display_line("Create plan from:")
    io_manager.display_line("1. Select documents from inputs/")
    io_manager.display_line("2. A specific file")
    io_manager.display_line("3. Enter tasks manually")
    io_manager.display_line("0. Back")
    choice = io_manager.prompt_index("Select an option", 3)
    if choice == 0:
        return
    if choice == 1:
        _create_plan_from_inputs()
    elif choice == 2:
        path = io_manager.prompt_line("Document file path")
        run_pipeline({"files": [path]})
    else:
        source = io_manager.prompt_line("Source label", allow_empty=True) or "MANUAL"
        tasks = io_manager.ingest_interactive_tasks(source)
        analyze_and_persist(tasks)

# Keep showing the main CLI menu until the user exits.
# Route each choice to the relevant plan-management workflow.
def interactive_menu() -> int:
    """Interactive main menu shown when no CLI arguments are supplied."""
    while True:
        choice = io_manager.show_main_menu()
        if choice in ("6", "q", "quit", "exit"):
            io_manager.display_line("Goodbye.")
            return 0
        plan = data_manager.load_plans()
        if choice == "1":
            _view_plans_flow(plan)
        elif choice == "2":
            _delete_plan_flow(plan)
        elif choice == "3":
            _search_week_flow(plan)
        elif choice == "4":
            _search_difficulty_flow(plan)
        elif choice == "5":
            _create_plan_flow()
        else:
            io_manager.banner("WARN", "Unknown option.")

# Parse command-line options and choose between interactive menu mode
# and processing files directly; return an exit status for the program.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="study-planner", description="AI Academic Workload Planner")
    parser.add_argument("--file", action="append", default=[], help="path to a document (repeatable)")
    parser.add_argument("--inputs", help="folder containing documents")
    parser.add_argument("--interactive", action="store_true", help="launch the interactive application menu")
    parsed = parser.parse_args(argv)
    if parsed.interactive:
        return interactive_menu()
    if parsed.file or parsed.inputs:
        return run_pipeline({"files": parsed.file, "inputs": parsed.inputs, "interactive": False})
    return interactive_menu()


if __name__ == "__main__":
    raise SystemExit(main())