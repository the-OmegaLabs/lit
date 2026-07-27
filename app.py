# Lit

import contextlib
import difflib
import io
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

try:
    from . import ascii
    from .ascii import Style
    from . import config
    from . import util

    from . import plugins
except ImportError:
    import ascii
    from ascii import Style
    import config
    import util

    import plugins

plugin = plugins.PluginManager()
plugin.load_plugin()
plugin.generate_tools()

# print(f'Loaded {len(plugin.plugins)} plugins, {len(plugin.tools)} tools.')

###########################
base_url = config.base_url
api_key = config.api_key
model = config.model
model_id = config.model_id
##########################

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
)

# Four constraints explain all the numbers below. They are not aesthetic
# preferences; they are hard limits imposed by the perception system:
#
# 1. The accent color should only mark "the current focus". Once the ember
#    gradient appears simultaneously in the prompt, bullets, headings, borders,
#    and status bar, it no longer points to anything — after accent-color
#    inflation, the eyes have nowhere to land and the entire screen is shouting.
#
# 2. Keep only three levels of grayscale. When the brightness difference between
#    adjacent levels is less than 40, terminals cannot reliably distinguish them.
#    The hierarchy becomes meaningless while the cognitive cost remains. Three
#    levels are close to the upper limit of what can be consistently perceived.
#
# 3. Spacing carries grouping semantics. When all spacing values are equal, the
#    proximity principle breaks down and the visual system cannot determine which
#    elements belong together — this is the real cause of "too crowded", not the
#    number of lines.
#
# 4. Allow only one motion source at a time. Motion is the strongest attention
#    attractor in the pre-attentive channel. Two or more concurrent moving
#    elements prevent attention from anchoring, producing the subjective feeling
#    of "tiring to look at".

if config.use_alt_theme:
    EMBER = [(56, 189, 248), (74, 222, 128)]  # sky → green
    ACCENT = (56, 189, 248)   # #38bdf8
    GOLD = (74, 222, 128)     # #4ade80
    ROSE = (56, 189, 248)     # compatibility alias
    OK_GREEN = (74, 222, 128)
    ERR_RED = (248, 113, 113)
    WARN_YELLOW = (251, 191, 36)
    # Three grayscale levels
    TEXT = (228, 232, 240)
    MUTED = (156, 164, 180)
    FAINT = (98, 106, 122)
    SILVER = TEXT
    DIM = MUTED
    S_TEXT = Style(fg=TEXT)
    S_MUTED = Style(fg=MUTED)
    S_DIM = Style(fg=DIM)
    S_FAINT = Style(fg=FAINT)
    S_ACCENT = Style(fg=ACCENT)
    S_GOLD = Style(fg=GOLD)
    S_OK = Style(fg=OK_GREEN)
    S_ERR = Style(fg=ERR_RED)
    S_WARN = Style(fg=WARN_YELLOW)
    # UI tiers: cool sky = user input; fresh green = agent
    AGENT = (74, 222, 128)
    AGENT_GUTTER = (56, 189, 248)
else:
    EMBER = [(255, 0, 175), (143, 1, 251)]  # neon pink → electric purple
    ACCENT = (255, 0, 175)   # #FF00AF
    GOLD = (143, 1, 251)     # #8F01FB
    ROSE = (255, 0, 175)     # compatibility alias
    OK_GREEN = (74, 222, 128)    # keep semantic green
    ERR_RED = (248, 113, 113)    # keep semantic red
    WARN_YELLOW = (251, 191, 36) # keep semantic yellow
    # Three grayscale levels
    TEXT = (228, 232, 240)
    MUTED = (156, 164, 180)
    FAINT = (98, 106, 122)
    SILVER = TEXT
    DIM = MUTED
    S_TEXT = Style(fg=TEXT)
    S_MUTED = Style(fg=MUTED)
    S_DIM = Style(fg=DIM)
    S_FAINT = Style(fg=FAINT)
    S_ACCENT = Style(fg=ACCENT)
    S_GOLD = Style(fg=GOLD)
    S_OK = Style(fg=OK_GREEN)
    S_ERR = Style(fg=ERR_RED)
    S_WARN = Style(fg=WARN_YELLOW)
    # UI tiers: neon pink = user input; electric purple = agent
    AGENT = (143, 1, 251)
    AGENT_GUTTER = (255, 0, 175)

S_AGENT = Style(fg=AGENT)
S_AGENT_GUTTER = Style(fg=AGENT_GUTTER)
GUTTER = '▎ '

# Only three spacing values are used. 0 = within-group spacing,
# 1 = between-group spacing, 2 = between-turn spacing.
# The amount of whitespace itself communicates whether elements belong to
# the same unit or represent separate units.
GAP_TIGHT = 0
GAP_BLOCK = 1
GAP_TURN = 2

# Body text reading width. A terminal may offer 200 columns, but lines longer
# than ~80 columns increase the risk of return-sweep errors. When reading long
# responses, this creates the feeling that "the text becomes harder to follow
# as you continue reading".
CONTENT_WIDTH = 80
INPUT_WIDTH = 84

# The bottom status bar's reactor and flux are the only motion sources.
# All other elements remain static.
FLUX_SPAN = 14

# Markdown Theme: Reserve the accent color instead of applying it to every
# bullet point. Remove background fills from inline code, as inline blocks
# within a paragraph create "visual gaps" that disrupt reading flow.
MD_THEME = ascii.MarkdownTheme(
    text=Style(fg=(205, 214, 244)),  # Text #cdd6f4
    accent_stops=[
        (203, 166, 247),  # Mauve #cba6f7
        (245, 194, 231),  # Pink #f5c2e7
    ],
    h2=Style(fg=(205, 214, 244), bold=True),   # Text
    h3=Style(fg=(180, 190, 254), bold=True),   # Lavender
    h4=Style(fg=(137, 180, 250), bold=True),   # Blue
    rule=Style(fg=(116, 199, 236)),            # Sapphire
    bullet=Style(fg=(148, 226, 213)),          # Teal
    number=Style(fg=(166, 227, 161)),          # Green
    quote_bar=Style(fg=(203, 166, 247)),       # Mauve
    quote_text=Style(
        fg=(156, 164, 180),
        italic=True
    ),
    code_inline=Style(fg=(250, 179, 135)),     # Peach
    code_border=Style(fg=(116, 199, 236)),     # Sapphire
    code_lang=Style(
        fg=(180, 190, 254),                    # Lavender
        italic=True
    ),
    table_border=Style(fg=(116, 199, 236)),    # Sapphire
)

logo = r""" __       __    ______
/\ \     /\ \  /\__  _\
\ \ \___ \ \ \ \/_/\ \/
 \ \____\ \ \_\   \ \_\
  \/____/  \/_/    \/_/
  """

def decode_output(data: bytes) -> str:
    if not data:
        return ""

    for encoding in (
        "utf-8",
        "utf-8-sig",
        "utf-16",
        "gb18030",
        "cp936",
        "latin1",  # Last choice
    ):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    return data.decode("utf-8", errors="replace")


def run_powershell(command: str, cancel: threading.Event | None = None):
    try:
        process = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                command,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.kill()
                    stdout, stderr = process.communicate()
                    return {
                        "stdout": decode_output(stdout),
                        "stderr": "interrupted by user",
                        "returncode": -1,
                    }

        return {
            "stdout": decode_output(stdout),
            "stderr": decode_output(stderr),
            "returncode": process.returncode,
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }


system = util.read_file(
    os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
).format(model=model)

