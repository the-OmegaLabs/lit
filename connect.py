from openai import OpenAI
from collections import defaultdict
import ascii

client = OpenAI(
    api_key="sk-DrpwsFXY6J8oZ7ssmjnKswYploZbqWxaEczadcetmvcH76B1",
    base_url="https://api.epstein.motorcycles/v1"
)

models = client.models.list()

groups = defaultdict(list)

for model in models:
    name, variant = model.id.rsplit("-", 1)
    groups[name].append(variant)

terminal = ascii.TerminalOutput()
terminal.clear_screen()

for name, variants in groups.items():
    print(f"{name} [{', '.join(variants)}]")