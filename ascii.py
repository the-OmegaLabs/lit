# Terminal Controlling

import sys
import shutil
import os
import math
import time
import queue
import threading
import re
from typing import Literal
import wcwidth
from dataclasses import dataclass


Color = tuple[int, int, int] | None


@dataclass(slots=True)
class FrameCell:
    """One terminal cell. Wide characters are present in both occupied cells."""

    char: str = ' '
    foreground: Color = None
    background: Color = None
    continuation: bool = False

    def copy(self):
        return FrameCell(self.char, self.foreground, self.background, self.continuation)


class FrameBuffer:
    """A readable, writable grid of terminal cells.

    Coordinates are zero based. Rectangle end coordinates are exclusive.
    ``cells`` (and ``buffer``) can be indexed directly as ``cells[y][x]``.
    """

    def __init__(self, width: int, height: int, fill: str = ' '):
        if width < 0 or height < 0:
            raise ValueError('framebuffer dimensions must not be negative')
        if wcwidth.wcswidth(fill) != 1:
            raise ValueError('fill must occupy exactly one terminal cell')
        self.width = width
        self.height = height
        self.cells = [[FrameCell(fill) for _ in range(width)] for _ in range(height)]
        self.buffer = self.cells

    def __getitem__(self, y):
        return self.cells[y]

    @staticmethod
    def _width(char: str) -> int:
        return max(0, wcwidth.wcwidth(char))

    def _clear_wide_at(self, x: int, y: int):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        cell = self.cells[y][x]
        if cell.continuation and x > 0:
            self.cells[y][x - 1] = FrameCell()
        elif self._width(cell.char) == 2 and x + 1 < self.width:
            right = self.cells[y][x + 1]
            if right.continuation and right.char == cell.char:
                self.cells[y][x + 1] = FrameCell()
        self.cells[y][x] = FrameCell()

    def put(self, x: int, y: int, char: str, foreground: Color = None,
            background: Color = None) -> int:
        """Write one character and return the number of occupied cells."""
        if len(char) != 1:
            raise ValueError('put expects exactly one character')
        width = self._width(char)
        if width == 0:
            return 0
        if not (0 <= x < self.width and 0 <= y < self.height):
            return width
        if width == 2 and x + 1 >= self.width:
            return width
        self._clear_wide_at(x, y)
        if width == 2:
            self._clear_wide_at(x + 1, y)
        self.cells[y][x] = FrameCell(char, foreground, background, False)
        if width == 2:
            self.cells[y][x + 1] = FrameCell(char, foreground, background, True)
        return width

    def write(self, x: int, y: int, content, foreground: Color = None,
              background: Color = None):
        """Write text or paste another framebuffer at ``x, y``."""
        if isinstance(content, FrameBuffer):
            for source_y, row in enumerate(content.cells):
                target_y = y + source_y
                if not 0 <= target_y < self.height:
                    continue
                for source_x, cell in enumerate(row):
                    target_x = x + source_x
                    if 0 <= target_x < self.width:
                        self.cells[target_y][target_x] = cell.copy()
            return
        start_x = x
        for char in str(content):
            if char == '\n':
                x, y = start_x, y + 1
                continue
            x += self.put(x, y, char, foreground, background)

    def get_frame(self, x1: int, y1: int, x2: int, y2: int):
        """Return an independent, color-preserving copy of a rectangle."""
        if x2 < x1 or y2 < y1:
            raise ValueError('rectangle end must not precede its start')
        left, top = max(0, x1), max(0, y1)
        right, bottom = min(self.width, x2), min(self.height, y2)
        result = FrameBuffer(max(0, right - left), max(0, bottom - top))
        for y, row in enumerate(self.cells[top:bottom]):
            result.cells[y] = [cell.copy() for cell in row[left:right]]
        result.buffer = result.cells
        return result

    def get_text(self) -> str:
        """Return logical text, suppressing the duplicate half of wide characters."""
        return '\n'.join(
            ''.join(cell.char for cell in row if not cell.continuation)
            for row in self.cells
        )

    def clear(self):
        for y in range(self.height):
            self.cells[y] = [FrameCell() for _ in range(self.width)]
        self.buffer = self.cells

class ControlCode:
    CLEAR_SCREEN = '\033[2J'
    CLEAR_LINE = '\033[2K'
    ENTER_ALTERNATE_BUFFER = '\033[?1049h'
    EXIT_ALTERNATE_BUFFER = '\033[?1049l'

    MOVE_CURSOR_TO_SCREEN_START = '\033[H'
    MOVE_CURSOR = lambda row, col: f'\033[{col};{row}H'

class TerminalAnimation:
    def __init__(self, terminal, frames, interval=0.1, frame_color: tuple[tuple] | tuple = (255, 255, 255), back_color: tuple[tuple] | tuple = None):
        self.terminal = terminal
        self.frames = tuple(frames)
        if not self.frames:
            raise ValueError('frames must not be empty')
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None
        self._position = (0, 0)
        self._frame_width = max(map(len, self.frames), default=0)
        self._draw_width = self._frame_width
        self._duration = None
        self._final_frame = ''

        self.keep_color = False
        self.keep_back = False
        

        if isinstance(frame_color[0], int):
            self.keep_color = True
            self.frame_color = frame_color
        else:
            self.frame_color = frame_color

        if back_color:
            if isinstance(back_color[0], int):
                self.keep_back = True
                self.back_color = back_color
            else:
                self.back_color = back_color
        else:
            self.back_color = None


    def start(self, position, duration=None, final_frame=''):
        if duration is not None and duration < 0:
            raise ValueError('duration must be zero or greater')

        self.stop(force=True)
        self._position = position
        self._duration = duration
        self._final_frame = str(final_frame)
        self._draw_width = max(self._frame_width, len(self._final_frame))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, force=False):
        if self._thread is None:
            return

        self._stop_event.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=self.interval * 2)
        self._thread = None

        if force:
            self._draw(' ' * self._draw_width)
        else:
            self._draw(self._final_frame, end=True)

    def _draw(self, frame, color: tuple = (255, 255, 255), back: tuple = None, end = False):
        x, y = self._position
        content = frame.ljust(self._draw_width)
        
        if end:
            self.terminal.send_command(
                f'\033[s\033[{y + 1};{x + 1}H{content}\033[u'
            )
        else:
            self.terminal.send_command(
                self.terminal.colored_text(f'\033[s\033[{y + 1};{x + 1}H{content}\033[u', color, back)
            )

    def _run(self):
        frame_index = 0
        deadline = (
            time.monotonic() + self._duration
            if self._duration is not None
            else None
        )

        while not self._stop_event.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break

            frame_color = self.frame_color    

            if not self.keep_color:
                frame_color = self.frame_color[frame_index]

            if self.back_color:
                if not self.keep_back:
                    back_color = self.back_color[frame_index]
            else:
                back_color = None

            self._draw(self.frames[frame_index], color=frame_color, back=back_color)

            frame_index = (frame_index + 1) % len(self.frames)

            wait_time = self.interval
            if deadline is not None:
                wait_time = min(wait_time, max(0, deadline - time.monotonic()))
            self._stop_event.wait(wait_time)

        if not self._stop_event.is_set():
            self._draw(self._final_frame, end=True)

class TerminalOutput:
    _CSI_RE = re.compile(r'\x1b\[([0-9;?]*)([ -/]*)([@-~])')

    def __init__(self):
        enable_vt()
        ensure_utf8()
        self.lock = threading.Lock()
        self.x = 0
        self.y = 0
        self._foreground = None
        self._background = None
        width, height = self.get_size()
        self.framebuffer = FrameBuffer(width, height)

    def colored_text(self, text, text_rgb: tuple, back_rgb: tuple):
        result = ""

        if text_rgb:
            r, g, b = text_rgb
            result += f'\033[38;2;{r};{g};{b}m'

        if back_rgb:
            r, g, b = back_rgb
            result += f'\033[48;2;{r};{g};{b}m'

        return result + text + '\033[0m'

    def send_command(self, *code):
        if isinstance(code, str):
            code = list(code)

        sys.stdout.write(''.join(code))
        sys.stdout.flush()

    def clear_screen(self):
        self.send_command(
            ControlCode.CLEAR_SCREEN, 
            ControlCode.MOVE_CURSOR_TO_SCREEN_START
        )

        self.x = 0
        self.y = 0
        self.framebuffer.clear()

    def get_frame(self, x1: int, y1: int, x2: int, y2: int):
        return self.framebuffer.get_frame(x1, y1, x2, y2)

    def write_frame(self, x: int, y: int, frame: FrameBuffer, draw=True):
        """Paste a frame into the model and optionally draw its ANSI rendering."""
        self.framebuffer.write(x, y, frame)
        if draw:
            old_x, old_y = self.x, self.y
            try:
                for row_number, row in enumerate(frame.cells):
                    self.move_cursor(x, y + row_number)
                    last_style = None
                    run = ''
                    for cell in row:
                        if cell.continuation:
                            continue
                        style = (cell.foreground, cell.background)
                        if last_style is not None and style != last_style:
                            self.send_command(self.colored_text(run, *last_style))
                            run = ''
                        run += cell.char
                        last_style = style
                    if run:
                        self.send_command(self.colored_text(run, *last_style))
            finally:
                self.move_cursor(old_x, old_y)

    def get_size(self):
        term = shutil.get_terminal_size()

        return term.columns, term.lines
    
    def get_string_width(self, string):
        return wcwidth.wcswidth(string)

    def print(self, *values, sep=' ', end='\n', flush=False):
        content = sep.join(map(str, values)) + end

        sys.stdout.write(content)

        width, height = self.get_size()

        position = 0
        for match in self._CSI_RE.finditer(content):
            self._track_text(content[position:match.start()], width, height)
            if match.group(3) == 'm':
                self._apply_sgr(match.group(1))
            position = match.end()
        self._track_text(content[position:], width, height)

        if flush:
            sys.stdout.flush()

    def _track_text(self, content, width, height):
        for ch in content:
            if ch == '\n':
                self.y += 1
                self.x = 0
            else:
                w = self.get_string_width(ch)
                if w < 0:
                    w = 0

                if w:
                    self.framebuffer.put(
                        self.x, self.y, ch, self._foreground, self._background
                    )

                self.x += w

                if self.x >= width: # fix width
                    self.y += self.x // width
                    self.x %= width

            if self.y >= height: # fix height
                self.y = height - 1

    def _apply_sgr(self, parameters):
        values = [int(value) if value else 0 for value in parameters.split(';')]
        index = 0
        while index < len(values):
            value = values[index]
            if value == 0:
                self._foreground = self._background = None
            elif value == 39:
                self._foreground = None
            elif value == 49:
                self._background = None
            elif value in (38, 48) and values[index + 1:index + 2] == [2]:
                rgb = values[index + 2:index + 5]
                if len(rgb) == 3:
                    if all(0 <= channel <= 255 for channel in rgb):
                        if value == 38:
                            self._foreground = tuple(rgb)
                        else:
                            self._background = tuple(rgb)
                    index += 4
            index += 1

    def move_cursor(self, x: int, y: int):
        self.send_command(ControlCode.MOVE_CURSOR(x, y))
        
        with self.lock:
            self.x = x
            self.y = y
        
    def put_char(self, position, char: str):
        term_w, term_y = self.get_size()

        if position:
            x, y = position
            old_x, old_y = self.x, self.y

            if (x < 0 or x > term_w or y < 0 or y > term_y): # viewport clipping
                return (None, None)

            self.move_cursor(*position)

        self.print(char[0], end='')

        if position:
            self.move_cursor(old_x, old_y)

        return self.x, self.y

    def print_rect(self, position: tuple, size: tuple):
        old_x, old_y = self.x, self.y

        x, y = position
        w, h = size

        top = '╭' + '─' * (w - 2) + '╮'
        bottom = '╰' + '─' * (w - 2) + '╯'

        if w < 2 or h < 2:
            return

        try:
            for cnt, i in enumerate(range(x, x + w)):
                self.put_char((i, y), top[cnt])
                self.put_char((i, y + h - 1), bottom[cnt])

            for i in range(y + 1, y + h - 1):
                self.put_char((x, i), '│')
                self.put_char((x + w - 1, i), '│')

        finally:
            self.move_cursor(old_x, old_y)

    def print_text(self, position: tuple, size: tuple, content: str, in_rect = False):
        old_x, old_y = self.x, self.y

        x, y = position
        w, h = size

        h -= 1

        if in_rect:
            x, y, w, h = x + 1, y + 1, w - 2, h - 1

        for cnt, line in enumerate(content.split('\n')[:h]):
            if self.get_string_width(line) > w - 3:
                line = line[:w - 3] + '...'
            
            for i, char in enumerate(line):
                self.put_char((x + i, y + cnt), char)

        if len(content.split('\n')[:h]) < len(content.split('\n')):
            for i in range(x, x + w):
                self.put_char((i, y + h), '.')

        self.move_cursor(old_x, old_y)

    def clear_line(self):
        self.send_command(
            ControlCode.CLEAR_LINE
        )

