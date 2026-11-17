import glob
import os
import time

import numpy as np
from PIL import Image, ImageDraw, ImageGrab

import config

try:
    from core import desktop
except Exception:
    desktop = None

_engine = None


# ---------------- screenshots ----------------
def capture():
    """Grab the screen. The Infinity terminal is blacked out. Returns (image, path)."""
    img = ImageGrab.grab().convert("RGB")

    if desktop and config.MASK_TERMINAL:
        cells = desktop.terminal_visible_cells()      # only the parts that are really visible
        if cells:
            covered = sum((c[2] - c[0]) * (c[3] - c[1]) for c in cells)
            if covered < 0.6 * img.width * img.height:   # skip if the terminal fills the screen
                draw = ImageDraw.Draw(img)
                for cell in cells:
                    draw.rectangle(cell, fill=(0, 0, 0))

    os.makedirs(config.SCREENS_DIR, exist_ok=True)
    name = f"screen_{time.strftime('%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.png"
    path = os.path.join(config.SCREENS_DIR, name)
    img.save(path)
    _cleanup()
    return img, path


def _cleanup():
    files = sorted(glob.glob(os.path.join(config.SCREENS_DIR, "*.png")), key=os.path.getmtime)
    for old in files[:-config.KEEP_SCREENSHOTS]:
        try:
            os.remove(old)
        except OSError:
            pass


def shrink(path):
    """Smaller copy for the vision model (faster and cheaper)."""
    img = Image.open(path)
    if img.width <= config.VISION_MAX_WIDTH:
        return path
    h = round(img.height * config.VISION_MAX_WIDTH / img.width)
    small = img.resize((config.VISION_MAX_WIDTH, h), Image.LANCZOS)
    small_path = path.replace(".png", "_small.png")
    small.save(small_path)
    return small_path


# ---------------- OCR ----------------
def _get_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr import RapidOCR
            _engine = ("new", RapidOCR())
        except ImportError:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _engine = ("old", RapidOCR())
            except ImportError:
                raise RuntimeError("OCR is not installed. Run: pip install rapidocr onnxruntime")
    return _engine


def read_text(path):
    """Returns a list of (text, box_points, confidence) for every text line on the image."""
    kind, engine = _get_engine()
    if kind == "new":
        res = engine(path)
        if res is None or res.txts is None or res.boxes is None:
            return []
        return [(t, b.tolist(), float(s)) for t, b, s in zip(res.txts, res.boxes, res.scores)]
    res, _ = engine(path)
    if not res:
        return []
    return [(t, b, float(s)) for b, t, s in res]


def _bounds(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), max(xs), min(ys), max(ys)


def all_text(path):
    """Every readable text line with its centre, top to bottom."""
    out = []
    for text, box, conf in read_text(path):
        if conf < config.OCR_MIN_CONFIDENCE:
            continue
        left, right, top, bottom = _bounds(box)
        out.append({"text": text, "x": int((left + right) / 2), "y": int((top + bottom) / 2)})
    out.sort(key=lambda m: (m["y"], m["x"]))
    return out


def find_text(query, path):
    """Find `query` inside the text lines. Position is estimated inside the line,
    so a word in the middle of 'File Edit View' is hit correctly."""
    q = query.strip().lower()
    found = []
    for text, box, conf in read_text(path):
        if conf < config.OCR_MIN_CONFIDENCE:
            continue
        t = text.lower()
        idx = t.find(q)
        if idx < 0:
            continue
        left, right, top, bottom = _bounds(box)
        frac = (idx + len(q) / 2) / max(len(t), 1)
        found.append({
            "line": text,
            "x": int(left + frac * (right - left)),
            "y": int((top + bottom) / 2),
            "conf": conf,
            "score": len(q) / max(len(t), 1),   # 1.0 = the line is exactly the query
        })
    found.sort(key=lambda m: (-m["score"], -m["conf"], m["y"]))
    return found


def find_text_in_region(query, img, region):
    """Like find_text, but only inside region=(left, top, right, bottom) of the screen image."""
    l, t, r, b = region
    crop = img.crop((l, t, r, b))
    os.makedirs(config.SCREENS_DIR, exist_ok=True)
    path = os.path.join(config.SCREENS_DIR, "_region.png")
    crop.save(path)
    matches = find_text(query, path)
    for m in matches:
        m["x"] += l
        m["y"] += t
    return matches