import importlib
import inspect
import os
from typing import Dict, List, Literal, Union, get_args, get_origin

def map_python_type_to_json(tp):
    """
    Python typing -> JSON Schema
    """

    if tp is inspect.Parameter.empty:
        return "string"

    origin = get_origin(tp)
    args = get_args(tp)

    if tp in (str,):
        return "string"

    if tp in (int,):
        return "integer"

    if tp in (float,):
        return "number"

    if tp in (bool,):
        return "boolean"

    if tp in (list, List):
        return {
            "type": "array",
            "items": {"type": "string"}
        }

    if tp in (dict, Dict):
        return "object"

    if origin is Literal:
        values = list(args)

        if all(isinstance(v, str) for v in values):
            return {
                "type": "string",
                "enum": values
            }

        if all(isinstance(v, int) for v in values):
            return {
                "type": "integer",
                "enum": values
            }

    if origin in (list, List):
        item_type = args[0] if args else str

        return {
            "type": "array",
            "items": map_python_type_to_json(item_type)
        }

    if origin in (dict, Dict):
        return {
            "type": "object"
        }

    if origin is Union:
        non_none = [
            x for x in args
            if x is not type(None)
        ]

        if len(non_none) == 1:
            schema = map_python_type_to_json(non_none[0])
            schema["nullable"] = True
            return schema


    # fallback
    return "string"

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