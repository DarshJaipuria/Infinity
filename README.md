# Infinity

A local AI agent for Windows that runs on your own machine using [Ollama](https://ollama.com).
Infinity can see your screen, control the mouse and keyboard, manage files, research the web,
write and test code, and compose Gmail drafts, all driven by a local LLM so nothing has to leave your computer.

It comes with a glass-style desktop GUI (PyQt6) and a classic terminal mode.

## Features

| Skill / tool group | What it does |
|---|---|
| **write_code** | Writes a complete program or GUI game, then runs and auto-tests it before handing it back |
| **file_manager** | Finds, reads, creates, edits, copies, moves, renames and deletes files and folders |
| **gmail_compose** | Opens Gmail in Chrome and drafts an email |
| **web_research** | Searches the web, reads pages and Wikipedia, and types organised notes into Notepad |
| **Screen & vision** | Screenshots, OCR (`read_screen_text`, `click_text`), and vision-model screen descriptions |
| **Mouse & keyboard** | Move, click, drag, scroll, type, hotkeys |
| **Documents** | Reads PDF, DOCX, CSV, JSON and images |
| **Memory** | Persistent user facts plus a scratchpad for working notes |
| **Workflows** | Save a finished turn as a reusable workflow (`/save_workflow`) |

## Requirements

- **Windows 10 / 11** (uses `pywin32`, the Windows registry and Windows input APIs)
- **Python 3.10+** (with tkinter, included in the python.org installer)
- **[Ollama](https://ollama.com/download)** installed and running
- A model pulled in Ollama. The default is set in `config.json` (`qwen3.5:4b`)

## Installation

```bash
git clone https://github.com/DarshJaipuria/Infinity.git
cd Infinity

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

ollama pull qwen3.5:4b
```

## Running

```bash
python main.py          # Glass GUI (default; falls back to the terminal if unavailable)
python main.py --cli    # classic terminal interface
```

## Configuration

Edit `config.json`:

| Key | Meaning | Default |
|---|---|---|
| `ollama_host` | Ollama server URL (the `OLLAMA_HOST` env var is the fallback) | `http://localhost:11434` |
| `model_id` | Ollama model used for everything | `qwen3.5:4b` |
| `context_length` | Context window in tokens | `32768` |
| `buffer_token` | Tokens kept free for the reply | `4096` |
| `primary_monitor` | Which monitor to capture | `1` |
| `screen_resolution` | Your screen size (`x`, `y`) | `1920 x 1080` |
| `keep_images` | Screenshots kept in the chat context | `1` |
| `n_retry` | Retries for failed model calls | `3` |
| `max_characters` | Max characters returned from a tool | `10000` |

Timing and behaviour options (typing speed, delays, headless typing, etc.) live in `config.py`.
Run `/update` in the app to reload `config.json` without restarting.

## Terminal commands

```
/help                  show all commands
/tools                 list skills and sub-tools
/memory                view long-term memory
/scratchpad            view the agent's working notes
/reset, /clear         start a fresh conversation
/update                reload config.json
/save_workflow <name>  save the current turn as a workflow
/do <tool> key=val     run any tool directly
/demo                  run a small mouse/keyboard demo
/run                   run the last generated script
/pos                   show the mouse position after a 4 second countdown
/in <sec> /do ...      run a tool after a delay
/exit, /bye            quit
```

## Project structure

```
main.py             entry point (GUI + CLI)
config.py           settings and the system prompt
config.json         runtime settings you are meant to edit
classes.py          Ollama client wrapper and chat helpers
utils.py            shared helpers
core/               agent loop, LLM, history, memory, screen/OCR, desktop input, research, code lab
skills/             high-level skills (write_code, file_manager, gmail_compose, web_research)
tools/              sub-tools the skills and agent call (mouse, keyboard, files, web, gmail, eyes)
functions/          tool-set implementations
tools_schema/       JSON schemas for each tool set
ui/                 PyQt6 glass GUI
workflows/          saved, reusable workflows
data/Shortcuts.md   keyboard-shortcut reference used for retrieval
```

## Safety

Infinity controls your real mouse and keyboard and can delete files.

- Press **Esc** to stop a running action.
- Keep the model and tool permissions in mind before asking it to modify or delete files.
- Generated code is test-run inside the `workspace/` folder.

## Troubleshooting

- **"Glass GUI unavailable"**: PyQt6 failed to load; the app falls back to `--cli`. Reinstall with `pip install PyQt6`.
- **Cannot connect to Ollama**: make sure Ollama is running and `ollama_host` is correct.
- **OCR errors**: reinstall with `pip install rapidocr onnxruntime`.
- **Clicks land in the wrong place**: set `screen_resolution` and `primary_monitor` in `config.json` to match your display.

## Privacy

Everything runs locally through Ollama. Chat history, logs, screenshots, memory and generated code are stored on your
machine and are excluded from git by `.gitignore`.