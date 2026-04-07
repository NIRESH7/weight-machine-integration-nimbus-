import sys
import serial
import serial.tools.list_ports
import threading
import time
import re
import asyncio
import pyautogui
import tkinter as tk
from tkinter import ttk, messagebox
from pynput import keyboard

# Bluetooth LE setup handled by asyncio automatically on Windows 10/11

try:
    from bleak import BleakScanner, BleakClient
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False

# CONFIG
BAUD_RATE = 9600
STABILITY_THRESHOLD = 0.05
STABILITY_READINGS = 5
TYPE_DELAY = 0.1
HOTKEY = keyboard.Key.f2

class WeighingSystemApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NimbusPost Weight Automator")
        self.root.geometry("450x650")
        self.root.attributes("-topmost", True)

        # State variables
        self.live_weight = 0.0
        self.is_stable = False
        self.current_order = 1
        self.total_orders = 10
        self.running = True
        self.readings_buffer = []
        
        self.selected_port = tk.StringVar()
        self.connection_mode = tk.StringVar(value="Serial")
        self.ble_device_address = None
        
        # Async Loop setup
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.loop_thread.start()

        self.setup_ui()
        self.refresh_ports()
        
        # Start Global Hotkey
        threading.Thread(target=self.hotkey_listener, daemon=True).start()
        
        # Start Initial Connection Monitor
        self.restart_connection()

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def setup_ui(self):
        style = ttk.Style()
        style.configure("Header.TLabel", font=("Helvetica", 12, "bold"))
        style.configure("Weight.TLabel", font=("Helvetica", 48, "bold"), foreground="#2c3e50")
        style.configure("Status.TLabel", font=("Helvetica", 9))
        style.configure("Accent.TButton", font=("Helvetica", 10, "bold"))

        # Main Weight Display
        lbl_weight_header = ttk.Label(self.root, text="LIVE WEIGHT (KG)", style="Header.TLabel")
        lbl_weight_header.pack(pady=(20, 0))

        self.lbl_weight = ttk.Label(self.root, text="0.00", style="Weight.TLabel")
        self.lbl_weight.pack(pady=5)

        self.lbl_stability = ttk.Label(self.root, text="READY TO PUT WEIGHT", foreground="gray")
        self.lbl_stability.pack()

        # Settings Section
        self.settings_frame = ttk.LabelFrame(self.root, text=" Connection Settings ")
        self.settings_frame.pack(fill="x", padx=20, pady=10)

        # Mode Selection
        mode_frame = ttk.Frame(self.settings_frame)
        mode_frame.pack(fill="x", padx=10, pady=5)
        ttk.Radiobutton(mode_frame, text="USB / Serial", variable=self.connection_mode, value="Serial", command=self.on_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="Bluetooth LE", variable=self.connection_mode, value="BLE", command=self.on_mode_change).pack(side="left", padx=5)

        # Port Selection for Serial
        self.port_frame = ttk.Frame(self.settings_frame)
        self.port_frame.pack(fill="x", padx=10, pady=5)
        self.port_dropdown = ttk.Combobox(self.port_frame, textvariable=self.selected_port, width=25)
        self.port_dropdown.pack(side="left", padx=5)
        ttk.Button(self.port_frame, text="↻", width=3, command=self.refresh_ports).pack(side="left")

        # BLE Selection
        self.ble_frame = ttk.Frame(self.settings_frame)
        self.btn_scan_ble = ttk.Button(self.ble_frame, text="🔍 SCAN FOR BLE SCALES", command=self.trigger_ble_scan)
        self.btn_scan_ble.pack(pady=5, fill="x", padx=10)
        self.lbl_ble_status = ttk.Label(self.ble_frame, text="No BLE device selected", style="Status.TLabel")
        self.lbl_ble_status.pack()

        ttk.Separator(self.root, orient='horizontal').pack(fill='x', pady=10, padx=20)

        # Order Control
        frame_order = ttk.Frame(self.root)
        frame_order.pack(pady=5)
        ttk.Label(frame_order, text="Total Orders:").grid(row=0, column=0, padx=5)
        self.ent_total_orders = ttk.Entry(frame_order, width=8)
        self.ent_total_orders.insert(0, str(self.total_orders))
        self.ent_total_orders.grid(row=0, column=1, padx=5)
        self.ent_total_orders.bind("<FocusOut>", self.update_total_orders)

        self.lbl_order_status = ttk.Label(self.root, text=f"Processing Order: {self.current_order} of {self.total_orders}", font=("Helvetica", 12, "bold"))
        self.lbl_order_status.pack(pady=5)

        # Action Buttons
        btn_update = ttk.Button(self.root, text="UPDATE & NEXT (F2)", style="Accent.TButton", command=self.trigger_automation)
        btn_update.pack(pady=10, padx=50, fill="x", ipady=15)

        btn_reset = ttk.Button(self.root, text="Reset Counter", command=self.reset_counter)
        btn_reset.pack(pady=5)

        # Status Bar
        self.lbl_status = ttk.Label(self.root, text="Ready", style="Status.TLabel", relief="sunken", anchor="w")
        self.lbl_status.pack(side="bottom", fill="x")

        # Set initial visibility
        self.on_mode_change()

    def on_mode_change(self):
        if self.connection_mode.get() == "Serial":
            self.ble_frame.pack_forget()
            self.port_frame.pack(fill="x", padx=10, pady=5)
        else:
            self.port_frame.pack_forget()
            self.ble_frame.pack(fill="x", padx=10, pady=5)
        self.restart_connection()

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        port_list.sort()
        self.port_dropdown['values'] = port_list
        if port_list and not self.selected_port.get():
            self.selected_port.set(port_list[0])

    def update_total_orders(self, event=None):
        try:
            self.total_orders = int(self.ent_total_orders.get())
            self.update_status_text()
        except: pass

    def update_status_text(self):
        self.lbl_order_status.config(text=f"Processing Order: {self.current_order} of {self.total_orders}")

    def reset_counter(self):
        self.current_order = 1
        self.update_status_text()

    def restart_connection(self):
        # Stop existing BLE connections
        if BLE_AVAILABLE:
            asyncio.run_coroutine_threadsafe(self._disconnect_all(), self.loop)
        
        self.live_weight = 0.0
        self.packet_count = 0
        self.lbl_weight.config(text="0.00", foreground="black")
        
        if self.connection_mode.get() == "Serial":
            threading.Thread(target=self.serial_reading_loop, daemon=True).start()
        elif self.ble_device_address:
            asyncio.run_coroutine_threadsafe(self.ble_connect_task(self.ble_device_address), self.loop)

    async def _disconnect_all(self):
        # Placeholder for cleanup
        pass

    def serial_reading_loop(self):
        while self.running and self.connection_mode.get() == "Serial":
            port = self.selected_port.get()
            if not port: 
                time.sleep(1)
                continue
            try:
                with serial.Serial(port, BAUD_RATE, timeout=0.1) as ser:
                    self.lbl_status.config(text=f"CONNECTED: {port}", foreground="green")
                    while self.running and self.connection_mode.get() == "Serial":
                        line = ser.readline().decode('ascii', errors='ignore').strip()
                        if line: self.process_raw_data(line)
                        time.sleep(0.01)
            except:
                self.lbl_status.config(text="Looking for Serial Scale...", foreground="orange")
                time.sleep(2)

    def trigger_ble_scan(self):
        if not BLE_AVAILABLE: return
        self.btn_scan_ble.config(text="⌛ SCANNING...", state="disabled")
        self.lbl_status.config(text="Searching for Bluetooth devices (10s)...", foreground="blue")
        asyncio.run_coroutine_threadsafe(self.run_ble_scan(), self.loop)

    async def run_ble_scan(self):
        try:
            devices = await BleakScanner.discover(timeout=10.0)
            self.root.after(0, lambda: self._show_scan_results(devices))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Scan failed: {e}"))
            self.root.after(0, lambda: self.btn_scan_ble.config(text="🔍 SCAN FOR BLE SCALES", state="normal"))

    def _show_scan_results(self, devices):
        self.btn_scan_ble.config(text="🔍 SCAN FOR BLE SCALES", state="normal")
        
        scan_win = tk.Toplevel(self.root)
        scan_win.title("Pick Your Scale")
        scan_win.geometry("350x400")
        
        lb = tk.Listbox(scan_win, font=("Helvetica", 10))
        lb.pack(fill="both", expand=True, padx=10, pady=10)
        
        for d in devices:
            name = d.name if d.name else "Unknown Device"
            lb.insert("end", f"{name} ({d.address})")
        
        def on_select():
            sel = lb.curselection()
            if sel:
                d = devices[sel[0]]
                self.ble_device_address = d.address
                self.lbl_ble_status.config(text=f"SELECTED: {d.name}")
                scan_win.destroy()
                self.restart_connection()

        ttk.Button(scan_win, text="CONNECT TO SELECTED", command=on_select).pack(pady=10)

    async def ble_connect_task(self, address):
        self.lbl_status.config(text=f"Connecting to {address}...", foreground="orange")
        try:
            # Increased timeout for warehouse environments
            async with BleakClient(address, timeout=30.0) as client:
                if client.is_connected:
                    self.lbl_status.config(text=f"🔍 DISCOVERING CHANNELS...", foreground="blue")
                    
                    found_count = 0
                    for s in client.services:
                        for c in s.characteristics:
                            if "notify" in c.properties:
                                try:
                                    await client.start_notify(c.uuid, self.ble_handler)
                                    found_count += 1
                                except: pass
                    
                    if found_count == 0:
                        self.lbl_status.config(text="Error: No notification channels found.", foreground="red")
                        return

                    self.lbl_status.config(text=f"✅ LISTENING ({found_count} Channels)", foreground="green")
                    while self.running and self.connection_mode.get() == "BLE" and client.is_connected:
                        await asyncio.sleep(2)
        except Exception as e:
            self.lbl_status.config(text=f"BLE ERROR: {type(e).__name__} - {e}", foreground="red")

    def ble_handler(self, sender, data):
        self.last_data_time = time.time()
        self.packet_count += 1
        raw_hex = data.hex().upper()
        uuid_full = str(sender.uuid) if hasattr(sender, 'uuid') else str(sender)
        uuid_short = uuid_full[:4] # Use first 4 of UUID
        
        if not hasattr(self, 'history'): self.history = {}
        
        # Check if the data is NEW for this channel
        is_new = self.history.get(uuid_short) != raw_hex
        self.history[uuid_short] = raw_hex
        
        # Build status: Putting NEW data at the front
        active_channels = sorted(self.history.keys(), key=lambda x: x == uuid_short, reverse=True)
        status_parts = []
        for u in active_channels[:4]:
            suffix = "*" if u == uuid_short and is_new else ""
            status_parts.append(f"{u}{suffix}:{self.history[u][:10]}")
        
        status_text = " | ".join(status_parts)
        self.root.after(0, lambda: self.lbl_status.config(text=status_text, foreground="#2980b9"))
        
        try:
            # TRY TO FIND NUMBERS
            weight = 0.0
            
            # Numeric decode attempt (ASCII)
            txt = data.decode('ascii', errors='ignore').strip()
            match = re.search(r"[-+]?\d*\.\d+|\d+", txt)
            if match:
                weight = float(match.group())
            
            # Binary decode attempt (Essae/Generic)
            if weight == 0 and len(data) >= 2:
                # Try common formats
                val_be = int.from_bytes(data[-2:], byteorder='big')
                val_le = int.from_bytes(data[-2:], byteorder='little')
                
                # Calibration check: Guess divisor based on value
                for v in [val_be, val_le]:
                    if 0 < v < 5000: weight = v / 10.0
                    elif 5000 <= v < 50000: weight = v / 100.0
                    if weight != 0: break

            if weight != 0 and 0.01 < weight < 500:
                self.root.after(0, lambda: self.process_weight_value(weight))
        except: pass

    def process_raw_data(self, data):
        match = re.search(r"[-+]?\d*\.\d+|\d+", data)
        if match:
            try: self.process_weight_value(float(match.group()))
            except: pass

    def process_weight_value(self, weight):
        self.live_weight = weight
        self.lbl_weight.config(text=f"{weight:.2f}")
        self.readings_buffer.append(weight)
        if len(self.readings_buffer) > STABILITY_READINGS: self.readings_buffer.pop(0)

        if len(self.readings_buffer) == STABILITY_READINGS:
            diff = max(self.readings_buffer) - min(self.readings_buffer)
            if diff < STABILITY_THRESHOLD and weight > 0.01:
                self.is_stable = True
                self.lbl_stability.config(text="STABLE WEIGHT DETECTED", foreground="#2e7d32")
                self.lbl_weight.config(foreground="#2e7d32")
            else:
                self.is_stable = False
                self.lbl_stability.config(text="WAITING FOR STABILITY...", foreground="orange")
                self.lbl_weight.config(foreground="black")

    def trigger_automation(self):
        if not self.is_stable:
            messagebox.showwarning("Warning", "Weight not stable yet.")
            return
        threading.Thread(target=self.type_weight, args=(f"{self.live_weight:.2f}",), daemon=True).start()

    def type_weight(self, value):
        time.sleep(TYPE_DELAY)
        pyautogui.write(value)
        pyautogui.press('enter')
        self.current_order += 1
        if self.current_order > self.total_orders:
            self.root.after(0, lambda: messagebox.showinfo("Done", "All orders complete!"))
            self.current_order = 1
        self.root.after(0, self.update_status_text)

    def hotkey_listener(self):
        with keyboard.Listener(on_press=self.on_press) as listener:
            listener.join()

    def on_press(self, key):
        if key == HOTKEY:
            self.root.after(0, self.trigger_automation)

if __name__ == "__main__":
    root = tk.Tk()
    app = WeighingSystemApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: sys.exit())
    root.mainloop()