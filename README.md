# MT5 Monitor

ระบบติดตามบัญชี MetaTrader 5 แบบเรียลไทม์ — EA (`MT5_DataSender.mq5`) ส่งสถานะบัญชีเข้าสู่ API (FastAPI) เก็บลง **PostgreSQL (Supabase)** แล้วแสดงผลบน Dashboard เว็บ

```
MT5 Terminal ──(HTTP POST /api/data ทุก 60 วิ)──> FastAPI (Render) ──> Supabase Postgres
                                                        │
                                                        └──> Dashboard (HTML/JS)
```

---

## โครงสร้างโปรเจกต์

| ไฟล์ / โฟลเดอร์ | หน้าที่ |
|---|---|
| `server.py` | FastAPI app, startup/shutdown, background alert loop, `/health` |
| `database.py` | ค่า config จาก env, connection pool (asyncpg), schema + seed |
| `models.py` | Pydantic model ของ payload ที่ EA ส่งมา |
| `routers/data.py` | `POST /api/data` — รับข้อมูลจาก EA (ตรวจ secret key) |
| `routers/accounts.py` | รายการ account, latest, rename/toggle/delete |
| `routers/history.py` | ประวัติ, stats, all-time, P&L calendar |
| `routers/alerts.py` | ตั้งค่าแจ้งเตือน Telegram |
| `index.html`, `dashboard.html`, `tabs/`, `static/` | หน้าเว็บ |
| `MT5_DataSender.mq5` | EA ฝั่ง MT5 (คัดลอกไปที่ `MQL5/Experts/`) |
| `render.yaml` | ค่าอ้างอิงสำหรับ deploy บน Render |

> ฐานข้อมูลเป็น **PostgreSQL เท่านั้น** (เดิมเคยใช้ SQLite — เลิกใช้แล้ว)

---

## Environment Variables

| Key | จำเป็น | คำอธิบาย |
|---|---|---|
| `DATABASE_URL` | ✅ | Supabase connection string |
| `SECRET_KEY` | ✅ | รหัสที่ EA ต้องส่งมาให้ตรงกัน |
| `SECRET_KEY_OLD` | — | คีย์เก่าที่ยังรับได้ชั่วคราว (คั่นด้วย `,` ถ้ามีหลายตัว) ใช้ตอน rotate |
| `PYTHON_VERSION` | — | เช่น `3.11.9` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | ค่า fallback ของแจ้งเตือน (ปกติตั้งใน Dashboard แทน) |

สร้างไฟล์ `.env` สำหรับรันในเครื่อง (ถูก gitignore ไว้แล้ว):

```ini
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
SECRET_KEY=mysecretkey
```

### ค่า `DATABASE_URL` ของ Supabase

ใช้ **Session pooler** (port `5432`) จาก *Supabase → Project Settings → Database → Connection string*

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

- โค้ดจะตรวจจับ URL ที่มี `supabase.co`/`supabase.com` แล้วเปิด SSL + `statement_cache_size=0` ให้อัตโนมัติ (รองรับ PgBouncer)
- ถ้าใช้ **transaction pooler (6543)** ก็ทำงานได้ แต่ session pooler เสถียรกว่าสำหรับ `asyncpg`

---

## รันในเครื่อง (Windows)

```batch
pip install -r requirements.txt
python server.py
```

เปิด http://localhost:8000 — ตรวจสุขภาพระบบที่ http://localhost:8000/health

---

## ติดตั้ง EA

1. คัดลอก `MT5_DataSender.mq5` → `...\MetaQuotes\Terminal\[ID]\MQL5\Experts\`
2. Compile ใน MetaEditor
3. MT5 → Tools → Options → Expert Advisors:
   - ✅ Allow automated trading
   - ✅ Allow WebRequest for listed URL → เพิ่ม `https://mt5server-ar7z.onrender.com` (หรือ `http://127.0.0.1:8000` ถ้ารันในเครื่อง)
4. ลาก EA ลง Chart แล้วตั้งค่า:

| Parameter | ตัวอย่าง | คำอธิบาย |
|---|---|---|
| `InpServerURL` | `https://mt5server-ar7z.onrender.com/api/data` | ปลายทาง |
| `InpAccountAlias` | `BTC_216` | ชื่อบัญชีที่แสดงบน Dashboard (ต้องไม่ซ้ำ) |
| `InpSecretKey` | `mysecretkey` | ต้องตรงกับ `SECRET_KEY` บน server |
| `InpInitialBalance` | `4200.0` | ทุนเริ่มต้น |
| `InpTimerInterval` | `60` | ส่งทุกกี่วินาที |

> หลายบัญชี = ติด EA หลายตัว เปลี่ยนแค่ `InpAccountAlias`

---

## API Endpoints

