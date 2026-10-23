# StudyPilot AI Academic Workload Planner

An AI-powered academic workload planner that extracts study tasks from
syllabus and course documents, estimates workload, applies planning
logic, and saves a weekly study plan.

------------------------------------------------------------------------

## Quick Start --- Docker

Docker is the recommended way to run the project because it provides the
required Python environment and dependencies inside a container.

### 1. Clone the repository

Open PowerShell or a terminal and clone the **main submission
repository**:

``` powershell
git clone https://github.com/marcuslah/INF1103_Project1_P1_G4.git
cd INF1103_Project1_P1_G4
```

Run `dir` in PowerShell (or `ls` in macOS/Linux) to check that you are
in the project root containing `Dockerfile`, `requirements.txt`, and
`main.py`.

### 2. Install and start Docker

Install Docker Desktop and make sure it is running before continuing.

### 3. Create your `.env` file

Copy `.env.example` and name the copy `.env`. Add your OpenRouter API
key:

``` env
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

**Never commit or share `.env`.** It contains your private API key. Keep
the actual key out of source code and Git.

### 4. Add your documents

Place academic documents in the `inputs/` folder.

Supported formats:

-   PDF
-   TXT
-   MD
-   JSON

### 5. Build the Docker image

Run this from the project root:

``` powershell
docker build -t workload-planner .
```

### 6. Run the planner

#### Option A --- Interactive mode (recommended when choosing documents)

``` powershell
docker run --rm -it `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  workload-planner --interactive
```

The interactive menu lets you manage saved plans and choose which
documents to process when creating a new plan.

#### Option B --- Process all supported documents in `inputs/`

``` powershell
docker run --rm `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  workload-planner --inputs inputs/
```

This processes supported documents found in `inputs/` without asking you
to select them individually.

The `inputs/` mount gives the container access to your documents. The
`data/` mount keeps saved plans on your computer after the container
exits.

> These multiline commands use PowerShell syntax. In Windows Command
> Prompt (CMD), use `^` for line continuation instead of the PowerShell
> backtick.

------------------------------------------------------------------------

## Interactive Mode

Interactive mode is useful when you want to choose specific documents or
manage saved plans.

### With Docker

``` powershell
docker run --rm -it `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  workload-planner --interactive
```

### With Python

