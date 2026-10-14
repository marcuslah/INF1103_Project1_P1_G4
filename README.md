# StudyPilot AI Academic Workload Planner

An AI-powered academic workload planner that extracts study tasks from syllabus and course documents, estimates workload, applies planning logic, and saves a weekly study plan.

**Repository:** `INF1103 AI Academic Workload Planner`

---

## Quick Start — Docker

Docker is the recommended way to run the project because it provides the required Python environment and dependencies inside the container.

### 1. Download or clone the repository

Open **Command Prompt (CMD)** or **PowerShell** and clone or download the repository to your computer.
After downloading or cloning, open a terminal in the **project root directory** — the folder containing the `Dockerfile`, `requirements.txt`, and `main.py`.
```
git clone https://github.com/Shixy403/INF1103-AIStudy-reference.git
cd INF1103-AIStudy-reference
```
To verify, run
```
dir
```

### 2. Make sure Docker is installed

Install and start Docker Desktop before continuing.

### 3. Create your `.env` file

Copy `.env.example` and rename file to:

```text
.env
```

Add your OpenRouter API key:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

**Never commit or share your `.env` file.** It contains your private API key and is excluded from Git.

### 4. Add your documents

Place your academic documents inside:

```text
inputs/
```

Supported formats are:

- PDF
- TXT
- MD
- JSON

### 5. Build the Docker image

Run this command from the project root:

```bash
docker build -t workload-planner .
```

### 6. Run the planner

Either

1. To select Individual / Multiple documents through CLI Interactive
```
docker run --rm -it `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/data:/app/data" `
  --env-file .env `
  workload-planner
```

OR

2. To Automatically process the supported documents in the `inputs/` folder:

```bash
docker run --rm -v "${PWD}/inputs:/app/inputs" --env-file .env workload-planner --inputs inputs/
```

The planner will extract tasks, calculate workload information, and generate a saved study plan.

---

## Interactive Mode

The interactive menu is the recommended way to create a plan when you want to choose which documents to process.

Run:

```bash
docker run --rm -it -v "${PWD}/inputs:/app/inputs" -v "${PWD}/data:/app/data" --env-file .env workload-planner
```

You will see:

```text
========================================
        AI STUDY PLANNER
========================================
1. View saved plans
2. Delete a plan
3. Search tasks by week
4. Search tasks by difficulty
5. Create new plan
6. Exit
```

Select:

```text
5. Create new plan
```

Then:

```text
1. Select documents from inputs/
```

The planner displays the available documents as a numbered list.

You can select:

- Individual documents: `1`
- Multiple documents: `1,3`
- A range: `1-3`
- All documents: `all`
- Cancel document selection: `0`
- Press Enter to use all documents

Only the selected documents are processed. The original files in `inputs/` are not modified.

---

## The Idea

University students often receive academic information across multiple documents such as:

- Module information
- Syllabuses
- Lecture notes
- Lab instructions
- Tutorial sheets
- Weekly schedules

Manually converting these documents into a structured study plan can be time-consuming.

The AI Academic Workload Planner automates this process.

The system:

1. Reads academic documents.
2. Extracts study tasks using an AI model.
3. Structures the extracted tasks.
4. Calculates workload information.
5. Applies planning and scheduling logic.
6. Saves the resulting study plan.
7. Allows users to search, edit, and manage saved plans.

---

## Architecture

The project uses a procedural architecture with separate managers for each responsibility.

```text
                    main.py
                       |
        +--------------+--------------+
        |              |              |
   io_manager.py  ai_manager.py  logic_manager.py
                                      |
                               data_manager.py
```

### `main.py`

Controls the application flow and connects the different managers.

### `io_manager.py`

Handles:

- User input
- CLI output
- File discovery
- Document selection
- Input validation
- Display formatting

`print()` and `input()` are kept inside this module.

### `ai_manager.py`

Handles communication with the AI service.

Responsibilities include:

- Sending document content to OpenRouter
- Using the configured DeepSeek model
- Parsing AI responses
- Sanitising JSON responses
- Handling AI/API failures

### `logic_manager.py`

Handles the planning logic.

Responsibilities include:

- Task validation
- Duplicate detection
- Workload calculations
- Difficulty handling
- Deadline handling
- Scheduling decisions
- Plan recalculation

### `data_manager.py`

Handles persistent storage.

Responsibilities include:

- Saving plans
- Loading plans
- Updating plans
- Deleting plans
- Creating backups
- Recovering from corrupted JSON
- Supporting data migration

---

## Requirements

### Recommended

- Docker Desktop
- OpenRouter API key

### Alternative: Run Directly with Python

The project can also be run without Docker.

Requirements:

- Python 3.x
- An OpenRouter API key

Install the dependencies from the project root:

```bash
pip install -r requirements.txt
```

Then run:

```bash
python main.py
```

Docker is recommended for normal use because it provides a consistent environment.

---

## Usage

### Interactive Mode

Start the interactive menu:

```bash
python main.py
```

Then select:

```text
5. Create new plan
```

and:

```text
1. Select documents from inputs/
```

The interactive mode allows users to choose which documents should be included in a new plan.

---

### Process the `inputs/` Folder

To process the supported documents found in the entire `inputs/` folder:

```bash
python main.py --inputs inputs/
```

This processes the supported documents found in `inputs/`.

---

### Process Individual Documents

A specific document can be supplied using `--file`:

```bash
python main.py --file "inputs/lecture_notes.pdf"
```

Multiple documents can also be supplied:

```bash
python main.py --file "inputs/lecture_notes.pdf" --file "inputs/tutorial.txt"
```

**Important:** `--file` expects a document file, not a folder.

This is invalid:

```bash
python main.py --file inputs/
```

Use `--inputs inputs/` when processing a folder.

---

## Supported Input Types

The planner supports:

| Format | Extension |
|---|---|
| PDF | `.pdf` |
| Text | `.txt` |
| Markdown | `.md` |
| JSON | `.json` |

Documents should be placed inside the `inputs/` directory when using the interactive or folder-based workflow.

---

## AI Model

The project uses OpenRouter to access the DeepSeek model:

```text
deepseek/deepseek-v4-flash
```

The API key is provided through the `.env` file:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

The API key should never be committed to GitHub or included directly in source code.

---

## Study Task Schema

Extracted study tasks are represented using structured fields such as:

```json
{
  "title": "Complete Week 3 Lab",
  "difficulty": "medium",
  "estimated_minutes": 90,
  "deadline": "2026-10-10"
}
```

The planner uses these fields to calculate workload and construct the study plan.

---

## Persistence

Generated plans are stored in:

```text
data/study_plans.json
```

The application also supports backup and recovery mechanisms for the saved data.

The `data/` directory is used for persistent application data and should be mounted when running the Docker container if plans need to remain available after the container exits.

Example:

```bash
docker run --rm -it \
  -v "${PWD}/inputs:/app/inputs" \
  -v "${PWD}/data:/app/data" \
  --env-file .env \
  workload-planner
```

---

## Docker

### Build

From the project root:

```bash
docker build -t workload-planner .
```

### Process all documents

```bash
docker run --rm \
  -v "${PWD}/inputs:/app/inputs" \
  -v "${PWD}/data:/app/data" \
  --env-file .env \
  workload-planner --inputs inputs/
```

### Interactive mode

```bash
docker run --rm -it \
  -v "${PWD}/inputs:/app/inputs" \
  -v "${PWD}/data:/app/data" \
  --env-file .env \
  workload-planner
```

The `inputs/` volume allows the container to access the user's documents.

The `data/` volume allows generated study plans to persist on the host computer.

---

## Testing

The project includes automated tests for the planning logic and interactive functionality.

Run the test suite:

```bash
pytest test_logic.py test_interactive.py -q
```

The tests are designed to run without requiring an OpenRouter API call.

---

## Project Structure

```text
.
├── ai_manager.py
├── data_manager.py
├── io_manager.py
├── logic_manager.py
├── main.py
│
├── inputs/
│   └── Academic documents
│
├── data/
│   └── study_plans.json
│
├── tests/
│   └── Test files
│
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
├── SPEC.md
├── CHECKLIST.md
└── README.md
```

---

## Security

API keys and other secrets must not be committed to the repository.

Use:

```text
.env
```

for local secrets.

The repository provides:

```text
.env.example
```

as a template.

Never commit:

```text
.env
```

or any file containing an actual API key, password, or other secret.

---

## Notes

The planner is designed as a command-line application and does not require a graphical user interface.

The recommended workflow is to use Docker so that the project can be run using a consistent environment without manually installing the Python dependencies on the host machine.