@dataclass(slots=True)
class TerminalEvent:
    """A platform-independent terminal input event.

    ``x`` and ``y`` are zero-based terminal cell coordinates.  Keyboard
    events contain both the decoded ``key`` name and, when available, the
    typed ``text``.
    """

    type: Literal['key', 'mouse', 'resize', 'paste']
    action: str
    key: str | None = None
    text: str | None = None
    x: int | None = None
    y: int | None = None
    button: str | None = None
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    width: int | None = None
    height: int | None = None


class TerminalInput_Windows:
    """Read keyboard and mouse INPUT_RECORD values from a Windows console."""

    def __init__(self, mouse=True):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self._kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        self._kernel32.GetStdHandle.restype = wintypes.HANDLE
        self._kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._kernel32.GetConsoleMode.restype = wintypes.BOOL
        self._kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel32.SetConsoleMode.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._handle = self._kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        self._closed = False

        class COORD(ctypes.Structure):
            _fields_ = [('X', wintypes.SHORT), ('Y', wintypes.SHORT)]

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ('bKeyDown', wintypes.BOOL),
                ('wRepeatCount', wintypes.WORD),
                ('wVirtualKeyCode', wintypes.WORD),
                ('wVirtualScanCode', wintypes.WORD),
                ('UnicodeChar', wintypes.WCHAR),
                ('dwControlKeyState', wintypes.DWORD),
            ]

        class MOUSE_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ('dwMousePosition', COORD),
                ('dwButtonState', wintypes.DWORD),
                ('dwControlKeyState', wintypes.DWORD),
                ('dwEventFlags', wintypes.DWORD),
            ]

        class WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
            _fields_ = [('dwSize', COORD)]

        class EVENT_UNION(ctypes.Union):
            _fields_ = [
                ('KeyEvent', KEY_EVENT_RECORD),
                ('MouseEvent', MOUSE_EVENT_RECORD),
                ('WindowBufferSizeEvent', WINDOW_BUFFER_SIZE_RECORD),
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [('EventType', wintypes.WORD), ('Event', EVENT_UNION)]

        self._kernel32.ReadConsoleInputW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.ReadConsoleInputW.restype = wintypes.BOOL
        self._record_type = INPUT_RECORD
        self._old_mode = wintypes.DWORD()
        if not self._kernel32.GetConsoleMode(self._handle, ctypes.byref(self._old_mode)):
            raise OSError(ctypes.get_last_error(), 'stdin is not a Windows console')

        mode = self._old_mode.value | 0x0008  # ENABLE_WINDOW_INPUT
        if mouse:
            mode |= 0x0080  # ENABLE_EXTENDED_FLAGS
            mode |= 0x0010  # ENABLE_MOUSE_INPUT
            mode &= ~0x0040  # disable QUICK_EDIT, which consumes clicks
        if not self._kernel32.SetConsoleMode(self._handle, mode):
            raise OSError(ctypes.get_last_error(), 'could not configure console input')

        self._last_buttons = 0

    @staticmethod
    def _modifiers(state):
        return {
            'ctrl': bool(state & (0x0004 | 0x0008)),
            'alt': bool(state & (0x0001 | 0x0002)),
            'shift': bool(state & 0x0010),
        }

    def _convert(self, record):
        if record.EventType == 0x0001:  # KEY_EVENT
            event = record.Event.KeyEvent
            names = {
                0x08: 'backspace', 0x09: 'tab', 0x0D: 'enter', 0x1B: 'escape',
                0x21: 'page_up', 0x22: 'page_down', 0x23: 'end', 0x24: 'home',
                0x25: 'left', 0x26: 'up', 0x27: 'right', 0x28: 'down',
                0x2D: 'insert', 0x2E: 'delete',
            }
            if 0x70 <= event.wVirtualKeyCode <= 0x7B:
                key = f'f{event.wVirtualKeyCode - 0x6F}'
            elif 0x41 <= event.wVirtualKeyCode <= 0x5A:
                key = chr(event.wVirtualKeyCode).lower()
            elif 0x30 <= event.wVirtualKeyCode <= 0x39:
                key = chr(event.wVirtualKeyCode)
            else:
                key = names.get(event.wVirtualKeyCode)
                if key is None:
                    key = event.UnicodeChar or f'vk_{event.wVirtualKeyCode}'
            text = event.UnicodeChar or None
            return TerminalEvent(
                type='key', action='down' if event.bKeyDown else 'up',
                key=key, text=text, **self._modifiers(event.dwControlKeyState)
            )

        if record.EventType == 0x0002:  # MOUSE_EVENT
            event = record.Event.MouseEvent
            state = event.dwButtonState
            flags = event.dwEventFlags
            button = None
            action = 'move' if flags == 0x0001 else 'down'
            if flags == 0x0004:  # MOUSE_WHEELED
                delta = self._ctypes.c_short(state >> 16).value
                button, action = ('wheel_up' if delta > 0 else 'wheel_down'), 'scroll'
            elif flags == 0x0008:  # MOUSE_HWHEELED
                delta = self._ctypes.c_short(state >> 16).value
                button, action = ('wheel_right' if delta > 0 else 'wheel_left'), 'scroll'
            else:
                changed = state ^ self._last_buttons
                button_bits = ((0x0001, 'left'), (0x0004, 'middle'), (0x0002, 'right'),
                               (0x0008, 'x1'), (0x0010, 'x2'))
                for bit, name in button_bits:
                    if changed & bit:
                        button = name
                        action = 'down' if state & bit else 'up'
                        break
                if button is None:
                    for bit, name in button_bits:
                        if state & bit:
                            button = name
                            break
                self._last_buttons = state & 0xFFFF
            return TerminalEvent(
                type='mouse', action=action, button=button,
                x=event.dwMousePosition.X, y=event.dwMousePosition.Y,
                **self._modifiers(event.dwControlKeyState)
            )

        if record.EventType == 0x0004:  # WINDOW_BUFFER_SIZE_EVENT
            size = record.Event.WindowBufferSizeEvent.dwSize
            return TerminalEvent(type='resize', action='resize', width=size.X, height=size.Y)
        return None

    def read_event(self, timeout=None):
        """Return the next event, or ``None`` when the timeout expires."""
        from ctypes import wintypes

        if self._closed:
            raise RuntimeError('terminal input is closed')
        wait_ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self._kernel32.WaitForSingleObject(self._handle, wait_ms)
            if result == 0x00000102:
                return None
            if result != 0:
                raise OSError(self._ctypes.get_last_error(), 'console input wait failed')
            record = self._record_type()
            count = wintypes.DWORD()
            if not self._kernel32.ReadConsoleInputW(
                self._handle, self._ctypes.byref(record), 1, self._ctypes.byref(count)
            ):
                raise OSError(self._ctypes.get_last_error(), 'console input read failed')
            converted = self._convert(record)
            if converted is not None:
                return converted
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                wait_ms = max(0, int(remaining * 1000))

    def poll_event(self):
        return self.read_event(timeout=0)

    def close(self):
        if not self._closed:
            self._kernel32.SetConsoleMode(self._handle, self._old_mode.value)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class TerminalInput_Linux:
    """Read raw keyboard input and SGR mouse events on Unix terminals."""

    _KEY_SEQUENCES = {
        b'\x1b[A': 'up', b'\x1b[B': 'down', b'\x1b[C': 'right', b'\x1b[D': 'left',
        b'\x1b[H': 'home', b'\x1b[F': 'end', b'\x1b[2~': 'insert',
        b'\x1b[3~': 'delete', b'\x1b[5~': 'page_up', b'\x1b[6~': 'page_down',
        b'\x1bOP': 'f1', b'\x1bOQ': 'f2', b'\x1bOR': 'f3', b'\x1bOS': 'f4',
        b'\x1b[15~': 'f5', b'\x1b[17~': 'f6', b'\x1b[18~': 'f7',
        b'\x1b[19~': 'f8', b'\x1b[20~': 'f9', b'\x1b[21~': 'f10',
        b'\x1b[23~': 'f11', b'\x1b[24~': 'f12',
    }

    def __init__(self, mouse=True):
        import termios
        import tty

        if not sys.stdin.isatty():
            raise OSError('stdin is not a terminal')
        self._fd = sys.stdin.fileno()
        self._termios = termios
        self._old_settings = termios.tcgetattr(self._fd)
        self._buffer = bytearray()
        self._closed = False
        self._mouse = mouse
        tty.setraw(self._fd)
        controls = '\x1b[?2004h'  # bracketed paste
        if mouse:
            # SGR coordinates, click/drag tracking, and mouse motion tracking.
            controls += '\x1b[?1000h\x1b[?1002h\x1b[?1006h'
        sys.stdout.write(controls)
        sys.stdout.flush()

    @staticmethod
    def _key_event(key, text=None, ctrl=False, alt=False):
        return TerminalEvent(
            type='key', action='down', key=key, text=text, ctrl=ctrl, alt=alt
        )

    def _parse_mouse(self):
        import re

        match = re.match(br'^\x1b\[<(\d+);(\d+);(\d+)([Mm])', self._buffer)
        if not match:
            return None
        code, x, y = map(int, match.group(1, 2, 3))
        released = bytes(match.group(4)) == b'm'
        consumed = match.end()
        del self._buffer[:consumed]
        base = code & 0b11000011
        if code & 64:
            buttons = {64: 'wheel_up', 65: 'wheel_down', 66: 'wheel_left', 67: 'wheel_right'}
            button, action = buttons.get(base, 'wheel'), 'scroll'
        else:
            button = {0: 'left', 1: 'middle', 2: 'right', 3: None}.get(base)
            action = 'up' if released or base == 3 else ('move' if code & 32 else 'down')
        return TerminalEvent(
            type='mouse', action=action, button=button, x=x - 1, y=y - 1,
            shift=bool(code & 4), alt=bool(code & 8), ctrl=bool(code & 16)
        )

    def _parse_buffer(self):
        if not self._buffer:
            return None
        if self._buffer.startswith(b'\x1b[<'):
            return self._parse_mouse()
        if self._buffer.startswith(b'\x1b[200~'):  # bracketed paste
            end = self._buffer.find(b'\x1b[201~')
            if end < 0:
                return None  # wait for the rest of the paste
            text = bytes(self._buffer[6:end]).decode('utf-8', 'replace')
            del self._buffer[:end + 6]
            return TerminalEvent(type='paste', action='paste', text=text)
        modified = re.match(br'^\x1b\[1;(\d+)([ABCDHF])', self._buffer)
        if modified:
            names = {b'A': 'up', b'B': 'down', b'C': 'right', b'D': 'left',
                     b'H': 'home', b'F': 'end'}
            mods = int(modified.group(1)) - 1
            key = names[modified.group(2)]
            del self._buffer[:modified.end()]
            return TerminalEvent(
                type='key', action='down', key=key,
                shift=bool(mods & 1), alt=bool(mods & 2), ctrl=bool(mods & 4),
            )
        modified = re.match(br'^\x1b\[(\d+);(\d+)~', self._buffer)
        if modified:
            names = {2: 'insert', 3: 'delete', 5: 'page_up', 6: 'page_down'}
            key = names.get(int(modified.group(1)))
            mods = int(modified.group(2)) - 1
            del self._buffer[:modified.end()]
            if key is None:
                return self._parse_buffer()
            return TerminalEvent(
                type='key', action='down', key=key,
                shift=bool(mods & 1), alt=bool(mods & 2), ctrl=bool(mods & 4),
            )
        for sequence, name in sorted(self._KEY_SEQUENCES.items(), key=lambda item: -len(item[0])):
            if self._buffer.startswith(sequence):
                del self._buffer[:len(sequence)]
                return self._key_event(name)
        first = self._buffer[0]
        if first == 0x1B:
            if len(self._buffer) == 1:
                return None
            del self._buffer[0]
            # An escape followed by a printable character conventionally means Alt.
            event = self._parse_buffer()
            if event and event.type == 'key':
                event.alt = True
            return event or self._key_event('escape')
        special = {0x03: 'ctrl_c', 0x04: 'ctrl_d', 0x08: 'backspace',
                   0x09: 'tab', 0x0A: 'enter', 0x0D: 'enter', 0x7F: 'backspace'}
        if first in special:
            del self._buffer[0]
            return self._key_event(special[first], chr(first) if first < 32 else None,
                                   ctrl=first in (0x03, 0x04), alt=False)
        if 0x01 <= first <= 0x1A:
            del self._buffer[0]
            letter = chr(first + 0x60)
            return self._key_event(letter, ctrl=True)
        # Wait until a complete UTF-8 character is available.
        for length in range(1, min(4, len(self._buffer)) + 1):
            try:
                text = bytes(self._buffer[:length]).decode('utf-8')
            except UnicodeDecodeError as error:
                if error.reason == 'unexpected end of data':
                    continue
                del self._buffer[0]
                return self._key_event('\ufffd', '\ufffd')
            del self._buffer[:length]
            return self._key_event(text, text)
        return None

    def read_event(self, timeout=None):
        """Return the next event, or ``None`` when the timeout expires."""
        import select

        if self._closed:
            raise RuntimeError('terminal input is closed')
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            event = self._parse_buffer()
            if event is not None:
                return event
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            ready, _, _ = select.select([self._fd], [], [], remaining)
            if not ready:
                # A lone ESC needs a short ambiguity timeout before it is a key.
                if self._buffer == b'\x1b':
                    self._buffer.clear()
                    return self._key_event('escape')
                return None
            data = os.read(self._fd, 4096)
            if not data:
                return None
            self._buffer.extend(data)
            if self._buffer == b'\x1b':
                ready, _, _ = select.select([self._fd], [], [], 0.025)
                if not ready:
                    self._buffer.clear()
                    return self._key_event('escape')

    def poll_event(self):
        return self.read_event(timeout=0)

    def close(self):
        if not self._closed:
            controls = '\x1b[?2004l'
            if self._mouse:
                controls += '\x1b[?1006l\x1b[?1002l\x1b[?1000l'
            sys.stdout.write(controls)
            sys.stdout.flush()
            self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old_settings)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class TerminalInput:
    """Cross-platform facade for terminal keyboard and mouse input."""

    def __init__(self, mouse=True):
        implementation = TerminalInput_Windows if sys.platform == 'win32' else TerminalInput_Linux
        self.input = implementation(mouse=mouse)

    def read_event(self, timeout=None):
        return self.input.read_event(timeout=timeout)

    def poll_event(self):
        return self.input.poll_event()

    def close(self):
        self.input.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class TerminalEventDispatcher:
    """Read the terminal in one thread and expose events through a queue."""

    def __init__(self, mouse=True):
        self._mouse = mouse
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._listen,
            name='terminal-input',
            daemon=True,
        )
        self._thread.start()
        return self

    def _listen(self):
        with TerminalInput(mouse=self._mouse) as terminal_input:
            while not self._stop.is_set():
                event = terminal_input.read_event(timeout=0.1)
                if event is not None:
                    self._events.put(event)

    def get_event(self, timeout=None):
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()


