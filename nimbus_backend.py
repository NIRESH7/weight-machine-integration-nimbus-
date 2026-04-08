import os
import re
import csv
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# Setup - Pathing is now relative to facilitate AWS/Linux hosting
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIVE_FILE = os.path.join(BASE_DIR, "active_report.csv")

app = FastAPI(title="Nimbus Cloud Backend (API-Only)")

# CORS Fix for Browser/Web/Mobile
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/")
def health_check():
    return {"status": "online", "mode": "cloud-api"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Save the file to the current directory
    content = await file.read()
    with open(ACTIVE_FILE, "wb") as f:
        f.write(content)
    
    # Process LBH Logic and clear weights
    rows = []
    try:
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
            
        return {"status": "success", "filename": file.filename, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV Error: {str(e)}")

@app.get("/products")
def get_products():
    if not os.path.exists(ACTIVE_FILE):
        return []
    with open(ACTIVE_FILE, mode='r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

@app.post("/capture/{order_id}")
def capture_weight(order_id: str, manual_weight: str = None):
    """
    In Cloud Mode, the weight is sent directly from the Mobile App.
    Mobile app sends the weight value in 'manual_weight'.
    """
    if not os.path.exists(ACTIVE_FILE):
        raise HTTPException(status_code=404, detail="No file active")
    
    if not manual_weight:
        raise HTTPException(status_code=400, detail="Weight value is required from mobile")

    rows = []
    with open(ACTIVE_FILE, mode='r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        
    if not rows:
        raise HTTPException(status_code=404, detail="CSV is empty")
        
    fieldnames = rows[0].keys()
    found = False
    
    for row in rows:
        if str(row.get('Order ID*', '')) == str(order_id):
            row['Weight(gm)'] = str(manual_weight)
            found = True
            break
            
    if found:
        with open(ACTIVE_FILE, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return {"status": "success", "weight": manual_weight}
    
    raise HTTPException(status_code=404, detail=f"Order ID {order_id} not found")

@app.get("/export")
def export_file():
    if not os.path.exists(ACTIVE_FILE):
        raise HTTPException(status_code=404, detail="Nothing to export")
    return FileResponse(ACTIVE_FILE, filename="final_export.csv")

if __name__ == "__main__":
    # AWS typically uses port 8000 or 80. 0.0.0.0 is required to be reachable from the internet.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