| Method | URL | คำอธิบาย |
|---|---|---|
| POST | `/api/data` | รับข้อมูลจาก EA (ต้องมี `secret`) |
| GET | `/health` | ตรวจสถานะ server + DB (`503` ถ้า DB ล่ม) |
| GET | `/api/accounts` | รายชื่อ accounts |
| GET | `/api/latest` | ข้อมูลล่าสุดทุก account |
| GET | `/api/latest/{alias}` | ข้อมูลล่าสุด 1 account |
| PATCH | `/api/accounts/{alias}` | แก้ไข config account |
| PUT | `/api/accounts/{alias}/rename` | เปลี่ยนชื่อที่แสดง |
| PUT | `/api/accounts/{alias}/toggle` | เปิด/ปิด account |
| DELETE | `/api/accounts/{alias}` | ลบ account |
| GET | `/api/history/{alias}` | ข้อมูลย้อนหลัง (`?start=&end=&limit=`) |
| GET | `/api/stats/{alias}` | สถิติสรุป (`?days=7`) |
| GET | `/api/alltime` , `/api/alltime/{alias}` | สรุปผลรวมทั้งหมด |
| GET | `/api/pnl/calendar/{alias}` | P&L รายวัน (ปฏิทิน) |
| GET | `/api/realized-profits` | กำไรที่ปิดแล้ว |
| GET/POST | `/api/alerts/settings` | ตั้งค่า Telegram |
| POST | `/api/alerts/account` | เปิด/ปิดแจ้งเตือนราย account |
| POST | `/api/alerts/test` | ทดสอบส่งข้อความ |
| GET | `/api/alerts/status` | สถานะการแจ้งเตือน |

---

## Deploy บน Render

ค่าที่ใช้จริง (service ถูกสร้างด้วยมือ ไม่ได้ผูกกับ Blueprint):

| Setting | ค่า |
|---|---|
| Repository | `https://github.com/krulovedev/mt5server` (branch `main`, auto-deploy) |
| Runtime | Python 3.11.9 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn server:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |
| Plan / Region | free / oregon |

ตั้ง `DATABASE_URL` และ `SECRET_KEY` ใน **Dashboard → Environment**

### คำสั่งที่ใช้บ่อย (Render CLI)

```bash
render login
render workspace set tea-d8h31sjtqb8s739c4pp0
render services                                  # ดู service + ID
render deploys list srv-d99k3o28qa3s73d61fgg     # ประวัติ deploy
render deploys create srv-d99k3o28qa3s73d61fgg   # สั่ง deploy ใหม่
render logs --resources srv-d99k3o28qa3s73d61fgg --tail
```

---

## การเปลี่ยน `SECRET_KEY` (rotate) โดยไม่ให้ EA หลุด

1. ตั้ง `SECRET_KEY` = คีย์ใหม่ ใน Render → Environment
2. ตั้ง `SECRET_KEY_OLD` = `mysecretkey` (คีย์เดิม) — server จะรับทั้งสองคีย์
3. อัปเดต `InpSecretKey` ใน EA ให้เป็นคีย์ใหม่
4. เมื่อ EA ทุกตัวอัปเดตแล้ว → ลบ `SECRET_KEY_OLD` ออก

---

## Troubleshooting

| อาการ | สาเหตุ/วิธีแก้ |
|---|---|
| เว็บค้าง ไม่ตอบสนอง (timeout) นานผิดปกติ | Render free tier **sleep** หลังไม่มีคนใช้ ~15 นาที — request แรกจะปลุก 30–60 วิ (EA ที่ส่งทุก 60 วิช่วย keep-alive) |
| Deploy `Live` แต่เว็บไม่ขึ้น | ดู log: มักเป็น `Application startup failed` เพราะ `DATABASE_URL` ต่อไม่ได้ |
| `asyncpg ... (ENOTFOUND) tenant/user ... not found` | โปรเจกต์ Supabase ถูก **pause** (free tier) → restore ที่ Dashboard หรือ `POST /v1/projects/{ref}/restore` |
| `401 Unauthorized` จาก `/api/data` | `InpSecretKey` ใน EA ไม่ตรงกับ `SECRET_KEY` ของ server |
| `WebRequest not allowed` | ยังไม่ได้เพิ่ม URL ใน Allow WebRequest |
| ข้อมูลหายหลัง redeploy | ตรวจว่า `DATABASE_URL` ยังชี้ Supabase (ไม่ใช่ SQLite ในเครื่อง) |

---

## หมายเหตุ

- `snapshots` เก็บสูงสุด `MAX_HISTORY = 100000` แถวต่อ account (ลบเก่าอัตโนมัติเมื่อรับข้อมูลใหม่)
- Supabase free tier จะ pause ถ้าไม่มี activity ~7 วัน — EA ที่ส่งข้อมูลสม่ำเสมอป้องกันเรื่องนี้ได้
- อย่า commit `.env` หรือ `DATABASE_URL` ลง git
