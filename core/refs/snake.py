"""Snake: menu, pause, levels (speed grows) and a saved top-5 high score table.
Standard library only (tkinter). Controls: arrows or WASD, P = pause, R = restart, Space/Enter = start."""
import json
import os
import random
import tkinter as tk
from tkinter import simpledialog

CELL = 24
COLS, ROWS = 24, 20
WIDTH, HEIGHT = COLS * CELL, ROWS * CELL
BAR = 40
SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snake_highscores.json")

BG1, BG2, BAR_BG = "#1b2430", "#202b38", "#10161e"
HEAD, BODY, FOOD = "#8dfc9c", "#37c871", "#ff5c5c"
DIRS = {"up": (0, -1), "w": (0, -1), "down": (0, 1), "s": (0, 1),
        "left": (-1, 0), "a": (-1, 0), "right": (1, 0), "d": (1, 0)}


def load_scores():
    try:
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [(str(n), int(s)) for n, s in data][:5]
    except (OSError, ValueError, TypeError):
        return []


def save_score(name, score):
    scores = load_scores() + [(name, score)]
    scores.sort(key=lambda item: item[1], reverse=True)
    scores = scores[:5]
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f)
    except OSError:
        pass
    return scores


def is_high_score(score):
    scores = load_scores()
    return score > 0 and (len(scores) < 5 or score > scores[-1][1])


