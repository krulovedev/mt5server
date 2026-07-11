# MT5 Monitor - คู่มือติดตั้ง (Windows)

## โครงสร้างไฟล์

```
mt5-monitor/
├── server.py          ← Python Server (FastAPI)
├── dashboard.html     ← หน้า Dashboard
├── start_server.bat   ← สคริปต์เปิด Server
└── mt5_monitor.db     ← ฐานข้อมูล SQLite (สร้างอัตโนมัติ)

MT5 Terminal/MQL5/Experts/
└── MT5_DataSender.mq5 ← EA สำหรับส่งข้อมูล
```

---

## STEP 1: ติดตั้ง Python และ Dependencies

```batch
:: ติดตั้ง Python 3.10+ จาก https://python.org

:: ติดตั้ง packages
pip install fastapi uvicorn aiosqlite pydantic
```

---

## STEP 2: สร้างไฟล์ start_server.bat

สร้างไฟล์ `start_server.bat` ไว้ที่โฟลเดอร์เดียวกับ server.py:

```batch
@echo off
cd /d %~dp0
echo Starting MT5 Monitor Server...
python server.py
pause
```

---

## STEP 3: ติดตั้ง MT5 EA

1. คัดลอก `MT5_DataSender.mq5` ไปยัง:
   `C:\Users\[ชื่อ User]\AppData\Roaming\MetaQuotes\Terminal\[ID]\MQL5\Experts\`

2. เปิด MetaEditor → Compile EA

3. เปิด Tools > Options > Expert Advisors:
   - ✅ Allow automated trading
   - ✅ Allow WebRequest for listed URL
   - เพิ่ม: `http://127.0.0.1:8000`  (หรือ IP Server)

---

## STEP 4: ติด EA บน Chart

กดลาก `MT5_DataSender` ลงบน Chart แล้วตั้งค่า:

| Parameter        | ค่า                                    | คำอธิบาย                |
|------------------|----------------------------------------|------------------------|
| ServerURL        | `http://127.0.0.1:8000/api/data`       | URL Server             |
| AccountAlias     | `MyAccount_01`                         | ชื่อที่แสดงใน Dashboard |
| InitialBalance   | `10000.0`                              | ทุนเริ่มต้น (USD)       |
| SendInterval     | `60`                                   | ส่งทุก 60 วินาที        |
| SecretKey        | `mysecretkey`                          | ต้องตรงกับ server.py   |

> ⚠️ ถ้ามี MT5 หลาย account ให้เปลี่ยน **AccountAlias** ให้ต่างกัน

---

## STEP 5: เปิด Server

ดับเบิลคลิก `start_server.bat`  
หรือรัน: `python server.py`

เปิด Dashboard: [http://localhost:8000](http://localhost:8000)

---

## การตั้งค่า Secret Key (สำคัญมาก)

แก้ค่า `SECRET_KEY` ใน `server.py` ให้ตรงกับ MQL5 EA:

```python
SECRET_KEY = "your_unique_secret_here"   # เปลี่ยนค่านี้
```

---

## ใช้ Server กับ MT5 หลาย Account

แต่ละ MT5 account ติด EA 1 ตัว เปลี่ยนแค่:
- **AccountAlias** → ชื่อที่ไม่ซ้ำกัน เช่น `Prop_01`, `Live_USD`, `Demo_Test`
- **InitialBalance** → ทุนเริ่มต้นของแต่ละ account

Server รองรับได้ไม่จำกัด account โดยอัตโนมัติ

---

## API Endpoints

| Method | URL                              | คำอธิบาย                      |
|--------|----------------------------------|-------------------------------|
| POST   | `/api/data`                      | รับข้อมูลจาก EA               |
| GET    | `/api/latest`                    | ข้อมูลล่าสุดทุก account       |
| GET    | `/api/latest/{alias}`            | ข้อมูลล่าสุด 1 account        |
| GET    | `/api/history/{alias}`           | ข้อมูลย้อนหลัง                |
| GET    | `/api/stats/{alias}?days=7`      | สถิติสรุป                     |
| GET    | `/api/accounts`                  | รายชื่อ accounts               |
| PATCH  | `/api/accounts/{alias}`          | แก้ไข config account          |

### ตัวอย่าง Query ย้อนหลัง
```
/api/history/MyAccount_01?start=2025-01-01T00:00:00&end=2025-01-31T23:59:59&limit=5000
```

---

## เพิ่มประสิทธิภาพ (Production)

### ใช้ Windows Service (เปิดอัตโนมัติตอน Boot)

```batch
pip install pywin32
python -c "import win32serviceutil"
```

หรือใช้ NSSM (Non-Sucking Service Manager):
```batch
nssm install MT5Monitor python "C:\mt5-monitor\server.py"
nssm set MT5Monitor AppDirectory "C:\mt5-monitor"
nssm start MT5Monitor
```

### Firewall (ถ้า MT5 อยู่เครื่องอื่น)
```batch
netsh advfirewall firewall add rule name="MT5Monitor" dir=in action=allow protocol=TCP localport=8000
```

---

## Performance

- EA ใช้ **EventSetTimer** (ไม่ใช้ OnTick) → CPU ต่ำมาก
- Server ใช้ **async/await + SQLite WAL mode** → RAM ~30MB
- Dashboard **polling ทุก 30 วินาที** (ปรับได้)
ailscale funnel --bg localhost:3000# mt5server
# mt5server
# mt5server
