"""io_console.py — All keyboard input and screen output goes through ConsoleIO.

This is the only class in the project that calls input() and print().
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable


class ConsoleIO:
    """Reads validated answers from the user and writes lines to the terminal.

    The input and output functions are passed in, so tests can supply fake
    answers and capture what would have been printed.
    """

    BANNER_WIDTH: int = 60
    BANNER_LEVELS: tuple[str, ...] = ("INFO", "WARN", "ERROR", "SUCCESS")

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    # ----------------------------- output -----------------------------

    def display_line(self, text: str = "") -> None:
        self._output(str(text))

    def banner(self, level: str, message: str) -> None:
        """Show a status message such as SUCCESS or ERROR. Unknown levels become INFO."""
        tag = str(level).strip().upper()
        if tag not in self.BANNER_LEVELS:
            tag = "INFO"
        divider = "=" * self.BANNER_WIDTH
        self._output(divider)
        self._output(f"[{tag}] {message}")
        self._output(divider)

    # ----------------------------- input -----------------------------

    def read(self, label: str) -> str:
        """Read one line. Exits cleanly when there is no more input (non-interactive run)."""
        try:
            return self._input(label)
        except EOFError:
            self.display_line("")
            raise SystemExit(0)

    def prompt_line(self, label: str, allow_empty: bool = False) -> str:
        """Read trimmed text, asking again while it is blank (unless blanks are allowed)."""
        while True:
            value = self.read(f"{label}: ").strip()
            if value or allow_empty:
                return value
            self.display_line("  ! Input cannot be empty.")

    def prompt_int(self, label: str, minimum: int = 0, maximum: int = 100) -> int:
        """Read a whole number between minimum and maximum, asking again until valid."""
        while True:
            raw = self.read(f"{label}: ").strip()
            try:
                value = int(raw)
            except ValueError:
                self.display_line("  ! Please enter a whole number.")
                continue
            if minimum <= value <= maximum:
                return value
            self.display_line(f"  ! Value must be between {minimum} and {maximum}.")

    def prompt_float(self, label: str, minimum: float = 0.0, maximum: float = 1000.0) -> float:
        """Read a decimal number between minimum and maximum, asking again until valid."""
        while True:
            raw = self.read(f"{label}: ").strip()
            try:
                value = float(raw)
            except ValueError:
                self.display_line("  ! Please enter a number.")
                continue
            if minimum <= value <= maximum:
                return value
            self.display_line(f"  ! Value must be between {minimum} and {maximum}.")

    @staticmethod
    def is_valid_date(value: str, fmt: str = "%Y-%m-%d") -> bool:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            return False

    def prompt_date(self, label: str, fmt: str = "%Y-%m-%d") -> str:
        """Read a date in the given format, asking again until it is a real date."""
        while True:
            raw = self.read(f"{label} ({fmt}): ").strip()
            if self.is_valid_date(raw, fmt):
                return raw
            self.display_line(f"  ! Invalid date, expected {fmt}.")

    def prompt_optional_date(self, label: str, fmt: str = "%Y-%m-%d") -> str:
        """Read a date or a blank answer (meaning no date)."""
        while True:
            raw = self.read(f"{label}: ").strip()
            if not raw or self.is_valid_date(raw, fmt):
                return raw
            self.display_line("  ! Invalid date, expected YYYY-MM-DD.")

    def prompt_choice(self, label: str, choices: list[str]) -> str:
        """Read one of the listed choices (case does not matter). Returns it in lower case."""
        self.display_line(f"{label} [{'/'.join(choices)}]")
        lowered = [choice.lower() for choice in choices]
        while True:
            raw = self.read("> ").strip().lower()
            if raw in lowered:
                return raw
            self.display_line("  ! Choose one of: " + ", ".join(choices))

    def confirm(self, prompt: str) -> bool:
        """Ask a yes/no question. Anything other than y, yes, n or no is asked again."""
        while True:
            answer = self.read(f"{prompt} [y/n]: ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.display_line("  ! Please answer y or n.")

    def prompt_index(self, label: str, count: int, allow_zero: bool = True) -> int:
        """Read a menu number from 1 to count (0 is also accepted when allow_zero is set)."""
        low = 0 if allow_zero else 1
        while True:
            raw = self.read(f"{label}: ").strip()
            try:
                value = int(raw)
            except ValueError:
                self.display_line("  ! Please enter a number.")
                continue
            if low <= value <= count:
                return value
            self.display_line(f"  ! Enter a number between {low} and {count}.")

    def prompt_indices(self, label: str, count: int) -> list[int]:
        """Read one or more selections from 1 to count.

        Accepts numbers separated by commas or spaces and ranges such as 1-3.
        "all" or a blank answer selects everything; 0 cancels (empty list).
        """
        while True:
            raw = self.read(f"{label}: ").strip().lower()
            if raw in ("", "all", "a"):
                return list(range(1, count + 1))
            if raw == "0":
                return []
            picked = self._parse_selection(raw, count)
            if picked:
                return picked
            self.display_line(f"  ! Enter numbers between 1 and {count}, a range like 1-3, or 'all'.")

    @staticmethod
    def _parse_selection(raw: str, count: int) -> list[int]:
        """Turn text like "1,3 5-7" into sorted numbers. Empty list when anything is invalid."""
        picked: set[int] = set()
        for token in raw.replace(",", " ").split():
            if "-" in token:
                low_text, _, high_text = token.partition("-")
                if not (low_text.isdigit() and high_text.isdigit()):
                    return []
                low, high = int(low_text), int(high_text)
                if low < 1 or high > count or low > high:
                    return []
                picked.update(range(low, high + 1))
            elif token.isdigit():
                value = int(token)
                if value < 1 or value > count:
                    return []
                picked.add(value)
            else:
                return []
        return sorted(picked)
