import random
import string
import threading
import time

import ascii
import util
import colorama

version = '0.0.1'
colorama.init()

SPECIAL_KEYS = {
    'escape', 'tab', 'insert', 'delete', 'home', 'end', 'page_up', 'page_down',
    'left', 'right', 'up', 'down',
}

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

class Lit:
    def __init__(self):
        self.terminal = ascii.TerminalOutput()
        self.terminal.clear_screen()

        term_size = self.terminal.get_size()

        self.logo = util.read_file('art.txt')
        
        self.model = f'kimi-k3 - epstein'

        self.draw_splash()

        self.terminal.move_cursor(0, term_size[1] - 1)
    
        try:
            with ascii.TerminalEventDispatcher(mouse=True) as events:
                while True:
                    text = self.read_line(events)
                    self.terminal.move_cursor(0, self.terminal.y)
                    self.terminal.clear_line()
        except KeyboardInterrupt:
            self.terminal.print('\nexit')


    def prompt_input(self, dispatcher, prompt):
        value = []
        self.terminal.print(prompt, end='', flush=True)

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
                    self.terminal.send_command('\b \b')
                continue

            if event.text and event.text.isprintable():
                value.append(event.text)
                self.terminal.print(event.text, end='', flush=True)

    def read_line(self, dispatcher, prompt='> '):
        value = []
        self.terminal.print(prompt, end='', flush=True)

        def redraw_shortcut(name):
            self.terminal.move_cursor(0, max(0, self.terminal.y - 1))
            self.terminal.clear_line()
            self.terminal.print(f'shortcut: {name}\n', end='', flush=True)
            self.terminal.clear_line()
            self.terminal.print(f'{prompt}{"".join(value)}', end='', flush=True)

        while True:
            event = dispatcher.get_event()

            if event.type == 'resize':
                self.terminal.print(
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
                        self.terminal.clear_line()
                        self.terminal.move_cursor(0, self.terminal.y)
                        answer = self.prompt_input(dispatcher, 'Exit Lit? [Y/n] ')

                        if answer.lower() == 'y' or not answer:
                            exit()

                    value.clear()
                    self.terminal.clear_line()
                    self.terminal.move_cursor(0, self.terminal.y)
                    self.terminal.print(prompt, end='', flush=True)
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

                animation = ascii.TerminalAnimation(self.terminal, frame, interval=0.15)
                animation.start(
                    (0, max(0, self.terminal.y - 3)),
                    duration=10,
                    final_frame=' ',
                )
                
                loading = [
                    "Thinking...",
                    "Analyzing...",
                    "Planning...",
                    "           "
                ]

                def worker():
                    for i in loading:
                        a = threading.Thread(target=lambda: self.animate_poster(f'{i}      ', 0.5, 0.15, 0.5, 0.05, None, 2), daemon=True)
                        a.start()

                        time.sleep(3)

                threading.Thread(target=worker, daemon=True).start()

                self.terminal.move_cursor(0, self.terminal.y)
                self.terminal.clear_line()
                return ''.join(value)

            if key == 'backspace':
                if value:
                    value.pop()
                    self.terminal.send_command('\b \b')

            if event.text and event.text.isprintable():
                value.append(event.text)
                self.terminal.print(event.text, end='', flush=True)


    def animate_poster(self, text = '', delay: float = 0, duration: float = 0, interval = 0.05, sleep = 0.1, callback = None, offset_x = 0, animations = []):
        time.sleep(delay)

        for cnt, i in enumerate(text):
            animation = ascii.TerminalAnimation(self.terminal, random.sample(string.printable, len(string.printable)), interval=interval)
            animation.start(
                (cnt + offset_x, max(0, self.terminal.y - 3)),
                duration=duration,
                final_frame=i,
            )

            animations.append(animation)

            time.sleep(sleep)
            
        time.sleep(duration)

        if callback:
            callback()

    def draw_splash(self):
        logo_width = len(self.logo.split('\n')[0])

        if len(self.model) < 15:
            offset = 0
        else:
            offset = len(self.model) - 15

        self.terminal.print_rect(position=(2, -1), size=(52 + offset, 11)) # outline
        self.terminal.print_text(position=(5, 1), size=(60, 11), in_rect=True, content=self.logo) # logo
        
        app_org_icon = self.terminal.colored_text(f'ø', text_rgb=(128, 128, 128), back_rgb=None)
        app_org = self.terminal.colored_text(f'Omega Labs', text_rgb=(192, 192, 192), back_rgb=None)
        app_ver = self.terminal.colored_text(f'(v{version})', text_rgb=(128, 128, 128), back_rgb=None)
        app_model = self.terminal.colored_text(self.model, text_rgb=(128, 128, 128), back_rgb=None)


        self.terminal.move_cursor(10 + logo_width, 3)
        self.terminal.print(app_org_icon, app_org)

        self.terminal.move_cursor(10 + logo_width, 4)
        self.terminal.print(f'Lit. {app_ver}')

        self.terminal.move_cursor(10 + logo_width, 6)
        self.terminal.print(f'Supercharged by')

        self.terminal.move_cursor(10 + logo_width, 7)
        self.terminal.print(app_model)


Lit()