class Select:
    """A small framebuffer-aware, keyboard driven selection prompt.

    The prompt is drawn over the current terminal contents.  The covered
    framebuffer region and cursor position are restored before ``run``
    returns (or raises), so it can safely be used inside an existing UI.
    """

    def __init__(self, title, items, terminal=None, *, subtitle=None,
                 position=None, size=None, dense=False,
                 selected=0, pointer='>', selected_color=(0, 0, 0),
                 selected_background=(220, 220, 220),
                 description_color=(128, 128, 128), background_color=None):
        self.title = str(title)
        self.subtitle = None if subtitle is None else str(subtitle)
        self.items = tuple(self._item_parts(item) for item in items)
        if not self.items:
            raise ValueError('items must not be empty')
        if not 0 <= selected < len(self.items):
            raise ValueError('selected index is out of range')
        self.terminal = terminal or TerminalOutput()
        if position is not None and (len(position) != 2 or min(position) < 0):
            raise ValueError('position must be a non-negative (x, y) tuple')
        if size is not None and (len(size) != 2 or min(size) <= 0):
            raise ValueError('size must be a positive (width, height) tuple')
        self.position = tuple(position) if position is not None else None
        self.size = tuple(size) if size is not None else None
        self.dense = bool(dense)
        self.selected = selected
        self.pointer = str(pointer)
        self.selected_color = selected_color
        self.selected_background = selected_background
        self.description_color = description_color
        self.background_color = background_color

    @staticmethod
    def _item_parts(item):
        """Return ``(label, description)`` for strings or two-item tuples."""
        if isinstance(item, (tuple, list)) and len(item) == 2:
            return str(item[0]), str(item[1])
        return str(item), None

    @staticmethod
    def _fit(text, width):
        """Clip text without splitting a wide terminal character."""
        result = []
        used = 0
        for char in str(text):
            char_width = max(0, wcwidth.wcwidth(char))
            if used + char_width > width:
                break
            result.append(char)
            used += char_width
        return ''.join(result)

    def _layout(self, origin_x, origin_y):
        term_width, term_height = self.terminal.get_size()
        if origin_x >= term_width or origin_y >= term_height:
            raise ValueError('position must be inside the terminal')
        # Keep the model in sync if the terminal was resized since creation.
        framebuffer = self.terminal.framebuffer
        if (framebuffer.width, framebuffer.height) != (term_width, term_height):
            resized = FrameBuffer(term_width, term_height)
            resized.write(0, 0, framebuffer)
            self.terminal.framebuffer = resized

        available_width = max(1, term_width - origin_x)
        available_rows = max(1, term_height - origin_y)
        if self.size is not None:
            available_width = min(available_width, self.size[0])
            available_rows = min(available_rows, self.size[1])
        header_rows = int(bool(self.title)) + int(self.subtitle is not None)
        if not self.dense and header_rows:
            header_rows += 1
        item_height = sum(1 + int(description is not None)
                          for _, description in self.items)
        if not self.dense:
            item_height += max(0, len(self.items) - 1)
        desired_height = header_rows + item_height
        height = available_rows if self.size is not None else min(desired_height,
                                                                  available_rows)
        # Always reserve at least one row for an option in small boxes.
        header_rows = min(header_rows, max(0, height - 1))
        prefix_width = wcwidth.wcswidth(self.pointer) + 1
        desired_width = max(
            [wcwidth.wcswidth(self.title)] +
            [prefix_width + wcwidth.wcswidth(label) for label, _ in self.items] +
            [prefix_width + wcwidth.wcswidth(description)
             for _, description in self.items if description]
        )
        width = available_width if self.size is not None else min(desired_width, available_width)
        return max(1, width), height, header_rows

    def _item_height(self, index):
        return 1 + int(self.items[index][1] is not None)

    def _visible_range(self, rows):
        """Find a scroll window containing the selected item."""
        gap = 0 if self.dense else 1
        start = 0
        while start <= self.selected:
            used = 0
            end = start
            while end < len(self.items):
                needed = self._item_height(end) + (gap if end > start else 0)
                if end > start and used + needed > rows:
                    break
                used += needed
                end += 1
                if used >= rows:
                    break
            if start <= self.selected < max(start + 1, end):
                return start, max(start + 1, end)
            start += 1
        return self.selected, self.selected + 1

    def _draw(self, x, y, width, height, header_rows):
        frame = FrameBuffer(width, height)
        if self.background_color is not None:
            for frame_row in frame.cells:
                for cell in frame_row:
                    cell.background = self.background_color
        row = 0
        if self.title and row < header_rows:
            frame.write(0, row, self._fit(self.title, width),
                        background=self.background_color)
            row += 1
        if self.subtitle is not None and row < header_rows:
            frame.write(0, row, self._fit(self.subtitle, width),
                        self.description_color, self.background_color)
            row += 1
        if not self.dense and row < header_rows:
            row += 1

        item_rows = max(1, height - row)
        start, end = self._visible_range(item_rows)
        prefix_width = wcwidth.wcswidth(self.pointer) + 1
        for index in range(start, end):
            if index > start and not self.dense and row < height:
                row += 1
            if row >= height:
                break
            label, description = self.items[index]
            active = index == self.selected
            prefix = f'{self.pointer} ' if active else ' ' * prefix_width
            line = self._fit(prefix + label, width)
            foreground = self.selected_color if active else None
            background = (self.selected_background if active
                          else self.background_color)
            # Color the entire selected row, including trailing empty cells.
            if active:
                for cell in frame[row]:
                    cell.foreground = foreground
                    cell.background = background
            frame.write(0, row, line, foreground, background)
            row += 1
            if description is not None and row < height:
                description_line = self._fit(' ' * prefix_width + description, width)
                frame.write(0, row, description_line, self.description_color,
                            self.background_color)
                row += 1
        self.terminal.write_frame(x, y, frame)
        return max(1, end - start)

    def run(self, dispatcher=None):
        """Show the prompt and return the selected item; Escape returns None."""
        cursor_x, cursor_y = self.terminal.x, self.terminal.y
        x, y = self.position or (cursor_x, cursor_y)
        width, height, header_rows = self._layout(x, y)
        saved = self.terminal.get_frame(x, y, x + width, y + height)
        owns_dispatcher = dispatcher is None
        if owns_dispatcher:
            dispatcher = TerminalEventDispatcher(mouse=False)

        try:
            if owns_dispatcher:
                dispatcher.start()
            visible_items = self._draw(x, y, width, height, header_rows)
            while True:
                event = dispatcher.get_event()
                if event is None or event.type != 'key' or event.action != 'down':
                    continue
                if event.key == 'up':
                    self.selected = (self.selected - 1) % len(self.items)
                elif event.key == 'down':
                    self.selected = (self.selected + 1) % len(self.items)
                elif event.key == 'home':
                    self.selected = 0
                elif event.key == 'end':
                    self.selected = len(self.items) - 1
                elif event.key == 'page_up':
                    self.selected = max(0, self.selected - visible_items)
                elif event.key == 'page_down':
                    self.selected = min(len(self.items) - 1,
                                        self.selected + visible_items)
                elif event.key == 'enter':
                    return self.items[self.selected][0]
                elif event.key == 'escape':
                    return None
                elif event.key == 'ctrl_c' or (event.ctrl and event.key == 'c'):
                    raise KeyboardInterrupt
                else:
                    continue
                visible_items = self._draw(x, y, width, height, header_rows)
        finally:
            if owns_dispatcher:
                dispatcher.stop()
            self.terminal.write_frame(x, y, saved)
            self.terminal.move_cursor(cursor_x, cursor_y)


