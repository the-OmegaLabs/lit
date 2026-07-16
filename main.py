import random
import string
import threading
import time

import ascii
import util
import colorama

colorama.init()

SPECIAL_KEYS = {
    'escape', 'tab', 'insert', 'delete', 'home', 'end', 'page_up', 'page_down',
    'left', 'right', 'up', 'down',
}

version = '0.0.1'


class TerminalAnimation:
    def __init__(self, terminal, frames, interval=0.1):
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

    def _draw(self, frame, end = False):
        x, y = self._position
        content = frame.ljust(self._draw_width)
        
        if end:
            self.terminal.send_command(
                f'\033[s\033[{y + 1};{x + 1}H{content}\033[u'
            )
        else:
            self.terminal.send_command(
                self.terminal.colored_text(f'\033[s\033[{y + 1};{x + 1}H{content}\033[u', (128, 128, 128), None)
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

            self._draw(self.frames[frame_index])
            frame_index = (frame_index + 1) % len(self.frames)

            wait_time = self.interval
            if deadline is not None:
                wait_time = min(wait_time, max(0, deadline - time.monotonic()))
            self._stop_event.wait(wait_time)

        if not self._stop_event.is_set():
            self._draw(self._final_frame, end=True)

def shortcut_name(event):
    modifiers = []
    if event.ctrl:
        modifiers.append('Ctrl')
    if event.alt:
        modifiers.append('Alt')
    if event.shift:
        modifiers.append('Shift')

    key = event.key or 'unknown'
    if key.startswith('ctrl_'):
        if 'Ctrl' not in modifiers:
            modifiers.append('Ctrl')
        key = key.removeprefix('ctrl_')

    display_key = key.upper() if len(key) == 1 else key.replace('_', ' ').title()
    return '+'.join((*modifiers, display_key))


def is_shortcut(event):
    key = event.key or ''
    return (
        event.ctrl
        or event.alt
        or key.startswith('ctrl_')
        or key in SPECIAL_KEYS
        or (key.startswith('f') and key[1:].isdigit())
    )


terminal = ascii.TerminalOutput()
terminal.clear_screen()

term_size = terminal.get_size()

logo = util.read_file('art.txt')
logo_width = len(logo.split('\n')[0])

model = f'kimi-k3 - epstein'

if len(model) < 15:
    offset = 0
else:
    offset = len(model) - 15

terminal.print_rect(position=(2, -1), size=(52 + offset, 11))
terminal.print_text(position=(5, 1), size=(60, 11), in_rect=True, content=logo)

terminal.move_cursor(10 + logo_width, 3)
formatted_org = terminal.colored_text(f'Omega Labs', text_rgb=(192, 192, 192), back_rgb=None)
terminal.print(f'{formatted_org}')

terminal.move_cursor(10 + logo_width, 4)
formatted_version = terminal.colored_text(f'(v{version})', text_rgb=(128, 128, 128), back_rgb=None)
terminal.print(f'Lit. {formatted_version}')

terminal.move_cursor(10 + logo_width, 6)
terminal.print(f'Supercharged by')
terminal.move_cursor(10 + logo_width, 7)

formatted_model = terminal.colored_text(model, text_rgb=(128, 128, 128), back_rgb=None)
terminal.print(formatted_model)

terminal.move_cursor(0, term_size[1] - 1)

def poster(text = '', delay: float = 0, duration: float = 0, interval = 0.05, sleep = 0.1, callback = None, offset_x = 0, animations = []):
    time.sleep(delay)

    for cnt, i in enumerate(text):
        animation = TerminalAnimation(terminal, random.sample(string.printable, len(string.printable)), interval=interval)
        animation.start(
            (cnt + offset_x, max(0, terminal.y - 3)),
            duration=duration,
            final_frame=i,
        )

        animations.append(animation)

        time.sleep(sleep)
        
    time.sleep(duration)

    if callback:
        callback()

def prompt_input(dispatcher, prompt):
    value = []
    terminal.print(prompt, end='', flush=True)

    while True:
        event = dispatcher.get_event()
        if event.type != 'key' or event.action != 'down':
            continue

        key = event.key or ''
        normalized_key = key.removeprefix('ctrl_').lower()

        if (event.ctrl or key.startswith('ctrl_')) and normalized_key in ('c', 'd'):
            raise KeyboardInterrupt

        if key == 'enter':
            return ''.join(value)

        if key == 'escape':
            return ''

        if key == 'backspace':
            if value:
                value.pop()
                terminal.send_command('\b \b')
            continue

        if event.text and event.text.isprintable():
            value.append(event.text)
            terminal.print(event.text, end='', flush=True)


def read_line(dispatcher, prompt='> '):
    value = []
    terminal.print(prompt, end='', flush=True)

    def redraw_shortcut(name):
        terminal.move_cursor(0, max(0, terminal.y - 1))
        terminal.clear_line()
        terminal.print(f'shortcut: {name}\n', end='', flush=True)
        terminal.clear_line()
        terminal.print(f'{prompt}{"".join(value)}', end='', flush=True)

    while True:
        event = dispatcher.get_event()

        if event.type == 'resize':
            terminal.print(
                f'\nterminal resized to {event.width}x{event.height}\n{prompt}{"".join(value)}',
                end='',
                flush=True,
            )
            continue

        if event.type != 'key' or event.action != 'down':
            continue

        key = event.key or ''
        normalized_key = key.removeprefix('ctrl_').lower()

        if is_shortcut(event):
            name = shortcut_name(event)

            if (event.ctrl or key.startswith('ctrl_')) and normalized_key == 'v':
                continue

            if key == 'escape':
                if not value:
                    terminal.clear_line()
                    terminal.move_cursor(0, terminal.y)
                    answer = prompt_input(dispatcher, 'Exit Lit? [Y/n] ')

                    if answer.lower() == 'y' or not answer:
                        exit()

                value.clear()
                terminal.clear_line()
                terminal.move_cursor(0, terminal.y)
                terminal.print(prompt, end='', flush=True)
                continue

            redraw_shortcut(name)

            if (event.ctrl or key.startswith('ctrl_')) and normalized_key in ('c', 'd'):
                raise KeyboardInterrupt
            continue

        if key == 'enter':
            frame = [
    "⠋", "⠙", "⠹", "⠸",
    "⠼", "⠴", "⠦", "⠧",
    "⠇", "⠏"
]

            animation = TerminalAnimation(terminal, frame, interval=0.15)
            animation.start(
                (0, max(0, terminal.y - 3)),
                duration=500,
                final_frame=' ',
            )
            
            loading = [
                "Thinking",
                "Analyzing",
                "Planning",
                "Reading",
                "Searching",
                "Inspecting",
                "Exploring",
                "Considering",
                "Reviewing",
                "Examining",
                "Checking",
                "Evaluating",
                "Calculating",
                "Comparing",
                "Refactoring",
                "Debugging",
                "Implementing",
                "Crafting",
                "Building",
                "Generating",
                "Brewing",
                "Cooking",
                "Noodling",
                "Pondering",
                "Cogitating",
                "Pontificating",
                "Percolating",
                "Meditating",
                "Contemplating",
                "Spelunking",
                "Schlepping",
                "Envisioning",
                "Synthesizing",
            ]

            def worker():
                for i in loading:
                    a = threading.Thread(target=lambda: poster(f'{i}...      ', 0.5, 0.15, 0.5, 0.05, None, 2), daemon=True)
                    a.start()

                    time.sleep(3)

            threading.Thread(target=worker, daemon=True).start()

            terminal.move_cursor(0, terminal.y)
            terminal.clear_line()
            return ''.join(value)

        if key == 'backspace':
           if value:
                value.pop()
                terminal.send_command('\b \b')

        if event.text and event.text.isprintable():
            value.append(event.text)
            terminal.print(event.text, end='', flush=True)


try:
    with ascii.TerminalEventDispatcher(mouse=True) as events:
        while True:
            text = read_line(events)
            terminal.move_cursor(0, terminal.y)
            terminal.clear_line()
except KeyboardInterrupt:
    terminal.print('\nexit')
