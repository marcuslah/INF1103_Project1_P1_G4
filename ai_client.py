"""ai_client.py — The contract for talking to an AI provider, and the Gemini implementation."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable

try:  # network client is optional at import time so offline tests never break
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from ai_config import AIConfig
from ai_errors import (
    AIConnectionError,
    AIHTTPError,
    AITimeoutError,
    MalformedResponseError,
    MissingAPIKeyError,
)


class AIClient(ABC):
    """Interface for any AI provider.

    ``complete`` returns the assistant's reply text and raises only AIError subclasses.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model answering the request."""

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Send chat messages and return the reply text."""


class RetryPolicy:
    """Decides how many attempts are made and how long to wait between them."""

    RETRYABLE_STATUS_CODES: tuple[int, ...] = (429, 503)

    def __init__(self, delays: tuple[float, ...] = (2, 4, 8)) -> None:
        self._delays = tuple(delays)

    @property
    def max_attempts(self) -> int:
        return len(self._delays)

    def is_last_attempt(self, attempt: int) -> bool:
        return attempt >= self.max_attempts - 1

    def delay_for(self, attempt: int) -> float:
        return self._delays[min(attempt, len(self._delays) - 1)]

    def should_retry_status(self, status_code: int) -> bool:
        return status_code in self.RETRYABLE_STATUS_CODES


class GeminiClient(AIClient):
    """Calls Gemini through its OpenAI-compatible chat endpoint, with retries."""

    def __init__(
        self,
        config: AIConfig,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config                                  # aggregation: shared settings object
        self._retry = retry_policy or RetryPolicy()            # composition: owned by this client
        self._sleep = sleep                                    # injectable so tests do not wait

    @property
    def model_name(self) -> str:
        return self._config.model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self._config.model,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _extract_content(payload: Any) -> str | None:
        """Pull the assistant message text out of an OpenAI-style response."""
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

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self._config.has_api_key:
            raise MissingAPIKeyError("GEMINI_API_KEY is not set")
        if requests is None:
            raise AIConnectionError("the 'requests' library is not installed")

        timeout = self._config.timeout
        for attempt in range(self._retry.max_attempts):
            last = self._retry.is_last_attempt(attempt)
            try:
                response = requests.post(
                    self._config.url, headers=self._headers(), json=self._body(messages), timeout=timeout,
                )
            except requests.Timeout:
                if last:
                    raise AITimeoutError(f"request timed out after {timeout}s") from None
                self._sleep(self._retry.delay_for(attempt))
                continue
            except requests.RequestException as exc:
                if last:
                    raise AIConnectionError(f"network error: {exc}") from None
                self._sleep(self._retry.delay_for(attempt))
                continue

            if self._retry.should_retry_status(response.status_code) and not last:
                self._sleep(self._retry.delay_for(attempt))
                continue
            if response.status_code != 200:
                snippet = (response.text or "")[:200]
                raise AIHTTPError(f"HTTP {response.status_code}: {snippet}")

            try:
                payload = response.json()
            except ValueError:
                raise MalformedResponseError("provider returned a non-JSON body") from None
            content = self._extract_content(payload)
            if content is None:
                raise MalformedResponseError("could not read content from the provider response")
            return str(content)

        raise AIHTTPError("server temporarily unavailable after multiple retries")
