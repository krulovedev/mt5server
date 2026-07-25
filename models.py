from pydantic import BaseModel

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
    timestamp:          str       = ""

class AccountConfig(BaseModel):
    alias:           str
    initial_balance: float = 10000.0
    note:            str   = ""

class AccountRename(BaseModel):
    display_name: str

class AlertSettingsPayload(BaseModel):
    global_enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""

class AccountAlertPayload(BaseModel):
    alias: str
    enabled: bool
