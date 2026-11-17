"""Tic Tac Toe: 2 players or vs the computer (easy or unbeatable), scoreboard, winning line highlight.
Standard library only (tkinter). Keys 1-9 place a mark, R starts a new round."""
import random
import tkinter as tk

WIN_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
BG, CELL_BG, WIN_BG = "#1e2733", "#2b3a4a", "#2f9e44"
COLORS = {"X": "#ff6b6b", "O": "#4dabf7"}


def winner_of(board):
    for a, b, c in WIN_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a], (a, b, c)
    return None, None


def minimax(board, turn, ai, human):
    win, _ = winner_of(board)
    if win == ai:
        return 1
    if win == human:
        return -1
    if all(board):
        return 0
    scores = []
    for i in range(9):
        if not board[i]:
            board[i] = turn
            scores.append(minimax(board, human if turn == ai else ai, ai, human))
            board[i] = ""
    return max(scores) if turn == ai else min(scores)


def best_move(board, ai, human):
    if not any(board):
        return random.choice([0, 2, 4, 6, 8])
    best, moves = -2, []
    for i in range(9):
        if not board[i]:
            board[i] = ai
            score = minimax(board, human, ai, human)
            board[i] = ""
            if score > best:
                best, moves = score, [i]
            elif score == best:
                moves.append(i)
    return random.choice(moves)


class TicTacToe:
    def __init__(self, root):
        self.root = root
        root.title("Tic Tac Toe")
        root.resizable(False, False)
        root.configure(bg=BG)
        self.mode = tk.StringVar(value="hard")
        self.scores = {"X": 0, "O": 0, "Draws": 0}
        self.starter = "X"
        self.pending = None

        top = tk.Frame(root, bg=BG)
        top.pack(pady=(12, 4))
        for text, value in (("2 Players", "two"), ("Computer: Easy", "easy"), ("Computer: Unbeatable", "hard")):
            tk.Radiobutton(top, text=text, value=value, variable=self.mode, command=self.reset_scores,
                           bg=BG, fg="white", selectcolor=CELL_BG, activebackground=BG,
                           activeforeground="white", font=("Segoe UI", 10)).pack(side="left", padx=6)

        self.status = tk.Label(root, text="", font=("Segoe UI", 16, "bold"), bg=BG, fg="white")
        self.status.pack(pady=4)

        grid = tk.Frame(root, bg=BG)
        grid.pack(padx=16, pady=6)
        self.buttons = []
        for i in range(9):
            b = tk.Button(grid, text="", width=4, font=("Segoe UI", 38, "bold"), bg=CELL_BG, fg="white",
                          activebackground="#364b60", relief="flat", command=lambda i=i: self.click(i))
            b.grid(row=i // 3, column=i % 3, padx=4, pady=4)
            self.buttons.append(b)

        self.score_label = tk.Label(root, text="", font=("Segoe UI", 12), bg=BG, fg="#ced4da")
        self.score_label.pack(pady=4)
        bar = tk.Frame(root, bg=BG)
        bar.pack(pady=(0, 12))
        tk.Button(bar, text="New Round (R)", command=self.new_round, font=("Segoe UI", 11),
                  bg="#364b60", fg="white", relief="flat", padx=10).pack(side="left", padx=6)
        tk.Button(bar, text="Reset Scores", command=self.reset_scores, font=("Segoe UI", 11),
                  bg="#364b60", fg="white", relief="flat", padx=10).pack(side="left", padx=6)
        root.bind("<Key>", self.on_key)
        self.new_round()

    def vs_computer(self):
        return self.mode.get() != "two"

    def on_key(self, event):
        key = event.keysym
        if key in "123456789" and len(key) == 1:
            self.click(int(key) - 1)
        elif key.lower() == "r":
            self.new_round()

    def reset_scores(self):
        self.scores = {"X": 0, "O": 0, "Draws": 0}
        self.starter = "X"
        self.new_round()

    def new_round(self):
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.board = [""] * 9
        self.over = False
        self.turn = self.starter
        self.starter = "O" if self.starter == "X" else "X"
        for b in self.buttons:
            b.config(text="", bg=CELL_BG, fg="white")
        self.update_status()
        self.update_scores()
        if self.vs_computer() and self.turn == "O":
            self.pending = self.root.after(500, self.computer_move)

    def click(self, i):
        if self.over or self.board[i] or (self.vs_computer() and self.turn != "X"):
            return
        self.play(i)

    def play(self, i):
        self.board[i] = self.turn
        self.buttons[i].config(text=self.turn, fg=COLORS[self.turn])
        win, line = winner_of(self.board)
        if win:
            self.finish(win, line)
        elif all(self.board):
            self.finish(None, None)
        else:
            self.turn = "O" if self.turn == "X" else "X"
            self.update_status()
            if self.vs_computer() and self.turn == "O":
                self.pending = self.root.after(450, self.computer_move)

    def computer_move(self):
        self.pending = None
        if self.over or self.turn != "O":
            return
        free = [i for i in range(9) if not self.board[i]]
        if not free:
            return
        i = random.choice(free) if self.mode.get() == "easy" else best_move(self.board, "O", "X")
        self.play(i)

    def finish(self, win, line):
        self.over = True
        if win:
            self.scores[win] += 1
            for i in line:
                self.buttons[i].config(bg=WIN_BG)
            if self.vs_computer():
                text = "You win!" if win == "X" else "Computer wins!"
            else:
                text = f"Player {win} wins!"
            self.status.config(text=text, fg=COLORS[win])
        else:
            self.scores["Draws"] += 1
            self.status.config(text="It's a draw!", fg="#ffd166")
        self.update_scores()

    def update_status(self):
        if self.vs_computer():
            text = "Your turn (X)" if self.turn == "X" else "Computer is thinking (O)..."
        else:
            text = f"Player {self.turn}'s turn"
        self.status.config(text=text, fg=COLORS[self.turn])

    def update_scores(self):
        names = ("You (X)", "Computer (O)") if self.vs_computer() else ("Player X", "Player O")
        self.score_label.config(
            text=f"{names[0]}: {self.scores['X']}    {names[1]}: {self.scores['O']}    Draws: {self.scores['Draws']}")


def main():
    root = tk.Tk()
    TicTacToe(root)
    root.mainloop()


if __name__ == "__main__":
    main()
