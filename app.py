import ctypes
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageGrab


HANDLE_SIZE = 14
MOVE_HANDLE_SIZE = 18
MIN_RECT_SIZE = 60
OVERLAY_COLOR = "#000001"
ACCENT_COLOR = "#33D1FF"
RECORDING_COLOR = "#FF4D4D"
HANDLE_FILL = "#FFFFFF"
TEXT_COLOR = "#F7F9FB"
CONTROL_BG = "#11151C"
CONTROL_FG = "#F7F9FB"
FRAME_INTERVAL_MS = 100
OUTPUT_DIR = Path("recordings")
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


def set_exclude_from_capture(window: tk.Toplevel, exclude: bool = True) -> None:
    if not hasattr(ctypes, "windll"):
        return

    try:
        window.update_idletasks()
        hwnd = window.winfo_id()
        affinity = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
    except Exception:
        # Keep recording functional even if the current Windows build ignores this flag.
        return


class OverlayWindow:
    def __init__(self, root: tk.Tk, on_rect_change) -> None:
        self.root = root
        self.on_rect_change = on_rect_change
        self.window = tk.Toplevel(root)
        self.window.title("GIF Maker Overlay")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=OVERLAY_COLOR)
        self.window.wm_attributes("-transparentcolor", OVERLAY_COLOR)

        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        self.window.geometry(f"{screen_width}x{screen_height}+0+0")

        self.canvas = tk.Canvas(
            self.window,
            bg=OVERLAY_COLOR,
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        margin_x = screen_width * 0.2
        margin_y = screen_height * 0.2
        self.rect = {
            "x1": margin_x,
            "y1": margin_y,
            "x2": screen_width - margin_x,
            "y2": screen_height - margin_y,
        }
        self.active_handle = None
        self.drag_mode = None
        self.drag_offset = (0.0, 0.0)
        self.recording = False

        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<B1-Motion>", self.handle_drag)
        self.canvas.bind("<ButtonRelease-1>", self.stop_drag)

        self.draw_overlay()
        set_exclude_from_capture(self.window)

    def on_resize(self, _event: tk.Event) -> None:
        self.draw_overlay()

    def draw_overlay(self) -> None:
        self.canvas.delete("overlay")

        x1, y1, x2, y2 = self.get_rect_coords()
        accent = RECORDING_COLOR if self.recording else ACCENT_COLOR
        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline=accent,
            width=3,
            tags="overlay",
        )

        label = f"{int(x2 - x1)} x {int(y2 - y1)}"
        label_y = max(24, y1 - 20)
        self.canvas.create_text(
            x1 + 4,
            label_y,
            text=label,
            fill=accent,
            anchor="w",
            font=("Segoe UI", 11, "bold"),
            tags="overlay",
        )

        if not self.recording:
            self.draw_handle("nw", x1, y1)
            self.draw_handle("ne", x2, y1)
            self.draw_handle("sw", x1, y2)
            self.draw_handle("se", x2, y2)
            self.draw_move_handle((x1 + x2) / 2, (y1 + y2) / 2)

    def draw_handle(self, name: str, cx: float, cy: float) -> None:
        half = HANDLE_SIZE / 2
        handle_id = self.canvas.create_rectangle(
            cx - half,
            cy - half,
            cx + half,
            cy + half,
            fill=HANDLE_FILL,
            outline=ACCENT_COLOR,
            width=2,
            tags=("overlay", f"handle-{name}"),
        )
        self.canvas.tag_bind(
            handle_id,
            "<ButtonPress-1>",
            lambda event, handle=name: self.start_resize(event, handle),
        )

    def draw_move_handle(self, cx: float, cy: float) -> None:
        half = MOVE_HANDLE_SIZE / 2
        self.canvas.create_rectangle(
            cx - half,
            cy - half,
            cx + half,
            cy + half,
            fill=ACCENT_COLOR,
            outline=HANDLE_FILL,
            width=2,
            tags=("overlay", "handle-move"),
        )
        self.canvas.create_text(
            cx,
            cy,
            text="+",
            fill=TEXT_COLOR,
            font=("Segoe UI", 12, "bold"),
            tags=("overlay", "handle-move"),
        )
        self.canvas.tag_bind("handle-move", "<ButtonPress-1>", self.start_move)

    def start_resize(self, event: tk.Event, handle: str) -> None:
        if self.recording:
            return
        self.drag_mode = "resize"
        self.active_handle = handle
        self.handle_drag(event)

    def start_move(self, event: tk.Event) -> None:
        if self.recording:
            return
        self.drag_mode = "move"
        x1, y1, x2, y2 = self.get_rect_coords()
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        self.drag_offset = (event.x - center_x, event.y - center_y)
        self.handle_drag(event)

    def handle_drag(self, event: tk.Event) -> None:
        if self.drag_mode == "resize":
            self.resize_rect(event)
        elif self.drag_mode == "move":
            self.move_rect(event)

    def resize_rect(self, event: tk.Event) -> None:
        if self.drag_mode != "resize" or not self.active_handle:
            return

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        x = min(max(event.x, 0), width)
        y = min(max(event.y, 0), height)

        x1, y1, x2, y2 = self.get_rect_coords()

        if "w" in self.active_handle:
            x1 = min(x, x2 - MIN_RECT_SIZE)
        if "e" in self.active_handle:
            x2 = max(x, x1 + MIN_RECT_SIZE)
        if "n" in self.active_handle:
            y1 = min(y, y2 - MIN_RECT_SIZE)
        if "s" in self.active_handle:
            y2 = max(y, y1 + MIN_RECT_SIZE)

        self.rect.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        self.draw_overlay()
        self.notify_rect_change()

    def move_rect(self, event: tk.Event) -> None:
        if self.drag_mode != "move":
            return

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        x1, y1, x2, y2 = self.get_rect_coords()
        rect_width = x2 - x1
        rect_height = y2 - y1

        offset_x, offset_y = self.drag_offset
        new_x1 = event.x - offset_x - (rect_width / 2)
        new_y1 = event.y - offset_y - (rect_height / 2)

        new_x1 = min(max(new_x1, 0), width - rect_width)
        new_y1 = min(max(new_y1, 0), height - rect_height)

        self.rect.update(
            {
                "x1": new_x1,
                "y1": new_y1,
                "x2": new_x1 + rect_width,
                "y2": new_y1 + rect_height,
            }
        )
        self.draw_overlay()
        self.notify_rect_change()

    def stop_drag(self, _event: tk.Event) -> None:
        self.drag_mode = None
        self.active_handle = None
        self.drag_offset = (0.0, 0.0)

    def set_recording(self, value: bool) -> None:
        self.recording = value
        self.draw_overlay()

    def hide(self) -> None:
        self.window.withdraw()

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.draw_overlay()

    def get_capture_bbox(self) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.get_rect_coords()
        return round(x1), round(y1), round(x2), round(y2)

    def get_rect_coords(self) -> tuple[float, float, float, float]:
        return self.rect["x1"], self.rect["y1"], self.rect["x2"], self.rect["y2"]

    def notify_rect_change(self) -> None:
        self.on_rect_change(self.get_capture_bbox())


