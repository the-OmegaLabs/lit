import ascii
import util
import colorama

colorama.init()

SPECIAL_KEYS = {
    'escape', 'tab', 'insert', 'delete', 'home', 'end', 'page_up', 'page_down',
    'left', 'right', 'up', 'down',
}

version = '0.0.1'

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
            terminal.move_cursor(0, terminal.y - 1)
            terminal.clear_line()
            terminal.print(f'input: {text}')
except KeyboardInterrupt:
    terminal.print('\nexit')
    
