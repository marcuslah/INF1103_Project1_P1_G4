"""test_ai_manager.py — AI pipeline tests. None of them contact a live API."""

from __future__ import annotations

import json

import pytest

import ai_client
from ai_client import AIClient, GeminiClient, RetryPolicy
from ai_config import AIConfig
from ai_errors import (
    AIConnectionError,
    AIError,
    AIHTTPError,
    AITimeoutError,
    ExtractionResult,
    MalformedResponseError,
    MissingAPIKeyError,
    SchemaValidationError,
)
from ai_manager import AIManager
from ai_parser import ResponseParser, TaskNormalizer, TaskResponseValidator
from ai_prompts import PromptBuilder, TaskExtractionPromptBuilder, TaskReviewPromptBuilder
from models import Task


class FakeAIClient(AIClient):
    """Stands in for GeminiClient: returns a canned reply or raises a given error."""

    def __init__(self, reply: str = "", error: AIError | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls: list[list[dict]] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete(self, messages):
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        return self._reply


GOOD_REPLY = json.dumps({
    "source_document": "week3.txt",
    "confidence": 0.8,
    "notes": "two tasks found",
    "tasks": [
        {"title": "Lab 3 report", "category": "lab", "deadline": "2026-03-10",
         "estimated_minutes": 90, "difficulty": "hard", "priority": "high"},
        {"title": "Read chapter 4", "category": "reading", "estimated_hours": 1,
         "due_date": "2026-03-12", "priority": "whenever"},
    ],
})


def manager_with(reply: str = "", error: AIError | None = None) -> tuple[AIManager, FakeAIClient]:
    client = FakeAIClient(reply, error)
    return AIManager(client), client


# ----------------------------- extraction -----------------------------

def test_extract_tasks_success() -> None:
    manager, client = manager_with(GOOD_REPLY)
    result = manager.extract_tasks("Week 3 lab sheet text", "week3.txt")
    assert result.ok is True
    assert result.model == "fake-model"
    assert result.confidence == 0.8
    assert [task.title for task in result.tasks] == ["Lab 3 report", "Read chapter 4"]
    assert all(isinstance(task, Task) for task in result.tasks)
    assert len(client.calls) == 1


def test_extract_tasks_fills_defaults_and_accepts_old_keys() -> None:
    manager, _client = manager_with(GOOD_REPLY)
    first, second = manager.extract_tasks("text", "week3.txt").tasks
    assert first.task_id == "week3-txt-t1"
    assert first.source_document == "week3.txt"
    assert first.source_type == "ai"
    assert second.estimated_minutes == 60          # estimated_hours converted
    assert second.deadline == "2026-03-12"         # due_date accepted
    assert second.priority == "medium"             # invalid value replaced
    assert second.difficulty == "medium"           # missing value defaulted


def test_extract_tasks_accepts_code_fenced_json() -> None:
    manager, _client = manager_with("```json\n" + GOOD_REPLY + "\n```")
    assert manager.extract_tasks("text", "doc").ok is True


def test_extract_tasks_malformed_reply() -> None:
    manager, _client = manager_with("Sorry, I cannot help with that.")
    result = manager.extract_tasks("text", "doc")
    assert result.ok is False
    assert result.error_code == "invalid_json"
    assert result.tasks == []


def test_extract_tasks_missing_tasks_list() -> None:
    manager, _client = manager_with(json.dumps({"confidence": 0.9}))
    result = manager.extract_tasks("text", "doc")
    assert result.ok is False
    assert result.error_code == "invalid_schema"


def test_extract_tasks_task_without_title() -> None:
    manager, _client = manager_with(json.dumps({"tasks": [{"title": "  "}, "junk"]}))
    result = manager.extract_tasks("text", "doc")
    assert result.error_code == "invalid_schema"
    assert "task 0 missing 'title'" in result.message
    assert "task 1 is not an object" in result.message


def test_extract_tasks_empty_document_never_calls_the_ai() -> None:
    manager, client = manager_with(GOOD_REPLY)
    result = manager.extract_tasks("   ", "doc")
    assert result.ok is False
    assert result.error_code == "empty_document"
    assert client.calls == []


@pytest.mark.parametrize("error, code", [
    (AITimeoutError("request timed out after 30s"), "timeout"),
    (AIConnectionError("network error"), "network_error"),
    (AIHTTPError("HTTP 500"), "http_error"),
    (MissingAPIKeyError("GEMINI_API_KEY is not set"), "no_api_key"),
])
def test_extract_tasks_reports_client_failures_without_raising(error, code) -> None:
    manager, _client = manager_with(error=error)
    result = manager.extract_tasks("text", "doc")
    assert result.ok is False
    assert result.error_code == code
    assert result.message == error.message


# ----------------------------- review -----------------------------

def structured_tasks() -> list[Task]:
    return [
        Task("m1", "Revise for quiz", estimated_minutes=0, difficulty="easy", priority="low", source_type="manual"),
        Task("m2", "Finish project", estimated_minutes=300, difficulty="medium", priority="medium", source_type="manual"),
    ]


def test_review_tasks_applies_ai_judgement() -> None:
    reply = json.dumps({"confidence": 0.7, "tasks": [
        {"task_id": "m1", "title": "Revise for quiz", "difficulty": "medium", "priority": "high", "estimated_minutes": 45},
        {"task_id": "m2", "title": "Finish project", "difficulty": "hard", "priority": "high", "estimated_minutes": 999},
    ]})
    manager, _client = manager_with(reply)
    result = manager.review_tasks(structured_tasks(), "MANUAL")
    first, second = result.tasks
    assert result.ok is True and result.warning == ""
    assert (first.difficulty, first.priority, first.estimated_minutes) == ("medium", "high", 45)
    assert (second.difficulty, second.priority) == ("hard", "high")
    assert second.estimated_minutes == 300          # an existing estimate is never overwritten
    assert first.confidence == 0.7
    assert "adjusted 2 of 2" in result.notes


def test_review_tasks_never_changes_title_deadline_or_category() -> None:
    reply = json.dumps({"tasks": [
        {"task_id": "m1", "title": "Something else", "deadline": "2030-01-01", "category": "exam"},
    ]})
    manager, _client = manager_with(reply)
    task = Task("m1", "Revise for quiz", category="revision", deadline="2026-03-10")
    reviewed = manager.review_tasks([task], "MANUAL").tasks[0]
    assert (reviewed.title, reviewed.deadline, reviewed.category) == ("Revise for quiz", "2026-03-10", "revision")


def test_review_tasks_ignores_invalid_suggestions_and_unknown_ids() -> None:
    reply = json.dumps({"tasks": [
        {"task_id": "m1", "title": "Revise for quiz", "difficulty": "extreme", "priority": "asap"},
        {"task_id": "ghost", "title": "Not ours", "difficulty": "hard"},
    ]})
    manager, _client = manager_with(reply)
    first, second = manager.review_tasks(structured_tasks(), "MANUAL").tasks
    assert (first.difficulty, first.priority) == ("easy", "low")
    assert (second.difficulty, second.priority) == ("medium", "medium")


def test_review_tasks_keeps_tasks_when_ai_is_unavailable() -> None:
    manager, _client = manager_with(error=MissingAPIKeyError("GEMINI_API_KEY is not set"))
    result = manager.review_tasks(structured_tasks(), "MANUAL")
    assert result.ok is True
    assert len(result.tasks) == 2
    assert "no_api_key" in result.warning
    assert result.tasks[0].priority == "low"


def test_review_tasks_with_no_tasks_skips_the_ai() -> None:
    manager, client = manager_with(GOOD_REPLY)
    assert manager.review_tasks([], "MANUAL").tasks == []
    assert client.calls == []


# ----------------------------- process_document -----------------------------

def test_process_document_sends_free_text_for_extraction() -> None:
    manager, client = manager_with(GOOD_REPLY)
    result = manager.process_document("Plain syllabus text", "syllabus.txt")
    assert result.ok and len(result.tasks) == 2
    assert "Document text" in client.calls[0][1]["content"]


def test_process_document_sends_json_task_files_for_review() -> None:
    document = json.dumps({"course_code": "INF1103", "tasks": [{"title": "Lab 1", "estimated_minutes": 0}]})
    reply = json.dumps({"confidence": 0.6, "tasks": [
        {"task_id": "inf1103-t1", "title": "Lab 1", "difficulty": "hard", "priority": "high", "estimated_minutes": 80},
    ]})
    manager, client = manager_with(reply)
    result = manager.process_document(document, "lab.json")
    task = result.tasks[0]
    assert len(client.calls) == 1                       # the record went through the AI
    assert "Review the structured study tasks" in client.calls[0][1]["content"]
    assert (task.source_document, task.source_type) == ("INF1103", "json")
    assert (task.difficulty, task.estimated_minutes) == ("hard", 80)


def test_process_document_json_without_tasks_is_treated_as_text() -> None:
    manager, client = manager_with(GOOD_REPLY)
    manager.process_document(json.dumps({"hello": "world"}), "odd.json")
    assert "Document text" in client.calls[0][1]["content"]


# ----------------------------- parser, validator, normaliser -----------------------------

def test_parser_extracts_json_from_surrounding_text() -> None:
    parser = ResponseParser()
    assert parser.parse('Here you go: {"tasks": []} Thanks!') == {"tasks": []}
    with pytest.raises(MalformedResponseError):
        parser.parse("")
    with pytest.raises(MalformedResponseError):
        parser.parse("[1, 2, 3]")
    with pytest.raises(MalformedResponseError):
        parser.parse("{broken")


def test_validator_lists_every_problem() -> None:
    validator = TaskResponseValidator()
    assert validator.problems({"tasks": [{"title": "ok"}]}) == []
    assert validator.problems("nope") == ["response is not an object"]
    with pytest.raises(SchemaValidationError):
        validator.validate({"tasks": "nope"})


def test_normalizer_skips_junk_and_sets_manual_confidence() -> None:
    tasks = TaskNormalizer().normalize([{"title": "A"}, 42, None], "My Notes.txt", source="manual")
    assert len(tasks) == 1
    assert tasks[0].task_id == "my-notes-txt-t1"
    assert tasks[0].confidence == 1.0
    assert TaskNormalizer().normalize("not a list", "x") == []


# ----------------------------- prompts -----------------------------

@pytest.mark.parametrize("builder", [TaskExtractionPromptBuilder(), TaskReviewPromptBuilder()])
def test_every_prompt_builder_produces_system_and_user_messages(builder: PromptBuilder) -> None:
    messages = builder.build("payload text", "source.txt")
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "JSON" in messages[0]["content"]
    assert "payload text" in messages[1]["content"]
    assert "source.txt" in messages[1]["content"]


def test_manager_accepts_a_custom_prompt_builder() -> None:
    class ShoutingPrompt(PromptBuilder):
        def _system_prompt(self) -> str:
            return "RETURN JSON"

        def _user_prompt(self, payload: str, source_name: str) -> str:
            return payload.upper()

    client = FakeAIClient(GOOD_REPLY)
    AIManager(client, extraction_prompt=ShoutingPrompt()).extract_tasks("quiet text", "doc")
    assert client.calls[0][1]["content"] == "QUIET TEXT"


# ----------------------------- config -----------------------------

def test_config_hides_the_api_key() -> None:
    config = AIConfig(api_key="super-secret-key")
    assert "super-secret-key" not in repr(config)
    assert config.has_api_key is True
    assert AIConfig(api_key="   ").has_api_key is False


def test_config_from_env(monkeypatch) -> None:
    monkeypatch.setattr("ai_config.load_dotenv", None)
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("REQUEST_TIMEOUT", "not-a-number")
    config = AIConfig.from_env()
    assert (config.api_key, config.model, config.timeout) == ("abc", "test-model", AIConfig.DEFAULT_TIMEOUT)


# ----------------------------- GeminiClient (network is faked) -----------------------------

class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def make_client(monkeypatch, outcomes: list) -> tuple[GeminiClient, list, list]:
    """Build a GeminiClient whose network calls return the queued outcomes in order."""
    posts: list[dict] = []
    sleeps: list[float] = []
    queue = list(outcomes)

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ai_client.requests, "post", fake_post)
    client = GeminiClient(AIConfig(api_key="test-key", timeout=5), sleep=sleeps.append)
    return client, posts, sleeps