class ControlPanel:
    def __init__(self, root: tk.Tk, app) -> None:
        self.root = root
        self.app = app
        self.window = tk.Toplevel(root)
        self.window.title("GIF Maker Controls")
        self.window.attributes("-topmost", True)
        self.window.configure(bg=CONTROL_BG)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.app.close)

        frame = tk.Frame(self.window, bg=CONTROL_BG, padx=14, pady=14)
        frame.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Adjust the rectangle, then press Start.")
        self.bounds_var = tk.StringVar(value="")
        default_output_path = self.app.build_default_output_path()
        self.directory_var = tk.StringVar(value=str(default_output_path.parent))
        self.filename_var = tk.StringVar(value=default_output_path.name)

        tk.Label(
            frame,
            text="GIF Recorder",
            bg=CONTROL_BG,
            fg=CONTROL_FG,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        tk.Label(
            frame,
            textvariable=self.status_var,
            bg=CONTROL_BG,
            fg=CONTROL_FG,
            wraplength=260,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(8, 6))

        tk.Label(
            frame,
            textvariable=self.bounds_var,
            bg=CONTROL_BG,
            fg="#9DB4C0",
            justify="left",
            font=("Consolas", 9),
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            frame,
            text="File Path",
            bg=CONTROL_BG,
            fg=CONTROL_FG,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        directory_row = tk.Frame(frame, bg=CONTROL_BG)
        directory_row.pack(fill="x", pady=(0, 8))

        tk.Entry(
            directory_row,
            textvariable=self.directory_var,
            width=34,
            bg="#1C2430",
            fg=CONTROL_FG,
            insertbackground=CONTROL_FG,
            relief="flat",
            font=("Segoe UI", 9),
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            directory_row,
            text="Folder",
            command=self.choose_output_directory,
            bg="#253240",
            fg=CONTROL_FG,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(8, 0))

        tk.Label(
            frame,
            text="File Name",
            bg=CONTROL_BG,
            fg=CONTROL_FG,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        tk.Entry(
            frame,
            textvariable=self.filename_var,
            bg="#1C2430",
            fg=CONTROL_FG,
            insertbackground=CONTROL_FG,
            relief="flat",
            font=("Segoe UI", 9),
        ).pack(fill="x", pady=(0, 10))

        button_row = tk.Frame(frame, bg=CONTROL_BG)
        button_row.pack(fill="x")

        self.start_button = tk.Button(
            button_row,
            text="Start",
            width=10,
            command=self.app.start_recording,
            bg=ACCENT_COLOR,
            fg="#08131A",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        self.start_button.pack(side="left")

        self.stop_button = tk.Button(
            button_row,
            text="Stop",
            width=10,
            command=self.app.stop_recording,
            state="disabled",
            bg="#253240",
            fg=CONTROL_FG,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        self.stop_button.pack(side="left", padx=(8, 0))

        tk.Button(
            button_row,
            text="Exit",
            width=10,
            command=self.app.close,
            bg="#253240",
            fg=CONTROL_FG,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(8, 0))
        set_exclude_from_capture(self.window)

    def update_bounds(self, bbox: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        self.bounds_var.set(f"Area: ({x1}, {y1}) - ({x2}, {y2})  |  {width} x {height}")
        self.reposition_near_bbox(bbox)

    def reposition_near_bbox(self, bbox: tuple[int, int, int, int]) -> None:
        self.window.update_idletasks()
        panel_width = self.window.winfo_width()
        panel_height = self.window.winfo_height()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x1, y1, x2, y2 = bbox
        margin = 16

        candidates = [
            (x2 + margin, y1),
            (x1 - panel_width - margin, y1),
            (x1, y2 + margin),
            (x1, y1 - panel_height - margin),
            (margin, margin),
        ]

        for pos_x, pos_y in candidates:
            if 0 <= pos_x <= screen_width - panel_width and 0 <= pos_y <= screen_height - panel_height:
                self.window.geometry(f"+{int(pos_x)}+{int(pos_y)}")
                return

        self.window.geometry(f"+{margin}+{margin}")

    def set_recording(self, value: bool) -> None:
        if value:
            self.status_var.set("Recording... press Stop when you're done.")
            self.start_button.config(state="disabled")
            self.stop_button.config(state="normal")
        else:
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def choose_output_directory(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.window,
            title="Select Output Folder",
            initialdir=self.directory_var.get() or str(OUTPUT_DIR),
        )
        if selected:
            self.directory_var.set(selected)

    def get_output_path(self) -> Path:
        directory = Path(self.directory_var.get().strip()) if self.directory_var.get().strip() else OUTPUT_DIR
        filename = self.filename_var.get().strip() or self.app.build_default_output_path().name
        if not filename.lower().endswith(".gif"):
            filename = f"{filename}.gif"
        return directory / filename

    def set_output_path(self, path: Path) -> None:
        self.directory_var.set(str(path.parent))
        self.filename_var.set(path.name)


class GifMakerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.withdraw()

        self.overlay = OverlayWindow(root, self.on_rect_change)
        self.controls = ControlPanel(root, self)

        self.recording = False
        self.frames = []
        self.capture_bbox = self.overlay.get_capture_bbox()
        self.output_path = self.build_default_output_path()
        self.capture_job = None

        self.root.bind_all("<Escape>", lambda _event: self.close())
        self.on_rect_change(self.capture_bbox)

    def build_default_output_path(self) -> Path:
        OUTPUT_DIR.mkdir(exist_ok=True)
        return OUTPUT_DIR / f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.gif"

    def on_rect_change(self, bbox: tuple[int, int, int, int]) -> None:
        self.capture_bbox = bbox
        self.controls.update_bounds(bbox)

    def start_recording(self) -> None:
        if self.recording:
            return

        self.output_path = self.controls.get_output_path()
        if self.output_path.exists():
            should_overwrite = messagebox.askyesno(
                "Overwrite GIF",
                f"The file already exists:\n\n{self.output_path}\n\nDo you want to overwrite it?",
                parent=self.controls.window,
            )
            if not should_overwrite:
                self.controls.set_status("Recording cancelled. Choose a different file name.")
                return
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self.recording = True

        self.controls.set_recording(True)
        self.controls.set_status("Recording... press Stop when you're done.")
        self.overlay.set_recording(True)
        self.controls.window.lift()
        self.capture_next_frame()

    def stop_recording(self) -> None:
        if not self.recording:
            return

        self.recording = False
        if self.capture_job is not None:
            self.root.after_cancel(self.capture_job)
            self.capture_job = None
        self.controls.set_recording(False)
        self.controls.set_status("Finalizing GIF...")
        self.overlay.set_recording(False)

        if not self.frames:
            self.controls.set_status("No frames captured. Try a longer recording.")
            return

        try:
            self.save_gif()
        except Exception as exc:
            self.controls.set_status("Failed to save the GIF.")
            messagebox.showerror("GIF Maker", f"Could not save the GIF.\n\n{exc}")
            return

        self.controls.set_status(f"Saved GIF: {self.output_path}")

    def capture_next_frame(self) -> None:
        if not self.recording:
            return

        frame = ImageGrab.grab(
            bbox=self.capture_bbox,
            include_layered_windows=False,
            all_screens=True,
        )
        self.frames.append(frame.convert("P", palette=Image.ADAPTIVE))

        if self.recording:
            self.capture_job = self.root.after(FRAME_INTERVAL_MS, self.capture_next_frame)

    def save_gif(self) -> None:
        duration = FRAME_INTERVAL_MS
        first_frame, *rest_frames = self.frames
        first_frame.save(
            self.output_path,
            save_all=True,
            append_images=rest_frames,
            duration=duration,
            loop=0,
            optimize=False,
        )

    def close(self) -> None:
        if self.recording:
            self.recording = False
        if self.capture_job is not None:
            self.root.after_cancel(self.capture_job)
            self.capture_job = None
        self.overlay.window.destroy()
        self.controls.window.destroy()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    GifMakerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
