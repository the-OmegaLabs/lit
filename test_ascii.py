import contextlib
import io
import unittest

from ascii import ControlCode, FrameBuffer, Select, TerminalEvent, TerminalOutput


class FrameBufferTests(unittest.TestCase):
    def test_alternate_buffer_control_codes(self):
        self.assertEqual(ControlCode.ENTER_ALTERNATE_BUFFER, '\033[?1049h')
        self.assertEqual(ControlCode.EXIT_ALTERNATE_BUFFER, '\033[?1049l')

    def test_wide_character_is_visible_in_both_cells(self):
        frame = FrameBuffer(6, 1)
        frame.write(1, 0, '中文', (1, 2, 3), (4, 5, 6))

        self.assertEqual([cell.char for cell in frame[0]], [' ', '中', '中', '文', '文', ' '])
        self.assertFalse(frame[0][1].continuation)
        self.assertTrue(frame[0][2].continuation)
        self.assertEqual(frame[0][2].foreground, (1, 2, 3))
        self.assertEqual(frame[0][2].background, (4, 5, 6))

    def test_get_frame_returns_logical_text_and_independent_colors(self):
        frame = FrameBuffer(8, 2)
        frame.write(1, 0, 'A中B', (10, 20, 30), (40, 50, 60))

        copy = frame.get_frame(1, 0, 5, 1)

        self.assertEqual(copy.get_text(), 'A中B')
        self.assertEqual(copy[0][1].char, '中')
        self.assertEqual(copy[0][2].char, '中')
        self.assertEqual(copy[0][1].foreground, (10, 20, 30))
        copy[0][0].char = 'X'
        self.assertEqual(frame[0][1].char, 'A')

    def test_frame_can_be_pasted_with_colors(self):
        source = FrameBuffer(4, 1)
        source.write(0, 0, '中A', (7, 8, 9), (1, 2, 3))
        target = FrameBuffer(6, 2)

        target.write(1, 1, source)

        self.assertEqual(target.get_frame(1, 1, 5, 2).get_text(), '中A ')
        self.assertEqual(target[1][1].foreground, (7, 8, 9))
        self.assertEqual(target[1][2].background, (1, 2, 3))

    def test_overwriting_half_of_wide_character_clears_both_halves(self):
        frame = FrameBuffer(4, 1)
        frame.write(0, 0, '中')

        frame.put(1, 0, 'X')

        self.assertEqual([cell.char for cell in frame[0]], [' ', 'X', ' ', ' '])

    def test_terminal_colored_text_updates_framebuffer_without_ansi_cells(self):
        terminal = TerminalOutput()
        colored = terminal.colored_text('中A', (11, 22, 33), (44, 55, 66))

        with contextlib.redirect_stdout(io.StringIO()):
            terminal.print(colored, end='')

        self.assertEqual([terminal.framebuffer[0][x].char for x in range(3)], ['中', '中', 'A'])
        self.assertEqual(terminal.framebuffer[0][0].foreground, (11, 22, 33))
        self.assertEqual(terminal.framebuffer[0][1].background, (44, 55, 66))
        self.assertEqual(terminal.framebuffer[0][2].foreground, (11, 22, 33))


class _Events:
    def __init__(self, *keys):
        self.events = [TerminalEvent('key', 'down', key=key) for key in keys]

    def get_event(self):
        return self.events.pop(0)


class SelectTests(unittest.TestCase):
    def test_select_uses_arrows_and_restores_framebuffer(self):
        terminal = TerminalOutput()
        terminal.framebuffer = FrameBuffer(20, 6)
        terminal.get_size = lambda: (20, 6)
        terminal.framebuffer.write(0, 0, 'under the prompt')
        before = terminal.framebuffer.get_text()

        with contextlib.redirect_stdout(io.StringIO()):
            choice = Select('Login', ['GitHub', 'Google', 'Microsoft'],
                            terminal=terminal).run(_Events('down', 'down', 'enter'))

        self.assertEqual(choice, 'Microsoft')
        self.assertEqual(terminal.framebuffer.get_text(), before)
        self.assertEqual((terminal.x, terminal.y), (0, 0))

    def test_select_escape_restores_and_returns_none(self):
        terminal = TerminalOutput()
        terminal.framebuffer = FrameBuffer(10, 3)
        terminal.get_size = lambda: (10, 3)
        terminal.framebuffer.write(0, 0, 'original')

        with contextlib.redirect_stdout(io.StringIO()):
            choice = Select('Pick', ['A', 'B'], terminal=terminal).run(
                _Events('escape'))

        self.assertIsNone(choice)
        self.assertTrue(terminal.framebuffer.get_text().startswith('original'))

    def test_select_position_size_description_and_restore(self):
        terminal = TerminalOutput()
        terminal.framebuffer = FrameBuffer(24, 8)
        terminal.get_size = lambda: (24, 8)
        terminal.framebuffer.write(0, 0, 'background contents')
        terminal.x, terminal.y = 1, 1
        before = terminal.framebuffer.get_text()
        prompt = Select(
            'Login',
            [('GitHub', 'Continue with GitHub'), ('Google', 'Use Google account')],
            terminal=terminal,
            subtitle='Choose a provider',
            position=(4, 2),
            size=(16, 8),
            background_color=(10, 20, 30),
        )

        drawn = []
        original_write_frame = terminal.write_frame
        def capture(x, y, frame, draw=True):
            drawn.append((x, y, frame.get_frame(0, 0, frame.width, frame.height)))
            original_write_frame(x, y, frame, draw)
        terminal.write_frame = capture

        with contextlib.redirect_stdout(io.StringIO()):
            choice = prompt.run(_Events('down', 'enter'))

        self.assertEqual(choice, 'Google')
        self.assertEqual((drawn[0][0], drawn[0][1]), (4, 2))
        self.assertEqual((drawn[0][2].width, drawn[0][2].height), (16, 6))
        self.assertIn('Choose a provide', drawn[0][2].get_text())
        self.assertIn('Continue with', drawn[0][2].get_text())
        subtitle_cell = drawn[0][2][1][0]
        self.assertEqual(subtitle_cell.foreground, (128, 128, 128))
        description_cell = drawn[0][2][4][2]
        self.assertEqual(description_cell.foreground, (128, 128, 128))
        self.assertEqual(description_cell.background, (10, 20, 30))
        self.assertEqual(drawn[0][2][5][15].background, (10, 20, 30))
        self.assertEqual(terminal.framebuffer.get_text(), before)
        self.assertEqual((terminal.x, terminal.y), (1, 1))

    def test_select_dense_removes_blank_rows(self):
        terminal = TerminalOutput()
        terminal.framebuffer = FrameBuffer(20, 6)
        terminal.get_size = lambda: (20, 6)
        prompt = Select('Pick', [['A', 'First'], 'B'], terminal=terminal,
                        dense=True)
        drawn = []
        terminal.write_frame = lambda x, y, frame, draw=True: drawn.append(frame)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(prompt.run(_Events('enter')), 'A')

        self.assertEqual(drawn[0].get_text().splitlines()[:4],
                         ['Pick   ', '> A    ', '  First', '  B    '])


if __name__ == '__main__':
    unittest.main()
