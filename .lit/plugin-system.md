# Plugin System

## Overview

Lit's plugin system allows extending the agent's toolset with custom Python
modules. Plugins are loaded at startup and their functions are automatically
exposed as OpenAI-compatible tool definitions, merged into the agent's tool
list alongside the built-in tools (`shell_command`, `read_file`, `write_file`,
`edit_file`).

## Directory Structure

```
plugins/
├── __init__.py          # PluginManager — loader, scanner, tool generator
├── execute_python.py    # Plugin: execute arbitrary Python code
├── machine_info.py      # Plugin: get system info, current time
```

## Plugin Contract

Each plugin file must define a class named `Plugin` with the following
attributes:

| Attribute           | Type   | Description                                 |
|---------------------|--------|---------------------------------------------|
| `self.name`         | `str`  | Human-readable name for the plugin.         |
| `self.export_function` | `dict` | Maps a verb string to a callable function. |

### Example

```python
class Plugin:
    def __init__(self):
        self.name = "My Custom Plugin"
        self.export_function = {
            "Do something": self.my_function
        }

    def my_function(self, arg1: str, arg2: int = 0):
        """Description of what this function does."""
        return {"result": arg1 * arg2}
```

### Rules

- The file name must **not** start with `_` (underscore-prefixed files are
  skipped).
- The file must end with `.py`.
- The class must be named exactly `Plugin`.
- The class's `__module__` must match the module name (i.e., it must be
  defined in the plugin file itself, not imported from elsewhere).
- The verb string in `export_function` is used as a display label in the UI.

## How It Works

### Loading (`PluginManager.load_plugin`)

1. Scans all `.py` files in the `plugins/` directory.
2. Skips files starting with `_` (e.g., `__init__.py` is skipped).
3. Imports each module via `importlib.import_module`, then calls
   `importlib.reload` to ensure fresh state.
4. Uses `inspect.getmembers` to find all classes named `Plugin` whose
   `__module__` matches the current module.
5. Stores the class reference in `self.plugins` keyed by module name.

### Tool Generation (`PluginManager.generate_tools`)

For each loaded plugin:

1. Instantiates the plugin class.
2. Iterates over `self.export_function` items.
3. For each function:
   - Uses `inspect.signature` to introspect parameters.
   - Maps Python type annotations to JSON schema types via
     `map_python_type_to_json`:
     - `str` → `"string"`
     - `int` → `"integer"`
     - `float` → `"number"`
     - `bool` → `"boolean"`
     - `list` → `"array"`
     - `dict` → `"object"`
     - Default: `"string"`
   - Parameters without defaults are marked as `required`.
   - `*args` and `**kwargs` are skipped.
   - The function's docstring becomes the tool description.
   - The tool name is prefixed with the module path (e.g.,
     `"plugins.execute_python.execute_python_code"`).

The generated tool definitions are stored in `self.tools` (a list of OpenAI
function-calling schemas) and `self.functions` (a dict mapping tool name →
`{"verb": ..., "function": ...}` for runtime dispatch).

### Integration in `app.py`

```python
plugin = plugins.PluginManager()
plugin.load_plugin()
plugin.generate_tools()

# Built-in tools + plugin tools
tools = tools + plugin.tools
```

#### Dispatch

In `dispatch_tool()` (line 1679), tool calls are dispatched as follows:

1. If the tool name matches a built-in tool (`shell_command`, `read_file`,
   `write_file`, `edit_file`), the corresponding handler is called.
2. Otherwise, if the name exists in `plugin.functions`, the stored function
   reference is called with `func(**args)`.
3. The result is wrapped as `{"success": True, "output": <return_value>}`.

#### UI Integration

- `TOOL_VERBS` (line 870) is populated from plugin functions for display in
   the tool card UI.
- `ToolCard._analyze()` (line 1080) handles plugin tool results by checking
   for `output.status`, `output.error`, and `output.output` fields.
- The `/plugin` command lists all installed plugin modules.

## Built-in Plugins

### `execute_python`

- **File**: `plugins/execute_python.py`
- **Exports**: `"Execute python"` → `execute_python_code(code: str)`
- **Description**: Executes Python code via `exec()`, capturing stdout, stderr,
  and exceptions. Returns a dict with `status`, `output`, and `error`.

### `machine_info`

- **File**: `plugins/machine_info.py`
- **Exports**:
  - `"Get system information"` → `get_client_system()`
  - `"Get current time"` → `get_current_time()`
- **Description**: Provides OS info (name, version, architecture, Python
  version) and current local time (with timezone, UTC offset, and epoch
  timestamp).

## Adding a New Plugin

1. Create a new `.py` file in the `plugins/` directory (e.g., `my_plugin.py`).
2. Define a `Plugin` class with `__init__` setting `self.name` and
   `self.export_function`.
3. Define exported functions with type annotations and docstrings.
4. Restart Lit — the plugin will be loaded automatically.

### Example

```python
# plugins/weather.py
class Plugin:
    def __init__(self):
        self.name = "Weather"
        self.export_function = {
            "Get weather": self.get_weather
        }

    def get_weather(self, city: str):
        """Get current weather for a city."""
        return {"city": city, "temperature": 22, "condition": "sunny"}
```