# ═══════════════════════════════════════════════════════════════════════════
# Flow rendering layer (v2)
#
# Everything below renders *flowing* UIs: an append-only transcript that
# scrolls naturally, plus a repainted-in-place live region at the bottom
# (status, streaming markdown, input box). This coexists with the absolute
# positioning layer above (FrameBuffer / TerminalOutput / Select), which is
# still used for overlays and the splash.
#
# Core ideas:
#   Style      — immutable text attributes (truecolor fg/bg + effects)
#   span       — (text, Style | None); a line is a list of spans
#   Screen     — flicker-free painter: append() permanent lines above a
#                live region that is diff-repainted every frame
#   TextField  — editing model for the input widget (wrap, history, words)
#   render_markdown / highlight_code — markdown → styled span-lines
#   gradients, shimmer, spinners — the animation toolkit
# ═══════════════════════════════════════════════════════════════════════════


def enable_vt():
    """Enable ANSI escape processing on Windows consoles (no-op elsewhere)."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        for std_handle in (-11, -12):
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def ensure_utf8():
    """Best-effort UTF-8 stdout/stderr on consoles with legacy codepages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            encoding = (stream.encoding or '').lower().replace('-', '')
            if encoding != 'utf8':
                stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


# ---------------------------------------------------------------- styles ----

from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True, slots=True)
class Style:
    """Immutable terminal text style. Call an instance to derive a variant:
    ``accent = Style(fg=(255, 122, 71)); accent(bold=True)``."""

    fg: Color = None
    bg: Color = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    reverse: bool = False

    def __call__(self, **changes):
        values = {name: getattr(self, name) for name in self.__slots__}
        values.update(changes)
        return Style(**values)

    def sgr(self) -> str:
        codes = []
        if self.bold:
            codes.append('1')
        if self.dim:
            codes.append('2')
        if self.italic:
            codes.append('3')
        if self.underline:
            codes.append('4')
        if self.reverse:
            codes.append('7')
        if self.strike:
            codes.append('9')
        if self.fg:
            codes.append('38;2;%d;%d;%d' % tuple(self.fg))
        if self.bg:
            codes.append('48;2;%d;%d;%d' % tuple(self.bg))
        return '\033[%sm' % ';'.join(codes) if codes else ''


PLAIN = Style()

_BREAK_AFTER = set(' -/,;:')


# ----------------------------------------------------------------- spans ----

def as_spans(value, style=None):
    """Normalize a str or span-list into a span-list."""
    if isinstance(value, str):
        return [(value, style)]
    return list(value)


def _char_width(char):
    return max(0, wcwidth.wcwidth(char))


def _iter_chars(spans):
    for text, style in spans:
        for char in text:
            yield char, style


def _merge_chars(chars):
    """[(char, style)] -> [(text, style)] merging equal neighbouring styles."""
    groups = []
    for char, style in chars:
        if groups and groups[-1][1] == style:
            groups[-1][0].append(char)
        else:
            groups.append([[char], style])
    return [(''.join(text), style) for text, style in groups]


def spans_text(spans):
    return ''.join(text for text, _ in spans)


def spans_width(spans):
    total = 0
    for text, _ in spans:
        total += max(0, wcwidth.wcswidth(text))
    return total


def render_spans(spans) -> str:
    """Span-line -> ANSI string (self-resetting)."""
    parts = []
    for text, style in spans:
        if not text:
            continue
        prefix = style.sgr() if style else ''
        if prefix:
            parts.append(prefix + text + '\033[0m')
        else:
            parts.append(text)
    return ''.join(parts)


def pad_spans(spans, width, style=None):
    gap = width - spans_width(spans)
    if gap > 0:
        return list(spans) + [(' ' * gap, style)]
    return list(spans)


def truncate_spans(spans, width, ellipsis='…', ellipsis_style=None):
    if width <= 0:
        return []
    if spans_width(spans) <= width:
        return list(spans)
    budget = width - sum(_char_width(c) for c in ellipsis)
    keep = []
    used = 0
    for char, style in _iter_chars(spans):
        char_width = _char_width(char)
        if used + char_width > budget:
            break
        keep.append((char, style))
        used += char_width
    merged = _merge_chars(keep)
    merged.append((ellipsis, ellipsis_style))
    return merged


def wrap_spans(spans, width, hang=0, hang_style=None):
    """wcwidth-aware wrap: latin breaks at spaces, CJK anywhere. Honours
    explicit newlines. Continuation lines are indented by ``hang`` spaces.
    Always returns at least one line."""
    width = max(2, width)
    hang = max(0, min(hang, width - 2))
    raw_lines = []
    line = []
    line_width = 0
    break_index = None
    limit = width

    def emit(rest):
        nonlocal line, line_width, break_index, limit
        raw_lines.append(line)
        while rest and rest[0][0] == ' ':
            rest.pop(0)
        line = rest
        line_width = sum(_char_width(c) for c, _ in rest)
        break_index = None
        for i, (c, _) in enumerate(rest):
            if c in _BREAK_AFTER or _char_width(c) == 2:
                break_index = i + 1
        limit = width - hang

    soft_break = False
    for char, style in _iter_chars(spans):
        if char == '\n':
            emit([])
            soft_break = False
            continue
        if soft_break and not line and char == ' ':
            continue  # eat leading spaces created by soft wrapping
        char_width = _char_width(char)
        if line and line_width + char_width > limit:
            if char == ' ':
                # a space overflowing the line IS the break point
                emit([])
                soft_break = True
                continue
            if break_index and break_index < len(line):
                head, rest = line[:break_index], line[break_index:]
                line = head
                emit(rest)
            else:
                emit([])
            soft_break = True
            if char == ' ' and not line:
                continue
        line.append((char, style))
        line_width += char_width
        if char in _BREAK_AFTER or char_width == 2:
            break_index = len(line)
    raw_lines.append(line)

    result = []
    for index, chars in enumerate(raw_lines):
        while chars and chars[-1][0] == ' ':
            chars.pop()
        merged = _merge_chars(chars)
        if index and hang:
            merged = [(' ' * hang, hang_style)] + merged
        result.append(merged)
    return result


# ---------------------------------------------------------------- colors ----

