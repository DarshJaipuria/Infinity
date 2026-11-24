# Infinity

A local AI agent for Windows that runs on your own machine using [Ollama](https://ollama.com).
Infinity can see your screen, control the mouse and keyboard, manage files, research the web,
write and test code, and compose Gmail drafts, all driven by a local LLM so nothing has to leave your computer.

It comes with a glass-style desktop GUI (PyQt6) and a classic terminal mode.

## Video Demo


https://github.com/user-attachments/assets/74f07172-c9f1-4e78-b28c-04bc3f4b26d0



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

- **Windows 10 / 11, 64-bit** (uses `pywin32`, the Windows registry and Windows input APIs)
- **Python 3.11, 3.12 or 3.13, 64-bit** with tkinter. **3.12 is recommended.**
  - Python 3.10 and older are not supported. Python 3.14 is untested.
  - Python 3.15 does not work yet (there is no ONNX Runtime wheel for it).
  - tkinter comes with the python.org installer when **"tcl/tk and IDLE"** is ticked (it is by default).
- **[Ollama](https://ollama.com/download)** installed and running
- A model pulled in Ollama. The default is set in `config.json` (`qwen3.5:4b`). A Qwen3.5 series model is recommended
  for best performance on computers with low memory (for 4 GB VRAM use `qwen3.5:4b`).

Optional shortcuts if you have [winget](https://learn.microsoft.com/windows/package-manager/winget/) (included in Windows 11):

```bat
winget install --id Python.Python.3.12 -e
winget install --id Ollama.Ollama -e
winget install --id Git.Git -e
```

## Installation

### Option A: one command (recommended)

Open **Command Prompt** or **PowerShell** and run:

```bat
git clone https://github.com/DarshJaipuria/Infinity.git
cd Infinity
setup.bat
```

`setup.bat` finds a compatible Python by itself (3.12, then 3.13, then 3.11, even if you have many versions installed),
creates the `.venv` virtual environment, installs everything from `requirements.txt`, pulls the Ollama model and
finishes with a health check (`doctor.py`). In PowerShell, type `.\setup.bat` (and later `.\run.bat`), because PowerShell does not run files from the current folder without the `.\` prefix.

Start Infinity afterwards with:

```bat
run.bat
```

For the classic terminal interface instead of the glass GUI:

```bat
run.bat --cli
```

`run.bat` always uses the `.venv` Python, so it works no matter which Python is first on your PATH, and you never
have to activate anything.

### Option B: manual installation, step by step

**1. Get the code**

```bat
git clone https://github.com/DarshJaipuria/Infinity.git
cd Infinity
```

**2. See which Pythons you have and pick one (3.11, 3.12 or 3.13)**

```bat
py -0p
```

This lists every installed Python with its path (the `*` marks the default). If none of 3.11-3.13 is listed, install
one: `winget install --id Python.Python.3.12 -e`, then open a **new** terminal.

**3. Create the virtual environment with that exact version**

```bat
py -3.12 -m venv .venv
```

Replace `3.12` with the version you chose. Use `py -3.13` or `py -3.11` if you prefer those. If the `py` command does
not exist on your machine, use the full path of the interpreter instead:

```powershell
& "C:\Users\<your-name>\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
```

**4. Activate it**

| Shell | Command |
|---|---|
| PowerShell | `.venv\Scripts\Activate.ps1` |
| Command Prompt | `.venv\Scripts\activate.bat` |

Your prompt now starts with `(.venv)`. If PowerShell says *"running scripts is disabled on this system"*, run this once
and activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**5. Check that you are using the right Python**

```bat
python --version
python -c "import sys; print(sys.executable)"
```

The path must end in `Infinity\.venv\Scripts\python.exe`. If it shows another location, the venv is not active.

**6. Install the packages**

```bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Always write `python -m pip`, not just `pip`. It guarantees the packages go into the same Python that will run Infinity.

**7. Pull the model**

```bat
ollama pull qwen3.5:4b
ollama list
```

**8. Check everything**

```bat
python doctor.py
```

`doctor.py` shows which Python is running, every package and its version, whether tkinter works, whether your screen
resolution matches `config.json`, and whether Ollama is reachable with the model pulled. It prints the exact fix for
anything that is missing.

**9. Run**

```bat
python main.py
```

This opens the glass GUI (the default; it falls back to the terminal if the GUI is unavailable). For the classic
terminal interface:

```bat
python main.py --cli
```

### Several Python versions installed?

This is the most common source of "I installed it but it says ModuleNotFoundError". Rules that avoid every problem:

1. **Pick the version explicitly** with the launcher: `py -3.12 -m venv .venv`. Never rely on whatever `python` happens to be first on PATH.
2. **Install and run with the venv's Python**, either after activating (`python -m pip ...`) or without activating at all:

   ```bat
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe main.py
   ```
3. **Check which Python you are really using** whenever in doubt:

   ```bat
   python -c "import sys; print(sys.version); print(sys.executable)"
   ```
4. **Wrong Python in the venv?** Delete it and recreate it with the right one. In Command Prompt:

   ```bat
   rmdir /s /q .venv
   py -3.12 -m venv .venv
   ```

   In PowerShell:

   ```powershell
   Remove-Item -Recurse -Force .venv
   py -3.12 -m venv .venv
   ```
5. **Packages installed in the wrong place?** `python doctor.py` prints the exact `"<python>" -m pip install -r requirements.txt` command for the Python you are running.

Other ways to get an isolated Python 3.12:

**conda / miniconda**

```bat
conda create -n infinity python=3.12 -y
conda activate infinity
python -m pip install -r requirements.txt
```

**uv**

```bat
uv venv --python 3.12 .venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

### Updating

```bat
git pull
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### What is in `requirements.txt`

| Group | Packages | Needed for |
|---|---|---|
| Model + terminal | `ollama`, `rich` | talking to Ollama, live terminal output |
| Screen + input | `pyautogui`, `pywin32`, `numpy`, `Pillow`, `opencv-python` | mouse, keyboard, windows, screenshots |
| OCR | `rapidocr`, `onnxruntime` | `read_screen_text`, `click_text` (models download on first use, so be online once) |
| GUI | `PyQt6` | the glass GUI (without it Infinity uses `--cli`) |
| Web | `ddgs`, `requests`, `beautifulsoup4`, `curl_cffi` | `web_research` |
| Documents | `pypdf`, `python-docx` | reading PDF and Word files |
| Code checks | `pyflakes`, `tiktoken` | `write_code` self-checks, token counting |
| Extra tool sets | `wikipedia-api`, `mss`, `langchain-core`, `langchain-community`, `rank-bm25` | optional tools in `functions/` (each loads only if present) |

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
setup.bat           one-step installer (finds Python, creates .venv, installs, pulls the model)
run.bat             starts Infinity with the .venv Python
doctor.py           setup health check (Python, packages, tkinter, screen size, Ollama)
requirements.txt    all Python dependencies
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

Run `python doctor.py` first. It finds most problems and prints the fix.

| Symptom | Cause and fix |
|---|---|
| `'py' is not recognized` | The Python launcher is missing. Reinstall Python from python.org (keep "py launcher" ticked), or use the full path to `python.exe` as shown above. |
| `running scripts is disabled on this system` (PowerShell) | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, or activate with `.venv\Scripts\activate.bat` from Command Prompt, or skip activation and use `.venv\Scripts\python.exe`. |
| `ModuleNotFoundError: No module named ...` although you installed it | You installed into a different Python. Run `python -m pip install -r requirements.txt` with the **venv** Python (see "Several Python versions installed?"). |
| `No matching distribution found for onnxruntime` (or `numpy`, `opencv`) | Your Python is too new (3.14 or 3.15) or 32-bit. Use 64-bit Python 3.12. Check with `python -c "import struct; print(struct.calcsize('P')*8)"` (must print `64`). |
| `ModuleNotFoundError: No module named '_tkinter'` / "no tkinter" | Reinstall Python from python.org with **"tcl/tk and IDLE"** ticked. Test with `python -m tkinter`. |
| **"Glass GUI unavailable"** | PyQt6 failed to load, so the app falls back to `--cli`. Reinstall with `python -m pip install --force-reinstall PyQt6`. If it says *DLL load failed*, install the Microsoft Visual C++ Redistributable: `winget install --id Microsoft.VCRedist.2015+.x64 -e`. |
| `ImportError: DLL load failed while importing win32gui` | `python -m pip install --force-reinstall pywin32`, then restart the terminal. |
| **Cannot connect to Ollama** | Make sure Ollama is running (tray icon, or `ollama serve` in another terminal) and `ollama_host` in `config.json` is correct. |
| `model 'qwen3.5:4b' not found` | `ollama pull qwen3.5:4b`, or set `model_id` in `config.json` to a model shown by `ollama list`. |
| Out of memory, or very slow answers | Lower `context_length` in `config.json` (for example `16384` or `8192`), or use a smaller model. |
| **OCR errors** | `python -m pip install --force-reinstall rapidocr onnxruntime`. The first OCR call downloads its models, so be online for it. |
| **Clicks land in the wrong place** | Set `screen_resolution` and `primary_monitor` in `config.json` to match your display (`doctor.py` compares them for you). |
| Install fails with `error: Microsoft Visual C++ 14.0 or greater is required` | A package had no ready-made wheel for your Python. Use Python 3.12 (64-bit) instead of a very new version. |

## Privacy

Everything runs locally through Ollama. Chat history, logs, screenshots, memory and generated code are stored on your
machine and are excluded from git by `.gitignore`.



