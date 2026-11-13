"""ai_config.py — Settings for the AI provider, read from environment variables."""

from __future__ import annotations

import os

try:  # .env loader is optional so tests run without it
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


class AIConfig:
    """Holds the API key, model name, endpoint and timeout. The key is never printed."""

    DEFAULT_MODEL: str = "gemini-3.8-flash"
    DEFAULT_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    DEFAULT_TIMEOUT: int = 30

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        url: str = DEFAULT_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        key = (api_key or "").strip()
        self._api_key = key or None
        self._model = model or self.DEFAULT_MODEL
        self._url = url or self.DEFAULT_URL
        self._timeout = int(timeout) if int(timeout) > 0 else self.DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "AIConfig":
        """Build the settings from GEMINI_API_KEY, GEMINI_MODEL and REQUEST_TIMEOUT."""
        if load_dotenv is not None:
            load_dotenv()
        try:
            timeout = int(os.getenv("REQUEST_TIMEOUT", str(cls.DEFAULT_TIMEOUT)))
        except ValueError:
            timeout = cls.DEFAULT_TIMEOUT
        return cls(
            api_key=os.getenv("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", cls.DEFAULT_MODEL) or cls.DEFAULT_MODEL,
            timeout=timeout,
        )

    @property
    def api_key(self) -> str | None:
        return self._api_key

    @property
    def has_api_key(self) -> bool:
        return self._api_key is not None

    @property
    def model(self) -> str:
        return self._model

    @property
    def url(self) -> str:
        return self._url

    @property
    def timeout(self) -> int:
        return self._timeout

    def __repr__(self) -> str:
        key_state = "set" if self.has_api_key else "missing"
        return f"AIConfig(model={self._model!r}, timeout={self._timeout}, api_key={key_state})"
