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

### EA v2.0 — Dashboard บน chart + สถิติเพิ่มเติม

EA (ตั้งแต่ v2.00) รวมความสามารถของ `AccountDashboardPro` ไว้ในตัวเดียว จึง **ไม่ต้องติด indicator บน chart อีก** (ถ้าติดทั้งคู่จะเห็น Dashboard ซ้อนกัน)

| กลุ่ม | Input | ค่า | คำอธิบาย |
|---|---|---|---|
| Statistics | `InpUseStatsStartDate` | `false` | กำหนดวันเริ่มนับสถิติเอง |
| | `InpStatsStartDate` | `2024.01.01` | วันเริ่มนับ (broker time) |
| | `InpUseGlobalVars` | `true` | จำค่า DD ข้ามการรีสตาร์ท MT5 |
| | `InpFullResyncMinutes` | `360` | full resync history ทุกกี่นาที (`0`=ปิด) |
| | `InpSendExtended` | `true` | ส่งสถิติชุดใหม่ไป server |
| Dashboard | `InpShowDashboard` | `true` | แสดง Dashboard บน chart |
| | `InpCorner` / `InpBaseX` / `InpBaseY` | | ตำแหน่ง |
| | `InpLineSpacing` / `InpFontName` / `InpFontSize` | | รูปแบบตัวอักษร |
| | `InpDDAsPercent` / `InpShowDDTime` | | รูปแบบการแสดง DD |
| | `InpShowResetButton` | `true` | ปุ่ม Reset DD |

**Dashboard บน chart แสดง 11 บรรทัด:** Buy / Sell / Total (orders + lots), P/L Today / Week / Total, Max DD Today / Week / Total (floating) + lots + เวลา, Stats Since, สถานะการส่งล่าสุด + ปุ่ม Reset DD

### ฟิลด์ใหม่ที่ EA v2.0 ส่งไป server

| ฟิลด์ | ความหมาย |
|---|---|
| `pl_today` / `pl_week` / `pl_total` | กำไร = closed + floating |
| `closed_pl_today` / `closed_pl_week` / `closed_pl_total` | กำไรจาก deal ที่ปิดแล้ว |
| `vol_today` / `vol_week` / `vol_total` | volume ที่ใช้ผลิตกำไร (closed lots + lots ที่เปิด) |
| `dd_today` / `dd_week` / `dd_total` | Max drawdown จาก **floating loss** |
| `dd_*_at` / `dd_*_lots` | เวลาที่ DD สูงสุด / lots ที่เปิดตอนนั้น |
| `stats_start` | วันเริ่มนับสถิติ (`""` = all-time) |

> EA v1.5 ที่ยังไม่ิปเดตยังส่งข้อมูลได้ปกติ ฟิลด์ใหม่จะเป็น `NULL` (ระบบตรวจ `Optional` ไว้แล้ว)

### การแยกบัญชีจริง (Real) กับบัญชีทดลอง (Demo)

ระบบแยกข้อมูล 2 กลุ่มนี้ออกจากกัน**ทุกส่วน** (overview, สถิติ all-time, realized P/L, รายการ account, หน้าแจ้งเตือน)

| ชั้น | การทำงาน |
|---|---|
| EA v2.01 | ส่ง `account_type` = `real` / `demo` / `contest` (อ่านจาก `ACCOUNT_TRADE_MODE` ของ MT5) |
| DB | `accounts.account_type` และ `snapshots.account_type` (migration อัตโนมัติ) |
| API | ทุก endpoint ที่เป็นรายการรับ `?mode=real\|demo\|contest` (`all` หรือไม่ใส่ = ทั้งหมด) |
| UI | ปุ่มสลับ **🟢 จริง / 🟡 ทดลอง / ทั้งหมด** มุมขวาบน (จำค่าใน localStorage) + ป้าย REAL/DEMO บนการ์ด |

- บัญชีที่ยังไม่ทราบประเภท (EA เก่า) จะเป็น `unknown` และ **ไม่ถูกนับรวม** ในโหมดจริง/ทดลอง (กันข้อมูลปนกัน) — เห็นได้ในโหมด "ทั้งหมด"
- กำหนดประเภทเองได้ที่ **ตั้งค่า → ประเภทบัญชี** (`PATCH /api/accounts/{alias}` ด้วย `account_type`)
- ตั้ง **สีพื้นหลังแยกตามโหมด** ได้ที่ ตั้งค่า → 🎨 สีพื้นหลังตามโหมด (เก็บใน `localStorage` ฝั่งเบราว์เซอร์)

### ประสิทธิภาพ (ทำไมกินทรัพยากรน้อย)

- **Timer เดียว 1 วินาที** (เดิม indicator + EA ใช้ timer คนละตัว) — งานต่อวินาทีคือวนเฉพาะ positions ที่เปิดอยู่
- **History อ่านแบบ incremental** ด้วย watermark (deal time + ticket): 1 รอบส่งข้อมูลวนเฉพาะ deal ใหม่ ไม่วนทั้ง history
- **Full resync เป็นรอบ** (ค่าเริ่มต้นทุก 6 ชม.) กันข้อมูลคลาดเคลื่อนจากการโหลด history ย้อนหลัง
- **Bucket Today/Week** คำนวณใหม่เฉพาะตอนเปลี่ยนวัน/สัปดาห์
- **UI อัปเดตเมื่อข้อความเปลี่ยน** + `ChartRedraw()` เฉพาะตอนเปลี่ยน
- **GlobalVariable** เขียนเมื่อค่าเปลี่ยน (เดิมเขียน 10 ตัวทุกวินาที)
- ฝั่ง server ใช้ `warm_latest_cache()` เติม cache จาก snapshot ล่าสุดตอน startup → dashboard ไม่ว่างหลัง deploy


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
