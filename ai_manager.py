from __future__ import annotations

import json
import os
import time
from typing import Any

try:  # Network client (optional at import time so offline tests never break).
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:  # .env loader (optional).
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv is not None:
    load_dotenv()

DEFAULT_MODEL: str = "gemini-3.8-flash"
DEFAULT_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_TITLE: str = "AI Academic Workload Planner"
DEFAULT_TIMEOUT: int = 30

VALID_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
VALID_DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
VALID_CATEGORIES: tuple[str, ...] = (
    "assignment",
    "exam",
    "tutorial",
    "lab",
    "project",
    "reading",
    "revision",
    "other",
)

RESPONSE_SCHEMA_HINT: str = (
    '{"source_document": "string", "confidence": 0.0, "notes": "string", "tasks": ['
    '{"title": "string", "description": "string", '
    '"category": "assignment|exam|tutorial|lab|project|reading|revision|other", '
    '"deadline": "YYYY-MM-DD or empty", "estimated_minutes": 0, '
    '"difficulty": "easy|medium|hard", "priority": "low|medium|high", '
    '"dependencies": ["string"]}]}'
)


# --------------------------- configuration ---------------------------

def get_model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL


def get_api_url() -> str:
    return DEFAULT_URL


def get_api_key() -> str | None:
    key = os.getenv("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()
    return None


def get_timeout() -> int:
    try:
        return int(os.getenv("REQUEST_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def build_headers(api_key: str) -> dict[str, str]:
    """Standard Bearer authorization header for Gemini's OpenAI-compatible endpoint."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
# --------------------------- request builders ---------------------------

def build_messages(document_text: str, source_name: str = "UNKNOWN") -> list[dict[str, str]]:
    """Build chat messages that extract study tasks from ANY academic document."""
    system = (
        "You are an academic workload analyst. Read the supplied academic document and "
        "identify only ACTIONABLE study tasks (things a student must do). Ignore purely "
        "informational content such as lecture times, course descriptions or admin notes. "
        "For every task: give a short title and description, choose a category, extract an "
        "explicit deadline when present (otherwise leave it empty), extract an explicit "
        "duration when present and otherwise ESTIMATE the minutes of work, set a difficulty, "
        "set a priority from deadlines and importance, and list dependencies on other tasks "
        "when evident. Respond with ONLY a single JSON object matching this schema, no prose "
        "and no code fences:\n" + RESPONSE_SCHEMA_HINT
    )
    user = (
        f"Source document: {source_name}\n"
        "Interpret the academic material below and return the study tasks.\n"
        "Document text:\n" + str(document_text or "")
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_request_body(messages: list[dict], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }


def error_response(code: str, message: str) -> dict[str, Any]:
    """Uniform error payload returned instead of raising."""
    return {
        "status": "error",
        "error_code": code,
        "message": message,
        "tasks": [],
    }




def call_openrouter(messages: list[dict], timeout: int = DEFAULT_TIMEOUT, max_retries: int = 3) -> dict[str, Any]:
    """POST to Gemini endpoint with retry logic for 503/429 transient errors."""
    api_key = get_api_key()
    if api_key is None:
        return error_response("no_api_key", "GEMINI_API_KEY is not set")
    if requests is None:
        return error_response("network_error", "the 'requests' library is not installed")

    url = get_api_url()
    model = get_model_name()
    headers = build_headers(api_key)
    body = build_request_body(messages, model)

    backoff_delays = [2, 4, 8]  # Wait seconds before retrying

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.Timeout:
            if attempt == max_retries - 1:
                return error_response("timeout", f"request timed out after {timeout}s")
            time.sleep(backoff_delays[attempt])
            continue
        except requests.RequestException as exc:
            if attempt == max_retries - 1:
                return error_response("network_error", f"network error: {exc}")
            time.sleep(backoff_delays[attempt])
            continue

        # If rate-limited (429) or server unavailable (503), wait and retry
        if response.status_code in (429, 503):
            if attempt < max_retries - 1:
                time.sleep(backoff_delays[attempt])
                continue

        if response.status_code != 200:
            snippet = (response.text or "")[:200]
            return error_response("http_error", f"HTTP {response.status_code}: {snippet}")

        try:
            return response.json()
        except ValueError:
            return error_response("invalid_json", "provider returned a non-JSON body")

    return error_response("http_error", "server temporarily unavailable after multiple retries")

# --------------------------- sanitizer + parsing ---------------------------

def sanitize_json(raw: str | None) -> str:
    """Remove code fences and extract the first JSON object or array from the text."""
    if raw is None:
        return ""
    kept_lines: list[str] = []
    for line in str(raw).splitlines():
        if line.strip().startswith("```"):
            continue
        kept_lines.append(line)
    text = "\n".join(kept_lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()
    return text


def parse_ai_content(content: str | None) -> tuple[dict | None, str | None]:
    """Sanitize then ``json.loads`` the AI content. Returns ``(data, error)``."""
    cleaned = sanitize_json(content)
    if not cleaned:
        return None, "empty AI content"
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"invalid AI JSON: {exc}"
    if not isinstance(data, dict):
        return None, "AI JSON root is not an object"
    return data, None


def validate_ai_response(data: dict) -> tuple[bool, list[str]]:
    """Check the parsed AI object against the expected response schema."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return False, ["response is not an object"]
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return False, ["missing or invalid 'tasks' list"]
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            problems.append(f"task {index} is not an object")
            continue
        if not str(task.get("title", "")).strip():
            problems.append(f"task {index} missing 'title'")
    return (len(problems) == 0), problems


# --------------------------- normalization ---------------------------

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_priority(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in VALID_PRIORITIES else "medium"


def _norm_difficulty(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in VALID_DIFFICULTIES else "medium"


def _norm_category(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in VALID_CATEGORIES else "other"


def _slug(value: Any) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or ""))
    text = "-".join(part for part in text.split("-") if part)
    return text[:32] or "doc"


def normalize_tasks(tasks: list, source_name: str, source: str = "ai") -> list[dict[str, Any]]:
    """Coerce raw task dicts into the canonical v2 task shape (legacy keys accepted)."""
    normalized: list[dict[str, Any]] = []
    if not isinstance(tasks, list):
        return normalized
    default_confidence = 1.0 if source == "manual" else 0.0
    stem = _slug(source_name)
    for index, raw in enumerate(tasks):
        if not isinstance(raw, dict):
            continue
        minutes = raw.get("estimated_minutes")
        if minutes is None and raw.get("estimated_hours") is not None:
            minutes = _to_float(raw.get("estimated_hours")) * 60.0
        deadline = raw.get("deadline")
        if deadline in (None, "") and raw.get("due_date"):
            deadline = raw.get("due_date")
        category = raw.get("category") or raw.get("task_type") or "other"
        dependencies = raw.get("dependencies")
        if not isinstance(dependencies, list):
            dependencies = []
        confidence = raw.get("confidence")
        if confidence is None:
            confidence = raw.get("ai_confidence", default_confidence)
        normalized.append({
            "task_id": str(raw.get("task_id") or f"{stem}-t{index + 1}"),
            "title": str(raw.get("title") or "Untitled task"),
            "description": str(raw.get("description") or ""),
            "category": _norm_category(category),
            "deadline": str(deadline or ""),
            "estimated_minutes": int(round(_to_float(minutes))),
            "difficulty": _norm_difficulty(raw.get("difficulty")),
            "priority": _norm_priority(raw.get("priority")),
            "dependencies": [str(dep) for dep in dependencies],
            "source_document": str(raw.get("source_document") or raw.get("course_code") or source_name or "UNKNOWN"),
            "source_type": str(raw.get("source_type") or source or "ai"),
            "confidence": _to_float(confidence, default_confidence),
        })
    return normalized


def _extract_content(payload: Any) -> str | None:
    """Pull the assistant message text out of an OpenRouter-style response."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and "content" in message:
                return message.get("content")
            if "text" in first:
                return first.get("text")
    if "content" in payload:
        return payload.get("content")
    return None


def extract_tasks(document_text: str, source_name: str = "UNKNOWN") -> dict[str, Any]:
    """End-to-end AI extraction from ANY document: build -> call -> sanitize -> validate -> normalize."""
    if not document_text or not str(document_text).strip():
        return error_response("empty_response", "no document text provided")
    if get_api_key() is None:
        return error_response("no_api_key", "GEMINI_API_KEY is not set; use manual entry instead")
    messages = build_messages(document_text, source_name)
    payload = call_openrouter(messages, get_timeout())
    if isinstance(payload, dict) and payload.get("status") == "error":
        return payload
    content = _extract_content(payload)
    if content is None:
        return error_response("invalid_json", "could not read content from the provider response")
    data, error = parse_ai_content(content)
    if error is not None:
        return error_response("invalid_json", error)
    ok, problems = validate_ai_response(data)
    if not ok:
        return error_response("invalid_json", "; ".join(problems))
    return {
        "status": "ok",
        "model": get_model_name(),
        "source_document": str(data.get("source_document") or source_name),
        "confidence": _to_float(data.get("confidence")),
        "notes": str(data.get("notes", "")),
        "tasks": normalize_tasks(data.get("tasks", []), source_name, source="ai"),
    }