MESSAGES = [{"role": "user", "content": "hi"}]


def test_gemini_client_returns_reply_text(monkeypatch) -> None:
    client, posts, sleeps = make_client(monkeypatch, [FakeResponse(200, chat_payload("hello"))])
    assert client.complete(MESSAGES) == "hello"
    assert posts[0]["headers"]["Authorization"] == "Bearer test-key"
    assert posts[0]["json"]["response_format"] == {"type": "json_object"}
    assert posts[0]["timeout"] == 5
    assert sleeps == []


def test_gemini_client_retries_503_then_succeeds(monkeypatch) -> None:
    client, posts, sleeps = make_client(monkeypatch, [
        FakeResponse(503, text="busy"), FakeResponse(429, text="slow down"), FakeResponse(200, chat_payload("ok")),
    ])
    assert client.complete(MESSAGES) == "ok"
    assert len(posts) == 3
    assert sleeps == [2, 4]


def test_gemini_client_gives_up_after_three_503s(monkeypatch) -> None:
    client, posts, _sleeps = make_client(monkeypatch, [FakeResponse(503, text="busy")] * 3)
    with pytest.raises(AIHTTPError) as caught:
        client.complete(MESSAGES)
    assert "503" in caught.value.message
    assert len(posts) == 3


def test_gemini_client_timeout_after_retries(monkeypatch) -> None:
    client, posts, sleeps = make_client(monkeypatch, [ai_client.requests.Timeout()] * 3)
    with pytest.raises(AITimeoutError):
        client.complete(MESSAGES)
    assert len(posts) == 3 and sleeps == [2, 4]