class SnakeGame:
    def __init__(self, root):
        self.root = root
        root.title("Snake")
        root.resizable(False, False)
        x = (root.winfo_screenwidth() - WIDTH) // 2
        y = (root.winfo_screenheight() - HEIGHT - BAR) // 2
        root.geometry(f"{WIDTH}x{HEIGHT + BAR}+{max(x, 0)}+{max(y, 0)}")
        self.canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT + BAR, bg=BG1, highlightthickness=0)
        self.canvas.pack()
        root.bind("<Key>", self.on_key)
        self.job = None
        self.best = max([s for _, s in load_scores()] or [0])
        self.draw_background()
        self.reset_state()
        self.state = "menu"
        self.draw()
        self.overlay("SNAKE", "Press SPACE or ENTER to start\nArrows / WASD to move  -  P to pause")

    # ---------- game state ----------
    def reset_state(self):
        cx, cy = COLS // 2, ROWS // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.direction = (1, 0)
        self.next_dir = (1, 0)
        self.score = 0
        self.level = 1
        self.delay = 130
        self.place_food()

    def place_food(self):
        free = [(x, y) for x in range(COLS) for y in range(ROWS) if (x, y) not in self.snake]
        self.food = random.choice(free) if free else (-1, -1)

    def start_game(self):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        self.reset_state()
        self.state = "playing"
        self.draw()
        self.job = self.root.after(self.delay, self.tick)

    def tick(self):
        self.job = None
        if self.state != "playing":
            return
        self.direction = self.next_dir
        hx, hy = self.snake[0]
        nx, ny = hx + self.direction[0], hy + self.direction[1]
        if not (0 <= nx < COLS and 0 <= ny < ROWS) or (nx, ny) in self.snake[:-1]:
            self.game_over()
            return
        self.snake.insert(0, (nx, ny))
        if (nx, ny) == self.food:
            self.score += 10
            self.level = self.score // 50 + 1
            self.delay = max(55, 130 - (self.level - 1) * 12)
            self.best = max(self.best, self.score)
            self.place_food()
        else:
            self.snake.pop()
        self.draw()
        self.job = self.root.after(self.delay, self.tick)

    def game_over(self):
        self.state = "over"
        self.best = max(self.best, self.score)
        self.draw()
        if is_high_score(self.score):
            name = simpledialog.askstring("New high score!", f"Score {self.score}. Enter your name:", parent=self.root)
            save_score((name or "Player").strip()[:12] or "Player", self.score)
        self.overlay("GAME OVER", f"Score: {self.score}\nPress SPACE or R to play again")

    def pause(self):
        self.state = "paused"
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        self.overlay("PAUSED", "Press P to continue", show_scores=False)

    def resume(self):
        self.state = "playing"
        self.draw()
        self.job = self.root.after(self.delay, self.tick)

    # ---------- input ----------
    def on_key(self, event):
        key = event.keysym.lower()
        if key in DIRS and self.state == "playing":
            dx, dy = DIRS[key]
            if (dx, dy) != (-self.direction[0], -self.direction[1]):
                self.next_dir = (dx, dy)
        elif key in ("space", "return"):
            if self.state in ("menu", "over"):
                self.start_game()
            elif self.state == "paused":
                self.resume()
        elif key == "p":
            if self.state == "playing":
                self.pause()
            elif self.state == "paused":
                self.resume()
        elif key == "r" and self.state in ("playing", "paused", "over"):
            self.start_game()

    # ---------- drawing ----------
    def draw_background(self):
        c = self.canvas
        for gx in range(COLS):
            for gy in range(ROWS):
                color = BG1 if (gx + gy) % 2 == 0 else BG2
                c.create_rectangle(gx * CELL, gy * CELL, (gx + 1) * CELL, (gy + 1) * CELL,
                                   fill=color, outline=color, tags="bg")
        c.create_rectangle(0, HEIGHT, WIDTH, HEIGHT + BAR, fill=BAR_BG, outline="", tags="bg")

    def draw(self):
        c = self.canvas
        c.delete("game")
        c.delete("overlay")
        fx, fy = self.food
        c.create_oval(fx * CELL + 3, fy * CELL + 3, (fx + 1) * CELL - 3, (fy + 1) * CELL - 3,
                      fill=FOOD, outline="#ffa0a0", width=2, tags="game")
        for i, (x, y) in enumerate(self.snake):
            c.create_rectangle(x * CELL + 1, y * CELL + 1, (x + 1) * CELL - 1, (y + 1) * CELL - 1,
                               fill=HEAD if i == 0 else BODY, outline="#12331f", tags="game")
        hx, hy = self.snake[0]
        dx, dy = self.direction
        cx, cy = hx * CELL + CELL / 2, hy * CELL + CELL / 2
        for side in (-1, 1):
            ex, ey = cx + dx * 5 - dy * 5 * side, cy + dy * 5 + dx * 5 * side
            c.create_oval(ex - 2.5, ey - 2.5, ex + 2.5, ey + 2.5, fill="black", tags="game")
        mid = HEIGHT + BAR // 2
        c.create_text(12, mid, text=f"Score: {self.score}", fill="white", anchor="w",
                      font=("Segoe UI", 13, "bold"), tags="game")
        c.create_text(WIDTH // 2, mid, text=f"Level {self.level}", fill="#ffd166",
                      font=("Segoe UI", 13, "bold"), tags="game")
        c.create_text(WIDTH - 12, mid, text=f"Best: {self.best}", fill="white", anchor="e",
                      font=("Segoe UI", 13, "bold"), tags="game")

    def overlay(self, title, subtitle, show_scores=True):
        c = self.canvas
        c.delete("overlay")
        c.create_rectangle(0, 0, WIDTH, HEIGHT, fill="black", stipple="gray50", outline="", tags="overlay")
        c.create_text(WIDTH // 2, 90, text=title, fill=HEAD, font=("Segoe UI", 38, "bold"), tags="overlay")
        c.create_text(WIDTH // 2, 160, text=subtitle, fill="white", font=("Segoe UI", 14),
                      justify="center", tags="overlay")
        if show_scores:
            c.create_text(WIDTH // 2, 235, text="TOP 5", fill="#ffd166", font=("Segoe UI", 15, "bold"), tags="overlay")
            scores = load_scores()
            for i in range(5):
                text = f"{i + 1}. {scores[i][0]:<12}{scores[i][1]:>5}" if i < len(scores) else f"{i + 1}. ---"
                c.create_text(WIDTH // 2, 265 + i * 26, text=text, fill="white",
                              font=("Consolas", 13), tags="overlay")


def main():
    root = tk.Tk()
    SnakeGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
