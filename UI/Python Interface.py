import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import math
import re
import threading
import time
import datetime

try:
    import serial
    import serial.tools.list_ports

    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


class GCodeVisualizer(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("G-Code Visualizer & Sender")
        self.geometry("1000x850")

        self.scale = 5.0
        self.origin_x = 50
        self.origin_y = 50
        self.grid_size = 500
        self.serial_port = None
        self.is_sending = False

        self.paned_window = tk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.left_panel = tk.Frame(self.paned_window)

        self.editor_frame = tk.Frame(self.left_panel)
        self.editor_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.text_input = tk.Text(self.editor_frame, width=40, height=20, undo=True, font=("Consolas", 10))
        self.text_input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.scrollbar = tk.Scrollbar(self.editor_frame, command=self.text_input.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_input.config(yscrollcommand=self.scrollbar.set)
        self.text_input.bind("<KeyRelease>", self.update_visualization)

        self.log_frame = tk.LabelFrame(self.left_panel, text="Serial Log", padx=5, pady=5)
        self.log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=5)

        self.log_text = tk.Text(self.log_frame, height=10, state='disabled', bg="#2b2b2b", fg="#00ff00",
                                font=("Consolas", 9))
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_scroll = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=self.log_scroll.set)

        self.control_frame = tk.Frame(self.left_panel)
        self.control_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        self.port_frame = tk.Frame(self.control_frame)
        self.port_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(self.port_frame, text="Port:").pack(side=tk.LEFT, padx=2)
        self.port_combo = ttk.Combobox(self.port_frame, width=10)
        self.port_combo.pack(side=tk.LEFT, padx=2)
        self.refresh_ports()
        tk.Button(self.port_frame, text="R", command=self.refresh_ports, width=3).pack(side=tk.LEFT, padx=2)

        self.btn_frame = tk.Frame(self.control_frame)
        self.btn_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.send_btn = tk.Button(self.btn_frame, text="Connect & Send", command=self.start_sending_thread,
                                  bg="#ddffdd")
        self.send_btn.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.toggle_btn = tk.Button(self.btn_frame, text="Toggle Pen (GT)", command=self.manual_toggle,
                                    bg="#f0f0f0")
        self.toggle_btn.pack(side=tk.LEFT, padx=5)

        self.paned_window.add(self.left_panel)
        self.canvas_frame = tk.Frame(self.paned_window, bg="white")
        self.canvas = tk.Canvas(self.canvas_frame, bg="#f0f0f0")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.paned_window.add(self.canvas_frame)

        default_code = (
            "G0 X10 Y10\n"
            "GT\n"
            "G1 X40 Y10\n"
            "G1 X40 Y40\n"
            "GT\n"
            "G0 X0 Y0"
        )

        self.text_input.insert("1.0", default_code)
        self.canvas.bind("<Configure>", self.on_resize)
        self.update_visualization()

        if not HAS_SERIAL:
            self.log_message("Error: 'pyserial' not installed.", "ERR")
            self.send_btn.config(state="disabled")

    def log_message(self, msg, tag="INFO"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state='normal')
        self.log_text.insert('end', f"[{timestamp}] [{tag}] {msg}\n")
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def refresh_ports(self):
        if not HAS_SERIAL:
            return
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports
        if ports:
            self.port_combo.current(0)

    def manual_toggle(self):
        port = self.port_combo.get()
        if not port:
            messagebox.showerror("Error", "No port selected")
            return

        thread = threading.Thread(target=self.send_single_command, args=(port, "GT"))
        thread.daemon = True
        thread.start()

    def send_single_command(self, port_name, cmd):
        try:
            with serial.Serial(port_name, 9600, timeout=1) as ser:
                time.sleep(1.5)
                ser.write((cmd + "\n").encode('utf-8'))
                self.log_message(f"Manual Cmd: {cmd}", "TX")
                start_time = time.time()
                while time.time() - start_time < 2.0:
                    if ser.in_waiting:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.log_message(line, "RX")
                            if "Done" in line: break
        except Exception as e:
            self.log_message(f"Manual Toggle Error: {e}", "ERR")

    def start_sending_thread(self):
        if self.is_sending: return
        port = self.port_combo.get()
        if not port:
            messagebox.showerror("Error", "No port selected")
            return

        raw_text = self.text_input.get("1.0", "end")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines: return

        self.is_sending = True
        self.send_btn.config(state="disabled", text="Running...")

        thread = threading.Thread(target=self.send_gcode_process, args=(port, lines))
        thread.daemon = True
        thread.start()

    def send_gcode_process(self, port_name, lines):
        try:
            self.log_message(f"Opening {port_name}...", "SYS")
            with serial.Serial(port_name, 9600, timeout=1) as ser:
                ser.dtr = False
                time.sleep(0.5)
                ser.dtr = True
                self.log_message("Waiting for 'System Ready'...", "SYS")

                connected = False
                boot_wait_start = time.time()
                while not connected:
                    if ser.in_waiting:
                        try:
                            line = ser.readline().decode('utf-8', errors='ignore').strip()
                            if line:
                                self.log_message(line, "RX")
                                connected = True
                        except:
                            pass
                    if time.time() - boot_wait_start > 4.0:
                        self.log_message(">>> PLEASE PRESS RESET BUTTON <<<", "ACTION")
                        boot_wait_start = time.time() + 5.0
                    time.sleep(0.1)

                ser.reset_input_buffer()

                job_lines = lines + ["G0 X0 Y0"]
                total = len(job_lines)

                for i, gcode in enumerate(job_lines):
                    def scale_match(match):
                        prefix = match.group(1)
                        value = float(match.group(2))
                        return f"{prefix}{value / 5.0:.3f}"

                    scaled_gcode = re.sub(r'([XYIJ])([-+]?\d*\.?\d+)', scale_match, gcode, flags=re.IGNORECASE)

                    if i == total - 1:
                        self.log_message("Auto-homing...", "SYS")

                    self.log_message(f"Sending {i + 1}/{total}: {scaled_gcode}", "TX")
                    ser.write((scaled_gcode + "\n").encode('utf-8'))

                    got_response = False
                    while not got_response:
                        if ser.in_waiting:
                            line = ser.readline().decode('utf-8', errors='ignore').strip()
                            if line:
                                self.log_message(line, "RX")
                                if any(word in line for word in ["Done", "ok", "Unsupported"]):
                                    got_response = True
                        time.sleep(0.05)

            self.log_message("Job finished.", "SYS")
        except Exception as e:
            self.log_message(f"Error: {e}", "ERR")
        finally:
            self.is_sending = False
            self.after(0, lambda: self.send_btn.config(state="normal", text="Connect & Send"))

    def on_resize(self, event):
        self.update_visualization()

    def to_screen_coords(self, x, y, canvas_height):
        screen_x = self.origin_x + (x * self.scale)
        screen_y = canvas_height - self.origin_y - (y * self.scale)
        return screen_x, screen_y

    def draw_grid(self, width, height):
        self.canvas.delete("all")
        grid_step = 10
        max_x = int((width - self.origin_x) / self.scale)
        max_y = int((height - self.origin_y) / self.scale)
        for i in range(0, max_x + 1, grid_step):
            x = self.origin_x + (i * self.scale)
            self.canvas.create_line(x, 0, x, height, fill="#e0e0e0")
            self.canvas.create_text(x, height - (self.origin_y / 2), text=str(i), fill="gray", font=("Arial", 8))
        for i in range(0, max_y + 1, grid_step):
            y = height - self.origin_y - (i * self.scale)
            self.canvas.create_line(0, y, width, y, fill="#e0e0e0")
            self.canvas.create_text(self.origin_x / 2, y, text=str(i), fill="gray", font=("Arial", 8))
        ox, oy = self.to_screen_coords(0, 0, height)
        self.canvas.create_line(0, oy, width, oy, fill="#ffcccc", width=2)
        self.canvas.create_line(ox, 0, ox, height, fill="#ccffcc", width=2)
        r = 4
        self.canvas.create_oval(ox - r, oy - r, ox + r, oy + r, fill="green", outline="black")

    def parse_value(self, line, key, default):
        pattern = f"{key}([-+]?\d*\.?\d+)"
        match = re.search(pattern, line, re.IGNORECASE)
        if match: return float(match.group(1))
        return default

    def update_visualization(self, event=None):
        if self.canvas.winfo_width() < 10: return
        self.draw_grid(self.canvas.winfo_width(), self.canvas.winfo_height())
        raw_text = self.text_input.get("1.0", "end")
        lines = raw_text.splitlines()
        cur_x, cur_y = 0.0, 0.0
        height = self.canvas.winfo_height()

        for line in lines:
            line = line.strip().upper()
            if not line: continue

            if line.startswith("GT"):
                continue

            is_g0 = line.startswith("G0")
            is_g1 = line.startswith("G1")
            is_g2 = line.startswith("G2")
            is_g3 = line.startswith("G3")
            if not (is_g0 or is_g1 or is_g2 or is_g3): continue

            tx = self.parse_value(line, 'X', cur_x)
            ty = self.parse_value(line, 'Y', cur_y)
            sx_start, sy_start = self.to_screen_coords(cur_x, cur_y, height)
            sx_end, sy_end = self.to_screen_coords(tx, ty, height)

            if is_g0:
                self.canvas.create_line(sx_start, sy_start, sx_end, sy_end, fill="gray", dash=(4, 2), width=1)
            elif is_g1:
                self.canvas.create_line(sx_start, sy_start, sx_end, sy_end, fill="blue", width=2)
            elif is_g2 or is_g3:
                i = self.parse_value(line, 'I', 0.0)
                j = self.parse_value(line, 'J', 0.0)
                cx, cy = cur_x + i, cur_y + j
                rad = math.sqrt(i ** 2 + j ** 2)
                if rad > 0:
                    bx0, by0 = self.to_screen_coords(cx - rad, cy + rad, height)
                    bx1, by1 = self.to_screen_coords(cx + rad, cy - rad, height)
                    start_ang = math.degrees(math.atan2(cur_y - cy, cur_x - cx))
                    end_ang = math.degrees(math.atan2(ty - cy, tx - cx))
                    extent = end_ang - start_ang
                    if is_g2 and extent >= 0:
                        extent -= 360
                    elif is_g3 and extent <= 0:
                        extent += 360
                    self.canvas.create_arc(bx0, by0, bx1, by1, start=start_ang, extent=extent, style=tk.ARC,
                                           outline="blue", width=2)
                else:
                    self.canvas.create_line(sx_start, sy_start, sx_end, sy_end, fill="red")

            self.canvas.create_oval(sx_end - 2, sy_end - 2, sx_end + 2, sy_end + 2, fill="red", outline="")
            cur_x, cur_y = tx, ty


if __name__ == "__main__":
    app = GCodeVisualizer()
    app.mainloop()