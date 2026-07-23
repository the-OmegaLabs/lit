# Terminal Controlling

import sys
import shutil
import os
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

    type: Literal['key', 'mouse', 'resize']
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
        if mouse:
            # SGR coordinates, click/drag tracking, and mouse motion tracking.
            sys.stdout.write('\x1b[?1000h\x1b[?1002h\x1b[?1006h')
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
            data = os.read(self._fd, 64)
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
            if self._mouse:
                sys.stdout.write('\x1b[?1006l\x1b[?1002l\x1b[?1000l')
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
