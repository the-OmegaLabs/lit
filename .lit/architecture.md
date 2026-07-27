# Architecture Decisions

## Overview

**Lit** is an LLM-powered command-line agent with a TUI interface. It runs
entirely in the terminal, supports file editing, shell command execution, and
plugin extensions.

## Key Design Decisions

### 1. Content-based file editing (not line numbers)

- `edit_file` locates text by content matching, not by line number.
- Three levels of matching: exact → trailing whitespace tolerant → indentation
  tolerant. Each level must produce a unique match.
- This design avoids the classic problem where earlier edits shift line numbers
  and break later edits.

### 2. TUI rendered via custom ASCII engine

- `ascii.py` provides a custom rendering engine (not curses or rich's live).
- Built on `spans` (list of `(text, Style)` tuples) for flexible layout.
- Only one motion source allowed at a time (the status bar's flux waveform).
- Three grayscale levels only — prevents terminal confusion.
- Two spacing values: within-group (0) and between-group (1).

### 3. Plugin system

- `plugins/__init__.py` scans for non-underscore modules containing a `Plugin`
  class with an `export_function` dict.
- Plugin functions are auto-generated as OpenAI tool definitions and merged
  into the tool list.

### 4. Newline preservation

- `_decode_source` / `_write_source` preserves the original newline style
  (LF / CRLF / CR) and BOM, preventing spurious diffs on Windows.

### 5. Read safety limits

- `MAX_READ_LINES = 2000` — prevents large file reads from flooding context.
- `write_file` refuses to overwrite an existing file when new content is less
  than half its length (prevents silent code loss).

## Data Flow

1. User types input → `read_prompt()` → returns text
2. Text appended to `messages` → sent to OpenAI API with streaming
3. Streaming response parsed for reasoning, content, and tool calls
4. Tool calls dispatched via `dispatch_tool()` → results appended to messages
5. Loop repeats until no tool calls → turn ends