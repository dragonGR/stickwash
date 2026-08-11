from __future__ import annotations

import os
import sys
import time
import threading
from typing import Sequence


class Theme:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and self._supports_color()

    @staticmethod
    def _supports_color() -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if not sys.stdout.isatty():
            return False
        term = os.environ.get("TERM", "")
        return term != "dumb"

    def c(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def cyan(self, text: str) -> str:
        return self.c("38;2;6;182;212", text)

    def emerald(self, text: str) -> str:
        return self.c("38;2;16;185;129", text)

    def amber(self, text: str) -> str:
        return self.c("38;2;245;158;11", text)

    def rose(self, text: str) -> str:
        return self.c("38;2;244;63;94", text)

    def slate(self, text: str) -> str:
        return self.c("38;2;71;85;105", text)

    def muted(self, text: str) -> str:
        return self.c("38;2;148;163;184", text)

    def bold(self, text: str) -> str:
        return self.c("1", text)


theme = Theme()


def set_color_enabled(enabled: bool) -> None:
    theme.enabled = enabled and Theme._supports_color()


def say(msg: str = "") -> None:
    print(msg)


def say_ok(msg: str) -> None:
    print(f"{theme.emerald('✓')} {msg}")


def say_warn(msg: str) -> None:
    print(f"{theme.amber('!')} {msg}")


def say_err(msg: str) -> None:
    print(f"{theme.rose('✗')} {msg}", file=sys.stderr)


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], title: str | None = None) -> None:
    if not headers:
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def top_border() -> str:
        parts = ["─" * (w + 2) for w in col_widths]
        return theme.slate("┌" + "┬".join(parts) + "┐")

    def mid_border() -> str:
        parts = ["─" * (w + 2) for w in col_widths]
        return theme.slate("├" + "┼".join(parts) + "┤")

    def bot_border() -> str:
        parts = ["─" * (w + 2) for w in col_widths]
        return theme.slate("└" + "┴".join(parts) + "┘")

    def format_row(row_cells: Sequence[str], is_header: bool = False) -> str:
        cells = []
        for i, w in enumerate(col_widths):
            val = str(row_cells[i]) if i < len(row_cells) else ""
            padded = val.ljust(w)
            if is_header:
                cells.append(f" {theme.bold(theme.cyan(padded))} ")
            else:
                cells.append(f" {padded} ")
        pipe = theme.slate("│")
        return f"{pipe}{pipe.join(cells)}{pipe}"

    if title:
        print(theme.bold(theme.cyan(title)))
    print(top_border())
    print(format_row(headers, is_header=True))
    print(mid_border())
    if not rows:
        empty_msg = "No data".center(sum(col_widths) + len(col_widths) * 3 - 1)
        pipe = theme.slate("│")
        print(f"{pipe}{empty_msg}{pipe}")
    else:
        for row in rows:
            print(format_row(row))
    print(bot_border())


class Spinner:
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, message: str, enabled: bool = True) -> None:
        self.message = message
        self.enabled = enabled and sys.stderr.isatty() and not os.environ.get("NO_COLOR")
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    def __enter__(self) -> Spinner:
        self._start_time = time.time()
        if self.enabled:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            print(f"-> {self.message}...", file=sys.stderr, flush=True)
        return self

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            elapsed = time.time() - self._start_time
            frame = theme.cyan(self.FRAMES[idx % len(self.FRAMES)])
            text = theme.muted(f"{self.message} ({elapsed:.1f}s)")
            sys.stderr.write(f"\r{frame} {text}")
            sys.stderr.flush()
            idx += 1
            time.sleep(0.08)

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object | None) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()

        elapsed = time.time() - self._start_time
        if self.enabled:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

        if exc_type is None:
            say_ok(f"{self.message} ({elapsed:.1f}s)")
        else:
            say_err(f"{self.message} failed ({elapsed:.1f}s)")


def render_card(header: str, content: str, width: int = 70) -> None:
    inner_w = max(width, len(content) + 2, len(header) + 4)
    pipe = theme.slate("│")

    dashes_needed = max(0, inner_w - len(header) - 1)
    top_line = theme.slate("┌─ ") + theme.bold(theme.cyan(header)) + theme.slate(" " + "─" * dashes_needed + "┐")
    bot_line = theme.slate("└" + "─" * (inner_w + 2) + "┘")

    padded_content = content.ljust(inner_w)
    mid_line = f"{pipe} {padded_content} {pipe}"

    print(top_line)
    print(mid_line)
    print(bot_line)


def render_menu(items: Sequence[tuple[str, str, str]]) -> None:
    for key, title, desc in items:
        badge = theme.bold(theme.cyan(f"[{key}]"))
        t_str = theme.bold(f"{title:<24}")
        d_str = theme.muted(desc) if desc else ""
        print(f"  {badge}  {t_str}  {d_str}")

