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
import subprocess

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
        self.packet_count = 0
        self.last_raw_packet = ""
        
        self.selected_port = tk.StringVar()
        self.selected_bt_classic_port = tk.StringVar()
        self.connection_mode = tk.StringVar(value="Serial")
        self.baud_rate = tk.IntVar(value=9600)
        self.tab_count = tk.IntVar(value=7)
        self.ser_current = None
        self.auto_update = tk.BooleanVar(value=False)
        self.has_typed = False
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
        ttk.Radiobutton(mode_frame, text="BT Classic", variable=self.connection_mode, value="Classic", command=self.on_mode_change).pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="BT LE", variable=self.connection_mode, value="BLE", command=self.on_mode_change).pack(side="left", padx=5)

        # Port Selection for Serial
        self.port_frame = ttk.Frame(self.settings_frame)
        self.port_frame.pack(fill="x", padx=10, pady=5)
        self.port_dropdown = ttk.Combobox(self.port_frame, textvariable=self.selected_port, width=25)
        self.port_dropdown.pack(side="left", padx=5)
        ttk.Button(self.port_frame, text="↻", width=3, command=self.refresh_ports).pack(side="left")

        # Classic BT Selection
        self.classic_bt_frame = ttk.Frame(self.settings_frame)
        self.btn_scan_classic = ttk.Button(self.classic_bt_frame, text="🔍 SCAN FOR BT DEVICES", command=self.trigger_classic_scan)
        self.btn_scan_classic.pack(pady=5, fill="x", padx=10)
        self.lbl_classic_status = ttk.Label(self.classic_bt_frame, text="No device selected", style="Status.TLabel")
        self.lbl_classic_status.pack()

        # Baud Rate Selector
        baud_frame = ttk.Frame(self.settings_frame)
        baud_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(baud_frame, text="Speed (Baud):").pack(side="left", padx=5)
        self.baud_dropdown = ttk.Combobox(baud_frame, textvariable=self.baud_rate, values=[2400, 4800, 9600, 19200, 38400, 115200], width=10)
        self.baud_dropdown.pack(side="left", padx=5)
        self.baud_dropdown.bind("<<ComboboxSelected>>", lambda e: self.restart_connection())
        
        ttk.Button(baud_frame, text="⚡ SEND TEST COMMAND", command=self.send_test_request).pack(side="left", padx=5)

        # BLE Selection
        self.ble_frame = ttk.Frame(self.settings_frame)
        self.btn_scan_ble = ttk.Button(self.ble_frame, text="🔍 SCAN FOR BLE SCALES", command=self.trigger_ble_scan)
        self.btn_scan_ble.pack(pady=5, fill="x", padx=10)
        self.lbl_ble_status = ttk.Label(self.ble_frame, text="No BLE device selected", style="Status.TLabel")
        self.lbl_ble_status.pack()

        ttk.Separator(self.root, orient='horizontal').pack(fill='x', pady=5, padx=20)

        # Auto-Update Feature
        self.ch_auto = ttk.Checkbutton(self.root, text="⚡ AUTO-UPDATE ON STABILITY", variable=self.auto_update)
        self.ch_auto.pack(pady=5)

        # TAB Jump Setting
        tab_frame = ttk.Frame(self.root)
        tab_frame.pack(pady=5)
        ttk.Label(tab_frame, text="TAB Jump (to next row):").pack(side="left", padx=5)
        ttk.Entry(tab_frame, textvariable=self.tab_count, width=5).pack(side="left", padx=5)

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
        self.port_frame.pack_forget()
        self.ble_frame.pack_forget()
        self.classic_bt_frame.pack_forget()

        if self.connection_mode.get() == "Serial":
            self.port_frame.pack(fill="x", padx=10, pady=5)
            self.refresh_ports()
        elif self.connection_mode.get() == "BLE":
            self.ble_frame.pack(fill="x", padx=10, pady=5)
        elif self.connection_mode.get() == "Classic":
            self.classic_bt_frame.pack(fill="x", padx=10, pady=5)
            self.refresh_bluetooth_ports()
        
        self.restart_connection()

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        port_list.sort()
        self.port_dropdown['values'] = port_list
        if port_list and not self.selected_port.get():
            self.selected_port.set(port_list[0])

    def refresh_bluetooth_ports(self):
        # Fallback refresh if scan window isn't used
        ports = serial.tools.list_ports.comports()
        bt_ports = [p for p in ports if "Bluetooth" in p.description or "BTHENUM" in p.hwid]
        if bt_ports:
            self.selected_bt_classic_port.set(bt_ports[0].device)
            self.lbl_classic_status.config(text=f"CONNECTED: {bt_ports[0].device}")

    def trigger_classic_scan(self):
        threading.Thread(target=self.run_classic_scan, daemon=True).start()

    def run_classic_scan(self):
        self.btn_scan_classic.config(text="⌛ SCANNING...", state="disabled")
        try:
            # Query Windows PnP system for Bluetooth Serial Ports
            cmd = 'powershell -Command "Get-PnpDevice -Class Ports | Where-Object { $_.FriendlyName -like \'*Bluetooth*\' } | Select-Object FriendlyName"'
            output = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='ignore')
            
            # Extract lines that look like "Standard Serial over Bluetooth link (COMx)"
            # Example line: Standard Serial over Bluetooth link (COM3)
            matches = re.findall(r"(.*Standard Serial over Bluetooth link \(COM\d+\).*)", output)
            if not matches:
                # If specifically filtered list is empty, try broader search
                matches = re.findall(r"(.*Serial.*Bluetooth.*COM\d+.*)", output)
                
            self.root.after(0, lambda: self._show_classic_scan_results(matches))
        except Exception as e:
            error_text = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"BT Scan failed: {error_text}"))
        finally:
            self.root.after(0, lambda: self.btn_scan_classic.config(text="🔍 SCAN FOR BT DEVICES", state="normal"))

    def _show_classic_scan_results(self, devices):
        scan_win = tk.Toplevel(self.root)
        scan_win.title("Pick Normal Bluetooth")
        scan_win.geometry("400x450")
        scan_win.attributes("-topmost", True)

        lb = tk.Listbox(scan_win, font=("Helvetica", 10))
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        # Cleanup device names for the list
        devices = [d.strip() for d in devices if d.strip() and not d.strip().startswith('FriendlyName')]
        for d in devices:
            lb.insert("end", d)

        if not devices:
            lb.insert("end", "No paired Bluetooth machines found.")
            lb.insert("end", "(Make sure you paired it in Windows Settings first)")

        def on_select():
            sel = lb.curselection()
            if sel and "paired" not in devices[sel[0]].lower():
                d_full = devices[sel[0]]
                # Extract COM port from "(COMx)"
                com_match = re.search(r"\( (COM\d+) \)", d_full.replace("(", "( ").replace(")", " )"))
                if not com_match: com_match = re.search(r"(COM\d+)", d_full)
                
                if com_match:
                    port = com_match.group(1)
                    self.selected_bt_classic_port.set(port)
                    self.lbl_classic_status.config(text=f"SELECTED: {port}")
                    scan_win.destroy()
                    self.restart_connection()
                else:
                    messagebox.showwarning("Warning", "Could not identify COM port in selection.")

        ttk.Button(scan_win, text="USE THIS DEVICE", command=on_select).pack(pady=10)

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
        
        if self.connection_mode.get() in ["Serial", "Classic"]:
            threading.Thread(target=self.serial_reading_loop, daemon=True).start()
        elif self.ble_device_address:
            asyncio.run_coroutine_threadsafe(self.ble_connect_task(self.ble_device_address), self.loop)

    async def _disconnect_all(self):
        # Placeholder for cleanup
        pass

    def serial_reading_loop(self):
        mode = self.connection_mode.get()
        while self.running and self.connection_mode.get() == mode:
            if mode == "Serial":
                port = self.selected_port.get()
            else: # Classic BT
                raw = self.selected_bt_classic_port.get()
                port = raw.split(" (")[0] if " (" in raw else raw

            if not port: 
                time.sleep(1)
                continue
            try:
                # Open with currently selected baud rate
                with serial.Serial(port, self.baud_rate.get(), timeout=1, rtscts=False, dsrdtr=True) as ser:
                    self.ser_current = ser # Store for sending commands
                    self.root.after(0, lambda: self.lbl_status.config(text=f"CONNECTED: {port} @ {self.baud_rate.get()}", foreground="green"))
                    while self.running and self.connection_mode.get() == mode:
                        if ser.in_waiting > 0:
                            raw_raw = ser.read(ser.in_waiting)
                            raw_data = raw_raw.decode('ascii', errors='ignore')
                            self.packet_count += 1
                            self.last_raw_packet = raw_data.strip()
                            
                            # Show activity and HEX (if no numbers found)
                            hex_data = raw_raw.hex().upper()[:8]
                            msg = f"CONNECTED: {port} | PACKETS: {self.packet_count} | HEX: {hex_data}"
                            self.root.after(0, lambda m=msg: self.lbl_status.config(text=m, foreground="green"))
                            
                            matches = re.findall(r"(\d*\.\d+|\d+)", raw_data)
                            if matches:
                                try:
                                    last_val = float(matches[-1])
                                    if 0.01 < last_val < 500:
                                        self.root.after(0, lambda val=last_val: self.process_weight_value(val))
                                except: pass
                        time.sleep(0.05)
            except Exception as e:
                self.ser_current = None
                self.root.after(0, lambda: self.lbl_status.config(text=f"Searching for Scale... ({type(e).__name__})", foreground="orange"))
                time.sleep(2)
            finally:
                self.ser_current = None

    def send_test_request(self):
        if not self.ser_current:
            messagebox.showwarning("Warning", "Scale not connected.")
            return
        try:
            # Common weight request commands: W(Enter), P(Enter), etc.
            self.ser_current.write(b"W\r\n")
            self.ser_current.write(b"P\r\n")
            self.lbl_status.config(text="COMMAND SENT (W/P)", foreground="blue")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send: {e}")

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
            error_text = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Scan failed: {error_text}"))
            self.root.after(0, lambda: self.btn_scan_ble.config(text="🔍 SCAN FOR BLE SCALES", state="normal"))

    def _show_scan_results(self, devices):
        self.btn_scan_ble.config(text="🔍 SCAN FOR BLE SCALES", state="normal")
        
        scan_win = tk.Toplevel(self.root)
        scan_win.title("Pick Your Scale")
        scan_win.geometry("450x450")
        scan_win.attributes("-topmost", True)
        
        lb = tk.Listbox(scan_win, font=("Helvetica", 10))
        lb.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Safely sort by signal strength (RSSI) with extreme defensive checks
        def get_rssi(dev):
            try:
                if hasattr(dev, 'rssi') and dev.rssi is not None:
                    return dev.rssi
                if hasattr(dev, 'metadata') and dev.metadata and 'rssi' in dev.metadata:
                    return dev.metadata['rssi']
            except: pass
            return -100
            
        devices = sorted(devices, key=get_rssi, reverse=True)
        
        for d in devices:
            name = d.name if d.name else "Unknown Device"
            rssi = get_rssi(d)
            rssi_display = rssi if rssi != -100 else "??"
            lb.insert("end", f"{name} ({d.address}) | Strength: {rssi_display}")
        
        def on_select():
            sel = lb.curselection()
            if sel:
                d = devices[sel[0]]
                self.ble_device_address = d.address
                display_name = d.name if d.name else d.address
                self.lbl_ble_status.config(text=f"SELECTED: {display_name}")
                scan_win.destroy()
                self.restart_connection()

        ttk.Button(scan_win, text="CONNECT TO SELECTED", command=on_select).pack(pady=10)

    async def ble_connect_task(self, address):
        retries = 3
        for attempt in range(retries):
            self.lbl_status.config(text=f"Connecting to {address} (Attempt {attempt+1}/{retries})...", foreground="orange")
            try:
                # Increased timeout for warehouse environments
                async with BleakClient(address, timeout=15.0) as client:
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
                    
                    if not self.running or self.connection_mode.get() != "BLE":
                        break
            except Exception as e:
                if attempt < retries - 1:
                    self.lbl_status.config(text=f"Retry {attempt+1} failed, waiting...", foreground="orange")
                    await asyncio.sleep(2)
                else:
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

        # Reset 'has_typed' only when item is removed (weight near 0)
        if weight < 0.02:
            self.has_typed = False

        if len(self.readings_buffer) == STABILITY_READINGS:
            diff = max(self.readings_buffer) - min(self.readings_buffer)
            if diff < STABILITY_THRESHOLD and weight > 0.01:
                if not self.is_stable:
                    self.is_stable = True
                    self.lbl_stability.config(text="STABLE WEIGHT DETECTED", foreground="#2e7d32")
                    self.lbl_weight.config(foreground="#2e7d32")
                    
                    # TRIGGER AUTO-UPDATE
                    if self.auto_update.get() and not self.has_typed and weight > 0.5: # 0.5kg threshold to avoid vibrations
                        self.has_typed = True
                        self.trigger_automation()
                
            else:
                self.is_stable = False
                self.lbl_stability.config(text="WAITING FOR STABILITY...", foreground="orange")
                self.lbl_weight.config(foreground="black")

    def trigger_automation(self):
        if not self.is_stable:
            messagebox.showwarning("Warning", "Weight not stable yet.")
            return
        
        # Calculate Grams (Multiply KG by 1000)
        grams_value = int(self.live_weight * 1000)
        
        threading.Thread(target=self.type_weight, args=(str(grams_value),), daemon=True).start()

    def type_weight(self, value):
        time.sleep(TYPE_DELAY)
        pyautogui.write(value)
        pyautogui.press('enter')
        
        # JUMP TO NEXT CELL
        time.sleep(0.5) # Wait for NimbusPort to save
        for _ in range(self.tab_count.get()):
            pyautogui.press('tab')
            time.sleep(0.05) # Tiny delay for UI stability
            
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