After installing the dependencies (see [Run directly with
Python](#run-directly-with-python)), run:

``` bash
python main.py --interactive
```

The menu lets you view saved plans, delete a plan, search tasks by week
or difficulty, create a new plan, and exit.

When creating a plan, choose the document-selection option. The
available documents are shown as a numbered list. Depending on the
prompt, you can select:

-   One document, such as `1`
-   Multiple documents, such as `1,3`
-   A range, such as `1-3`
-   All documents, using `all`
-   Cancel selection, using `0`
-   Press Enter to use all documents, if the prompt offers that default

Only selected documents are processed. The original files in `inputs/`
are not modified.

------------------------------------------------------------------------

## The Idea

University students receive academic information across multiple
documents, such as syllabuses, lecture notes, lab instructions, tutorial
sheets, and weekly schedules. Manually turning these documents into a
structured study plan can be time-consuming.

The planner is designed to:

1.  Read academic documents.
2.  Extract study tasks using an AI model when AI extraction is
    required.
3.  Normalize tasks into a structured format.
4.  Calculate workload and risk metrics.
5.  Apply planning and scheduling logic.
6.  Save the resulting study plan.
7.  Let users search, edit, and manage saved plans.

**Note:** Not every input necessarily requires an API call. For example,
a valid JSON input that already contains a top-level `tasks` list can be
normalized directly without AI extraction.

------------------------------------------------------------------------

## Architecture

The project uses a procedural architecture with separate managers for
different responsibilities. `main.py` coordinates the application; the
managers are not a strict one-way pipeline because the exact path
depends on the input and operation.

``` text
                         main.py
                    (orchestrates flow)
                            |
             +--------------+--------------+
             |              |              |
        io_manager.py  ai_manager.py  logic_manager.py
             |              ^              |
             +---- data_manager.py --------+
                    (persistent data)
```

### `main.py`

Coordinates the application flow and calls the relevant managers.

### `io_manager.py`

Handles:

-   User input and CLI output
-   File discovery and document selection
-   Reading supported input files
-   Input validation and display formatting

`print()` and `input()` are kept inside this module.

### `ai_manager.py`

Handles AI extraction and response processing when required, including:

-   Sending extracted document text to OpenRouter
-   Using the configured DeepSeek model
-   Parsing and sanitizing AI responses
-   Normalizing task records
-   Handling AI/API failures

### `logic_manager.py`

Handles deterministic planning logic, including:

-   Duplicate-task detection
-   Workload and risk calculations
-   Task decisions using rules R1--R7
-   Deadline and capacity considerations
-   Weekly scheduling and rebalancing
-   Task-edit validation and plan recalculation

### `data_manager.py`

Handles persistent data operations, including:

-   Parsing JSON safely
-   Loading and saving plans
-   Updating and deleting plans
-   Backup and recovery for corrupted JSON
-   Supporting data migration

------------------------------------------------------------------------

## Requirements

### Recommended

-   Docker Desktop
-   An OpenRouter API key for AI extraction

### Run directly with Python

You can also run the project without Docker.

Requirements:

-   Python version compatible with the dependencies in
    `requirements.txt`
-   An OpenRouter API key for workflows that require AI extraction

Install dependencies from the project root:

``` bash
python -m pip install -r requirements.txt
```

Start interactive mode:

``` bash
python main.py --interactive
```

Process all supported documents in the input folder:

``` bash
python main.py --inputs inputs/
```

Process one or more individual documents:

``` bash
python main.py --file "inputs/lecture_notes.pdf"
```

``` bash
python main.py --file "inputs/lecture_notes.pdf" --file "inputs/tutorial.txt"
```

**Important:** `--file` expects a document file, not a folder. This is
invalid:

``` bash
python main.py --file inputs/
```

Use `--inputs inputs/` to process a folder.

------------------------------------------------------------------------

## Supported Input Types

  -----------------------------------------------------------------------
  Format                  Extension               Notes
  ----------------------- ----------------------- -----------------------
  PDF                     `.pdf`                  Text is extracted
                                                  locally using `pypdf`.
                                                  Image-only scanned PDFs
                                                  need OCR, which is not
                                                  currently included.

  Text                    `.txt`                  Plain text

  Markdown                `.md`                   Markdown text

  JSON                    `.json`                 Structured input can
                                                  bypass AI extraction
                                                  when it contains a
                                                  valid top-level `tasks`
                                                  list.
  -----------------------------------------------------------------------

Place documents in `inputs/` for interactive or folder-based workflows.

------------------------------------------------------------------------

## AI Model

The project accesses the configured DeepSeek model through OpenRouter:

``` text
deepseek/deepseek-v4-flash
```

Provide the API key through `.env`:

``` env
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

Never commit an actual API key to GitHub or hard-code it in source code.
The `.env.example` file should contain only a placeholder.

------------------------------------------------------------------------

## Study Task Schema

A task is represented using structured fields. A simplified example is:

``` json
{
  "title": "Complete Week 3 Lab",
  "difficulty": "medium",
  "estimated_minutes": 90,
  "deadline": "2026-10-10"
}
```

The planner can also use fields such as `task_id`, `description`,
`category`, `priority`, `dependencies`, `source_document`,
`source_type`, and `confidence`, depending on the input and
normalization process.

For structured JSON input, the outer object should contain a top-level
`tasks` list, for example:

``` json
{
  "source_document": "example.json",
  "tasks": [
    {
      "title": "Complete Week 3 Lab",
      "difficulty": "medium",
      "estimated_minutes": 90,
      "deadline": "2026-10-10"
    }
  ]
}
```

Valid JSON syntax alone does not guarantee that every task has all the
expected fields; the application normalizes task records.

------------------------------------------------------------------------

## Persistence

Generated plans are stored in:

``` text
data/study_plans.json
```

The application includes backup and recovery mechanisms for saved data.

When running with Docker, mount `data/` as shown in the commands above
if you want plans to remain available after the container exits.

------------------------------------------------------------------------

## Testing

The project includes automated tests for planning logic and interactive
functionality.

Run the tests from the project root:

``` bash
python -m pytest test_logic.py test_interactive.py -q
```

These tests are designed to run without making an OpenRouter API call.

------------------------------------------------------------------------

## Project Structure

``` text
.
├── ai_manager.py
├── data_manager.py
├── io_manager.py
├── logic_manager.py
├── main.py
├── inputs/
│   └── Academic documents
├── data/
│   └── study_plans.json
├── tests/
│   └── Test files (if present in this checkout)
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
├── SPEC.md
├── CHECKLIST.md
└── README.md
```

The exact files and test layout may vary slightly by repository
revision.

------------------------------------------------------------------------

## Security

-   Keep API keys and other secrets in `.env`.
-   Do not commit `.env`, passwords, or files containing real
    credentials.
-   Use `.env.example` as a template with placeholder values only.
-   Before committing, inspect `git status` and the staged diff to
    confirm that secrets are not included.

------------------------------------------------------------------------

## Notes

The planner is a command-line application and does not require a
graphical user interface.

Docker is recommended for a consistent runtime environment. Use
`--interactive` when you want the interactive menu, and
`--inputs inputs/` when you want to process all supported documents in
the input folder.
