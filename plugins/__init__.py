import importlib
import inspect
import os

def map_python_type_to_json(annotation):
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    return mapping.get(annotation, "string")

class PluginManager:
    def __init__(self):
        self.plugins = {}
        self.tools = []
        self.functions = {}
        self.functions_name = {}

    def load_plugin(self):
        self.plugins = {}

        for file in os.listdir(os.path.dirname(__file__)):
            if file.startswith("_") or not file.endswith(".py"):
                continue

            module_name = f"plugins.{file[:-3]}"

            module = importlib.import_module(module_name)
            importlib.reload(module)

            for name, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ == module.__name__ and name == 'Plugin':
                    self.plugins[module_name] = cls

    def generate_tools(self):
        self.tools = []
        self.functions = {}
        self.plugin_name = {}

        invaild_plugin = []

        for module in self.plugins:
            try:
                plugin = self.plugins.get(module)() # init the plugin
                self.plugin_name[module] = {
                    'name': plugin.name,
                    'version': plugin.version,
                    'author': plugin.author,
                }
            except Exception as f:
                print(f'Error when initialization plugin \"{module}\" ({plugin.name}): ')
                print(f'  {f}')
                invaild_plugin.append(module)

                continue

            try:
                for verb, tool in plugin.export_function.items():
                    sig = inspect.signature(tool)

                    properties = {}
                    required = []

                    for name, param in sig.parameters.items():
                        if param.kind in (
                            inspect.Parameter.VAR_POSITIONAL,
                            inspect.Parameter.VAR_KEYWORD
                        ):
                            continue

                        param_type = map_python_type_to_json(param.annotation)

                        properties[name] = {
                            "type": param_type
                        }

                        if param.default is inspect.Parameter.empty:
                            required.append(name)

                    self.tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": f"{module}.{tool.__name__}",
                                "description": inspect.getdoc(tool) or "",
                                "parameters": {
                                    "type": "object",
                                    "properties": properties,
                                    "required": required,
                                },
                            },
                        }
                    )

                    self.functions[f"{module}.{tool.__name__}"] = {'verb': verb, 'function': tool}

            except Exception as f:
                print(f'Error when loading plugin \"{module}\" ({plugin.name}): ')
                print(f'  {f}')

        for i in invaild_plugin:
            self.plugins.pop(i)