def hex_rgb(value: str):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def blend(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (round(a[0] + (b[0] - a[0]) * t),
            round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


def sample_gradient(stops, t):
    if len(stops) == 1:
        return stops[0]
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    scaled = t * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    return blend(stops[index], stops[index + 1], scaled - index)


def _pingpong(t):
    t %= 1.0
    return 1.0 - abs(2.0 * t - 1.0)


def gradient_spans(text, stops, phase=None, style=PLAIN):
    """Colour ``text`` with a gradient. ``phase=None`` is a static
    left-to-right ramp; pass a float (e.g. ``t * 0.4``) to make it flow."""
    chars = list(str(text))
    denominator = max(1, len(chars) - 1)
    out = []
    for index, char in enumerate(chars):
        position = index / denominator
        if phase is None:
            color = sample_gradient(stops, position)
        else:
            color = sample_gradient(stops, _pingpong(position * 0.75 + phase))
        out.append((char, style(fg=color)))
    return _merge_chars(out)


def shimmer_spans(text, t, base, highlight, speed=18.0, band=2.8, style=PLAIN):
    """A soft light band sweeping repeatedly across the text."""
    chars = list(str(text))
    total = sum(_char_width(c) for c in chars) or 1
    period = total + 14.0
    center = (t * speed) % period - 7.0
    out = []
    position = 0.0
    for char in chars:
        char_width = _char_width(char)
        mid = position + char_width / 2.0
        glow = math.exp(-((mid - center) / band) ** 2)
        out.append((char, style(fg=blend(base, highlight, glow))))
        position += char_width
    return _merge_chars(out)


SPINNERS = {
    'dots': ('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏', 0.08),
    'arc': ('◜◠◝◞◡◟', 0.10),
    'pulse': ('●●◉◉◎◎○○◎◎◉◉', 0.07),
    'spark': ('✶✸✹✺✹✸', 0.12),
    'flame': ('▁▂▃▅▆▇█▇▆▅▃▂', 0.06),
    'reactor': ('⣾⣽⣻⢿⡿⣟⣯⣷', 0.09),
    'orbit': ('◐◓◑◒', 0.12),
}


def spinner_frame(name, t):
    frames, interval = SPINNERS[name]
    return frames[int(t / interval) % len(frames)]


# --------------------------------------------------------- motion toolkit --
# Character-forward animation primitives for building a distinctive UI:
#   flux_spans  — a reactor waveform faked from ▁▂▃▄▅▆▇█ in a single row
#   rail_spans  — a dim baseline with a bright energised pulse gliding across
#   spine_cell  — one cell of a vertical gradient spine that flows over time
# All are pure functions of ``t`` (deterministic per frame; no RNG state).

EMBER_STOPS = [(255, 184, 107), (255, 122, 71), (255, 77, 109)]
_FLUX_LEVELS = ' ▁▂▃▄▅▆▇█'


def breath(t, low=0.0, high=1.0, period=2.0, phase=0.0):
    """A smooth 0→1→0 cosine oscillation; handy for pulsing brightness."""
    frac = 0.5 - 0.5 * math.cos((t / max(1e-6, period) + phase) * math.tau)
    return low + (high - low) * frac


def flux_spans(width, t, stops=None, *, energy=1.0, speed=7.0,
               scan_speed=12.0, style=PLAIN):
    """A living 'reactor core' rendered as one row of block elements.

    Two summed sines make an organic standing wave; a sine envelope keeps
    the energy contained toward the centre; a Gaussian scan band sweeps a
    white-hot highlight across (wrapping at the edges). Colour ramps along
    ``stops`` by position, brightened by local amplitude."""
    width = max(1, width)
    stops = stops or EMBER_STOPS
    denominator = max(1, width - 1)
    center = (t * scan_speed) % width
    top = len(_FLUX_LEVELS) - 1
    out = []
    for x in range(width):
        position = x / denominator
        envelope = math.sin(math.pi * position) ** 0.7 if width > 2 else 1.0
        wave = (0.55
                + 0.30 * math.sin(x * 0.55 - t * speed)
                + 0.20 * math.sin(x * 0.27 + t * speed * 0.6)
                + 0.14 * math.sin(x * 0.90 - t * speed * 1.7))
        amplitude = envelope * wave * energy
        amplitude = 0.0 if amplitude < 0 else 1.0 if amplitude > 1 else amplitude
        glyph = _FLUX_LEVELS[int(round(amplitude * top))]
        color = sample_gradient(stops, position)
        color = blend((26, 28, 38), color, 0.28 + 0.72 * amplitude)
        distance = min(abs(x - center), width - abs(x - center))
        glow = math.exp(-(distance / 2.1) ** 2)
        color = blend(color, (255, 248, 236), glow * 0.75)
        out.append((glyph, style(fg=color)))
    return _merge_chars(out)


def rail_spans(width, t, *, base=(60, 66, 82), glow=(255, 170, 120),
               speed=26.0, glow_width=5.0, style=PLAIN):
    """A flowing 'attention rail': a dim ``─`` baseline with a bright ``━``
    segment bouncing back and forth. Replaces a boxed border with motion."""
    width = max(1, width)
    span = max(1, width - 1)
    cycle = (t * speed) % (2 * span)
    center = cycle if cycle <= span else 2 * span - cycle
    out = []
    for x in range(width):
        intensity = math.exp(-((x - center) / glow_width) ** 2)
        color = blend(base, glow, intensity)
        glyph = '━' if intensity > 0.4 else '─'
        out.append((glyph, style(fg=color)))
    return _merge_chars(out)


def spine_cell(index, total, t, stops=None, *, glyph='▍', speed=1.6,
               style=PLAIN):
    """One vertical spine cell whose colour flows down the column over time."""
    stops = stops or EMBER_STOPS
    total = max(1, total)
    position = index / total - t * (speed / max(4, total))
    return (glyph, style(fg=sample_gradient(stops, _pingpong(position))))


# ------------------------------------------------------------------ boxes ----

def box_lines(content, width, style=PLAIN, title=None, title_style=None,
              rounded=True, pad=1):
    """Wrap span-lines in a box; content is clipped/padded to fit."""
    tl, tr, bl, br = ('╭', '╮', '╰', '╯') if rounded else ('┌', '┐', '└', '┘')
    width = max(6, width)
    inner = width - 2 - pad * 2
    fill = width - 2
    if title is not None:
        label = truncate_spans(as_spans(title, title_style), max(1, fill - 4))
        label_width = spans_width(label)
        tail = max(0, fill - 3 - label_width)
        top = [(tl + '─ ', style), *label, (' ' + '─' * tail + tr, style)]
    else:
        top = [(tl + '─' * fill + tr, style)]
    out = [top]
    for line in content:
        body = pad_spans(truncate_spans(as_spans(line), inner), inner)
        out.append([('│' + ' ' * pad, style), *body, (' ' * pad + '│', style)])
    out.append([(bl + '─' * fill + br, style)])
    return out


# --------------------------------------------------------------- markdown ----

class MarkdownTheme:
    """Colour scheme for render_markdown / highlight_code. Any attribute can
    be overridden via keyword arguments."""

    def __init__(self, **overrides):
        accent = (255, 122, 71)
        self.text = Style(fg=(222, 226, 235))
        self.accent_stops = [(255, 184, 107), (255, 122, 71), (255, 77, 109)]
        self.h1 = Style(bold=True)
        self.h2 = Style(fg=accent, bold=True)
        self.h3 = Style(fg=(255, 184, 107), bold=True)
        self.h4 = Style(fg=(148, 155, 170), bold=True)
        self.rule = Style(fg=(75, 85, 99))
        self.bullet = Style(fg=accent, bold=True)
        self.number = Style(fg=accent)
        self.quote_bar = Style(fg=accent)
        self.quote_text = Style(fg=(148, 155, 170), italic=True)
        self.code_inline = Style(fg=(255, 184, 107), bg=(42, 45, 58))
        self.code_border = Style(fg=(70, 78, 95))
        self.code_lang = Style(fg=(148, 155, 170), italic=True)
        self.code_text = Style(fg=(190, 197, 210))
        self.link = Style(fg=(56, 189, 248), underline=True)
        self.strike = Style(fg=(107, 114, 128), strike=True)
        self.table_border = Style(fg=(70, 78, 95))
        self.table_header = Style(bold=True)
        self.task_done = Style(fg=(74, 222, 128))
        self.task_todo = Style(fg=(148, 155, 170))
        self.syntax = {
            'keyword': Style(fg=(198, 120, 221)),
            'string': Style(fg=(152, 195, 121)),
            'number': Style(fg=(209, 154, 102)),
            'comment': Style(fg=(116, 123, 136), italic=True),
            'func': Style(fg=(97, 175, 239)),
            'builtin': Style(fg=(229, 192, 123)),
            'decorator': Style(fg=(229, 192, 123), italic=True),
            'op': Style(fg=(130, 137, 151)),
            'var': Style(fg=(224, 108, 117)),
            'cmdlet': Style(fg=(97, 175, 239)),
            'param': Style(fg=(86, 182, 194)),
            'key': Style(fg=(224, 108, 117)),
            'const': Style(fg=(209, 154, 102)),
            'tag': Style(fg=(224, 108, 117)),
        }
        for name, value in overrides.items():
            setattr(self, name, value)


MD_THEME = MarkdownTheme()

_LANG_ALIASES = {
    'py': 'python', 'python3': 'python',
    'js': 'javascript', 'jsx': 'javascript', 'ts': 'javascript',
    'tsx': 'javascript', 'typescript': 'javascript', 'node': 'javascript',
    'sh': 'bash', 'shell': 'bash', 'zsh': 'bash', 'console': 'bash',
    'ps': 'powershell', 'ps1': 'powershell', 'pwsh': 'powershell',
    'yml': 'yaml', 'jsonc': 'json', 'c++': 'c', 'cpp': 'c', 'h': 'c',
    'hpp': 'c', 'cs': 'c', 'java': 'c', 'golang': 'go', 'rs': 'rust',
    'htm': 'html', 'xml': 'html',
}

_SYNTAX_RULES = {
    'python': [
        ('comment', r'#[^\n]*'),
        ('string', r'(?:[rRbBuUfF]{1,3})?(?:"""(?:\\.|(?!""")[\s\S])*(?:"""|$)'
                   r"|'''(?:\\.|(?!''')[\s\S])*(?:'''|$)"
                   r'|"(?:\\.|[^"\\\n])*(?:"|$)'
                   r"|'(?:\\.|[^'\\\n])*(?:'|$))"),
        ('decorator', r'@[\w.]+'),
        ('keyword', r'\b(?:def|class|return|if|elif|else|for|while|try|except'
                    r'|finally|with|as|import|from|pass|break|continue|lambda'
                    r'|yield|global|nonlocal|assert|del|raise|not|and|or|in'
                    r'|is|async|await|match|case)\b'),
        ('const', r'\b(?:True|False|None)\b'),
        ('builtin', r'\b(?:self|cls|print|len|range|enumerate|zip|map|filter'
                    r'|int|str|float|bool|list|dict|set|tuple|type|super'
                    r'|isinstance|getattr|setattr|hasattr|open|input|sorted'
                    r'|sum|min|max|abs|any|all|repr|Exception|ValueError'
                    r'|TypeError|KeyError|RuntimeError)\b'),
        ('number', r'\b(?:0[xXoObB][0-9a-fA-F_]+'
                   r'|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*\()'),
        ('op', r'[-+*/%=<>!&|^~:]+'),
    ],
    'javascript': [
        ('comment', r'//[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'"(?:\\.|[^"\\\n])*(?:"|$)'
                   r"|'(?:\\.|[^'\\\n])*(?:'|$)"
                   r'|`(?:\\.|[^`\\])*(?:`|$)'),
        ('keyword', r'\b(?:function|return|if|else|for|while|do|switch|case'
                    r'|break|continue|new|delete|typeof|instanceof|in|of|var'
                    r'|let|const|class|extends|super|import|export|from'
                    r'|default|try|catch|finally|throw|async|await|yield'
                    r'|this|static|get|set)\b'),
        ('const', r'\b(?:true|false|null|undefined|NaN)\b'),
        ('number', r'\b\d[\d_]*(?:\.\d+)?\b'),
        ('func', r'\b[A-Za-z_$][\w$]*(?=\s*\()'),
        ('op', r'[-+*/%=<>!&|^~?:]+'),
    ],
    'json': [
        ('key', r'"(?:\\.|[^"\\])*"(?=\s*:)'),
        ('string', r'"(?:\\.|[^"\\])*(?:"|$)'),
        ('const', r'\b(?:true|false|null)\b'),
        ('number', r'-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b'),
    ],
    'bash': [
        ('comment', r'#[^\n]*'),
        ('string', r'"(?:\\.|[^"\\])*(?:"|$)|\x27[^\x27]*(?:\x27|$)'),
        ('var', r'\$\{?\w+\}?'),
        ('keyword', r'\b(?:if|then|else|elif|fi|for|in|do|done|while|case'
                    r'|esac|function|return|local|export|source|echo|cd|set'
                    r'|exit|shift|read)\b'),
        ('param', r'(?<=\s)--?[\w-]+'),
        ('number', r'\b\d+\b'),
    ],
    'powershell': [
        ('comment', r'#[^\n]*|<#[\s\S]*?(?:#>|$)'),
        ('string', r'@?"(?:`.|[^"`])*(?:"|$)|@?\x27[^\x27]*(?:\x27|$)'),
        ('var', r'\$\{?[\w:]+\}?'),
        ('keyword', r'\b(?:if|else|elseif|switch|foreach|for|while|do'
                    r'|function|param|return|try|catch|finally|throw|begin'
                    r'|process|end|in|filter|where)\b'),
        ('cmdlet', r'\b[A-Z][a-z]+-[A-Z]\w+\b'),
        ('param', r'(?<=[\s(])-\w+'),
        ('number', r'\b\d+\b'),
    ],
    'c': [
        ('comment', r'//[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'"(?:\\.|[^"\\\n])*(?:"|$)|\x27(?:\\.|[^\x27\\\n])*(?:\x27|$)'),
        ('keyword', r'\b(?:if|else|for|while|do|switch|case|break|continue'
                    r'|return|struct|enum|union|typedef|static|const|void'
                    r'|int|long|short|char|float|double|unsigned|signed'
                    r'|sizeof|class|public|private|protected|virtual|new'
                    r'|delete|namespace|using|template|typename|try|catch'
                    r'|throw|override|final|import|package)\b'),
        ('const', r'\b(?:NULL|nullptr|true|false)\b'),
        ('number', r'\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?[fFlLuU]*)\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*\()'),
        ('op', r'[-+*/%=<>!&|^~?:]+'),
    ],
    'go': [
        ('comment', r'//[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'"(?:\\.|[^"\\\n])*(?:"|$)|`[^`]*(?:`|$)'),
        ('keyword', r'\b(?:func|return|if|else|for|range|switch|case|break'
                    r'|continue|type|struct|interface|map|chan|go|defer'
                    r'|select|package|import|var|const|fallthrough|goto)\b'),
        ('const', r'\b(?:true|false|nil|iota)\b'),
        ('number', r'\b\d[\d_]*(?:\.\d+)?\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*\()'),
    ],
    'rust': [
        ('comment', r'//[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'"(?:\\.|[^"\\])*(?:"|$)'),
        ('keyword', r'\b(?:fn|let|mut|return|if|else|for|while|loop|match'
                    r'|struct|enum|impl|trait|pub|use|mod|crate|self|super'
                    r'|where|move|async|await|dyn|ref|static|const|unsafe'
                    r'|break|continue|in|as)\b'),
        ('const', r'\b(?:true|false|None|Some|Ok|Err)\b'),
        ('number', r'\b\d[\d_]*(?:\.\d+)?(?:[iuf]\d+)?\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*[(!])'),
        ('decorator', r'#\[[^\]]*\]?'),
    ],
    'sql': [
        ('comment', r'--[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'\x27[^\x27]*(?:\x27|$)'),
        ('keyword', r'\b(?i:select|from|where|insert|into|values|update|set'
                    r'|delete|create|table|drop|alter|join|left|right|inner'
                    r'|outer|on|group|by|order|having|limit|offset|as|and'
                    r'|or|not|null|is|in|like|between|distinct|union|index'
                    r'|primary|key|foreign)\b'),
        ('number', r'\b\d+(?:\.\d+)?\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*\()'),
    ],
    'yaml': [
        ('comment', r'#[^\n]*'),
        ('key', r'(?m:^\s*[\w.-]+(?=\s*:))'),
        ('string', r'"(?:\\.|[^"\\])*(?:"|$)|\x27[^\x27]*(?:\x27|$)'),
        ('const', r'\b(?:true|false|null|yes|no)\b'),
        ('number', r'\b\d+(?:\.\d+)?\b'),
    ],
    'ini': [
        ('comment', r'[;#][^\n]*'),
        ('tag', r'(?m:^\s*\[[^\]\n]*\]?)'),
        ('key', r'(?m:^\s*[\w.-]+(?=\s*=))'),
        ('number', r'\b\d+(?:\.\d+)?\b'),
    ],
    'html': [
        ('comment', r'<!--[\s\S]*?(?:-->|$)'),
        ('string', r'"[^"]*(?:"|$)|\x27[^\x27]*(?:\x27|$)'),
        ('tag', r'</?[\w-]+|/?>'),
        ('key', r'\b[\w-]+(?==)'),
    ],
    'generic': [
        ('comment', r'(?:#|//)[^\n]*|/\*[\s\S]*?(?:\*/|$)'),
        ('string', r'"(?:\\.|[^"\\\n])*(?:"|$)'
                   r"|'(?:\\.|[^'\\\n])*(?:'|$)"
                   r'|`(?:\\.|[^`\\])*(?:`|$)'),
        ('const', r'\b(?:true|false|null|none|True|False|None|nil)\b'),
        ('number', r'\b\d[\d_]*(?:\.\d+)?\b'),
        ('func', r'\b[A-Za-z_]\w*(?=\s*\()'),
    ],
}

_LANG_PATTERNS = {}


def _lang_pattern(lang):
    lang = _LANG_ALIASES.get(lang, lang)
    if lang not in _SYNTAX_RULES:
        lang = 'generic'
    if lang not in _LANG_PATTERNS:
        rules = _SYNTAX_RULES[lang]
        pattern = '|'.join(
            '(?P<t%d>%s)' % (index, expr) for index, (_, expr) in enumerate(rules)
        )
        _LANG_PATTERNS[lang] = (rules, re.compile(pattern))
    return _LANG_PATTERNS[lang]


def highlight_code(code, lang='', theme=None):
    """Syntax-highlight ``code``; returns one span-line per source line."""
    theme = theme or MD_THEME
    rules, pattern = _lang_pattern((lang or '').lower())
    styles = [None] * len(code)
    for match in pattern.finditer(code):
        token = rules[int(match.lastgroup[1:])][0]
        style = theme.syntax.get(token)
        for i in range(match.start(), match.end()):
            styles[i] = style
    lines = [[]]
    for char, style in zip(code, styles):
        if char == '\n':
            lines.append([])
        else:
            lines[-1].append((char, style or theme.code_text))
    return [_merge_chars(chars) for chars in lines]


_MD_FENCE = re.compile(r'^(\s{0,3})(`{3,}|~{3,})\s*([^\s`]*)\s*$')
_MD_HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
_MD_HR = re.compile(r'^\s{0,3}([-*_])(?:\s*\1){2,}\s*$')
_MD_UL = re.compile(r'^(\s*)([-*+])\s+(.*)$')
_MD_OL = re.compile(r'^(\s*)(\d{1,9})[.)]\s+(.*)$')
_MD_QUOTE = re.compile(r'^\s{0,3}(>+)\s?(.*)$')
_MD_TASK = re.compile(r'^\[([ xX])\]\s+(.*)$')
_MD_TABLE_SEP = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$')

_INLINE = re.compile(
    r'(?P<code>`+)(?P<code_t>.+?)(?P=code)'
    r'|\*\*\*(?P<bi_t>.+?)\*\*\*'
    r'|\*\*(?P<b_t>.+?)\*\*'
    r'|\*(?P<i_t>[^\s*](?:[^*]*[^\s*])?)\*'
    r'|(?<![\w`])_(?P<iu_t>[^\s_](?:[^_]*[^\s_])?)_(?!\w)'
    r'|~~(?P<s_t>.+?)~~'
    r'|\[(?P<l_t>[^\]]+)\]\((?P<l_u>[^)\s]+)(?:\s+"[^"]*")?\)'
)


def parse_inline(text, base=None, theme=None):
    """Markdown inline syntax -> spans."""
    theme = theme or MD_THEME
    base = base if base is not None else theme.text
    out = []
    position = 0
    for match in _INLINE.finditer(text):
        if match.start() > position:
            out.append((text[position:match.start()], base))
        if match.group('code'):
            out.append((match.group('code_t'), theme.code_inline))
        elif match.group('bi_t') is not None:
            out.extend(parse_inline(match.group('bi_t'),
                                    base(bold=True, italic=True), theme))
        elif match.group('b_t') is not None:
            out.extend(parse_inline(match.group('b_t'), base(bold=True), theme))
        elif match.group('i_t') is not None:
            out.extend(parse_inline(match.group('i_t'), base(italic=True), theme))
        elif match.group('iu_t') is not None:
            out.extend(parse_inline(match.group('iu_t'), base(italic=True), theme))
        elif match.group('s_t') is not None:
            out.append((match.group('s_t'), theme.strike))
        elif match.group('l_t') is not None:
            out.append((match.group('l_t'), theme.link))
        position = match.end()
    if position < len(text):
        out.append((text[position:], base))
    return out or [('', base)]


def _md_code_block(code_lines, lang, width, theme):
    code = '\n'.join(code_lines).replace('\t', '    ')
    inner = max(4, width - 4)
    label = (lang or 'code')[:24]
    tail = max(0, width - 6 - len(label))
    out = [[('╭─ ', theme.code_border), (label, theme.code_lang),
            (' ' + '─' * tail + '╮', theme.code_border)]]
    highlighted = highlight_code(code, lang, theme) if code else [[]]
    for source_line in highlighted:
        for piece in wrap_spans(source_line, inner):
            body = pad_spans(piece, inner)
            out.append([('│ ', theme.code_border), *body,
                        (' │', theme.code_border)])
    out.append([('╰' + '─' * (width - 2) + '╯', theme.code_border)])
    return out


def _md_table(rows, width, theme):
    def cells(row):
        row = row.strip()
        if row.startswith('|'):
            row = row[1:]
        if row.endswith('|'):
            row = row[:-1]
        return [cell.strip() for cell in row.split('|')]

    header = cells(rows[0])
    body = [cells(row) for row in rows[2:]]
    ncols = max([len(header)] + [len(row) for row in body])
    header += [''] * (ncols - len(header))
    body = [row + [''] * (ncols - len(row)) for row in body]

    parsed_header = [parse_inline(cell, theme.table_header, theme)
                     for cell in header]
    parsed_body = [[parse_inline(cell, theme.text, theme) for cell in row]
                   for row in body]

    widths = [max([spans_width(parsed_header[col])] +
                  [spans_width(row[col]) for row in parsed_body] + [3])
              for col in range(ncols)]
    available = max(ncols * 3, width - 3 * (ncols - 1))
    guard = 0
    while sum(widths) > available and guard < 500:
        widest = widths.index(max(widths))
        if widths[widest] <= 3:
            break
        widths[widest] -= 1
        guard += 1

    def build_row(parsed, pad_style=None):
        line = []
        for col in range(ncols):
            cell = pad_spans(truncate_spans(parsed[col], widths[col]),
                             widths[col], pad_style)
            line.extend(cell)
            if col < ncols - 1:
                line.append((' │ ', theme.table_border))
        return line

    out = [build_row(parsed_header)]
    separator = []
    for col in range(ncols):
        separator.append(('─' * widths[col], theme.table_border))
        if col < ncols - 1:
            separator.append(('─┼─', theme.table_border))
    out.append(separator)
    for row in parsed_body:
        out.append(build_row(row))
    return out


def render_markdown(source, width, theme=None):
    """Markdown -> span-lines. Line-forward and prefix-stable: rendering a
    stable prefix (see ``markdown_stable_cut``) yields an exact prefix of
    rendering the full document, which enables progressive streaming."""
    theme = theme or MD_THEME
    width = max(8, width)
    out = []

    def space():
        if out and out[-1] != []:
            out.append([])

    lines = source.split('\n')
    total = len(lines)
    fence = None  # (marker, lang, buffer)
    # Previous block kind, so the renderer can put a blank line at the seams
    # the source forgot. A heading welded to its own body text stops working
    # as a grouping cue: proximity says "these belong together" while the
    # heading is trying to say "a new thing starts here".
    kind = None
    index = 0
    while index < total:
        raw = lines[index].rstrip('\r')
        index += 1
        if fence is not None:
            closing = _MD_FENCE.match(raw)
            if (closing and closing.group(2)[0] == fence[0][0]
                    and len(closing.group(2)) >= len(fence[0])
                    and not closing.group(3)):
                out.extend(_md_code_block(fence[2], fence[1], width, theme))
                fence = None
            else:
                fence[2].append(raw)
            continue
        opening = _MD_FENCE.match(raw)
        if opening:
            space()
            fence = (opening.group(2), opening.group(3).lower(), [])
            kind = None
            continue
        if not raw.strip():
            space()
            kind = None
            continue
        heading = _MD_HEADING.match(raw)
        if heading:
            space()
            level = len(heading.group(1))
            text = heading.group(2)
            if level == 1:
                out.extend(wrap_spans(
                    gradient_spans(text, theme.accent_stops,
                                   style=Style(bold=True)), width))
                out.append([('─' * min(width, max(12, spans_width(as_spans(text)))),
                             theme.rule)])
            else:
                style = {2: theme.h2, 3: theme.h3}.get(level, theme.h4)
                out.extend(wrap_spans([(text, style)], width))
            out.append([])  # breathing room under every heading
            kind = 'heading'
            continue
        if _MD_HR.match(raw):
            space()
            out.append([('─' * width, theme.rule)])
            kind = None
            continue
        quote = _MD_QUOTE.match(raw)
        if quote:
            if kind in ('text', 'list'):
                space()
            kind = 'quote'
            depth = min(len(quote.group(1)), 4)
            bar = '│ ' * depth
            content = parse_inline(quote.group(2), theme.quote_text, theme)
            for piece in wrap_spans(content, max(4, width - 2 * depth)):
                out.append([(bar, theme.quote_bar), *piece])
            continue
        unordered = _MD_UL.match(raw)
        if unordered:
            if kind in ('text', 'quote'):
                space()
            kind = 'list'
            indent = len(unordered.group(1).expandtabs(4))
            level = min(indent // 2, 5)
            pad = '  ' * level
            body = unordered.group(3)
            task = _MD_TASK.match(body)
            if task:
                done = task.group(1).lower() == 'x'
                glyph = ('● ', theme.task_done) if done else ('○ ', theme.task_todo)
                text_style = (Style(fg=(107, 114, 128), strike=True)
                              if done else theme.text)
                marker = [(pad, None), glyph]
                content = parse_inline(task.group(2), text_style, theme)
            else:
                bullets = '•◦▪·'
                marker = [(pad + bullets[level % 4] + ' ', theme.bullet)]
                content = parse_inline(body, theme.text, theme)
            hang = len(pad) + 2
            out.extend(wrap_spans(marker + content, width, hang=hang))
            continue
        ordered = _MD_OL.match(raw)
        if ordered:
            if kind in ('text', 'quote'):
                space()
            kind = 'list'
            indent = len(ordered.group(1).expandtabs(4))
            level = min(indent // 2, 5)
            pad = '  ' * level
            marker_text = pad + ordered.group(2) + '. '
            marker = [(marker_text, theme.number)]
            content = parse_inline(ordered.group(3), theme.text, theme)
            out.extend(wrap_spans(marker + content, width, hang=len(marker_text)))
            continue
        if ('|' in raw and index < total and lines[index].count('-') >= 2
                and '|' in lines[index] and _MD_TABLE_SEP.match(lines[index])):
            table_rows = [raw, lines[index]]
            index += 1
            while index < total and '|' in lines[index] and lines[index].strip():
                table_rows.append(lines[index])
                index += 1
            space()
            out.extend(_md_table(table_rows, width, theme))
            kind = None
            continue
        # An indented line right after a list item or quote is that block's
        # lazy continuation, not a new paragraph — don't split it off.
        if kind in ('list', 'quote') and not raw[:1].isspace():
            space()
        out.extend(wrap_spans(parse_inline(raw, theme.text, theme), width))
        kind = 'text'
    if fence is not None:
        out.extend(_md_code_block(fence[2], fence[1], width, theme))
    return out


def markdown_stable_cut(source):
    """Split streaming markdown into ``(stable, tail)`` where the stable
    part's rendering is final. Cuts at the last blank line outside fences;
    the final (still growing) line is never stable."""
    lines = source.split('\n')
    fence = None
    cut = 0
    for index, raw in enumerate(lines[:-1]):
        match = _MD_FENCE.match(raw)
        if fence is None:
            if match and match.group(3) is not None:
                fence = match.group(2)
            elif not raw.strip():
                cut = index + 1
        elif (match and match.group(2)[0] == fence[0]
                and len(match.group(2)) >= len(fence) and not match.group(3)):
            fence = None
    if cut == 0:
        return '', source
    return '\n'.join(lines[:cut]), '\n'.join(lines[cut:])


# ----------------------------------------------------------------- screen ----

class Screen:
    """Flicker-free flow renderer: permanent transcript lines above a live
    region that is repainted in place every frame.

    The live region is a callable ``fn(t, width, height) -> [span-lines]``;
    it is always the last block on screen. ``append`` writes permanent lines
    above it. All terminal output must go through this object while active.
    """

    def __init__(self, out=None, fps=24):
        self.out = out or sys.stdout
        self.lock = threading.RLock()
        self._live = None
        self._painted = 0
        self._fps = fps
        self._stop = threading.Event()
        self._thread = None
        self._epoch = time.monotonic()
        enable_vt()
        ensure_utf8()

    # -- lifecycle
    def start(self):
        with self.lock:
            self._write('\033[?25l')
            self._flush()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='screen-paint')
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        with self.lock:
            self._live = None
            self._write('\033[0m\033[?25h')
            self._flush()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def _loop(self):
        interval = 1.0 / self._fps
        while not self._stop.wait(interval):
            if self._live is not None:
                self.paint()

    # -- info
    def size(self):
        term = shutil.get_terminal_size()
        return term.columns, term.lines

    def now(self):
        return time.monotonic() - self._epoch

    # -- low level
    def _write(self, data):
        self.out.write(data)

    def _flush(self):
        try:
            self.out.flush()
        except Exception:
            pass

    def _render_line(self, line, width):
        line = as_spans(line) if not isinstance(line, list) else line
        return render_spans(truncate_spans(line, max(1, width - 1)))

    def _erase_live(self):
        if self._painted:
            sequence = '\033[%dF\033[J' % self._painted
            self._painted = 0
            return sequence
        return ''

    # -- api
    def append(self, *lines):
        """Write permanent transcript lines above the live region."""
        with self.lock:
            width, _ = self.size()
            sequence = '\033[?2026h' + self._erase_live()
            for line in lines:
                sequence += '\033[2K' + self._render_line(line, width) + '\n'
            self._write(sequence + '\033[?2026l')
            self._flush()
        self.paint()

    def set_live(self, fn):
        with self.lock:
            self._live = fn
        self.paint()

    def clear_live(self, *final_lines):
        """Drop the live region, optionally leaving permanent lines."""
        with self.lock:
            self._live = None
            width, _ = self.size()
            sequence = '\033[?2026h' + self._erase_live()
            for line in final_lines:
                sequence += '\033[2K' + self._render_line(line, width) + '\n'
            self._write(sequence + '\033[?2026l')
            self._flush()

    def paint(self):
        with self.lock:
            live = self._live
            if live is None:
                return
            width, height = self.size()
            try:
                lines = live(self.now(), width, height) or []
            except Exception as error:  # never let a paint error kill the UI
                lines = [[('⚠ render error: %r' % (error,),
                           Style(fg=(248, 113, 113)))]]
            lines = lines[-(max(1, height - 1)):]
            sequence = '\033[?2026h'
            sequence += '\033[%dF' % self._painted if self._painted else '\r'
            for line in lines:
                sequence += '\033[2K' + self._render_line(line, width) + '\n'
            sequence += '\033[J\033[?2026l'
            self._painted = len(lines)
            self._write(sequence)
            self._flush()

    def handle_resize(self):
        with self.lock:
            self._painted = 0
            self._write('\r\033[J')
            self._flush()
        self.paint()

    def clear_screen(self):
        with self.lock:
            self._painted = 0
            self._write('\033[2J\033[H')
            self._flush()
        self.paint()


# -------------------------------------------------------------- text field ----

class TextField:
    """Editing model for a (multi-line) input widget. Drawing-free: feed it
    events, then lay it out with ``layout`` and render however you like."""

    def __init__(self):
        self.chars = []
        self.cursor = 0
        self.history = []
        self._history_index = None
        self._stash = ''

    # -- content
    @property
    def text(self):
        return ''.join(self.chars)

    def set_text(self, value):
        self.chars = list(str(value).replace('\r', '').replace('\t', '    '))
        self.cursor = len(self.chars)

    def clear(self):
        self.chars = []
        self.cursor = 0
        self._history_index = None

    def insert(self, text):
        text = str(text).replace('\r\n', '\n').replace('\r', '\n')
        text = text.replace('\t', '    ')
        for char in text:
            if char == '\n' or char.isprintable():
                self.chars.insert(self.cursor, char)
                self.cursor += 1

    def backspace(self):
        if self.cursor:
            self.cursor -= 1
            self.chars.pop(self.cursor)

    def delete(self):
        if self.cursor < len(self.chars):
            self.chars.pop(self.cursor)

    # -- word motion
    def _is_word(self, index):
        return self.chars[index] not in ' \n'

    def word_left(self):
        i = self.cursor
        while i and not self._is_word(i - 1):
            i -= 1
        while i and self._is_word(i - 1):
            i -= 1
        self.cursor = i

    def word_right(self):
        i, n = self.cursor, len(self.chars)
        while i < n and not self._is_word(i):
            i += 1
        while i < n and self._is_word(i):
            i += 1
        self.cursor = i

    def kill_word(self):
        end = self.cursor
        self.word_left()
        del self.chars[self.cursor:end]

    def line_home(self):
        i = self.cursor
        while i and self.chars[i - 1] != '\n':
            i -= 1
        self.cursor = i

    def line_end(self):
        i, n = self.cursor, len(self.chars)
        while i < n and self.chars[i] != '\n':
            i += 1
        self.cursor = i

    # -- history
    def history_add(self, text):
        if text.strip() and (not self.history or self.history[-1] != text):
            self.history.append(text)

    def history_prev(self):
        if not self.history:
            return
        if self._history_index is None:
            self._stash = self.text
            self._history_index = len(self.history)
        if self._history_index > 0:
            self._history_index -= 1
            self.set_text(self.history[self._history_index])

    def history_next(self):
        if self._history_index is None:
            return
        self._history_index += 1
        if self._history_index >= len(self.history):
            self._history_index = None
            self.set_text(self._stash)
        else:
            self.set_text(self.history[self._history_index])

    # -- layout
    def _layout_full(self, inner_width):
        inner_width = max(2, inner_width)
        rows = [[]]
        cells = [0]
        positions = []
        for char in self.chars:
            if char == '\n':
                positions.append((len(rows) - 1, cells[-1]))
                rows.append([])
                cells.append(0)
                continue
            char_width = max(1, _char_width(char))
            if cells[-1] + char_width > inner_width:
                rows.append([])
                cells.append(0)
            positions.append((len(rows) - 1, cells[-1]))
            rows[-1].append(char)
            cells[-1] += char_width
        if self.cursor < len(positions):
            cursor_row, cursor_col = positions[self.cursor]
        else:
            cursor_row, cursor_col = len(rows) - 1, cells[-1]
        return rows, cursor_row, cursor_col, positions

    def layout(self, inner_width):
        """Hard-wrap to ``inner_width`` cells. Returns
        ``(rows, cursor_row, cursor_col)`` with cursor col in cells."""
        rows, cursor_row, cursor_col, _ = self._layout_full(inner_width)
        return rows, cursor_row, cursor_col

    def move_vertical(self, delta, inner_width):
        """Move the cursor a visual row up/down. Returns False at an edge."""
        rows, cursor_row, cursor_col, positions = self._layout_full(inner_width)
        target = cursor_row + delta
        if not 0 <= target < len(rows):
            return False
        best = None
        for index, (row, col) in enumerate(positions):
            if row == target:
                if col <= cursor_col:
                    best = index
                elif best is None:
                    best = index
                    break
            elif row > target:
                break
        if best is None:
            self.cursor = len(self.chars)
            return True
        row, col = positions[best]
        char_width = max(1, _char_width(self.chars[best]))
        if col + char_width <= cursor_col:
            is_last = best + 1 >= len(positions) or positions[best + 1][0] != row
            if is_last and self.chars[best] != '\n':
                best += 1
        self.cursor = best
        return True

    # -- events
    def feed(self, event):
        """Apply a terminal event. Returns one of:
        'submit' | 'changed' | 'up' | 'down' | 'escape' | 'tab' | None."""
        if event.type == 'paste':
            self.insert(event.text or '')
            return 'changed'
        if event.type != 'key' or event.action != 'down':
            return None
        key = event.key or ''
        ctrl = event.ctrl or key.startswith('ctrl_')
        plain = key.removeprefix('ctrl_')
        if key == 'enter':
            if event.alt or event.shift:
                self.insert('\n')
                return 'changed'
            return 'submit'
        if key == 'escape':
            return 'escape'
        if key == 'tab':
            return 'tab'
        if key in ('up', 'down'):
            return key
        if key == 'backspace':
            if ctrl or event.alt:
                self.kill_word()
            else:
                self.backspace()
            return 'changed'
        if key == 'delete':
            self.delete()
            return 'changed'
        if key == 'left':
            if ctrl:
                self.word_left()
            elif self.cursor:
                self.cursor -= 1
            return 'changed'
        if key == 'right':
            if ctrl:
                self.word_right()
            elif self.cursor < len(self.chars):
                self.cursor += 1
            return 'changed'
        if key == 'home':
            self.line_home()
            return 'changed'
        if key == 'end':
            self.line_end()
            return 'changed'
        if ctrl and plain == 'a':
            self.line_home()
            return 'changed'
        if ctrl and plain == 'e':
            self.line_end()
            return 'changed'
        if ctrl and plain == 'u':
            del self.chars[:self.cursor]
            self.cursor = 0
            return 'changed'
        if ctrl and plain == 'k':
            del self.chars[self.cursor:]
            return 'changed'
        if ctrl and plain == 'w':
            self.kill_word()
            return 'changed'
        if ctrl or event.alt:
            return None
        if event.text and (event.text.isprintable() or event.text == ' '):
            self.insert(event.text)
            return 'changed'
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Signature motion primitives (v3)
#
# Pure functions of (width, t) so they render deterministically and can be
# unit-tested at a fixed t. Palette is passed in (``stops``). These power the
# activity strip (bouncer_line) and the fold-out transitions (fold_lines /
# dim_spans); the input rail keeps using spine_cell / rail_spans above.
# ═══════════════════════════════════════════════════════════════════════════


def _clamp01(value):
    return 0.0 if value < 0 else 1.0 if value > 1 else value


TRAIL_DENSITY = '█▓▒░'  # motion-blur ramp, densest nearest the head


def bouncer_line(width, t, stops=None, *, speed=15.0, tail=10,
                 head=' ', bg=(18, 20, 28), head_color=(255, 247, 233),
                 ease=1.0):
    """A one-line 'DVD bouncer': a bright head glyph swings across the row and
    bounces off both edges, dragging a motion-blur trail behind it. The trail
    is purely abstract — a density ramp (``█▓▒░``) fading into ``bg``, never
    text.

    ``ease`` (0..1) shapes the travel curve, blending a linear ping-pong (0)
    with a harmonic swing (1): the head decelerates into each edge, hangs for
    a beat, then accelerates back out. The trail stretches with the
    *instantaneous* speed, so the blur is longest mid-flight and collapses at
    the turnaround — the motion reads as weight rather than a sliding block.

    Returns one span-line of exactly ``width`` cells. Deterministic in ``t``."""
    stops = stops or EMBER_STOPS
    width = max(6, width)
    span = width - 1
    ease = _clamp01(ease)

    cycle = (t * speed) % (2 * span)
    direction = 1 if cycle <= span else -1
    leg = cycle if direction == 1 else 2 * span - cycle   # 0 → span
    linear = leg / span
    harmonic = 0.5 - 0.5 * math.cos(math.pi * linear)
    head_col = int(round(((1.0 - ease) * linear + ease * harmonic) * span))

    # instantaneous speed (1 mid-flight, 0 at the turnaround) drives blur length
    rate = (1.0 - ease) + ease * math.sin(math.pi * linear)
    count = 0 if tail <= 0 else max(1, min(int(round(tail * rate)), width - 1))
    levels = len(TRAIL_DENSITY)

    grid = [(' ', None)] * width
    grid[head_col] = (head, Style(fg=head_color, bold=True))
    for index in range(count):
        col = head_col - (index + 1) * direction
        if not 0 <= col < width:
            continue
        near = 1.0 - index / max(1, count)          # 1 at the head, 0 at the end
        glyph = TRAIL_DENSITY[min(levels - 1, int((1.0 - near) * levels))]
        base = sample_gradient(stops, 0.30 + 0.55 * near)
        grid[col] = (glyph, Style(fg=blend(bg, base, 0.12 + 0.88 * near)))
    return _merge_chars(grid)


def dim_spans(spans, factor, bg=(16, 18, 26)):
    """Fade a span-line toward ``bg`` by ``factor`` (0 keeps it, 1 hides it)."""
    factor = _clamp01(factor)
    out = []
    for text, style in spans:
        if style is not None and style.fg is not None:
            out.append((text, style(fg=blend(style.fg, bg, factor))))
        else:
            out.append((text, style))
    return out


def fold_lines(lines, progress, bg=(16, 18, 26)):
    """Collapse a block of span-lines for a fold-out transition: ``progress``
    0 → full height, 1 → gone. Rows retract from the bottom while the survivors
    fade, so a panel folds away instead of blinking out."""
    progress = _clamp01(progress)
    keep = max(0, int(round(len(lines) * (1.0 - progress))))
    fade = min(1.0, progress * 1.4)
    return [dim_spans(line, fade, bg) for line in lines[:keep]]