tools = [
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": "Runs a PowerShell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "PowerShell command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file, or a line range of one.\n\n"
                "Every output line is prefixed with 'NNN | '. Those numbers are "
                "for REPORTING and NAVIGATION only — never for addressing an "
                "edit. When you go on to call edit_file, copy the text WITHOUT "
                "the 'NNN | ' prefix.\n\n"
                "The result also reports `total_lines` and `truncated`, so you "
                "can tell whether you have actually seen the whole file. Do not "
                "edit a file you have only partially read."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": (
                            "First line to read (1-based). "
                            "If omitted, reads from the beginning."
                        )
                    },
                    "end_line": {
                        "type": "integer",
                        "description": (
                            "Last line to read (inclusive, 1-based). "
                            "If omitted, reads until the end."
                        )
                    }
                },
                "required": [
                    "path"
                ]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a NEW file, or completely rewrite a small one.\n\n"
                "Never use this to modify an existing file — use edit_file. "
                "Rewriting a file you only remember means silently dropping the "
                "parts you forgot, and nothing in the result will tell you that "
                "happened. This tool will refuse to overwrite an existing file "
                "when the new content is less than half its current length."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content to write."
                    }
                },
                "required": [
                    "path",
                    "content"
                ]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Modify an existing file by replacing exact text. This tool "
                "locates the edit by CONTENT, never by line number, so earlier "
                "edits shifting the file cannot break a later one.\n\n"
                "Workflow:\n"
                "1. read_file the region you intend to change.\n"
                "2. Copy the text to be replaced into `old_text`, character for "
                "character, including its exact indentation. Strip the "
                "'NNN | ' line-number prefix that read_file adds.\n"
                "3. Put the replacement text in `new_text`.\n\n"
                "Rules:\n"
                "- `old_text` must appear EXACTLY ONCE in the file. If it "
                "appears more than once, extend it with the surrounding lines "
                "until it is unique — do not guess which one.\n"
                "- To DELETE text: leave `new_text` empty.\n"
                "- To INSERT text: include an existing nearby line in BOTH "
                "`old_text` and `new_text`, and add your new lines around it in "
                "`new_text`. There is no separate insert mode.\n"
                "- On failure the file is left completely untouched and the "
                "error names the problem; when the text is not found the error "
                "includes the closest actual text in the file. Read that, then "
                "retry with the real text. Never retry the same `old_text` "
                "twice, and never fall back to write_file.\n\n"
                "Example — change one line:\n"
                "  old_text: \"    timeout = 30\"\n"
                "  new_text: \"    timeout = 60\"\n\n"
                "Example — insert an import after another:\n"
                "  old_text: \"import os\"\n"
                "  new_text: \"import os\\nimport sys\"\n\n"
                "Example — delete a block:\n"
                "  old_text: \"def unused():\\n    return None\"\n"
                "  new_text: \"\""
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file."
                    },
                    "old_text": {
                        "type": "string",
                        "description": (
                            "The exact existing text to replace, copied "
                            "verbatim from the file including indentation. "
                            "Must match exactly once unless replace_all is set. "
                            "Do not include read_file's 'NNN | ' prefix."
                        )
                    },
                    "new_text": {
                        "type": "string",
                        "description": (
                            "The replacement text. Empty string deletes "
                            "old_text."
                        )
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": (
                            "Replace every occurrence instead of requiring a "
                            "unique match. Only for deliberate rename-style "
                            "changes; defaults to false."
                        )
                    }
                },
                "required": [
                    "path",
                    "old_text",
                    "new_text"
                ]
            }
        }
    }
]

tools = tools + plugin.tools # merge plugin tools

MAX_READ_LINES = 2000 # max reading limit: cutoff when reach.
DIFF_CONTEXT = 2
MAX_DIFF_LINES = 40

_NUMBERED = re.compile(r'^ *(\d+) *\| ?')


def _decode_source(data: bytes):
    """→ (text, newline, bom): Normalize everything to \n for processing, and restore it when writing back.

    The old implementation used read_text() for reading and write_text() for writing. On Windows, 
    this round trip would convert an LF file entirely into CRLF — meaning every edit would silently 
    rewrite the whole file, causing the diff to be full of noise."""

    text = decode_output(data)
    bom = text.startswith('﻿')
    if bom:
        text = text[1:]
    if '\r\n' in text:
        newline = '\r\n'
    elif '\r' in text:
        newline = '\r'
    else:
        newline = '\n'
    return text.replace('\r\n', '\n').replace('\r', '\n'), newline, bom


def _read_source(path: Path):
    text, newline, bom = _decode_source(path.read_bytes())
    if '\x00' in text:
        raise ValueError('Seem like a binary.')
    return text, newline, bom


def _write_source(path: Path, text: str, newline='\n', bom=False):
    if newline != '\n':
        text = text.replace('\n', newline)
    if bom:
        text = '﻿' + text
    path.write_bytes(text.encode('utf-8'))


def _strip_numbering(text: str) -> str:
    """Remove the '%6d | ' line-number prefix inserted by read_file.

    Smaller/weaker models often copy the line-number prefix into old_text,
    causing the replacement match to fail inevitably.
    The prefix is stripped only when all lines contain the prefix and the line
    numbers form a continuous sequence. Since real source code virtually never
    matches both conditions, this avoids accidentally altering code that
    naturally contains the '|' character."""
    rows = text.split('\n')
    numbers = []
    out = []
    for row in rows:
        if not row.strip():
            out.append(row)
            continue
        match = _NUMBERED.match(row)
        if match is None:
            return text
        numbers.append(int(match.group(1)))
        out.append(row[match.end():])
    if len(numbers) < 2:
        return text
    if any(b - a != 1 for a, b in zip(numbers, numbers[1:])):
        return text
    return '\n'.join(out)


def _leading_space(row: str) -> str:
    return row[:len(row) - len(row.lstrip())]


# Three levels of matching with progressively relaxed rules. Start strict and
# loosen gradually, while requiring a unique match at every level — the purpose
# of loosening is to tolerate common whitespace mistakes made by weaker models,
# not to let them guess the correct location.
_NORMALIZERS = (
    ('exact', lambda row: row),
    ('trailing', lambda row: row.rstrip()),
    ('indent', lambda row: row.strip()),
)


def _match_windows(file_rows, anchor_rows, normalize):
    count = len(anchor_rows)
    if count == 0 or count > len(file_rows):
        return []
    target = [normalize(row) for row in anchor_rows]
    body = [normalize(row) for row in file_rows]
    return [i for i in range(len(file_rows) - count + 1)
            if body[i:i + count] == target]


def _relative_shape(rows):
    """The indentation amount of each line relative to the first line.

    The loosest matching level uses strip() on each line, meaning indentation is
    completely ignored — in that case, "if x:" + "return 1" could match an area
    with a completely different structure. Applying one more check using the
    relative indentation pattern preserves the block structure while still
    tolerating cases where the entire block's indentation is shifted by a few
    spaces."""

    base = None
    out = []
    for row in rows:
        if not row.strip():
            out.append(None)
            continue
        indent = len(_leading_space(row).expandtabs(4))
        if base is None:
            base = indent
        out.append(indent - base)
    return out


