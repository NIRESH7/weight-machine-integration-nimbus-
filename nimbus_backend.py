import os
import re
import time
import threading
import csv
import uvicorn
import serial
import serial.tools.list_ports
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List

# Setup
PROJECT_DIR = r"c:\Users\Admin\Desktop\nimbus"
ACTIVE_FILE = os.path.join(PROJECT_DIR, "active_report.csv")

app = FastAPI(title="Nimbus Bluetooth Backend (Mobile-First)")

# CORS Fix for Browser/Web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bluetooth State
class ScaleState:
    def __init__(self):
        self.current_weight = 0.0
        self.is_connected = False
        self.port = None # Waiting for user to connect
        self.baud = 9600
        self.running = True
        self.thread = None
        self.status_log = "Waiting for connection..."

scale = ScaleState()

# Dimension Logic (Pcs to LBH)
def get_dimensions(pcs_str):
    try:
        pcs = int(pcs_str)
        if 1 <= pcs <= 2: return "8", "2", "6"
        elif 3 <= pcs <= 4: return "10", "4", "8"
        elif 5 <= pcs <= 10: return "14", "6", "12"
        elif 11 <= pcs <= 15: return "19", "8", "15"
        elif 16 <= pcs <= 25: return "24", "10", "20"
        else: return "", "", ""
    except:
        return "", "", ""

# Scale Background Thread
def scale_listener(port):
    while scale.running and scale.port == port:
        try:
            with serial.Serial(port, scale.baud, timeout=1) as ser:
                msg = f"Connected to {port} @ {scale.baud}"
                scale.status_log = msg
                print(f"DEBUG: {msg}")
                scale.is_connected = True
                last_data_time = time.time()
                last_trigger_time = time.time()
                bauds = [9600, 38400, 2400, 4800, 19200, 115200]
                
                while scale.running and scale.port == port:
                    if ser.in_waiting > 0:
                        last_data_time = time.time()
                        raw_bytes = ser.read(ser.in_waiting)
                        raw = raw_bytes.decode('ascii', errors='ignore')
                        scale.status_log = f"SIGNAL: '{raw.strip()}'"
                        print(f"RAW DATA: '{raw}'")
                        
                        matches = re.findall(r"[-+]?\s*\d*\.\d+|\d+", raw)
                        if matches:
                            try:
                                scale.current_weight = float(matches[-1].replace(' ', ''))
                                scale.status_log = f"PARSED: {scale.current_weight}"
                                print(f"MATCH: {scale.current_weight}")
                            except: pass
                    
                    # Send trigger every 2 seconds (Request Weight)
                    if time.time() - last_trigger_time > 2.0:
                        ser.write(b'W\n') # Common 'Weight' request
                        ser.write(b'P\n') # Common 'Print' request
                        ser.write(b'R\n') # Common 'Read' request
                        last_trigger_time = time.time()

                    # Cycle baud if no data for 6 seconds
                    if time.time() - last_data_time > 6:
                        idx = bauds.index(scale.baud)
                        scale.baud = bauds[(idx + 1) % len(bauds)]
                        scale.status_log = f"NO DATA. Switching to {scale.baud}..."
                        print(f"DEBUG: No data. Trying {scale.baud} baud...")
                        break
                    
                    time.sleep(0.1)
        except Exception as e:
            scale.is_connected = False
            scale.status_log = f"ERROR: {str(e)}"
            time.sleep(2)

@app.get("/scan")
def scan_ports():
    ports = serial.tools.list_ports.comports()
    return [{"port": p.device, "desc": p.description} for p in ports]

@app.post("/connect/{port}")
def connect_scale(port: str):
    scale.port = port
    if scale.thread and scale.thread.is_alive():
        pass # Thread logic handles port change
    else:
        scale.thread = threading.Thread(target=scale_listener, args=(port,), daemon=True)
        scale.thread.start()
    return {"status": "connecting", "port": port}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Save the file
    content = await file.read()
    with open(ACTIVE_FILE, "wb") as f:
        f.write(content)
    
    # Process LBH Logic and clear weights
    with open(ACTIVE_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
        
    for row in rows:
        row['Weight(gm)'] = "" # Clear weights
        l, b, h = get_dimensions(row.get('Total Products Count', "0"))
        row['Length(cm)'] = l
        row['Breadth(cm)'] = b
        row['Height(cm)'] = h
        
    with open(ACTIVE_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        
    return {"status": "success", "filename": file.filename}

@app.get("/products")
def get_products():
    if not os.path.exists(ACTIVE_FILE):
        return []
    with open(ACTIVE_FILE, mode='r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

@app.get("/scale_status")
def get_status():
    return {
        "connected": scale.is_connected,
        "weight": scale.current_weight,
        "port": scale.port,
        "status_log": scale.status_log
    }

@app.post("/capture/{order_id}")
def capture_weight(order_id: str):
    if not os.path.exists(ACTIVE_FILE):
        raise HTTPException(status_code=404, detail="No file active")
    
    with open(ACTIVE_FILE, mode='r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fieldnames = rows[0].keys() if rows else []

    found = False
    grams = int(scale.current_weight * 1000)
    
    for row in rows:
        if str(row.get('Order ID*', '')) == str(order_id):
            row['Weight(gm)'] = str(grams)
            found = True
            break
            
    if found:
        with open(ACTIVE_FILE, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return {"status": "success", "weight": grams}
    
    raise HTTPException(status_code=404, detail="Order not found")

@app.get("/export")
def export_file():
    return FileResponse(ACTIVE_FILE, filename="final_export.csv")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