def test_gemini_client_connection_error_then_recovery(monkeypatch) -> None:
    client, _posts, _sleeps = make_client(monkeypatch, [
        ai_client.requests.ConnectionError("down"), FakeResponse(200, chat_payload("back")),
    ])
    assert client.complete(MESSAGES) == "back"


def test_gemini_client_connection_error_after_retries(monkeypatch) -> None:
    client, _posts, _sleeps = make_client(monkeypatch, [ai_client.requests.ConnectionError("down")] * 3)
    with pytest.raises(AIConnectionError):
        client.complete(MESSAGES)


def test_gemini_client_does_not_retry_other_http_errors(monkeypatch) -> None:
    client, posts, _sleeps = make_client(monkeypatch, [FakeResponse(401, text="bad key")])
    with pytest.raises(AIHTTPError) as caught:
        client.complete(MESSAGES)
    assert "401" in caught.value.message
    assert len(posts) == 1


def test_gemini_client_non_json_body(monkeypatch) -> None:
    client, _posts, _sleeps = make_client(monkeypatch, [FakeResponse(200, payload=None, text="<html>")])
    with pytest.raises(MalformedResponseError):
        client.complete(MESSAGES)


def test_gemini_client_unexpected_payload_shape(monkeypatch) -> None:
    client, _posts, _sleeps = make_client(monkeypatch, [FakeResponse(200, {"choices": []})])
    with pytest.raises(MalformedResponseError):
        client.complete(MESSAGES)


def test_gemini_client_without_api_key_never_calls_the_network(monkeypatch) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("network must not be used")

    monkeypatch.setattr(ai_client.requests, "post", explode)
    with pytest.raises(MissingAPIKeyError):
        GeminiClient(AIConfig(api_key=None)).complete(MESSAGES)


def test_retry_policy() -> None:
    policy = RetryPolicy(delays=(1, 2))
    assert policy.max_attempts == 2
    assert policy.is_last_attempt(1) and not policy.is_last_attempt(0)
    assert policy.should_retry_status(503) and not policy.should_retry_status(500)


def test_fake_and_real_clients_share_the_interface() -> None:
    for client in (FakeAIClient("x"), GeminiClient(AIConfig(api_key="k"))):
        assert isinstance(client, AIClient)
        assert isinstance(client.model_name, str)


def test_extraction_result_factories() -> None:
    failure = ExtractionResult.failure(AITimeoutError("slow"))
    assert (failure.ok, failure.error_code, failure.message) == (False, "timeout", "slow")
    kept = ExtractionResult.unreviewed([Task("a", "A")], AIConnectionError("down"))
    assert kept.ok is True and "network_error" in kept.warning
