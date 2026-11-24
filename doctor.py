"""Infinity setup check.   Run:  python doctor.py

Shows which Python is running, whether every package is installed, whether tkinter works and whether
Ollama is reachable with your model pulled. It prints the exact command that fixes each problem.
"""
import importlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import platform
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OK, WARN, BAD = "[ OK ]", "[WARN]", "[FAIL]"

# (module to import, pip package name, what it is for, required?)
PACKAGES = [
    ("ollama", "ollama", "talks to the Ollama server", True),
    ("rich", "rich", "terminal output", True),
    ("pyautogui", "pyautogui", "mouse and keyboard", True),
    ("win32gui", "pywin32", "window handling (Windows only)", True),
    ("numpy", "numpy", "image maths", True),
    ("PIL", "Pillow", "screenshots", True),
    ("cv2", "opencv-python", "canvas and color detection", True),
    ("rapidocr", "rapidocr", "OCR (reading text on screen)", True),
    ("onnxruntime", "onnxruntime", "runs the OCR models", True),
    ("PyQt6.QtWidgets", "PyQt6", "the glass GUI (without it: python main.py --cli)", False),
    ("ddgs", "ddgs", "web search", True),
    ("requests", "requests", "web, Wikipedia, weather", True),
    ("bs4", "beautifulsoup4", "reading web pages", True),
    ("curl_cffi", "curl_cffi", "fewer blocked web pages", False),
    ("pypdf", "pypdf", "reading PDF files", False),
    ("docx", "python-docx", "reading Word files", False),
    ("pyflakes", "pyflakes", "checks generated code", False),
    ("tiktoken", "tiktoken", "token counting", False),
    ("wikipediaapi", "wikipedia-api", "extra Wikipedia tool", False),
    ("mss", "mss", "fast screenshots (desktop tool set)", False),
    ("langchain_core", "langchain-core", "shortcut search (desktop tool set)", False),
    ("langchain_community", "langchain-community", "shortcut search (desktop tool set)", False),
    ("rank_bm25", "rank-bm25", "shortcut search (desktop tool set)", False),
]


def line(status, text):
    print(f"{status} {text}")


def check_python():
    problems = 0
    v = sys.version_info
    print(f"Python      : {platform.python_version()}  ({sys.executable})")
    if (3, 11) <= (v.major, v.minor) <= (3, 13):
        line(OK, "Python version is supported (3.11 - 3.13).")
    else:
        line(BAD, "Unsupported Python version. Use 3.12 (recommended), 3.11 or 3.13.")
        problems += 1
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        line(WARN, "Not inside a virtual environment. Recommended: py -3.12 -m venv .venv  then activate it.")
    else:
        line(OK, f"Virtual environment active ({sys.prefix}).")
    if os.name != "nt":
        line(WARN, "Infinity is built for Windows 10/11. Some tools will not work on this system.")
    try:
        importlib.import_module("tkinter")
        line(OK, "tkinter is available (needed for the code editor window).")
    except Exception as e:      # noqa: BLE001
        line(BAD, f"tkinter is missing ({e}). Re-run the python.org installer and keep 'tcl/tk and IDLE' ticked.")
        problems += 1
    return problems


def check_packages():
    missing_required, missing_optional = [], []
    for module, pip_name, purpose, required in PACKAGES:
        if module == "win32gui" and os.name != "nt":
            continue
        try:
            if module == "PyQt6.QtWidgets":
                importlib.import_module(module)         # a real import: catches broken Qt DLLs too
            elif importlib.util.find_spec(module.split(".")[0]) is None:
                raise ImportError("not installed")
            try:
                version = metadata.version(pip_name)
            except metadata.PackageNotFoundError:
                version = "?"
            line(OK, f"{pip_name:20} {version:12} {purpose}")
        except Exception as e:      # noqa: BLE001
            note = "required" if required else "optional"
            line(BAD if required else WARN, f"{pip_name:20} MISSING ({note})  {purpose}  [{str(e)[:50]}]")
            (missing_required if required else missing_optional).append(pip_name)
    return missing_required, missing_optional


def check_config():
    problems = 0
    path = os.path.join(ROOT, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        line(OK, "config.json is valid.")
    except Exception as e:      # noqa: BLE001
        line(BAD, f"config.json problem: {e}")
        return None, 1
    try:
        import pyautogui
        w, h = pyautogui.size()
        res = cfg.get("screen_resolution", {})
        if (res.get("x"), res.get("y")) != (w, h):
            line(WARN, f"Your screen is {w}x{h} but config.json says {res.get('x')}x{res.get('y')}. "
                       "Set screen_resolution in config.json, or clicks will land in the wrong place.")
        else:
            line(OK, f"Screen resolution matches config.json ({w}x{h}).")
    except Exception:       # noqa: BLE001
        pass
    return cfg, problems


def check_ollama(cfg):
    host = (cfg or {}).get("ollama_host") or os.getenv("OLLAMA_HOST") or "http://localhost:11434"
    if not host.startswith("http"):
        host = "http://" + host
    model = (cfg or {}).get("model_id", "qwen3.5:4b")
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=4) as resp:
            names = [m.get("name", "") for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        line(BAD, f"Cannot reach Ollama at {host}. Install it from https://ollama.com/download and start it "
                  "(it runs in the system tray, or run:  ollama serve).")
        return 1
    line(OK, f"Ollama is running at {host} ({len(names)} model(s) installed).")
    wanted = {model, model if ":" in model else model + ":latest"}
    if wanted & set(names):
        line(OK, f"Model '{model}' is pulled.")
        return 0
    line(BAD, f"Model '{model}' is not pulled yet. Run:  ollama pull {model}")
    return 1


def main():
    if "--print-model" in sys.argv:             # used by setup.bat
        try:
            with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
                print(json.load(f).get("model_id", "qwen3.5:4b"))
        except Exception:       # noqa: BLE001
            print("qwen3.5:4b")
        return 0
    print("=" * 64)
    print(" Infinity setup check")
    print("=" * 64)
    problems = check_python()
    print()
    missing_required, missing_optional = check_packages()
    problems += len(missing_required)
    print()
    cfg, p = check_config()
    problems += p
    problems += check_ollama(cfg)
    print()
    if missing_required or missing_optional:
        print("To install what is missing, run this with the SAME Python:")
        print(f'    "{sys.executable}" -m pip install -r requirements.txt')
        print()
    if problems:
        print(f"Result: {problems} problem(s) to fix (see [FAIL] lines above).")
        return 1
    print("Result: everything needed is in place. Start Infinity with:  python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
