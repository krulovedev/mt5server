from pydantic import BaseModel
from typing import Optional

class MT5DataPayload(BaseModel):
    secret:             str
    alias:              str
    account_number:     int
    broker:             str       = ""
    server:             str       = ""
    currency:           str       = "USD"
    leverage:           int       = 100
    balance:            float
    equity:             float
    margin:             float     = 0.0
    free_margin:        float     = 0.0
    margin_level:       float     = 0.0
    profit:             float     = 0.0
    credit:             float     = 0.0
    initial_balance:    float     = 10000.0
    drawdown_amount:    float     = 0.0
    drawdown_pct:       float     = 0.0
    equity_drawdown_pct: float    = 0.0
    open_orders:        int       = 0
    buy_orders:         int       = 0
    sell_orders:        int       = 0
    total_lots:         float     = 0.0
    buy_lots:           float     = 0.0
    sell_lots:          float     = 0.0
    withdrawal:         float     = 0.0
    net_deposit:        float     = 0.0
    timestamp:          str       = ""
    # ประเภทบัญชี: real | demo | contest | unknown (EA v2.01 ส่งมา)
    account_type:       Optional[str] = None

    # --- สถิติชุดใหม่ (EA v2.0 / AccountDashboardPro) ---
    # P/L = closed + floating (ตามมุมมองของ EA)
    pl_today:           Optional[float] = None
    pl_week:            Optional[float] = None
    pl_total:           Optional[float] = None
    closed_pl_today:    Optional[float] = None
    closed_pl_week:     Optional[float] = None
    closed_pl_total:    Optional[float] = None
    # volume ที่ใช้ผลิต P/L (closed lots + lots ที่เปิดอยู่)
    vol_today:          Optional[float] = None
    vol_week:           Optional[float] = None
    vol_total:          Optional[float] = None
    # Max drawdown จาก floating loss (ไม่ใช่ balance DD)
    dd_today:           Optional[float] = None
    dd_today_at:        Optional[str]   = None
    dd_today_lots:      Optional[float] = None
    dd_week:            Optional[float] = None
    dd_week_at:         Optional[str]   = None
    dd_week_lots:       Optional[float] = None
    dd_total:           Optional[float] = None
    dd_total_at:        Optional[str]   = None
    dd_total_lots:      Optional[float] = None
    stats_start:        Optional[str]   = None

class AccountConfig(BaseModel):
    alias:           str
    initial_balance: float = 10000.0
    note:            str   = ""
    account_type:    Optional[str] = None   # กำหนดเองได้: real | demo | contest

class AccountRename(BaseModel):
    display_name: str

class AlertSettingsPayload(BaseModel):
    global_enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""

class AccountAlertPayload(BaseModel):
    alias: str
    enabled: bool
