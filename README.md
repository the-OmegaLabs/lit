![Lit](./.static/main.png)

# Lit

**Lit** `(Let's do IT)` is an LLM-powered command-line agent that runs directly in your terminal.

It can read and modify files, execute shell commands, run Python code,
and help you complete programming tasks through an interactive terminal interface.

---

## ✨ Features

- Interactive terminal-based AI agent
- File reading, writing, and editing
- Shell command execution
- Python execution
- Streaming responses with markdown rendering
- Persistent project memory
- Cross-platform terminal support

---

## 🚀 Quick Start

### Prerequisites

- Python >= 3.14
- A terminal with truecolor support

### Install

```bash
# Clone the repository
git clone https://github.com/the-OmegaLabs/lit.git
cd lit

# Install dependencies
uv sync
```

### Configure

Edit `config.py` to set your API key and model:

```python
base_url = "https://api.example.com/api/v1"
api_key = "your-api-key-here"
model = "gpt-5.6-sol - Example"
model_id = "gpt-5.6-sol"
use_alt_theme = False
```

### Run

```bash
python -m lit
```
---

## 🤝 Contributing

Lit is an open-source project led by Omega Labs. Contributions, issues, and feature requests are welcome.

---

## 📄 License

License information will be announced later.