def _refit_indent(new_rows, anchor_rows, file_rows):
    """Align the indentation of new_text with the actual indentation in the file.

    Weak models often produce indentation that differs by a few spaces. Instead of
    failing the match because of this, shift the indentation of the entire block
    based on the actual indentation at the matched location. When tabs and spaces
    are mixed, it is impossible to infer safely, so return None and let the caller
    raise an error rather than guessing."""
     
    def first_indent(rows):
        for row in rows:
            if row.strip():
                return _leading_space(row)
        return ''

    want = first_indent(file_rows)
    have = first_indent(anchor_rows)
    if want == have:
        return list(new_rows)
    if want.startswith(have):
        pad = want[len(have):]
        return [pad + row if row.strip() else row for row in new_rows]
    if have.startswith(want):
        cut = len(have) - len(want)
        out = []
        for row in new_rows:
            if not row.strip():
                out.append(row)
                continue
            if row[:cut].strip(): # struct not match
                return None  
            out.append(row[cut:])
        return out
    return None


def _nearest_context(file_rows, anchor_rows, span=3):
    """When old_text fails to match, report the closest location in the file with
    line-numbered context.

    The goal is to make failures recoverable: by showing the model the actual file
    content, the next attempt can use the correct old_text instead of repeatedly
    retrying the same invalid anchor."""
    probe = next((row.strip() for row in anchor_rows if row.strip()), '')
    if not probe:
        return None
    best, score = None, 0.0
    for index, row in enumerate(file_rows):
        ratio = difflib.SequenceMatcher(None, probe, row.strip()).ratio()
        if ratio > score:
            best, score = index, ratio
    if best is None or score < 0.5:
        return None
    low = max(0, best - span)
    high = min(len(file_rows), best + span + 1)
    return {
        "closest_line": best + 1,
        "similarity": round(score, 2),
        "actual_text": '\n'.join('%6d | %s' % (i + 1, file_rows[i])
                                 for i in range(low, high)),
    }


def _unified(before: str, after: str, name: str) -> str:
    """Return the changes themselves to the model, so it does not need to read the
    file again to verify the result.

    This also resolves the conflict between the system instructions "do not read
    the file again after editing" and "you must confirm that the edit was correct" —
    the evidence is provided together with the return value."""
    diff = list(difflib.unified_diff(
        before.split('\n'), after.split('\n'),
        fromfile=name, tofile=name, n=DIFF_CONTEXT, lineterm=''))
    if len(diff) > MAX_DIFF_LINES:
        diff = diff[:MAX_DIFF_LINES]
        diff.append('... (diff truncated)')
    return '\n'.join(diff)


def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    include_line_numbers: bool = True
):
    """Read a text file.

    The return value includes the total line count and `truncated`. The model must
    know whether it has seen the complete content; otherwise, it may start making
    changes based on only a partial view of the file.
    """
    target = Path(path)

    if not target.exists():
        raise FileNotFoundError('File not found: %s' % path)

    source, _, _ = _read_source(target)
    rows = source.split('\n')
    if rows and rows[-1] == '':
        rows = rows[:-1]
    total = len(rows)

    start = 0 if start_line is None else max(start_line - 1, 0)
    end = total if end_line is None else min(end_line, total)
    end = max(end, start)

    truncated = False
    if end - start > MAX_READ_LINES:
        end = start + MAX_READ_LINES
        truncated = True

    window = rows[start:end]
    if include_line_numbers:
        body = '\n'.join('%6d | %s' % (start + offset + 1, row)
                         for offset, row in enumerate(window))
    else:
        body = '\n'.join(window)

    return {
        "content": body,
        "total_lines": total,
        "shown": [start + 1, end] if window else [0, 0],
        "truncated": truncated,
    }


def write_file(
    path: str,
    content: str
):
    """Create a new file, or rewrite an entire file.

    Use `edit_file` when modifying an existing file. Having the model rewrite a
    large file from memory will almost certainly cause code to be silently lost,
    and this kind of mistake is completely invisible in the return value — it is
    the most tempting and dangerous fallback after an edit failure. Therefore, this
    function adds a safeguard: overwriting an existing file is rejected if the new
    content is reduced by more than half.
    """
    target = Path(path)
    existed = target.exists()
    previous = None
    newline, bom = '\n', False

    if existed:
        try:
            previous, newline, bom = _read_source(target)
        except Exception:
            previous = None
        if previous is not None:
            old_count = len(previous.split('\n'))
            new_count = len(content.split('\n'))
            if old_count >= 40 and new_count * 2 < old_count:
                return {
                    "success": False,
                    "error": "Write rejected: %s currently has %d lines, but the new content only "
                            "contains %d lines. This usually means code was lost while rewriting "
                            "the file from memory. To modify an existing file, use edit_file to "
                            "make targeted changes. If you really intend to shorten the file, "
                            "delete the file first and then write it again." % (path, old_count, new_count),
                }

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        _write_source(target, content, newline, bom)
    except Exception as error:
        return {"success": False, "error": str(error)}

    result = {
        "success": True,
        "path": str(target),
        "created": not existed,
        "total_lines": len(content.split('\n')),
    }
    if previous is not None and previous != content:
        result["diff"] = _unified(previous, content, str(target))
    return result


def edit_file(
    path: str,
    old_text: str,
    new_text: str = "",
    replace_all: bool = False
):
    """Replace a section of text in a file by matching its content.

    - `old_text` must be the actual original text that exists in the file, and it
    must match uniquely by default.
    - Leaving `new_text` empty deletes the matched text.
    - Insertion does not require a separate mode: simply include the anchor line in
    `new_text` as well — this removes the semantic ambiguity that previously
    depended on whether a parameter was accidentally omitted to switch between
    insert and replace behavior.
    """
    target = Path(path)

    if not target.exists():
        return {"success": False,
                "error": "File does not exist: %s (use write_file to create a new file)" % path}
    if not old_text:
        return {"success": False,
                "error": "`old_text` cannot be empty. To rewrite the entire file, use "
                        "`write_file`; to append at the end, use an existing section "
                        "from the end of the file as `old_text`, then repeat that "
                        "section in `new_text` and append the new content after it."}

    try:
        source, newline, bom = _read_source(target)
    except Exception as error:
        return {"success": False, "error": str(error)}

    old_text = _strip_numbering(old_text)
    new_text = _strip_numbering(new_text)

    file_rows = source.split('\n')
    anchor_rows = old_text.split('\n')
    if len(anchor_rows) > 1 and anchor_rows[-1] == '':
        anchor_rows = anchor_rows[:-1]
    if new_text == '':
        new_rows = []
    else:
        new_rows = new_text.split('\n')
        if len(new_rows) > 1 and new_rows[-1] == '':
            new_rows = new_rows[:-1]

    count = len(anchor_rows)
    mode = None
    hits = []
    for name, normalize in _NORMALIZERS:
        found = _match_windows(file_rows, anchor_rows, normalize)
        if name == 'indent' and found:
            shape = _relative_shape(anchor_rows)
            found = [i for i in found
                     if _relative_shape(file_rows[i:i + count]) == shape]
        if found:
            mode = name
            hits = found
            break

    if not hits:
        payload = {
            "success": False,
            "error": "Could not find old_text in %s. The file was not modified. Use "
                    "read_file to inspect the actual content at that location and copy it "
                    "exactly (including indentation). Do not retry the same text from "
                    "memory." % path,
        }
        hint = _nearest_context(file_rows, anchor_rows)
        if hint:
            payload["closest_match"] = hint
        return payload

    if len(hits) > 1 and not replace_all:
        return {
            "success": False,
            "error": "`old_text` appears %d times in %s, so the target location cannot be "
                    "determined. The file was not modified. Expand `old_text` with enough "
                    "surrounding context to make the match unique; or, if you really "
                    "intend to replace all occurrences, pass `replace_all=true`."
                    % (len(hits), path),
            "match_lines": [i + 1 for i in hits[:20]],
        }

    spans = hits if replace_all else hits[:1]
    result_rows = list(file_rows)

    # Replace from the end to the beginning: modifying earlier positions first
    # would invalidate the indexes of later matches — exactly the old problem with
    # line-number-based addressing.
    for start in sorted(spans, reverse=True):
        window = result_rows[start:start + count]
        block = new_rows
        if mode == 'indent':
            block = _refit_indent(new_rows, anchor_rows, window)
            if block is None:
                return {
                    "success": False,
                    "error": "`old_text` indentation does not match the file, and tabs and spaces "
                            "are mixed, so it cannot be safely aligned. The file was not modified. "
                            "Please copy the indentation exactly as it appears in the file.",
                }
        result_rows[start:start + count] = block

    updated = '\n'.join(result_rows)
    if updated == source:
        return {"success": False,
                "error": "`old_text` and `new_text` are identical. The file was not changed."}

    try:
        _write_source(target, updated, newline, bom)
    except Exception as error:
        return {"success": False, "error": str(error)}

    return {
        "success": True,
        "path": str(target),
        "replacements": len(spans),
        "matched": mode,          # exact / trailing / indent
        "first_line": min(spans) + 1,
        "total_lines": len(result_rows),
        "diff": _unified(source, updated, str(target)),
    }


