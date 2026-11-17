import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON_PATH = os.path.join(BASE_DIR, "config.json")

# Runtime JSON configuration defaults (Infinity)
_json_cfg = {}
if os.path.isfile(CONFIG_JSON_PATH):
    try:
        with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as _f:
            _json_cfg = json.load(_f)
    except Exception:
        _json_cfg = {}

# Model and Engine Settings (Ollama Base)
MODEL = _json_cfg.get("model_id", "qwen3.5:4b")
OLLAMA_HOST = _json_cfg.get("ollama_host", os.getenv("OLLAMA_HOST", "http://localhost:11434"))
THINK = False

# Context and Token Limits
NUM_CTX = int(_json_cfg.get("context_length", 12288))
CTX_TOKEN = NUM_CTX
BUFFER_TOKEN = int(_json_cfg.get("buffer_token", 2048))
N_RETRY = int(_json_cfg.get("n_retry", 3))
MAX_CHARACTERS = int(_json_cfg.get("max_characters", 10000))
KEEP_IMAGES = int(_json_cfg.get("keep_images", 1))

# Screen and Monitor settings
_res = _json_cfg.get("screen_resolution", {"x": 1920, "y": 1080})
RES_X = int(_res.get("x", 1920))
RES_Y = int(_res.get("y", 1080))
PRIMARY_MONITOR = int(_json_cfg.get("primary_monitor", 1))

# Agent Execution Limits
MAX_STEPS = 8            # router: max main-tool calls per request
MAX_SKILL_STEPS = 10     # inside one main tool: max sub-tool calls
RUN_TIMEOUT = 10         # seconds a test run of generated code may take
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

# Typing & Automation Timing
VISIBLE_TYPING = True          # False = save silently without opening Notepad
TYPE_DELAY = 0.03              # seconds per character (higher = slower typing)
SHOW_CODE_IN_TERMINAL = False  # True = also print the full code in the terminal
EDITOR_HOLD = 2.0              # seconds the editor stays open after saving
ACTION_DELAY = 0.4             # pause after every hand action, so you can follow it
MOVE_DURATION = 0.4            # seconds the pointer takes to glide to a spot
DRAG_STEP = 0.15               # seconds per segment while dragging
DRAG_POINT_STEP = 8            # pixels between mouse events while dragging
DRAG_EVENT_DELAY = 0.02        # seconds between those events (higher = slower, smoother)

# Vision and Screen Monitoring
SCREENS_DIR = os.path.join(BASE_DIR, "screens")
KEEP_SCREENSHOTS = 15          # older screenshots are deleted automatically
MASK_TERMINAL = True           # black out the Infinity terminal in screenshots
VISION_MAX_WIDTH = 1280        # screenshots are shrunk to this width for the vision model
OCR_MIN_CONFIDENCE = 0.5       # ignore text the OCR is unsure about

# File Explorer Automation
EXPLORER_NAV_PX = 165
EXPLORER_TOP_PX = 165
FILEOP_TIMEOUT = 120

# Gmail Automation
GMAIL_ACCOUNT_INDEX = 0
GMAIL_TITLE_HINTS = ["gmail", "compose mail"]
GMAIL_TYPE_DELAY = 0.02
GMAIL_RETURN_TO_TERMINAL = True

# Code Lab & Generation
CODE_MODEL = None
CODE_THINK = False
CODE_TEMPERATURE = 0.3
CODE_MAX_TOKENS = 7000
CODE_MAX_REPAIRS = 3
SMOKE_SECONDS = 7
CODE_IDLE_TIMEOUT = 240

# Web Research & Scraping
RESEARCH_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Infinity Research")
RESEARCH_SOURCES = 4
RESEARCH_CHARS_PER_SOURCE = 4000
RESEARCH_WORDS = 600
RESEARCH_MODEL = None
RESEARCH_MINIMIZE_TERMINAL = True
NOTEPAD_TYPE_DELAY = 0.012
NOTEPAD_SETTLE = 2.0
WEB_RETRIES = 2
WEB_TIMEOUT = 20

