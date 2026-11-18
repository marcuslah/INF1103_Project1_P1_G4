# StudyPilot — AI Academic Workload Planner

StudyPilot reads academic documents (syllabuses, lab sheets, tutorial sheets),
uses an AI model to extract the study tasks in them, applies planning rules,
and saves a week-by-week study plan.

Phase 2 of the INF1103 team project: the Phase 1 procedural application has been
refactored into an object-oriented system.

------------------------------------------------------------------------

## Quick start with Docker

Docker is the recommended way to run the project. Nothing needs to be installed
on your machine except Docker Desktop.

### 1. Clone the repository

```powershell
git clone https://github.com/marcuslah/INF1103_Project1_P1_G4.git
cd INF1103_Project1_P1_G4
```

### 2. Create your `.env` file

Copy `.env.example` to `.env` and add your Gemini API key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

**Never commit or share `.env`.** It is listed in `.gitignore`.

### 3. Build the image

```powershell
docker build -t studypilot .
```

### 4. Run the automated tests

The tests need no API key and no internet connection.

```powershell
docker run --rm studypilot python -m pytest -q
```

### 5. Run the application

Put your documents in the `inputs/` folder, then start the interactive menu:

```powershell
docker run --rm -it `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  studypilot
```

To process every document in `inputs/` without the menu:

```powershell
docker run --rm `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  studypilot python main.py --inputs inputs/
```

The `inputs/` mount gives the container your documents. The `data/` mount keeps
saved plans on your computer after the container exits.

> These multi-line commands use PowerShell syntax. In Command Prompt use `^`
> instead of the backtick; in macOS/Linux use `\` and `$(pwd)` instead of `${PWD}`.

------------------------------------------------------------------------

## Run directly with Python

Requires Python 3.11 or newer.

```bash
python -m pip install -r requirements.txt
python -m pytest -q                      # run the tests
python main.py                           # interactive menu
python main.py --inputs inputs/          # process a folder
python main.py --file inputs/week3.pdf   # process one file (repeatable)
```

------------------------------------------------------------------------

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes, for AI features | none | Key for the Gemini API |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | AI model name |
| `REQUEST_TIMEOUT` | No | `30` | Seconds to wait for the AI before timing out |
| `STUDY_WEEKLY_CAPACITY` | No | `20` | Weekly study limit in hours |
| `STORAGE_BACKEND` | No | `json` | `json` or `sqlite` (see Advanced feature) |
| `PLAN_PATH` | No | `data/study_plans.json` | JSON storage file |
| `PLAN_DB_PATH` | No | `data/study_plans.db` | SQLite database file |

Without an API key the application still starts. Document extraction reports a
clear error, and manually entered tasks are kept with a warning that the AI
review was unavailable.

------------------------------------------------------------------------

## Main menu

```
1. View saved plans
2. Delete a plan
3. Search tasks by week
4. Search tasks by difficulty
5. Create new plan
6. Workload summary
7. Exit
```

Supported input files: `.pdf`, `.txt`, `.md`, `.json`. Image-only (scanned) PDFs
are not supported because there is no OCR.

------------------------------------------------------------------------

## Architecture

`main.py` holds `StudyPilotApp`, which coordinates four managers. Managers pass
objects (`Task`, `StudyPlan`) to each other; only the Data Manager converts
them to dictionaries for storage.

```text
User input -> IO Manager -> AI Manager -> Logic Manager -> Data Manager -> IO Manager (display)
```

| Manager | Main class | Files | Responsibility |
|---|---|---|---|
| IO | `IOManager` | `io_manager.py`, `io_console.py`, `io_renderer.py`, `document_reader.py` | All input, output and document reading |
| AI | `AIManager` | `ai_manager.py`, `ai_client.py`, `ai_prompts.py`, `ai_parser.py`, `ai_config.py`, `ai_errors.py` | Build prompts, call the API, parse and validate the reply |
| Logic | `LogicManager` | `logic_manager.py`, `logic_rules.py`, `logic_metrics.py`, `logic_scheduler.py`, `logic_queries.py`, `logic_summary.py`, `logic_config.py` | Business rules R1-R7, metrics, weekly schedule |
| Data | `DataManager` | `data_manager.py`, `repository.py`, `json_repository.py`, `sqlite_repository.py` | Save, load and query plans |

Shared domain classes (`Task`, `StudyPlan`, `Decision`, `WeekSchedule`,
`PlanAnalysis`) are in `models.py`.

**Every record passes through the AI Manager.** Free-text documents are sent for
task extraction. JSON task files and manually typed tasks are sent for AI review,
which can correct difficulty and priority and fill in a missing time estimate.

### Business rules

The first rule that applies decides the task.

| Rule | Condition | Decision |
|---|---|---|
| R1 | Category is reading, priority is low, and the week would exceed capacity | REJECT |
| R2 | Priority is low and the task takes under 20 minutes | REJECT |
| R3 | Exam or project due within 7 days | FLAG |
| R4 | Burnout index is 80 or more | FLAG |
| R5 | Deadline is within 2 days of another task's deadline | FLAG |
| R6 | One task needs more than 720 minutes | FLAG |
| R7 | None of the above | ACCEPT |

------------------------------------------------------------------------

## New feature: workload summary

Menu option 6 shows one summary across **all** saved plans: total workload,
minutes per category, tasks per difficulty, the busiest calendar weeks, how many
tasks were accepted, flagged and rejected, and a list of every flagged task.

Classes: `PlanSummaryReport` (`logic_summary.py`), `TableRenderer.summary`
(`io_renderer.py`), `StudyPilotApp._show_summary` (`main.py`).
Tests: `test_summary.py`, plus summary tests in `test_io_manager.py` and `test_app.py`.

## Advanced feature: database integration

Plans can be stored in a SQLite database instead of the JSON file, with full
create, read, update and delete. Set this in `.env`:

```env
STORAGE_BACKEND=sqlite
```

`SqlitePlanRepository` and `JsonPlanRepository` both implement the
`PlanRepository` interface, so the rest of the application does not change.
SQLite is part of Python's standard library, so Docker needs no extra setup.
The database file is created in `data/`, which is kept by the `data/` volume mount.

Tests: `test_sqlite_repository.py`, and the shared storage tests in
`test_data_manager.py` run against both backends.

------------------------------------------------------------------------

## Testing

```bash
python -m pytest -q
```

| Test file | Covers |
|---|---|
| `test_models.py` | `Task`, `StudyPlan`, `Decision`, `WeekSchedule` |
| `test_ai_manager.py` | AI pipeline with a fake client: malformed replies, bad schema, timeouts, retries |
| `test_logic.py` | Rules R1-R7 with hardcoded sample AI output, the pipeline, edits, queries |
| `test_logic_planning.py` | Metrics, timeline hints, session splitting, weekly schedule |
| `test_summary.py` | New feature: workload summary |
| `test_data_manager.py` | Storage interface on JSON and SQLite, missing and corrupt files |
| `test_sqlite_repository.py` | Advanced feature: database storage |
| `test_io_manager.py` | Input validation, tables, menus |
| `test_document_reader.py` | Reading text and PDF files, missing and unreadable files |
| `test_app.py` | The whole application end to end with a fake keyboard and fake AI |

No test contacts the live API.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. It installs the
dependencies, runs the test suite, builds the Docker image, and runs the test
suite again inside the container. Results are on the repository's **Actions** tab.

------------------------------------------------------------------------

## Persistence

By default plans are stored in `data/study_plans.json`. A missing file starts an
empty store. A corrupt file is copied to `data/study_plans.corrupt.<timestamp>.json`
and the application starts with an empty store rather than crashing.