def format_elapsed(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    else:
        return f"{seconds:.2f}s"


# ═══════════════════════════════════════════════════════════════════════════
# UI — flow rendering on the ascii engine
# ═══════════════════════════════════════════════════════════════════════════

COMMANDS = [
    ('/help', 'Show help and shortcuts'),
    ('/clear', 'Clear screen and start a new session'),
    ('/model', 'View current model'),
    ('/plugin', 'Show all loaded plugins'),
    ('/exit', 'Exit Lit'),
]

TOOL_VERBS = {
    'shell_command': 'Run',
    'read_file': 'Read',
    'write_file': 'Write',
    'edit_file': 'Edit'
}

for i, v in plugin.functions.items(): # merge from plugin
    TOOL_VERBS[i] = v['verb']

PLACEHOLDER = 'Ask anything, or task an agent…'

PREVIEW_LINES = 2

# Number of turns for which the bottom shortcut hint is displayed
# (progressive disclosure: it should disappear once the user has learned it).
HINT_TURNS = 3

def _short(text, limit=64):
    line = str(text).split('\n', 1)[0].strip()
    if len(line) > limit:
        return line[:limit - 1] + '…'
    return line


def hint_bar(left, right, width):
    left = ascii.truncate_spans(
        left, max(4, width - ascii.spans_width(right) - 3))
    gap = width - 1 - ascii.spans_width(left) - ascii.spans_width(right)
    return [*left, (' ' * max(1, gap), None), *right]


def base_rail(width, head=16):
    """Static bottom border line below the input box: a short warm-colored segment
    on the left side (aligned with the prompt), fading into dark gray toward the
    right.

    Previously this was a bright bar sweeping back and forth at 26 characters per
    second. Because it stayed permanently below the input box, there was always
    something moving in the user's peripheral vision while they paused to think.
    Continuous peripheral motion creates a sense of unfinished urgency, making it
    hard to relax. A static line can provide the same visual closure for this
    L-shaped frame."""
    width = max(1, width)
    head = min(head, width)
    spans = ascii.gradient_spans('─' * head, [ROSE, GOLD])
    if width > head:
        spans.append(('─' * (width - head), Style(fg=GOLD)))
    return spans


class ToolCard:
    """One tool invocation: an animated running line, then a permanent
    transcript card with a result preview."""

    def __init__(self, name, args):
        self.name = name
        self.args = args or {}
        self.verb = TOOL_VERBS.get(name, name)
        self.summary = self._summary()
        self.started = time.monotonic()
        self.done = False
        self.ok = True
        self.elapsed = 0.0
        self.preview = []
        self.hidden = 0  # Number of preview lines that are collapsed

    def _summary(self):
        args = self.args
        if self.name == 'shell_command':
            return _short(args.get('command', ''))
        if self.name == 'read_file':
            text = str(args.get('path', ''))
            if args.get('start_line') or args.get('end_line'):
                text += ' [%s~%s]' % (args.get('start_line') or 1,
                                      args.get('end_line') or 'end')
            return text
        if self.name == 'write_file':
            return '%s (%d char)' % (args.get('path', ''),
                                    len(str(args.get('content', ''))))
        if self.name == 'edit_file':
            def rows(text):
                text = str(text)
                return len(text.rstrip('\n').split('\n')) if text.strip() else 0
            old = rows(args.get('old_text', ''))
            new = rows(args.get('new_text', ''))
            if not old:
                # The model called using the old signature (start_line/end_line) — do not invent
                # a "delete 0 lines" operation. Show only the path truthfully; the error details
                # are explained in the preview.
                return str(args.get('path', ''))
            if not new:
                operation = 'Delete %d line' % old
            elif old == new:
                operation = 'Modify %d line' % old
            else:
                operation = '%d → %d line' % (old, new)
            if args.get('replace_all'):
                operation += ' · All'
            return '%s  %s' % (args.get('path', ''), operation)
        if self.name in plugin.functions:
            strings = ''

            for k, v in self.args.items():
                strings += f'{k}: "{v}",'
            
            return _short(strings)
        
        return ''

    def live_line(self, t):
        color = ascii.sample_gradient(EMBER, 0.5 + 0.5 * math.sin(t * 3.0))
        parts = [(ascii.spinner_frame('arc', t) + ' ', Style(fg=color, bold=True)),
                 (self.verb, Style(fg=TEXT, bold=True))]
        if self.summary:
            parts.append(('  ' + self.summary, S_MUTED))
        parts.append(('  ' + format_elapsed(time.monotonic() - self.started),
                      S_FAINT))
        return parts

    def finish(self, result):
        self.elapsed = time.monotonic() - self.started
        self.ok, self.preview = self._analyze(result or {})
        self.done = True

    def _analyze(self, result):
        # The purpose of the preview is to let people confirm that "nothing went
        # wrong", not to make them read the output here.
        # A half-truncated four-line snippet is awkward: it is neither understandable
        # nor complete, and forces the brain to fill in the missing parts — which is
        # more cognitively demanding than a clean line-count summary. Therefore, keep
        # only two lines and collapse the rest into a count.
        ok = True
        preview = []
        total = [0]
        soft_err = Style(fg=(224, 122, 122))

        def add(text, style=S_FAINT, cap=PREVIEW_LINES):
            rows = [line.rstrip() for line in str(text).strip().split('\n')
                    if line.strip()]
            total[0] += len(rows)
            for line in rows[:cap]:
                preview.append((line, style))

        if self.name == 'shell_command':
            ok = result.get('returncode') == 0
            out = (result.get('stdout') or '').strip()
            err = (result.get('stderr') or '').strip()
            if out:
                add(out)
            if err:
                add(err, soft_err, cap=2)
            if not out and not err:
                preview.append(('(No output)', S_FAINT(italic=True)))
        elif self.name == 'read_file':
            ok = bool(result.get('success'))
            if ok:
                # Show "which section was read / how many lines the file has", rather than only
                # "how many lines were read" — make it visible whether the Agent edited after
                # only taking a quick glance.
                total_rows = result.get('total_lines', 0)
                low, high = (result.get('shown') or [0, 0])[:2]
                if low <= 1 and high >= total_rows:
                    label = '%d line' % total_rows
                else:
                    label = '%d~%d line · Total %d' % (low, high, total_rows)
                if result.get('truncated'):
                    label += ' · Truncated'
                preview.append((label, S_FAINT))
            else:
                add(result.get('error', ''), soft_err)
        elif self.name in ('write_file', 'edit_file'):
            ok = bool(result.get('success'))
            if not ok:
                add(result.get('error', ''), soft_err)
            else:
                rows = (result.get('diff') or '').split('\n')
                plus = sum(1 for row in rows
                           if row[:1] == '+' and row[:3] != '+++')
                minus = sum(1 for row in rows
                            if row[:1] == '-' and row[:3] != '---')
                bits = []
                if plus or minus:
                    bits.append('+%d -%d' % (plus, minus))
                if result.get('created'):
                    bits.append('Created %d line' % result.get('total_lines', 0))
                if result.get('replacements', 1) > 1:
                    bits.append('%d places' % result['replacements'])
                # 命中方式暴露出来：indent 意味着模型的缩进本来是错的，工具替它
                # 兜住了。看得见，才知道该不该去改提示词。
                if result.get('matched') in ('trailing', 'indent'):
                    bits.append('Fuzzy matching (%s)' % result['matched'])
                if bits:
                    preview.append(('  ·  '.join(bits), S_FAINT))
        elif self.name == 'get_client_system':
            ok = bool(result.get('success'))
            data = result.get('data') or {}
            if ok:
                preview.append(('%s %s · Python %s' % (
                    data.get('os', '?'), data.get('release', '?'),
                    data.get('python_version', '?')), S_FAINT))
            else:
                add(result.get('error', ''), soft_err)
        elif self.name == 'get_current_time':
            ok = bool(result.get('success'))
            data = result.get('data') or {}
            if ok:
                preview.append((str(data.get('local_time', '')), S_FAINT))
            else:
                add(result.get('error', ''), soft_err)
        elif self.name in plugin.functions:
            ok = bool(result.get('success'))
            output = result.get('output') or {}
            if isinstance(output, dict):
                if output.get('status') == 'error':
                    ok = False
                if output.get('error'):
                    add(output.get('error'), soft_err, cap=2)
                if output.get('output'):
                    add(output.get('output'))
            if not ok and result.get('error'):
                add(result.get('error'), soft_err)
        else:
            if result.get('error'):
                ok = False
                add(result.get('error'), soft_err)
        shown = preview[:PREVIEW_LINES]
        self.hidden = max(0, total[0] - len(shown))
        return ok, shown

    def final_lines(self, width):
        dot = ('● ', S_OK if self.ok else S_ERR)
        parts = [dot, (self.verb, Style(fg=TEXT, bold=True))]
        if self.summary:
            parts.append(('  ' + self.summary, S_MUTED))
        parts.append(('  (%s)' % format_elapsed(self.elapsed), S_FAINT))
        lines = [ascii.truncate_spans(parts, width)]
        for index, (text, style) in enumerate(self.preview):
            prefix = '  ⎿  ' if index == 0 else '     '
            lines.append(ascii.truncate_spans(
                [(prefix, S_FAINT), (text, style)], width))
        if self.hidden:
            prefix = '  ⎿  ' if not self.preview else '     '
            lines.append([(prefix, S_FAINT),
                          ('… %d more lines' % self.hidden, S_FAINT(italic=True))])
        return lines


class TurnView:
    """Live view of one agent turn: streaming reasoning + markdown with
    progressive commit into the transcript, tool cards, and a status bar."""

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.started = time.monotonic()
        term_width, _ = app.screen.size()
        # width is the *content* width; the 2-cell agent gutter is added on top
        self.width = max(24, min(term_width - 4, CONTENT_WIDTH))
        self.phase = 'ignite'
        self.reason_text = ''
        self.reason_started = None
        self.content = ''
        self.committed_lines = 0
        self.committed_len = 0
        self._cache = (0, [])
        self.tool_card = None
        self.tool_count = 0
        self.header_done = False
        self.trailing_blank = True  # Whether the submitted content ends with a blank line (used by _separate)
        self.interrupted = False
        self.cancelling = False
        self.error = None
        self.done = False

    # ------------------------------------------------- agent-tier framing
    def _gut(self, line):
        """Prefix one span-line with the agent gutter (cool left rule)."""
        return [(GUTTER, S_AGENT_GUTTER), *line]

    def emit_header(self):
        """Commit the agent block header once (◈ Lit · model)."""
        with self.lock:
            if self.header_done:
                return
            self.header_done = True
        head = [('◈ ', S_AGENT(bold=True)), ('Lit', Style(fg=TEXT, bold=True))]

        if self.app.turns <= 1:
            head.append(('  ' + model, S_FAINT))
        self.app.screen.append(head)

    def _commit(self, *lines):
        """Commit agent lines to the transcript, guttered under the header."""
        if not lines:
            return
        self.emit_header()
        self.app.screen.append(*[self._gut(line) for line in lines])
        self.trailing_blank = not lines[-1]

    def _separate(self):
        """One empty line between two different blocks (思考 / 正文 / 工具卡)。

        This is the core of the change: blocks always have one blank line between
        them, while lines inside a block stay adjacent. Spacing is no longer arbitrary;
        it communicates whether elements belong together. Users can recognize section
        boundaries visually without reading every word."""
        if not self.trailing_blank:
            self._commit([])

    # ------------------------------------------------------------- content
    def _render_full(self):
        if self._cache[0] != len(self.content):
            self._cache = (len(self.content),
                           ascii.render_markdown(self.content, self.width,
                                                 MD_THEME))
        return self._cache[1]

    def new_segment(self):
        with self.lock:
            had_content = bool(self.content.strip())
            self.content = ''
            self.committed_lines = 0
            self.committed_len = 0
            self._cache = (0, [])
            if self.phase not in ('tool',):
                self.phase = 'ignite'
        if had_content:
            self._separate()

    def push_content(self, delta):
        fresh = []
        opening = False
        with self.lock:
            self.content += delta
            self.phase = 'stream'
            stable, _ = ascii.markdown_stable_cut(self.content)
            if len(stable) > self.committed_len:
                lines = ascii.render_markdown(stable, self.width, MD_THEME)
                fresh = lines[self.committed_lines:]
                opening = self.committed_lines == 0
                self.committed_lines = len(lines)
                self.committed_len = len(stable)
        if fresh:
            if opening:
                self._separate()
            self._commit(*fresh)

    def finish_content(self):
        fresh = []
        opening = False
        with self.lock:
            if self.content.strip():
                lines = self._render_full()
                fresh = lines[self.committed_lines:]
                opening = self.committed_lines == 0
                self.committed_lines = len(lines)
                self.committed_len = len(self.content)
        if fresh:
            if opening:
                self._separate()
            self._commit(*fresh)

    # ------------------------------------------------------------ reasoning
    def push_reason(self, delta):
        with self.lock:
            if self.reason_started is None:
                self.reason_started = time.monotonic()
            self.reason_text += delta
            self.phase = 'reason'

    def finish_reason(self):
        line = None
        with self.lock:
            if self.reason_started is not None:
                elapsed = time.monotonic() - self.reason_started
                self.reason_started = None
                line = [('✻ ', S_GOLD),
                        ('Thought %s' % format_elapsed(elapsed),
                         Style(fg=MUTED, italic=True))]
        if line:
            self._separate()
            self._commit(line)

    # ---------------------------------------------------------------- tools
    def begin_tool(self, card):
        with self.lock:
            self.tool_card = card
            self.tool_count += 1
            self.phase = 'tool'

    def end_tool(self, card):
        self._separate()
        self._commit(*card.final_lines(self.width))
        with self.lock:
            self.tool_card = None
            self.phase = 'plan'

    # ----------------------------------------------------------------- live
    # These two lines used to have separate 22-character bouncing animations.
    # Combined with the status bar's reactor and flux animations, the screen could
    # contain four independent motion sources competing for attention. Motion is
    # now limited to a single source (the status bar); these lines are static and
    # only communicate "what is happening". The status bar alone provides the
    # indication that the system is active.
    def _thinking_row(self, t):
        elapsed = time.monotonic() - (self.reason_started or time.monotonic())
        return self._gut([('✻ ', S_GOLD),
                          ('Thinking ', Style(fg=TEXT, bold=True)),
                          ('  ' + format_elapsed(elapsed), S_FAINT)])

    def _tool_row(self, card, t):
        label = [('◌ ', S_GOLD), (card.verb, Style(fg=TEXT, bold=True))]
        if card.summary:
            label.append(('  ' + card.summary, S_MUTED))
        label.append(('  ' + format_elapsed(time.monotonic() - card.started),
                      S_FAINT))
        return self._gut(ascii.truncate_spans(label, self.width))

    def live(self, t, w, h):
        with self.lock:
            lines = []
            if self.reason_started is not None:
                lines.append(self._thinking_row(t))
                lines.append(self._gut([]))
            if self.content and self.phase == 'stream':
                tail = self._render_full()[self.committed_lines:]
                if tail:
                    for row in tail[-max(2, h - 7):]:
                        lines.append(self._gut(row))
                    lines.append(self._gut([]))
            card = self.tool_card
            if card is not None and not card.done:
                lines.append(self._tool_row(card, t))
                lines.append(self._gut([]))
            lines.append(self._status_line(t, w))
            return lines

    def snapshot_live(self, t, w, h):
        with self.lock:
            return [self._status_line(t, w)]

    def _status_line(self, t, w=None):
        # The bottom instrument bar — the reactor spinner and the flux waveform.
        # It is the only motion source on the entire screen, so it stays. But the
        # surrounding elements are reduced: verbs no longer shimmer (the waveform is
        # already moving, and animated text on the same line creates two overlapping
        # motion sources, making the text harder to read).
        # The waveform is shortened from 22 characters to 14, and "esc to interrupt"
        # now appears only after 2 seconds — responses that finish within a second never
        # need it, and keeping it permanently visible only consumes attention budget.
        elapsed = time.monotonic() - self.started
        if self.cancelling:
            stops = [ROSE, (255, 128, 150)]
            verb = 'Interrupting'
            energy = 0.5
        else:
            stops = EMBER
            verb = {
                'ignite': 'Igniting...',
                'reason': 'Thinking...',
                'stream': 'Responding...',
                'tool': 'Executing...',
                'plan': 'Planning...'
            }.get(self.phase, 'Thinking')

            energy = {'ignite': 1.15, 'reason': 1.0, 'stream': 0.62,
                      'tool': 0.85, 'plan': 0.5}.get(self.phase, 0.8)
        head = ascii.sample_gradient(stops, ascii.breath(t, 0.0, 1.0, 1.4))
        # parts = [(ascii.spinner_frame('dots', t) + ' ',
        #           Style(fg=head, bold=True))]
        parts = []
        
        span = FLUX_SPAN if w is None else max(6, min(FLUX_SPAN, w // 4))
        parts.append((verb, Style(fg=MUTED, bold=True)))
        parts.append(('  ', None))
        parts += ascii.flux_spans(span, t, stops, energy=energy)
        parts.append(('  ' + format_elapsed(elapsed), S_FAINT))
        if self.tool_count:
            if self.tool_count > 1:
                parts.append((' · %d Tools' % self.tool_count, S_FAINT))
            else:
                parts.append((' · %d Tool' % self.tool_count, S_FAINT))
        if elapsed > 2.0:
            parts.append(('   ESC To Interrupt', S_FAINT))
        return parts


class LitApp:
    def __init__(self):
        self.screen = ascii.Screen(fps=24)
        self.field = ascii.TextField()
        self.messages = [{"role": "system", "content": system}]
        self.cancel = threading.Event()
        self._ctrl_c_deadline = 0.0
        self.notice = ''
        self.notice_until = 0.0
        self.turns = 0

    # ------------------------------------------------------------- helpers
    # def save_chat(self):
    #     try:
    #         with open('chat.json', 'w', encoding='utf-8') as f:
    #             f.write(json.dumps(indent=2, ensure_ascii=False,
    #                                obj=self.messages[1:]))
    #     except Exception:
    #         pass

    def set_notice(self, text, seconds=1.8):
        self.notice = text
        self.notice_until = time.monotonic() + seconds

    def echo_lines(self, text):
        # Keep one blank line before and after: together with the line at the end of
        # run_turn, this creates a 2-line gap between turns —
        # the largest spacing in the entire layout. As a result, it naturally becomes
        # the strongest separator, allowing the eye to find where the previous turn
        # begins without reading the content.
        width, _ = self.screen.size()
        wrapped = ascii.wrap_spans([(text, Style(fg=TEXT, bold=True))],
                                   max(20, min(width - 4, CONTENT_WIDTH)))
        lines = [[]]
        for index, row in enumerate(wrapped):
            prefix = ('❯ ', S_ACCENT(bold=True)) if index == 0 else ('  ', None)
            lines.append([prefix, *row])
        lines.append([])
        return lines

    # -------------------------------------------------------------- splash
    def splash_lines(self, phase=None):
        rows = logo.split('\n')
        logo_width = max(ascii.spans_width([(row, None)]) for row in rows)
        info = [
            [],
            [('ø ', S_DIM), ('Omega Labs', Style(fg=SILVER, bold=True))],
            [('Lit. ', S_TEXT), ('(v0.2.0)', S_DIM)],
            [],
            [('Supercharged by', S_DIM)],
            [(model, S_MUTED)],
        ]
        while len(info) < len(rows):
            info.append([])
        info_width = max(ascii.spans_width(line) for line in info)
        content = []
        for index, row in enumerate(rows):
            row = row + ' ' * (logo_width - ascii.spans_width([(row, None)]))
            row_phase = None if phase is None else phase + index * 0.05
            left = ascii.gradient_spans(row, EMBER, phase=row_phase)
            content.append([*left, ('   ', None), *info[index]])
        box = ascii.box_lines(content, logo_width + info_width + 9,
                              style=S_FAINT, pad=2)
        # tips = [('  ', None), ('✦ ', S_ACCENT),
        #         ('Start task · ', S_DIM), ('/', Style(fg=GOLD, bold=True)),
        #         (' Commands · ', S_DIM), ('esc', S_GOLD), (' Interrupt · ', S_DIM),
        #         ('ctrl+c', S_GOLD), (' Quit', S_DIM)]
        return [[], *box, []]

    def play_splash(self, events):
        start = time.monotonic()

        def live(t, w, h):
            return self.splash_lines(phase=(time.monotonic() - start) * 0.55)

        self.screen.set_live(live)
        deadline = start + 1.6
        while time.monotonic() < deadline:
            event = events.get_event(timeout=0.05)
            if event is None:
                continue
            if event.type == 'resize':
                self.screen.handle_resize()
            elif event.type == 'key' and event.action == 'down':
                break
        self.screen.clear_live(*self.splash_lines(phase=None))

    # --------------------------------------------------------------- input
    def _inner_width(self):
        width, _ = self.screen.size()
        return min(width - 2, INPUT_WIDTH) - 4

    def _caret(self, t):
        # Previously, the color pulsed between gold and rose at 5Hz. The blinking itself
        # is already enough to communicate "this is the cursor"; making the color
        # animate as well creates a motion source that carries no additional information.
        return Style(fg=(18, 20, 26), bg=GOLD, bold=True)

    def _cursor_row(self, chars, ccol, t, focused=True):
        on = focused and (int(t * 2.2) % 3) != 2
        caret = self._caret(t)
        spans = []
        used = 0
        placed = False
        for char in chars:
            char_width = max(1, ascii._char_width(char))
            if not placed and used == ccol and on:
                spans.append((char, caret))
                placed = True
            else:
                spans.append((char, S_TEXT))
            used += char_width
        if not placed and on:
            spans.append((' ', caret))
        return spans

    def input_lines(self, t, w, matches, selected):
        # No box. The frame is an open L: a gradient spine down the left and a rail
        # across the bottom. Both are static now — the input box is a place to "pause
        # and think", so nothing should be moving there.
        width = max(30, min(w - 2, INPUT_WIDTH))
        inner = width - 4
        rows, cursor_row, cursor_col = self.field.layout(inner)
        max_rows = 8
        if len(rows) <= max_rows:
            start = 0
        else:
            start = min(max(0, cursor_row - max_rows + 1),
                        len(rows) - max_rows)
        visible = rows[start:start + max_rows]
        total = max(1, len(visible))

        lines = []
        if matches:
            selected = min(selected, len(matches) - 1)
            lines.append([])
            for index, (command, description) in enumerate(matches):
                active = index == selected
                marker = ('▸ ', S_ACCENT(bold=True)) if active else ('  ', None)
                command_style = Style(fg=GOLD, bold=True) if active else S_MUTED
                description_style = S_TEXT if active else S_FAINT
                lines.append([('   ', None), marker,
                              ('%-9s' % command, command_style),
                              ('  ' + description, description_style)])
            lines.append([])

        for offset, row in enumerate(visible):
            abs_row = start + offset
            spine = ascii.spine_cell(offset, total, 0.0, EMBER)
            if abs_row == 0:
                mark = ('❯ ', S_ACCENT(bold=True))
            else:
                mark = ('  ', None)
            if not self.field.chars and abs_row == 0:
                on = (int(t * 2.2) % 3) != 2
                caret = [(' ', self._caret(t))] if on else []
                body = [*caret, (PLACEHOLDER, S_FAINT(italic=True))]
            elif abs_row == cursor_row:
                body = self._cursor_row(row, cursor_col, t)
            else:
                body = [(''.join(row), S_TEXT)] if row else []
            lines.append([spine, (' ', None), mark, *body])

        lines.append(base_rail(width))

        # Shortcut hints are information that "only needs to be learned once". Keeping
        # them permanently visible means every screen forces users to review something
        # they already know, wasting attention budget. Show them for the first few
        # turns, then collapse them; also collapse them when the input box already
        # contains content (at that point users are thinking about what to write, not
        # looking for entry points).
        # Keep the line itself always present to avoid layout shifts caused by
        # appearing/disappearing — jitter is more annoying than the hint itself.
        now = time.monotonic()
        if self.notice and now < self.notice_until:
            left = [('  ✱ ', S_WARN), (self.notice, S_WARN)]
        elif self.turns < HINT_TURNS and not self.field.chars:
            left = [('  ', None), ('/', S_ACCENT), (' Command · ', S_FAINT),
                    ('↑↓', S_MUTED), (' History · ', S_FAINT),
                    ('Ctrl+C', S_MUTED), (' Exit', S_FAINT)]
        else:
            left = [('  ', None)]
        right = [(model + ' ', S_FAINT)]
        lines.append(hint_bar(left, right, width))
        return lines

    def read_prompt(self, events):
        self.field.clear()
        menu = {'sel': 0}

        def matches():
            text = self.field.text
            if not text.startswith('/') or ' ' in text or '\n' in text:
                return []
            return [c for c in COMMANDS if c[0].startswith(text)]

        def live(t, w, h):
            return self.input_lines(t, w, matches(), menu['sel'])

        self.screen.set_live(live)
        while True:
            event = events.get_event(timeout=0.2)
            if event is None:
                continue
            if event.type == 'resize':
                self.screen.handle_resize()
                continue
            if event.type == 'mouse':
                continue
            if event.type == 'key' and event.action == 'down':
                key = event.key or ''
                ctrl = event.ctrl or key.startswith('ctrl_')
                plain = key.removeprefix('ctrl_')
                if ctrl and plain in ('c', 'd'):
                    now = time.monotonic()
                    if now < self._ctrl_c_deadline:
                        self.screen.clear_live()
                        return None
                    self._ctrl_c_deadline = now + 1.6
                    self.set_notice('Press Ctrl+C again to exit')
                    self.screen.paint()
                    continue

            with self.screen.lock:
                action = self.field.feed(event)
            current = matches()

            if action == 'submit':
                if current:
                    text = current[min(menu['sel'], len(current) - 1)][0]
                else:
                    text = self.field.text
                if not text.strip():
                    continue
                self.field.history_add(text)
                self.screen.clear_live(*self.echo_lines(text.strip()))
                return text
            if action in ('up', 'down'):
                delta = -1 if action == 'up' else 1
                with self.screen.lock:
                    if current:
                        menu['sel'] = (menu['sel'] + delta) % len(current)
                    elif '\n' in self.field.text:
                        self.field.move_vertical(delta, self._inner_width())
                    elif action == 'up':
                        self.field.history_prev()
                    else:
                        self.field.history_next()
            elif action == 'tab':
                if current:
                    with self.screen.lock:
                        self.field.set_text(
                            current[min(menu['sel'], len(current) - 1)][0])
            elif action == 'escape':
                with self.screen.lock:
                    if self.field.text:
                        self.field.clear()
                        menu['sel'] = 0
            elif action == 'changed':
                menu['sel'] = 0
            self.screen.paint()

    # ------------------------------------------------------------ commands
    def run_command(self, text):
        name = text.split()[0].lower()
        if name == '/exit':
            return 'exit'
        if name == '/model':
            self.screen.append(
                [('  Model  ', S_DIM), (model, S_TEXT)],
                [('  Endpoint  ', S_DIM), ('ark.cn-beijing.volces.com', S_MUTED)],
                [])
        elif name == '/plugin':
            self.screen.append([("List of installed plugins:", S_TEXT)])

            for i in plugin.plugins:
                self.screen.append([(f"  {i}:", S_TEXT)])
                for j in plugin.functions:
                    if i in j:
                        print(f'  {j}')

                self.screen.append([])

        elif name == '/clear':
            self.messages = [{"role": "system", "content": system}]
            self.screen.clear_screen()
            self.screen.append(*self.splash_lines(phase=None))
            self.screen.append([('  ✦ Context cleared', S_OK)], [])
        elif name == '/help':
            shortcuts = [
                ('ESC', 'Interrupt / Clear input'),
                ('Ctrl+C', 'Exit Lit'),
                ('↑ ↓', 'History / Select menu item'),
                ('Tab', 'Auto-complete command'),
                ('alt+enter', 'New line (Windows: shift+enter also works)'),
                ('ctrl+← →', 'Jump by word'),
                ('ctrl+u / k / w', 'Delete to start / end / Delete word'),
                ('home / end', 'Start / End of line'),
            ]
            lines = [[],
                     [('  ', None),
                      *ascii.gradient_spans('Command', EMBER,
                                            style=Style(bold=True))]]
            for command, description in COMMANDS:
                lines.append([('    %-9s ' % command, S_ACCENT),
                              (description, S_MUTED)])
            lines.append([])
            lines.append([('  ', None),
                          *ascii.gradient_spans('Shortcut', EMBER,
                                                style=Style(bold=True))])
            for keys, description in shortcuts:
                lines.append([('    %-16s ' % keys, S_TEXT),
                              (description, S_MUTED)])
            lines.append([])
            self.screen.append(*lines)
        else:
            self.screen.append(
                [('  Unknown command %s · /help View all commands.' % name, S_WARN)], [])
        return None

    # ---------------------------------------------------------------- turn
    def dispatch_tool(self, view, tc):
        name = tc["name"]
        try:
            args = json.loads(tc["arguments"] or '{}')
            if not isinstance(args, dict):
                raise ValueError('arguments must be a JSON object')
        except Exception as error:
            card = ToolCard(name, {})
            view.begin_tool(card)
            result = {"success": False,
                      "error": "invalid tool arguments: %s" % error}
            card.finish(result)
            view.end_tool(card)
            return result

        card = ToolCard(name, args)
        view.begin_tool(card)
        try:
            if name == 'shell_command':
                result = run_powershell(args["command"], self.cancel)
            elif name == 'read_file':
                try:
                    result = {"success": True,
                              **read_file(args["path"], args.get("start_line"),
                                          args.get("end_line"))}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
            elif name == 'write_file':
                try:
                    result = write_file(args["path"], args["content"])
                except Exception as e:
                    result = {"success": False, "error": str(e)}
            elif name == 'edit_file':
                # Models often carry assumptions from other harnesses and may still pass
                # start_line. Instead of raising a TypeError, clearly explain the new API
                # contract. A single actionable error is better than a series of confusing
                # exceptions.
                if 'old_text' not in args and (
                        'start_line' in args or 'end_line' in args
                        or 'content' in args):
                    result = {
                        "success": False,
                        "error": "edit_file now uses content-based matching: please provide "
                                "old_text and new_text. start_line / end_line / content are no longer "
                                "accepted. First use read_file to get the original text to modify, "
                                "remove the line number prefixes, and copy it exactly into old_text.",
                    }
                else:
                    try:
                        result = edit_file(
                            args["path"], args.get("old_text", ""),
                            args.get("new_text", ""),
                            bool(args.get("replace_all", False)))
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
            elif name in plugin.functions:
                func = plugin.functions.get(name)['function']

                try:
                    result = {"success": True,
                              "output": func(**args)}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
            else:
                result = {"success": False, "error": f"Unknown tool: {name}"}
        except Exception as error:
            result = {"success": False, "error": str(error)}
        card.finish(result)
        view.end_tool(card)
        return result

    def turn_worker(self, view):
        try:
            while True:
                view.new_segment()
                response = client.chat.completions.create(
                    model=model_id,
                    messages=self.messages,
                    tools=tools,
                    stream=True
                )
                tool_calls = {}
                interrupted = False
                for chunk in response:
                    if self.cancel.is_set():
                        interrupted = True
                        try:
                            response.close()
                        except Exception:
                            pass
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, 'reasoning_content', None)
                    if reasoning:
                        view.push_reason(reasoning)
                    if delta.content:
                        view.finish_reason()
                        view.push_content(delta.content)
                    if delta.tool_calls:
                        view.finish_reason()
                        with view.lock:
                            if view.phase in ('ignite', 'reason'):
                                view.phase = 'plan'
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls:
                                tool_calls[idx] = {
                                    "id": tc.id, "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls[idx]["id"] = tc.id
                            if tc.function.name:
                                tool_calls[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[idx]["arguments"] += \
                                    tc.function.arguments
                view.finish_reason()
                view.finish_content()

                if interrupted:
                    if view.content.strip():
                        self.messages.append(
                            {"role": "assistant", "content": view.content})
                    view.interrupted = True
                    return

                if not tool_calls:
                    self.messages.append(
                        {"role": "assistant", "content": view.content})
                    return

                assistant_message = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"]
                            }
                        }
                        for tc in tool_calls.values()
                    ]
                }
                if view.content.strip():
                    assistant_message["content"] = view.content
                self.messages.append(assistant_message)

                for tc in tool_calls.values():
                    if self.cancel.is_set():
                        view.interrupted = True
                        result = {"success": False,
                                  "error": "interrupted by user"}
                    else:
                        result = self.dispatch_tool(view, tc)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False)
                    })
                if view.interrupted:
                    return
        except Exception as error:
            view.error = error
        finally:
            view.done = True

    def run_turn(self, events, text):
        self.messages.append({"role": "user", "content": text})
        self.turns += 1
        view = TurnView(self)
        self.cancel.clear()
        worker = threading.Thread(target=self.turn_worker, args=(view,),
                                  daemon=True)
        self.screen.set_live(view.live)
        view.emit_header()
        worker.start()
        while worker.is_alive():
            event = events.get_event(timeout=0.1)
            if event is None:
                continue
            if event.type == 'resize':
                self.screen.handle_resize()
                continue
            if event.type != 'key' or event.action != 'down':
                continue
            key = event.key or ''
            ctrl = event.ctrl or key.startswith('ctrl_')
            plain = key.removeprefix('ctrl_')
            if key == 'escape':
                self.cancel.set()
                view.cancelling = True
            elif ctrl and plain in ('c', 'd'):
                now = time.monotonic()
                if now < self._ctrl_c_deadline:
                    raise KeyboardInterrupt
                self._ctrl_c_deadline = now + 1.6
                self.cancel.set()
                view.cancelling = True
        worker.join()
        self._fold_out(view.snapshot_live(self.screen.now(),
                                          *self.screen.size()))
        self.screen.clear_live()
        if view.interrupted:
            view._separate()
            self.screen.append(view._gut([('● Interrupted', S_WARN)]), [])
        elif view.error is not None:
            view._separate()
            self.screen.append(
                view._gut([('● Error ', S_ERR(bold=True)),
                           (_short(str(view.error), max(24, view.width - 8)),
                            S_ERR)]), [])
        elif not view.trailing_blank:
            self.screen.append([])

    def _fold_out(self, lines, duration=0.24):
        """Retract the live block with a short fold instead of a hard cut."""
        if not lines:
            return
        start = self.screen.now()

        def live(t, w, h):
            return ascii.fold_lines(lines, (t - start) / duration)

        self.screen.set_live(live)
        time.sleep(duration + 0.05)

    # ----------------------------------------------------------------- run
    def run(self):
        self.screen.start()
        try:
            with ascii.TerminalEventDispatcher(mouse=False) as events:
                self.play_splash(events)
                while True:
                    # self.save_chat()
                    text = self.read_prompt(events)
                    if text is None:
                        break
                    stripped = text.strip()
                    if not stripped:
                        continue
                    if stripped.lower() in ('exit', 'quit', 'q'):
                        break
                    if stripped.startswith('/'):
                        if self.run_command(stripped) == 'exit':
                            break
                        continue
                    self.run_turn(events, text)
        except KeyboardInterrupt:
            pass
        finally:
            self.screen.clear_live()
            self.screen.stop()
            sys.stdout.write('\n')
            sys.stdout.flush()


def main():
    LitApp().run()


if __name__ == '__main__':
    main()