# History & Storage Paths
DATA_DIR = os.path.join(BASE_DIR, "data")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
MEMORY_FILE = os.path.join(DATA_DIR, "memory.md")
SCRATCHPAD_FILE = os.path.join(DATA_DIR, "agent_scratchpad.md")
SHORTCUTS_FILE = os.path.join(DATA_DIR, "Shortcuts.md")
WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")
LOGS_FILE = os.path.join(DATA_DIR, "logs.log")
MAX_HISTORY_MESSAGES = 10

# Base System Prompt
SYSTEM_PROMPT = """You are Infinity, a helpful AI agent running locally on the user's computer.

You have access to specialized skills and direct tools:
- File, Document & Assignment Tools:
  - find_item(name, root), list_folder(path), path_exists(path): search for files by name/keywords or list folder contents (e.g. in E:\\assignments).
  - read_file(path), read_pdf(path), read_docx(path), read_image(path), read_csv(path), read_json(path): read text, PDFs (all pages), Word documents, images, CSVs, or JSON files.
  - create_file, write_file, patch_file, create_folder, copy_item, move_item, rename_item, delete_item: create, modify, copy, move, rename, or delete files and folders.
- Screen, Vision & Mouse/Keyboard Tools:
  - get_mouse_position: get the current X and Y coordinates of the user's mouse cursor immediately.
  - get_screen_size, get_active_window: get screen dimensions or active window title.
  - take_screenshot: capture a screenshot of the screen and save it to a file.
  - describe_screen, read_screen_text, find_text_on_screen, click_text, verify_screen: inspect or read what is on the screen.
  - mouse_move, click, double_click, right_click, scroll, type_text, press_key, hotkey, wait: control mouse and keyboard.
- Web & Live Information Tools:
  - get_weather: get current weather for any city.
  - web_search, read_webpage, wiki_summary: search the web, fetch live prices/news/facts, or read Wikipedia.
  - web_research: research a topic in depth or type organized research notes into Notepad.
- Application Skills:
  - write_code: write and auto-test a complete program, script, or GUI game.
  - gmail_compose: compose or draft an email in Gmail.
- Memory & Notes:
  - update_system_memory: save or update user facts when asked to remember or forget.
  - update_scratchpad: update your temporary notes or checklist.

CRITICAL RULES:
1. When asked to find and solve an assignment or document in a folder (e.g. "Find the chemistry assignment in E:\\assignments and solve it completely"):
   - Step 1: Call find_item(name="chemistry", root="E:\\assignments") or list_folder(path="E:\\assignments") to locate the exact file path.
   - Step 2: Call read_file(path=...) (or read_pdf / read_docx / read_image) to read the entire assignment.
   - Step 3: Solve every single question in the assignment and display the complete, numbered answer for each question clearly in chat.
2. Always call the actual tool to perform file, screen, mouse, or web operations. Never claim you created, copied, renamed, moved, or deleted a file without calling the tool first.
3. If the user asks multiple questions in a single prompt (for example, weather in a city AND the price of Bitcoin), call the needed tools for EVERY question and answer ALL of them in your final response."""


def update_from_json():
    """Reload settings from config.json dynamically."""
    global MODEL, OLLAMA_HOST, NUM_CTX, CTX_TOKEN, BUFFER_TOKEN
    global N_RETRY, MAX_CHARACTERS, KEEP_IMAGES, RES_X, RES_Y, PRIMARY_MONITOR
    if os.path.isfile(CONFIG_JSON_PATH):
        try:
            with open(CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            MODEL = cfg.get("model_id", MODEL)
            OLLAMA_HOST = cfg.get("ollama_host", OLLAMA_HOST)
            NUM_CTX = int(cfg.get("context_length", NUM_CTX))
            CTX_TOKEN = NUM_CTX
            BUFFER_TOKEN = int(cfg.get("buffer_token", BUFFER_TOKEN))
            N_RETRY = int(cfg.get("n_retry", N_RETRY))
            MAX_CHARACTERS = int(cfg.get("max_characters", MAX_CHARACTERS))
            KEEP_IMAGES = int(cfg.get("keep_images", KEEP_IMAGES))
            res = cfg.get("screen_resolution", {})
            RES_X = int(res.get("x", RES_X))
            RES_Y = int(res.get("y", RES_Y))
            PRIMARY_MONITOR = int(cfg.get("primary_monitor", PRIMARY_MONITOR))
        except Exception:
            pass