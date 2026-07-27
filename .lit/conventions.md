# Conventions

## Code Style

- Follow existing codebase style: descriptive variable names, no single-letter
  names unless explicitly requested.
- No inline comments unless explicitly requested by the user.
- No copyright headers or license notices.
- Keep changes minimal and focused on the task.

## Markdown Theme (`MD_THEME`)

- Accent color reserved for emphasis, not applied to every bullet.
- Inline code has no background fill (avoids visual gaps in paragraphs).
- Defined in `app.py` as `MD_THEME`.

## UI Spacing

- `GAP_TIGHT = 0` — within-group spacing
- `GAP_BLOCK = 1` — between-group spacing
- `GAP_TURN = 2` — between-turn spacing (largest visual separator)
- `CONTENT_WIDTH = 80` — body text reading width
- `INPUT_WIDTH = 84` — input box width

## Status Bar

- Only motion source on the screen: flux waveform + reactor spinner.
- "ESC to interrupt" only appears after 2 seconds elapsed.
- Hint bar shown for first 3 turns only (progressive disclosure).

## File Editing

- Always use `edit_file` for modifications, never `write_file` to rewrite.
- Copy text verbatim from `read_file` output, stripping the `NNN | ` prefix.
- `old_text` must match exactly once (unless `replace_all` is set).
- After `edit_file` succeeds, do not re-read the file — the diff is sufficient.

## Testing

- No existing test framework. Do not add tests unless the codebase already has
  them or the task specifically requires it.
- Start with the most specific tests, expand gradually.