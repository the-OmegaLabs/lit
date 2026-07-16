# Terminal Controlling

import sys
import shutil
import os
import time
import queue
import threading
from typing import Literal
import wcwidth
from dataclasses import dataclass

class ControlCode:
    CLEAR_SCREEN = '\033[2J'
    CLEAR_LINE = '\033[2K'

    MOVE_CURSOR_TO_SCREEN_START = '\033[H'
    MOVE_CURSOR = lambda row, col: f'\033[{col};{row}H'

class TerminalOutput:
    def __init__(self):
        self.lock = threading.Lock()
        self.x = 0
        self.y = 0

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

    def get_size(self):
        term = shutil.get_terminal_size()

        return term.columns, term.lines
    
    def get_string_width(self, string):
        return wcwidth.wcswidth(string)

    def print(self, *values, sep=' ', end='\n', flush=False):
        content = sep.join(map(str, values)) + end

        sys.stdout.write(content)

        width, height = self.get_size()

        for ch in content:
            if ch == '\n':
                self.y += 1
                self.x = 0
            else:
                w = self.get_string_width(ch)
                if w < 0:
                    w = 0

                self.x += w

                if self.x >= width: # fix width
                    self.y += self.x // width
                    self.x %= width

            if self.y >= height: # fix height
                self.y = height - 1

        if flush:
            sys.stdout.flush()

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
