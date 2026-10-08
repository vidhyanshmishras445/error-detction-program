import hashlib
import os
import random
import secrets
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

DB_FILE = "quiz_app.db"


class QuizDatabase:
    """Handles SQLite persistence for users and quiz history."""

    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quiz_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    quiz_num INTEGER NOT NULL,
                    date_created TEXT NOT NULL,
                    total_q INTEGER NOT NULL,
                    score TEXT NOT NULL,
                    UNIQUE(username, quiz_num)
                )
            """)
            conn.commit()

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 100000
        )
        return key.hex()

    def register_user(self, username, password):
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
        pw_hash = self._hash_password(password, salt)

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                    (username, pw_hash, salt_hex),
                )
                conn.commit()
            return True, "Registration successful! You can now log in."
        except sqlite3.IntegrityError:
            return False, "Username already exists. Please choose another."

    def verify_user(self, username, password):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT password_hash, salt FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()

            if not row:
                return False, "Username not found."

            stored_hash, salt_hex = row
            salt = bytes.fromhex(salt_hex)
            computed_hash = self._hash_password(password, salt)

            if secrets.compare_digest(computed_hash, stored_hash):
                return True, "Login successful!"
            return False, "Incorrect password."

    def load_history(self, username=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "SELECT quiz_num, date_created, total_q, score, username FROM quiz_history WHERE username = ? ORDER BY quiz_num ASC",
                    (username,),
                )
            else:
                cursor.execute(
                    "SELECT quiz_num, date_created, total_q, score, username FROM quiz_history ORDER BY id ASC"
                )

            rows = cursor.fetchall()
            return [
                {
                    "quiz_num": r[0],
                    "date": r[1],
                    "total_q": r[2],
                    "score": r[3],
                    "username": r[4],
                }
                for r in rows
            ]

    def save_or_update_score(
        self, username, quiz_num, date_str, total_q, score_str
    ):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO quiz_history (username, quiz_num, date_created, total_q, score)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username, quiz_num) DO UPDATE SET
                    score = excluded.score,
                    date_created = excluded.date_created,
                    total_q = excluded.total_q
                """,
                (username, quiz_num, date_str, total_q, score_str),
            )
            conn.commit()

    def delete_score(self, username, quiz_num):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM quiz_history WHERE username = ? AND quiz_num = ?",
                (username, quiz_num),
            )
            conn.commit()

    def clear_all_history(self, username: str | None = None) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "DELETE FROM quiz_history WHERE username = ?", (username,)
                )
            else:
                cursor.execute("DELETE FROM quiz_history")
            conn.commit()

    def get_max_quiz_num(self, username):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(quiz_num) FROM quiz_history WHERE username = ?",
                (username,),
            )
            res = cursor.fetchone()[0]
            return res if res is not None else 0


class PhotoQuizApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Interactive Student Quiz App")
        self.root.geometry("850x780")
        self.root.configure(bg="#eceff1")

        self.is_fullscreen = False
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.exit_fullscreen)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Style Configuration
        self.setup_ttk_styles()

        # Database Manager
        self.db = QuizDatabase()

        # Session State
        self.current_user = None

        # Quiz State
        self.image_folder = ""
        self.all_images = []
        self.quiz_images = []
        self.user_answers = []
        self.current_index = 0
        self.total_time_limit = 0
        self.total_time_left = 0
        self.timer_job = None
        self.quiz_counter = 0
        self.photo_img = None

        # Primary Frames
        self.auth_frame = tk.Frame(self.root, bg="#eceff1")
        self.setup_frame = tk.Frame(self.root, bg="#eceff1")
        self.quiz_frame = tk.Frame(self.root, bg="#eceff1")
        self.results_frame = tk.Frame(self.root, bg="#eceff1")

        self.build_auth_screen()

    def setup_ttk_styles(self):
        """Sets up modern TTK styling for progress bars and tables."""
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Custom Timer Progress Bar Style
        self.style.configure(
            "Timer.Horizontal.TProgressbar",
            thickness=10,
            troughcolor="#cfd8dc",
            background="#1e88e5",
            bordercolor="#eceff1",
        )

        # Custom Treeview Styling
        self.style.configure(
            "Treeview",
            background="#ffffff",
            foreground="#37474f",
            rowheight=28,
            fieldbackground="#ffffff",
            font=("Sans", 10),
        )
        self.style.configure(
            "Treeview.Heading",
            font=("Sans", 10, "bold"),
            background="#1e88e5",
            foreground="#ffffff",
        )
        self.style.map(
            "Treeview",
            background=[("selected", "#bbdefb")],
            foreground=[("selected", "#0d47a1")],
        )

    def bind_hover(self, widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None):
        """Utility method to bind dynamic interactive hover effects to buttons."""
        def on_enter(e):
            if widget["state"] != tk.DISABLED:
                widget.config(bg=hover_bg)
                if hover_fg:
                    widget.config(fg=hover_fg)

        def on_leave(e):
            if widget["state"] != tk.DISABLED:
                widget.config(bg=normal_bg)
                if normal_fg:
                    widget.config(fg=normal_fg)

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def stop_timer(self):
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None

    def on_closing(self):
        self.stop_timer()
        self.root.destroy()

    def toggle_fullscreen(self, event=None):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)

    def exit_fullscreen(self, event=None):
        self.is_fullscreen = False
        self.root.attributes("-fullscreen", False)

    # ==================== KEYBOARD SHORTCUTS ====================
    def bind_quiz_shortcuts(self):
        self.root.bind("<Left>", lambda e: self.prev_question())
        self.root.bind("<Right>", lambda e: self.next_question())
        for key, letter in [
            ("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"),
            ("1", "A"), ("2", "B"), ("3", "C"), ("4", "D")
        ]:
            self.root.bind(key, lambda e, val=letter: self.select_option_by_shortcut(val))

    def unbind_quiz_shortcuts(self):
        self.root.unbind("<Left>")
        self.root.unbind("<Right>")
        for key in ["a", "b", "c", "d", "1", "2", "3", "4"]:
            self.root.unbind(key)

    def select_option_by_shortcut(self, option_letter):
        if self.quiz_frame.winfo_ismapped():
            self.selected_answer.set(option_letter)
            self.update_option_styles()

    # ==================== AUTHENTICATION SCREEN ====================
    def build_auth_screen(self):
        self.stop_timer()
        self.unbind_quiz_shortcuts()
        self.setup_frame.pack_forget()
        self.quiz_frame.pack_forget()
        self.results_frame.pack_forget()

        for widget in self.auth_frame.winfo_children():
            widget.destroy()

        self.auth_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        card = tk.Frame(
            self.auth_frame,
            bg="#ffffff",
            bd=0,
            highlightbackground="#cfd8dc",
            highlightthickness=1,
            padx=35,
            pady=35,
        )
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        tk.Label(
            card,
            text="🎓 Interactive Quiz Portal",
            font=("Sans", 20, "bold"),
            bg="#ffffff",
            fg="#1565c0",
        ).pack(pady=(0, 20))

        tk.Label(
            card, text="Username", font=("Sans", 10, "bold"), bg="#ffffff", fg="#546e7a"
        ).pack(anchor="w", pady=(5, 2))
        self.username_entry = tk.Entry(
            card, font=("Sans", 11), width=28, bd=1, relief=tk.SOLID
        )
        self.username_entry.pack(pady=(0, 12), ipady=4)

        tk.Label(
            card, text="Password", font=("Sans", 10, "bold"), bg="#ffffff", fg="#546e7a"
        ).pack(anchor="w", pady=(5, 2))
        self.password_entry = tk.Entry(
            card, font=("Sans", 11), width=28, bd=1, relief=tk.SOLID, show="*"
        )
        self.password_entry.pack(pady=(0, 20), ipady=4)

        self.username_entry.bind("<Return>", lambda e: self.handle_login())
        self.password_entry.bind("<Return>", lambda e: self.handle_login())

        btn_box = tk.Frame(card, bg="#ffffff")
        btn_box.pack()

        login_btn = tk.Button(
            btn_box,
            text="Login",
            command=self.handle_login,
            bg="#1e88e5",
            fg="white",
            font=("Sans", 10, "bold"),
            width=11,
            pady=6,
            bd=0,
            cursor="hand2",
        )
        login_btn.pack(side=tk.LEFT, padx=5)
        self.bind_hover(login_btn, "#1e88e5", "#1565c0")

        register_btn = tk.Button(
            btn_box,
            text="Register",
            command=self.handle_register,
            bg="#43a047",
            fg="white",
            font=("Sans", 10, "bold"),
            width=11,
            pady=6,
            bd=0,
            cursor="hand2",
        )
        register_btn.pack(side=tk.LEFT, padx=5)
        self.bind_hover(register_btn, "#43a047", "#2e7d32")

    def handle_login(self):
        user = self.username_entry.get().strip()
        pw = self.password_entry.get().strip()

        if not user or not pw:
            messagebox.showerror("Error", "Please enter both username and password.")
            return

        success, msg = self.db.verify_user(user, pw)
        if success:
            self.current_user = user
            self.quiz_counter = self.db.get_max_quiz_num(self.current_user)
            self.auth_frame.pack_forget()
            self.build_setup_screen()
        else:
            messagebox.showerror("Login Failed", msg)

    def handle_register(self):
        user = self.username_entry.get().strip()
        pw = self.password_entry.get().strip()

        if not user or not pw:
            messagebox.showerror("Error", "Please enter both username and password.")
            return

        if len(pw) < 4:
            messagebox.showwarning(
                "Weak Password", "Password must be at least 4 characters long."
            )
            return

        success, msg = self.db.register_user(user, pw)
        if success:
            messagebox.showinfo("Success", msg)
        else:
            messagebox.showerror("Registration Error", msg)

    def logout(self):
        self.stop_timer()
        self.current_user = None
        self.image_folder = ""
        self.all_images = []
        self.quiz_images = []
        self.user_answers = []
        self.quiz_counter = 0
        self.photo_img = None
        self.build_auth_screen()

    # ==================== SETUP SCREEN ====================
    def build_setup_screen(self):
        self.stop_timer()
        self.unbind_quiz_shortcuts()
        for widget in self.setup_frame.winfo_children():
            widget.destroy()

        self.setup_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)

        top_bar = tk.Frame(self.setup_frame, bg="#eceff1")
        top_bar.pack(fill=tk.X, pady=(0, 15))

        user_info = tk.Label(
            top_bar,
            text=f"👤 Logged in as: {self.current_user}",
            font=("Sans", 11, "bold"),
            bg="#eceff1",
            fg="#1565c0",
        )
        user_info.pack(side=tk.LEFT)

        logout_btn = tk.Button(
            top_bar,
            text="Logout",
            command=self.logout,
            bg="#e53935",
            fg="white",
            font=("Sans", 9, "bold"),
            padx=10,
            pady=3,
            bd=0,
            cursor="hand2",
        )
        logout_btn.pack(side=tk.RIGHT)
        self.bind_hover(logout_btn, "#e53935", "#c62828")

        card = tk.Frame(
            self.setup_frame,
            bg="#ffffff",
            bd=0,
            highlightbackground="#cfd8dc",
            highlightthickness=1,
            padx=30,
            pady=20,
        )
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card,
            text="Quiz Configuration",
            font=("Sans", 18, "bold"),
            bg="#ffffff",
            fg="#263238",
        ).pack(pady=5)

        tk.Label(
            card,
            text="⌨ Controls: Press [F11] Fullscreen | [Esc] Windowed",
            font=("Sans", 9, "italic"),
            bg="#ffffff",
            fg="#78909c",
        ).pack(pady=(0, 15))

        self.folder_btn = tk.Button(
            card,
            text="📂 Select Question Images Folder",
            command=self.select_folder,
            font=("Sans", 11, "bold"),
            bg="#eceff1",
            fg="#37474f",
            bd=1,
            relief=tk.SOLID,
            padx=15,
            pady=8,
            cursor="hand2",
        )
        self.folder_btn.pack(pady=10)
        self.bind_hover(self.folder_btn, "#eceff1", "#cfd8dc")

        folder_text = (
            f"✓ Loaded {len(self.all_images)} images from: {os.path.basename(self.image_folder)}"
            if self.all_images
            else "No folder selected"
        )
        folder_color = "#2e7d32" if self.all_images else "#c62828"
        self.folder_label = tk.Label(
            card,
            text=folder_text,
            fg=folder_color,
            font=("Sans", 10, "italic"),
            bg="#ffffff",
        )
        self.folder_label.pack(pady=(0, 15))

        tk.Label(
            card,
            text="Number of Questions:",
            font=("Sans", 11, "bold"),
            bg="#ffffff",
            fg="#37474f",
        ).pack(pady=(5, 2))
        self.num_questions_entry = tk.Entry(
            card, font=("Sans", 11), justify="center", bd=1, relief=tk.SOLID, width=15
        )
        self.num_questions_entry.insert(0, "5")
        self.num_questions_entry.pack(ipady=3)

        tk.Label(
            card,
            text="Total Quiz Time Limit (minutes):",
            font=("Sans", 11, "bold"),
            bg="#ffffff",
            fg="#37474f",
        ).pack(pady=(12, 2))
        self.time_limit_entry = tk.Entry(
            card, font=("Sans", 11), justify="center", bd=1, relief=tk.SOLID, width=15
        )
        self.time_limit_entry.insert(0, "5")
        self.time_limit_entry.pack(ipady=3)

        btn_frame = tk.Frame(card, bg="#ffffff")
        btn_frame.pack(pady=25)

        start_state = tk.NORMAL if self.all_images else tk.DISABLED
        start_bg = "#43a047" if self.all_images else "#b0bec5"
        self.start_btn = tk.Button(
            btn_frame,
            text="🚀 Start Quiz",
            command=self.start_quiz,
            bg=start_bg,
            fg="white",
            font=("Sans", 12, "bold"),
            state=start_state,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2" if self.all_images else "arrow",
        )
        self.start_btn.pack(side=tk.LEFT, padx=10)
        if self.all_images:
            self.bind_hover(self.start_btn, "#43a047", "#2e7d32")

        self.history_btn = tk.Button(
            btn_frame,
            text="📊 View Marks History",
            command=self.show_history_window,
            bg="#0288d1",
            fg="white",
            font=("Sans", 12, "bold"),
            bd=0,
            padx=18,
            pady=8,
            cursor="hand2",
        )
        self.history_btn.pack(side=tk.LEFT, padx=10)
        self.bind_hover(self.history_btn, "#0288d1", "#01579b")

    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return

        self.image_folder = folder
        valid_extensions = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
        self.all_images = [
            os.path.join(self.image_folder, f)
            for f in os.listdir(self.image_folder)
            if f.lower().endswith(valid_extensions)
        ]

        if self.all_images:
            self.folder_label.config(
                text=f"✓ Loaded {len(self.all_images)} images from: {os.path.basename(self.image_folder)}",
                fg="#2e7d32",
            )
            self.start_btn.config(state=tk.NORMAL, bg="#43a047", cursor="hand2")
            self.bind_hover(self.start_btn, "#43a047", "#2e7d32")
        else:
            self.folder_label.config(
                text="No valid images found in this folder!", fg="#c62828"
            )
            self.start_btn.config(state=tk.DISABLED, bg="#b0bec5", cursor="arrow")

    def start_quiz(self):
        if not self.all_images:
            messagebox.showerror("Error", "No question images available.")
            return

        try:
            total_req = int(self.num_questions_entry.get())
            total_minutes = float(self.time_limit_entry.get())
            if total_req <= 0 or total_minutes <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid Input", "Please enter valid positive numbers."
            )
            return

        if total_req > len(self.all_images):
            messagebox.showwarning(
                "Notice",
                f"Only {len(self.all_images)} images available. Using all.",
            )
            total_req = len(self.all_images)

        images_copy = list(self.all_images)
        random.shuffle(images_copy)
        self.quiz_images = images_copy[:total_req]
        self.user_answers = ["No Answer"] * len(self.quiz_images)

        self.quiz_counter += 1
        self.total_time_limit = int(total_minutes * 60)
        self.total_time_left = self.total_time_limit

        self.setup_frame.pack_forget()
        self.build_quiz_screen()
        self.bind_quiz_shortcuts()
        self.load_question(0)
        self.start_total_timer()

    # ==================== QUIZ SCREEN ====================
    def build_quiz_screen(self):
        for widget in self.quiz_frame.winfo_children():
            widget.destroy()

        self.quiz_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        header_frame = tk.Frame(self.quiz_frame, bg="#eceff1")
        header_frame.pack(fill=tk.X, pady=(0, 5))

        self.progress_label = tk.Label(
            header_frame,
            text="",
            font=("Sans", 12, "bold"),
            bg="#eceff1",
            fg="#263238",
        )
        self.progress_label.pack(side=tk.LEFT)

        self.timer_label = tk.Label(
            header_frame,
            text="",
            font=("Sans", 12, "bold"),
            fg="#d32f2f",
            bg="#eceff1",
        )
        self.timer_label.pack(side=tk.RIGHT)

        # Interactive Progress bar for Time
        self.time_progressbar = ttk.Progressbar(
            self.quiz_frame,
            style="Timer.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
        )
        self.time_progressbar.pack(fill=tk.X, pady=(2, 8))

        # Canvas for image question
        self.image_canvas = tk.Label(
            self.quiz_frame,
            text="Loading Question...",
            bg="#ffffff",
            relief=tk.SOLID,
            bd=1,
        )
        self.image_canvas.pack(fill=tk.BOTH, expand=True, pady=5)

        # Keyboard Helper hint bar
        hint_label = tk.Label(
            self.quiz_frame,
            text="💡 Tip: Use [A, B, C, D] or [1-4] to select answers | Use [← / →] to navigate",
            font=("Sans", 9, "italic"),
            bg="#eceff1",
            fg="#546e7a",
        )
        hint_label.pack(pady=2)

        # Interactive Radio Cards Container
        self.options_frame = tk.Frame(self.quiz_frame, bg="#eceff1")
        self.options_frame.pack(pady=10)

        self.selected_answer = tk.StringVar()
        self.radio_buttons = {}

        for letter in ["A", "B", "C", "D"]:
            rb = tk.Radiobutton(
                self.options_frame,
                text=f"Option {letter}",
                variable=self.selected_answer,
                value=letter,
                font=("Sans", 12, "bold"),
                indicatoron=0,
                width=11,
                height=2,
                bd=0,
                cursor="hand2",
                command=self.update_option_styles,
            )
            rb.pack(side=tk.LEFT, padx=10)
            self.radio_buttons[letter] = rb

        nav_frame = tk.Frame(self.quiz_frame, bg="#eceff1")
        nav_frame.pack(pady=10)

        self.prev_btn = tk.Button(
            nav_frame,
            text="◄ Previous",
            command=self.prev_question,
            font=("Sans", 11, "bold"),
            bg="#78909c",
            fg="white",
            bd=0,
            pady=6,
            width=12,
            cursor="hand2",
        )
        self.prev_btn.pack(side=tk.LEFT, padx=10)
        self.bind_hover(self.prev_btn, "#78909c", "#546e7a")

        self.next_btn = tk.Button(
            nav_frame,
            text="Next ►",
            command=self.next_question,
            font=("Sans", 11, "bold"),
            bg="#1e88e5",
            fg="white",
            bd=0,
            pady=6,
            width=12,
            cursor="hand2",
        )
        self.next_btn.pack(side=tk.LEFT, padx=10)
        self.bind_hover(self.next_btn, "#1e88e5", "#1565c0")

        self.submit_btn = tk.Button(
            nav_frame,
            text="✔ Submit Quiz",
            command=self.finish_quiz,
            font=("Sans", 11, "bold"),
            bg="#43a047",
            fg="white",
            bd=0,
            pady=6,
            width=12,
            cursor="hand2",
        )
        self.bind_hover(self.submit_btn, "#43a047", "#2e7d32")

    def update_option_styles(self):
        current_selection = self.selected_answer.get()
        for letter, rb in self.radio_buttons.items():
            if letter == current_selection:
                rb.config(
                    bg="#1565c0",
                    fg="#ffffff",
                    activebackground="#0d47a1",
                    activeforeground="#ffffff",
                    selectcolor="#1565c0",
                    relief=tk.SUNKEN,
                )
            else:
                rb.config(
                    bg="#ffffff",
                    fg="#37474f",
                    activebackground="#eceff1",
                    activeforeground="#37474f",
                    selectcolor="#ffffff",
                    relief=tk.RAISED,
                )

    def save_current_selection(self):
        val = self.selected_answer.get()
        if val in ["A", "B", "C", "D"]:
            self.user_answers[self.current_index] = val

    def load_question(self, index):
        if not self.quiz_images or index < 0 or index >= len(self.quiz_images):
            return

        self.current_index = index
        self.progress_label.config(
            text=f"Question {self.current_index + 1} of {len(self.quiz_images)}"
        )

        saved_val = self.user_answers[self.current_index]
        self.selected_answer.set(
            saved_val if saved_val in ["A", "B", "C", "D"] else ""
        )
        self.update_option_styles()

        self.prev_btn.config(
            state=tk.DISABLED if self.current_index == 0 else tk.NORMAL,
            bg="#b0bec5" if self.current_index == 0 else "#78909c",
        )

        if self.current_index == len(self.quiz_images) - 1:
            self.next_btn.pack_forget()
            self.submit_btn.pack(side=tk.LEFT, padx=10)
        else:
            self.submit_btn.pack_forget()
            self.next_btn.pack(side=tk.LEFT, padx=10)

        img_path = self.quiz_images[self.current_index]
        try:
            with Image.open(img_path) as raw_img:
                img = raw_img.copy()

            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "transparency" in img.info or img.mode == "PA" else "RGB")

            self.root.update_idletasks()
            canvas_width = max(self.image_canvas.winfo_width(), 650)
            canvas_height = max(self.image_canvas.winfo_height(), 380)

            img.thumbnail((canvas_width, canvas_height))
            self.photo_img = ImageTk.PhotoImage(img)
            self.image_canvas.config(image=self.photo_img, text="")
        except Exception:
            self.photo_img = None
            self.image_canvas.config(
                image="",
                text=f"Error loading image:\n{os.path.basename(img_path)}",
            )

    def prev_question(self):
        self.save_current_selection()
        if self.current_index > 0:
            self.load_question(self.current_index - 1)

    def next_question(self):
        self.save_current_selection()
        if self.current_index < len(self.quiz_images) - 1:
            self.load_question(self.current_index + 1)

    def start_total_timer(self):
        self.stop_timer()
        self.update_total_timer()

    def update_total_timer(self):
        mins, secs = divmod(self.total_time_left, 60)
        self.timer_label.config(
            text=f"⏱ Remaining: {mins:02d}:{secs:02d}"
        )

        # Update Progress bar visual
        pct = (self.total_time_left / self.total_time_limit) * 100
        self.time_progressbar["value"] = pct

        if self.total_time_left > 0:
            self.total_time_left -= 1
            self.timer_job = self.root.after(1000, self.update_total_timer)
        else:
            self.timer_job = None
            self.save_current_selection()
            messagebox.showinfo(
                "Time's Up!",
                "Total time limit reached! Submitting your quiz now.",
            )
            self.finish_quiz()

    def finish_quiz(self):
        self.save_current_selection()
        self.stop_timer()
        self.unbind_quiz_shortcuts()
        self.show_results()

    # ==================== RESULTS SCREEN ====================
    def show_results(self):
        self.quiz_frame.pack_forget()
        for widget in self.results_frame.winfo_children():
            widget.destroy()

        self.results_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)

        card = tk.Frame(
            self.results_frame,
            bg="#ffffff",
            bd=0,
            highlightbackground="#cfd8dc",
            highlightthickness=1,
            padx=25,
            pady=20,
        )
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card,
            text=f"🎉 Quiz #{self.quiz_counter} Complete",
            font=("Sans", 18, "bold"),
            bg="#ffffff",
            fg="#263238",
        ).pack(pady=5)

        tk.Label(
            card,
            text=f"Candidate: {self.current_user}",
            font=("Sans", 11),
            bg="#ffffff",
            fg="#546e7a",
        ).pack(pady=(0, 10))

        list_frame = tk.Frame(card, bg="#ffffff")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        result_list = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=("Sans", 11),
            bg="#f8f9fa",
            fg="#263238",
            selectbackground="#e3f2fd",
            selectforeground="#0d47a1",
            bd=1,
            relief=tk.SOLID,
        )
        result_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=result_list.yview)

        for i, img_path in enumerate(self.quiz_images):
            img_name = os.path.basename(img_path)
            selected_option = self.user_answers[i]
            result_list.insert(
                tk.END, f"  Q{i + 1} ({img_name}): Selected -> {selected_option}"
            )

        marks_frame = tk.Frame(
            card,
            bg="#e8f5e9",
            bd=0,
            padx=15,
            pady=12,
        )
        marks_frame.pack(fill=tk.X, pady=15)

        tk.Label(
            marks_frame,
            text="Score / Marks:",
            font=("Sans", 11, "bold"),
            bg="#e8f5e9",
            fg="#2e7d32",
        ).pack(side=tk.LEFT, padx=5)

        default_score = f"0/{len(self.quiz_images)}"
        self.score_entry = tk.Entry(
            marks_frame, font=("Sans", 11, "bold"), width=12, justify="center", bd=1, relief=tk.SOLID
        )
        self.score_entry.insert(0, default_score)
        self.score_entry.pack(side=tk.LEFT, padx=10, ipady=3)

        self.save_score_btn = tk.Button(
            marks_frame,
            text="💾 Save Score",
            command=self.save_marks,
            font=("Sans", 10, "bold"),
            bg="#2e7d32",
            fg="white",
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.save_score_btn.pack(side=tk.LEFT, padx=5)
        self.bind_hover(self.save_score_btn, "#2e7d32", "#1b5e20")

        self.score_status_label = tk.Label(
            marks_frame,
            text="",
            font=("Sans", 10, "italic"),
            bg="#e8f5e9",
            fg="#1565c0",
        )
        self.score_status_label.pack(side=tk.LEFT, padx=10)

        # Auto-save score record initially
        self.save_marks(show_status=False)

        btn_return = tk.Button(
            card,
            text="↩ Return to Main Menu",
            command=self.return_to_setup,
            font=("Sans", 11, "bold"),
            bg="#37474f",
            fg="white",
            bd=0,
            pady=8,
            padx=20,
            cursor="hand2",
        )
        btn_return.pack(pady=10)
        self.bind_hover(btn_return, "#37474f", "#212121")

    def save_marks(self, show_status=True):
        score_val = self.score_entry.get().strip()
        if not score_val:
            if show_status:
                messagebox.showwarning("Warning", "Please enter a score before saving.")
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        self.db.save_or_update_score(
            username=self.current_user,
            quiz_num=self.quiz_counter,
            date_str=now_str,
            total_q=len(self.quiz_images),
            score_str=score_val,
        )

        if show_status:
            self.score_status_label.config(text="✓ Saved to SQLite DB!")

    # ==================== HISTORY MODAL ====================
    def show_history_window(self):
        history_win = tk.Toplevel(self.root)
        history_win.title(f"Marks History - {self.current_user}")
        history_win.geometry("680x460")
        history_win.configure(bg="#eceff1")
        history_win.transient(self.root)
        history_win.grab_set()

        tk.Label(
            history_win,
            text=f"📊 Quiz History for {self.current_user}",
            font=("Sans", 15, "bold"),
            bg="#eceff1",
            fg="#263238",
        ).pack(pady=12)

        columns = ("quiz_num", "date", "total_q", "score")
        tree = ttk.Treeview(
            history_win, columns=columns, show="headings", height=10
        )

        tree.heading("quiz_num", text="Quiz #")
        tree.heading("date", text="Date & Time")
        tree.heading("total_q", text="Questions")
        tree.heading("score", text="Score")

        tree.column("quiz_num", width=90, anchor="center")
        tree.column("date", width=190, anchor="center")
        tree.column("total_q", width=110, anchor="center")
        tree.column("score", width=130, anchor="center")

        tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        def refresh_tree():
            for item in tree.get_children():
                tree.delete(item)
            history = self.db.load_history(username=self.current_user)
            for entry in history:
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        f"Quiz {entry['quiz_num']}",
                        entry["date"],
                        entry["total_q"],
                        entry["score"],
                    ),
                )
            self.quiz_counter = self.db.get_max_quiz_num(self.current_user)

        refresh_tree()

        btn_frame = tk.Frame(history_win, bg="#eceff1")
        btn_frame.pack(pady=12)

        def delete_selected():
            selected_item = tree.selection()
            if not selected_item:
                messagebox.showwarning(
                    "Selection Error",
                    "Please select a record from the list to delete.",
                    parent=history_win,
                )
                return

            item_values = tree.item(selected_item[0], "values")
            quiz_num = int(item_values[0].replace("Quiz ", "").strip())

            if messagebox.askyesno(
                "Confirm Delete",
                f"Are you sure you want to delete Quiz #{quiz_num}?",
                parent=history_win,
            ):
                self.db.delete_score(self.current_user, quiz_num)
                refresh_tree()

        def clear_all():
            if messagebox.askyesno(
                "Confirm Clear",
                "Delete all history for your account?",
                parent=history_win,
            ):
                self.db.clear_all_history(username=self.current_user)
                refresh_tree()

        btn_delete = tk.Button(
            btn_frame,
            text="Delete Selected",
            command=delete_selected,
            font=("Sans", 10, "bold"),
            bg="#e53935",
            fg="white",
            padx=12,
            pady=5,
            bd=0,
            cursor="hand2",
        )
        btn_delete.pack(side=tk.LEFT, padx=5)
        self.bind_hover(btn_delete, "#e53935", "#c62828")

        btn_clear = tk.Button(
            btn_frame,
            text="Clear My History",
            command=clear_all,
            font=("Sans", 10, "bold"),
            bg="#d32f2f",
            fg="white",
            padx=12,
            pady=5,
            bd=0,
            cursor="hand2",
        )
        btn_clear.pack(side=tk.LEFT, padx=5)
        self.bind_hover(btn_clear, "#d32f2f", "#b71c1c")

        close_btn = tk.Button(
            btn_frame,
            text="Close",
            command=history_win.destroy,
            font=("Sans", 10, "bold"),
            bg="#78909c",
            fg="white",
            padx=15,
            pady=5,
            bd=0,
            cursor="hand2",
        )
        close_btn.pack(side=tk.LEFT, padx=5)
        self.bind_hover(close_btn, "#78909c", "#455a64")

    def return_to_setup(self):
        self.save_marks(show_status=False)
        self.results_frame.pack_forget()
        self.build_setup_screen()


if __name__ == "__main__":
    root = tk.Tk()
    app = PhotoQuizApp(root)
    root.mainloop()