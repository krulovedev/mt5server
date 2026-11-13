//+------------------------------------------------------------------+
//|                                              MT5_DataSender.mq5  |
//|                                      Copyright 2026, MT5Monitor  |
//|                                                                  |
//|  v2.00 - รวม AccountDashboardPro (dashboard บน chart) เข้ากับ EA   |
//|          ที่ส่งข้อมูลเข้าสู่ server และเพิ่มสถิติชุดใหม่            |
//|                                                                  |
//|  หลักการออกแบบเพื่อใช้ทรัพยากรน้อยที่สุด:                          |
//|   - Timer เดียว (1 วินาที) แทน timer 2 ตัว                          |
//|   - OnTimer ไม่แตะ history ทุกวินาที: คำนวณเฉพาะ positions (ถูกมาก)  |
//|   - History อ่านแบบ incremental ด้วย watermark (deal time + ticket) |
//|     + full resync เป็นรอบ (ค่าตั้งต้น 6 ชม.)                        |
//|   - Bucket Today/Week คำนวณใหม่เฉพาะตอนเปลี่ยนวัน/สัปดาห์           |
//|   - Label อัปเดตเมื่อข้อความเปลี่ยนเท่านั้น + ChartRedraw เฉพาะตอนเปลี่ยน |
//|   - GlobalVariable เขียนเมื่อค่าเปลี่ยนเท่านั้น                       |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MT5Monitor"
#property link      ""
#property version   "2.00"

#define DASH_LINES   11
#define GV_PREFIX    "MT5DS_"

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Server ==="
input string   InpServerURL      = "http://127.0.0.1:8000/api/data"; // Server URL
input string   InpAccountAlias   = "MyAccount_01";                   // Account Alias
input string   InpSecretKey      = "mysecretkey";                    // Secret Key
input double   InpInitialBalance = 10000.0;                          // ทุนเริ่มต้น (Initial Balance)
input int      InpTimerInterval  = 60;                               // ส่งข้อมูลทุกๆ (วินาที)

input group "=== Statistics ==="
input bool     InpUseStatsStartDate = false;                          // กำหนดวันเริ่มนับสถิติเอง
input datetime InpStatsStartDate    = D'2024.01.01 00:00:00';         // วันเริ่มนับ (broker time)
input bool     InpUseGlobalVars     = true;                           // จำค่า DD ข้ามการรีสตาร์ท MT5
input int      InpFullResyncMinutes = 360;                            // Full resync history ทุก (นาที, 0=ปิด)
input bool     InpSendExtended      = true;                           // ส่งสถิติชุดใหม่ไป server ด้วย

input group "=== Dashboard บน Chart ==="
input bool                InpShowDashboard  = true;             // แสดง Dashboard
input ENUM_BASE_CORNER    InpCorner         = CORNER_LEFT_UPPER; // มุมที่แสดง
input int                 InpBaseX          = 20;               // ระยะห่างจากขอบ X
input int                 InpBaseY          = 30;               // ระยะห่างจากขอบ Y
input int                 InpLineSpacing    = 18;               // ระยะห่างระหว่างบรรทัด
input string              InpFontName       = "Consolas";       // ฟอนต์
input int                 InpFontSize       = 10;               // ขนาดฟอนต์
input bool                InpDDAsPercent    = false;            // แสดง DD เป็น %
input bool                InpShowDDTime     = true;             // แสดงเวลาที่ DD สูงสุด
input bool                InpShowResetButton= true;             // แสดงปุ่ม Reset DD

//+------------------------------------------------------------------+
//| Structures / state                                               |
//+------------------------------------------------------------------+
struct DDState
  {
   double            maxDD;
   datetime          when;
   double            lots;
  };

DDState  g_ddToday, g_ddWeek, g_ddTotal;

//--- live position state
int      g_buyCount   = 0;
int      g_sellCount  = 0;
double   g_buyLots    = 0.0;
double   g_sellLots   = 0.0;
double   g_totalLots  = 0.0;
double   g_floatPL    = 0.0;   // ผลรวม floating (profit + swap) ของ positions
double   g_floatLoss  = 0.0;   // >= 0 คือกำลังขาดทุน

//--- history aggregates
double   g_closedPLTotal = 0.0;
double   g_closedVolTotal= 0.0;
double   g_closedPLToday = 0.0;
double   g_closedVolToday= 0.0;
double   g_closedPLWeek  = 0.0;
double   g_closedVolWeek = 0.0;
double   g_depositTotal  = 0.0;
double   g_withdrawalTotal = 0.0;

datetime g_lastDealTime  = 0;
ulong    g_lastDealTicket= 0;
datetime g_lastFullSync  = 0;

//--- scheduling / housekeeping
datetime g_statsStart     = 0;
datetime g_lastCheck      = 0;
uint     g_lastSendMs     = 0;
bool     g_gvDirty        = false;
uint     g_lastErrorMs    = 0;
string   g_sendStatus     = "waiting";

//--- dashboard objects
bool     g_dashReady   = false;
string   g_objPrefix   = "";
string   g_btnReset    = "";
string   g_labelName[DASH_LINES];
string   g_labelText[DASH_LINES];
color    g_labelColor[DASH_LINES];

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
string IsoTime(datetime t)
  {
   if(t <= 0)
      return("");
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return(StringFormat("%04d-%02d-%02dT%02d:%02d:%02d", dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec));
  }

datetime DayStartOf(datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return(StructToTime(dt));
  }

datetime WeekStartOf(datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   int back = (dt.day_of_week == 0) ? 6 : (dt.day_of_week - 1);   // จันทร์ = เริ่มสัปดาห์
   datetime ws = t - (datetime)(back * 86400);
   return(DayStartOf(ws));
  }

//+------------------------------------------------------------------+
//| Global variable persistence                                      |
//+------------------------------------------------------------------+
string GvKey(string suffix) { return(GV_PREFIX + (string)AccountInfoInteger(ACCOUNT_LOGIN) + "_" + suffix); }

void LoadState()
  {
   if(!InpUseGlobalVars)
      return;

   // ถ้าผู้ใช้เปลี่ยนวันเริ่มนับ → ไม่โหลดยอด DD Total เดิม (เหมือน indicator เดิม)
   bool statsStartChanged = false;
   if(GlobalVariableCheck(GvKey("statsStart")))
     {
      datetime savedStart = (datetime)GlobalVariableGet(GvKey("statsStart"));
      statsStartChanged = (savedStart != g_statsStart);
      if(statsStartChanged)
         Print("MT5_DataSender: Statistics start date changed - Total Max DD reset.");
     }

   if(GlobalVariableCheck(GvKey("ddToday_max")))
     {
      g_ddToday.maxDD = GlobalVariableGet(GvKey("ddToday_max"));
      g_ddToday.when  = (datetime)GlobalVariableGet(GvKey("ddToday_time"));
      g_ddToday.lots  = GlobalVariableGet(GvKey("ddToday_lots"));
     }
   if(GlobalVariableCheck(GvKey("ddWeek_max")))
     {
      g_ddWeek.maxDD = GlobalVariableGet(GvKey("ddWeek_max"));
      g_ddWeek.when  = (datetime)GlobalVariableGet(GvKey("ddWeek_time"));
      g_ddWeek.lots  = GlobalVariableGet(GvKey("ddWeek_lots"));
     }
   if(!statsStartChanged && GlobalVariableCheck(GvKey("ddTotal_max")))
     {
      g_ddTotal.maxDD = GlobalVariableGet(GvKey("ddTotal_max"));
      g_ddTotal.when  = (datetime)GlobalVariableGet(GvKey("ddTotal_time"));
      g_ddTotal.lots  = GlobalVariableGet(GvKey("ddTotal_lots"));
     }
   if(GlobalVariableCheck(GvKey("lastCheck")))
      g_lastCheck = (datetime)GlobalVariableGet(GvKey("lastCheck"));
  }

void SaveState()
  {
   if(!InpUseGlobalVars || !g_gvDirty)
      return;

   GlobalVariableSet(GvKey("ddToday_max"),  g_ddToday.maxDD);
   GlobalVariableSet(GvKey("ddToday_time"), (double)g_ddToday.when);
   GlobalVariableSet(GvKey("ddToday_lots"), g_ddToday.lots);
   GlobalVariableSet(GvKey("ddWeek_max"),   g_ddWeek.maxDD);
   GlobalVariableSet(GvKey("ddWeek_time"),  (double)g_ddWeek.when);
   GlobalVariableSet(GvKey("ddWeek_lots"),  g_ddWeek.lots);
   GlobalVariableSet(GvKey("ddTotal_max"),  g_ddTotal.maxDD);
   GlobalVariableSet(GvKey("ddTotal_time"), (double)g_ddTotal.when);
   GlobalVariableSet(GvKey("ddTotal_lots"), g_ddTotal.lots);
   GlobalVariableSet(GvKey("lastCheck"),    (double)g_lastCheck);
   GlobalVariableSet(GvKey("statsStart"),   (double)g_statsStart);

   g_gvDirty = false;
  }

void ResetAllDD()
  {
   datetime now = TimeCurrent();
   g_ddToday.maxDD = 0.0; g_ddToday.when = now; g_ddToday.lots = 0.0;
   g_ddWeek.maxDD  = 0.0; g_ddWeek.when  = now; g_ddWeek.lots  = 0.0;
   g_ddTotal.maxDD = 0.0; g_ddTotal.when = now; g_ddTotal.lots = 0.0;
   g_gvDirty = true;
   SaveState();
   RefreshLabels(TimeCurrent(), true);
  }

//+------------------------------------------------------------------+
//| History aggregation                                              |
//+------------------------------------------------------------------+
// คำนวณ P/L + volume ของ deal ที่ปิดสถานะ ในช่วงเวลาที่กำหนด (HistorySelect ครั้งเดียว)
// ไม่แตะยอดฝาก/ถอน เพื่อไม่ให้นับซ้ำกับ SyncHistory
bool CalcClosedStats(datetime from, datetime to, double &pl, double &vol)
  {
   pl  = 0.0;
   vol = 0.0;
   if(!HistorySelect(from, to))
      return(false);

   int deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;

      long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY)
         continue;

      pl += HistoryDealGetDouble(ticket, DEAL_PROFIT)
            + HistoryDealGetDouble(ticket, DEAL_SWAP)
            + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
            + HistoryDealGetDouble(ticket, DEAL_FEE);
      vol += HistoryDealGetDouble(ticket, DEAL_VOLUME);
     }
   return(true);
  }

// คำนวณ bucket Today หรือ Week ใหม่ทั้งก้อน (เรียกเฉพาะตอนเปลี่ยนวัน/สัปดาห์)
void RecalcBucket(int which /*0=today,1=week*/)
  {
   datetime now  = TimeCurrent();
   datetime from = (which == 0) ? DayStartOf(now) : WeekStartOf(now);
   double pl = 0.0, vol = 0.0;
   if(!CalcClosedStats(from, now, pl, vol))
      return;

   if(which == 0) { g_closedPLToday = pl; g_closedVolToday = vol; }
   else           { g_closedPLWeek  = pl; g_closedVolWeek  = vol; }
  }

// full = อ่านทั้งหมดใหม่ตั้งแต่ stats start (ใช้ตอน init / resync เป็นรอบ)
// incremental = อ่านเฉพาะ deal ใหม่ต่อจาก watermark
void SyncHistory(bool full)
  {
   datetime now = TimeCurrent();
   datetime from = full ? g_statsStart : (g_lastDealTime > 0 ? g_lastDealTime : g_statsStart);

   if(full)
     {
      g_closedPLTotal  = 0.0;
      g_closedVolTotal = 0.0;
      g_depositTotal   = 0.0;
      g_withdrawalTotal= 0.0;
      g_lastDealTime   = 0;
      g_lastDealTicket = 0;
     }

   if(!HistorySelect(from, now))
     {
      if(full) { g_lastFullSync = now; }
      return;
     }

   int deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;

      datetime dt = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      if(!full)
        {
         if(dt < g_lastDealTime) continue;
         if(dt == g_lastDealTime && ticket <= g_lastDealTicket) continue;
        }

      long type = HistoryDealGetInteger(ticket, DEAL_TYPE);
      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);

      if(type == DEAL_TYPE_BALANCE)
        {
         if(profit > 0.0)      g_depositTotal    += profit;
         else if(profit < 0.0) g_withdrawalTotal += -profit;
        }
      else
        {
         long entry = HistoryDealGetInteger(ticket, DEAL_ENTRY);
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
           {
            g_closedPLTotal += profit
                               + HistoryDealGetDouble(ticket, DEAL_SWAP)
                               + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
                               + HistoryDealGetDouble(ticket, DEAL_FEE);
            g_closedVolTotal += HistoryDealGetDouble(ticket, DEAL_VOLUME);
           }
        }

      if(dt > g_lastDealTime)
        { g_lastDealTime = dt; g_lastDealTicket = ticket; }
      else if(dt == g_lastDealTime && ticket > g_lastDealTicket)
         g_lastDealTicket = ticket;
     }

   if(full)
     {
      g_lastFullSync = now;
      RecalcBucket(0);
      RecalcBucket(1);
     }
  }

//+------------------------------------------------------------------+
//| Live positions (ถูกมาก: วนเฉพาะ positions ที่เปิดอยู่)              |
//+------------------------------------------------------------------+
void UpdatePositions()
  {
   g_buyCount = 0; g_sellCount = 0;
   g_buyLots  = 0.0; g_sellLots = 0.0;
   g_floatPL  = 0.0;

   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      double vol = PositionGetDouble(POSITION_VOLUME);
      g_floatPL += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);

      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
        { g_buyCount++; g_buyLots += vol; }
      else
        { g_sellCount++; g_sellLots += vol; }
     }

   g_totalLots  = g_buyLots + g_sellLots;
   g_floatLoss  = (g_floatPL < 0.0) ? MathAbs(g_floatPL) : 0.0;
  }

//+------------------------------------------------------------------+
//| DD tracking                                                      |
//+------------------------------------------------------------------+
void UpdateDDState(datetime now, bool statsStarted)
  {
   bool changed = false;

   if(g_floatLoss > g_ddToday.maxDD)
     { g_ddToday.maxDD = g_floatLoss; g_ddToday.when = now; g_ddToday.lots = g_totalLots; changed = true; }

   if(g_floatLoss > g_ddWeek.maxDD)
     { g_ddWeek.maxDD = g_floatLoss; g_ddWeek.when = now; g_ddWeek.lots = g_totalLots; changed = true; }

   if(statsStarted && g_floatLoss > g_ddTotal.maxDD)
     { g_ddTotal.maxDD = g_floatLoss; g_ddTotal.when = now; g_ddTotal.lots = g_totalLots; changed = true; }

   if(changed)
      g_gvDirty = true;
  }

//+------------------------------------------------------------------+
//| Rollover (วัน/สัปดาห์ใหม่)                                         |
//+------------------------------------------------------------------+
void HandleRollover(datetime now)
  {
   if(g_lastCheck <= 0)
     {
      g_lastCheck = now;
      return;
     }

   MqlDateTime a, b;
   TimeToStruct(g_lastCheck, a);
   TimeToStruct(now, b);

   bool newDay  = (a.day != b.day || a.mon != b.mon || a.year != b.year);
   bool newWeek = (WeekStartOf(g_lastCheck) != WeekStartOf(now));

   if(newDay)
     {
      g_ddToday.maxDD = 0.0; g_ddToday.when = now; g_ddToday.lots = 0.0;
      RecalcBucket(0);
      g_gvDirty = true;
     }
   if(newWeek)
     {
      g_ddWeek.maxDD = 0.0; g_ddWeek.when = now; g_ddWeek.lots = 0.0;
      RecalcBucket(1);
      g_gvDirty = true;
     }

   g_lastCheck = now;
  }

//+------------------------------------------------------------------+
//| Dashboard objects                                                |
//+------------------------------------------------------------------+
void SetupDashboard()
  {
   if(!InpShowDashboard)
      return;

   g_objPrefix = "MT5DS_" + (string)ChartID() + "_";
   g_btnReset  = g_objPrefix + "BtnReset";

   g_labelName[0]  = g_objPrefix + "Buy";
   g_labelName[1]  = g_objPrefix + "Sell";
   g_labelName[2]  = g_objPrefix + "Total";
   g_labelName[3]  = g_objPrefix + "ProfToday";
   g_labelName[4]  = g_objPrefix + "ProfWeek";
   g_labelName[5]  = g_objPrefix + "ProfTotal";
   g_labelName[6]  = g_objPrefix + "DDToday";
   g_labelName[7]  = g_objPrefix + "DDWeek";
   g_labelName[8]  = g_objPrefix + "DDTotal";
   g_labelName[9]  = g_objPrefix + "StatsSince";
   g_labelName[10] = g_objPrefix + "SendStatus";

   g_labelColor[0]  = clrLime;
   g_labelColor[1]  = clrTomato;
   g_labelColor[2]  = clrGold;
   g_labelColor[3]  = clrAqua;
   g_labelColor[4]  = clrOrange;
   g_labelColor[5]  = clrWhite;
   g_labelColor[6]  = clrMagenta;
   g_labelColor[7]  = clrMediumPurple;
   g_labelColor[8]  = clrBrown;
   g_labelColor[9]  = clrSilver;
   g_labelColor[10] = clrGray;

   for(int i = 0; i < DASH_LINES; i++)
     {
      g_labelText[i] = "";
      ObjectDelete(0, g_labelName[i]);
      if(!ObjectCreate(0, g_labelName[i], OBJ_LABEL, 0, 0, 0))
        {
         Print("MT5_DataSender: cannot create label ", g_labelName[i], " err=", GetLastError());
         continue;
        }
      ObjectSetInteger(0, g_labelName[i], OBJPROP_CORNER,     InpCorner);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_XDISTANCE,  InpBaseX);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_YDISTANCE,  InpBaseY + i * InpLineSpacing);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_COLOR,      g_labelColor[i]);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_FONTSIZE,   InpFontSize);
      ObjectSetString (0, g_labelName[i], OBJPROP_FONT,       InpFontName);
      ObjectSetString (0, g_labelName[i], OBJPROP_TEXT,       "");
      ObjectSetInteger(0, g_labelName[i], OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_HIDDEN,     true);
      ObjectSetInteger(0, g_labelName[i], OBJPROP_ZORDER,     100);
     }

   if(InpShowResetButton)
     {
      ObjectDelete(0, g_btnReset);
      if(ObjectCreate(0, g_btnReset, OBJ_BUTTON, 0, 0, 0))
        {
         ObjectSetInteger(0, g_btnReset, OBJPROP_CORNER,     InpCorner);
         ObjectSetInteger(0, g_btnReset, OBJPROP_XDISTANCE,  InpBaseX);
         ObjectSetInteger(0, g_btnReset, OBJPROP_YDISTANCE,  InpBaseY + DASH_LINES * InpLineSpacing + 6);
         ObjectSetInteger(0, g_btnReset, OBJPROP_XSIZE,      90);
         ObjectSetInteger(0, g_btnReset, OBJPROP_YSIZE,      20);
         ObjectSetString (0, g_btnReset, OBJPROP_TEXT,       "Reset DD");
         ObjectSetString (0, g_btnReset, OBJPROP_FONT,       InpFontName);
         ObjectSetInteger(0, g_btnReset, OBJPROP_FONTSIZE,   9);
         ObjectSetInteger(0, g_btnReset, OBJPROP_COLOR,      clrWhite);
         ObjectSetInteger(0, g_btnReset, OBJPROP_BGCOLOR,    clrFireBrick);
         ObjectSetInteger(0, g_btnReset, OBJPROP_BORDER_COLOR, clrBlack);
         ObjectSetInteger(0, g_btnReset, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, g_btnReset, OBJPROP_STATE,      false);
         ObjectSetInteger(0, g_btnReset, OBJPROP_HIDDEN,     true);
         ObjectSetInteger(0, g_btnReset, OBJPROP_ZORDER,     100);
        }
     }

   g_dashReady = true;
  }

void DestroyDashboard()
  {
   for(int i = 0; i < DASH_LINES; i++)
      ObjectDelete(0, g_labelName[i]);
   ObjectDelete(0, g_btnReset);
   g_dashReady = false;
  }

// อัปเดตเฉพาะ label ที่ข้อความเปลี่ยน (force=true เพื่อบังคับวาดใหม่)
void RefreshLabels(datetime now, bool force)
  {
   if(!g_dashReady)
      return;

   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   bool   statsStarted = (now >= g_statsStart);
   double todayPL  = g_closedPLToday + g_floatPL;
   double weekPL   = g_closedPLWeek  + g_floatPL;
   double totalPL  = g_closedPLTotal + g_floatPL;
   double todayVol = g_closedVolToday + g_totalLots;
   double weekVol  = g_closedVolWeek  + g_totalLots;
   double totalVol = g_closedVolTotal + g_totalLots;

   string t[DASH_LINES];
   t[0]  = StringFormat("Buy:   %d orders | Lots: %.2f", g_buyCount,  g_buyLots);
   t[1]  = StringFormat("Sell:  %d orders | Lots: %.2f", g_sellCount, g_sellLots);
   t[2]  = StringFormat("Total: %d orders | Lots: %.2f", g_buyCount + g_sellCount, g_totalLots);
   t[3]  = StringFormat("Today:  %+.2f %s | Lots: %.2f", todayPL, cur, todayVol);
   t[4]  = StringFormat("Week:   %+.2f %s | Lots: %.2f", weekPL,  cur, weekVol);
   t[5]  = StringFormat("Total:  %+.2f %s | Lots: %.2f", totalPL, cur, totalVol);
   t[6]  = FormatDD(g_ddToday, "DD Today");
   t[7]  = FormatDD(g_ddWeek,  "DD Week");
   t[8]  = FormatDD(g_ddTotal, "DD Total");

   if(InpUseStatsStartDate)
      t[9] = statsStarted
             ? ("Stats Since: " + IsoTime(g_statsStart))
             : ("Stats Start: " + IsoTime(g_statsStart) + " (not reached)");
   else
      t[9] = "Stats Since: All-Time";

   t[10] = "Sent: " + g_sendStatus;

   bool changed = false;
   for(int i = 0; i < DASH_LINES; i++)
     {
      if(!force && t[i] == g_labelText[i])
         continue;
      if(ObjectSetString(0, g_labelName[i], OBJPROP_TEXT, t[i]))
        {
         g_labelText[i] = t[i];
         changed = true;
        }
     }

   if(changed)
      ChartRedraw(0);
  }

string FormatDD(const DDState &rec, string label)
  {
   string out = label + ": ";
   if(InpDDAsPercent)
     {
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      if(bal < 0.01) bal = 1.0;
      out += StringFormat("%.2f%%", (rec.maxDD / bal) * 100.0);
     }
   else
      out += StringFormat("%.2f %s", rec.maxDD, AccountInfoString(ACCOUNT_CURRENCY));

   out += StringFormat(" | Lots: %.2f", rec.lots);

   if(InpShowDDTime)
     {
      MqlDateTime dt;
      TimeToStruct(rec.when, dt);
      out += StringFormat(" [%02d.%02d.%02d %02d:%02d]", dt.year % 100, dt.mon, dt.day, dt.hour, dt.min);
     }
   return(out);
  }

//+------------------------------------------------------------------+
//| ส่งข้อมูลไป server                                                |
//+------------------------------------------------------------------+
void SendAccountData()
  {
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      g_sendStatus = "offline";
      return;
     }

   long   accountNumber = AccountInfoInteger(ACCOUNT_LOGIN);
   string broker        = AccountInfoString(ACCOUNT_COMPANY);
   string server        = AccountInfoString(ACCOUNT_SERVER);
   string currency      = AccountInfoString(ACCOUNT_CURRENCY);
   long   leverage      = AccountInfoInteger(ACCOUNT_LEVERAGE);

   double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
   double margin      = AccountInfoDouble(ACCOUNT_MARGIN);
   double freeMargin  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   double profit      = AccountInfoDouble(ACCOUNT_PROFIT);
   double credit      = AccountInfoDouble(ACCOUNT_CREDIT);

   // Drawdown จากยอด balance เทียบ peak (เหมือน EA เดิม)
   double peak       = MathMax(InpInitialBalance, balance);
   double ddAmount   = 0.0;
   double ddPct      = 0.0;
   if(peak > balance)
     {
      ddAmount = peak - balance;
      ddPct    = (ddAmount / peak) * 100.0;
     }

   double eqDDPct = 0.0;
   if(balance > 0.0 && equity < balance)
      eqDDPct = ((balance - equity) / balance) * 100.0;

   string alias  = InpAccountAlias;
   string brokerE = broker, serverE = server, currencyE = currency, aliasE = alias;
   StringReplace(brokerE,   "\"", "'");
   StringReplace(serverE,   "\"", "'");
   StringReplace(currencyE, "\"", "'");
   StringReplace(aliasE,    "\"", "'");

   datetime now = TimeCurrent();

   string s;
   StringReserve(s, 1600);
   s += "{";
   s += "\"secret\":\"" + InpSecretKey + "\",";
   s += "\"alias\":\"" + aliasE + "\",";
   s += "\"account_number\":" + (string)accountNumber + ",";
   s += "\"broker\":\"" + brokerE + "\",";
   s += "\"server\":\"" + serverE + "\",";
   s += "\"currency\":\"" + currencyE + "\",";
   s += "\"leverage\":" + (string)leverage + ",";
   s += "\"balance\":" + DoubleToString(balance, 2) + ",";
   s += "\"equity\":" + DoubleToString(equity, 2) + ",";
   s += "\"margin\":" + DoubleToString(margin, 2) + ",";
   s += "\"free_margin\":" + DoubleToString(freeMargin, 2) + ",";
   s += "\"margin_level\":" + DoubleToString(marginLevel, 2) + ",";
   s += "\"profit\":" + DoubleToString(profit, 2) + ",";
   s += "\"credit\":" + DoubleToString(credit, 2) + ",";
   s += "\"initial_balance\":" + DoubleToString(InpInitialBalance, 2) + ",";
   s += "\"drawdown_amount\":" + DoubleToString(ddAmount, 2) + ",";
   s += "\"drawdown_pct\":" + DoubleToString(ddPct, 4) + ",";
   s += "\"equity_drawdown_pct\":" + DoubleToString(eqDDPct, 4) + ",";
   s += "\"open_orders\":" + (string)(g_buyCount + g_sellCount) + ",";
   s += "\"buy_orders\":" + (string)g_buyCount + ",";
   s += "\"sell_orders\":" + (string)g_sellCount + ",";
   s += "\"total_lots\":" + DoubleToString(g_totalLots, 2) + ",";
   s += "\"buy_lots\":" + DoubleToString(g_buyLots, 2) + ",";
   s += "\"sell_lots\":" + DoubleToString(g_sellLots, 2) + ",";
   s += "\"withdrawal\":" + DoubleToString(g_withdrawalTotal, 2) + ",";
   s += "\"net_deposit\":" + DoubleToString(g_depositTotal, 2) + ",";
   s += "\"timestamp\":\"" + IsoTime(now) + "\"";

   if(InpSendExtended)
     {
      s += ",\"pl_today\":"         + DoubleToString(g_closedPLToday + g_floatPL, 2);
      s += ",\"pl_week\":"          + DoubleToString(g_closedPLWeek  + g_floatPL, 2);
      s += ",\"pl_total\":"         + DoubleToString(g_closedPLTotal + g_floatPL, 2);
      s += ",\"closed_pl_today\":"  + DoubleToString(g_closedPLToday, 2);
      s += ",\"closed_pl_week\":"   + DoubleToString(g_closedPLWeek, 2);
      s += ",\"closed_pl_total\":"  + DoubleToString(g_closedPLTotal, 2);
      s += ",\"vol_today\":"        + DoubleToString(g_closedVolToday + g_totalLots, 2);
      s += ",\"vol_week\":"         + DoubleToString(g_closedVolWeek  + g_totalLots, 2);
      s += ",\"vol_total\":"        + DoubleToString(g_closedVolTotal + g_totalLots, 2);
      s += ",\"dd_today\":"         + DoubleToString(g_ddToday.maxDD, 2);
      s += ",\"dd_today_at\":\""    + IsoTime(g_ddToday.when) + "\"";
      s += ",\"dd_today_lots\":"    + DoubleToString(g_ddToday.lots, 2);
      s += ",\"dd_week\":"          + DoubleToString(g_ddWeek.maxDD, 2);
      s += ",\"dd_week_at\":\""     + IsoTime(g_ddWeek.when) + "\"";
      s += ",\"dd_week_lots\":"     + DoubleToString(g_ddWeek.lots, 2);
      s += ",\"dd_total\":"         + DoubleToString(g_ddTotal.maxDD, 2);
      s += ",\"dd_total_at\":\""    + IsoTime(g_ddTotal.when) + "\"";
      s += ",\"dd_total_lots\":"    + DoubleToString(g_ddTotal.lots, 2);
      s += ",\"stats_start\":\""    + IsoTime(g_statsStart) + "\"";
     }

   s += "}";

   char   post[];
   char   result[];
   string resultHeaders;
   StringToCharArray(s, post, 0, WHOLE_ARRAY, CP_UTF8);
   int n = ArraySize(post);
   if(n > 0 && post[n - 1] == 0)
      ArrayResize(post, n - 1);

   string headers = "Content-Type: application/json\r\n";
   int res = WebRequest("POST", InpServerURL, headers, 5000, post, result, resultHeaders);

   if(res == 200 || res == 201)
     {
      g_sendStatus = "OK " + IsoTime(now);
     }
   else
     {
      g_sendStatus = StringFormat("ERR %d @%s", res, IsoTime(now));
      uint ms = GetTickCount();
      if(ms - g_lastErrorMs > 300000)   // log ไม่เกินทุก 5 นาที
        {
         g_lastErrorMs = ms;
         Print("MT5_DataSender: send failed. HTTP=", res, " err=", GetLastError());
         if(res == -1 && GetLastError() == 4014)
            Print("MT5_DataSender: add '", InpServerURL, "' to Tools > Options > Expert Advisors > Allow WebRequest");
        }
     }
  }

//+------------------------------------------------------------------+
//| Init / Deinit / Timer / Events                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpTimerInterval <= 0)
     {
      Print("MT5_DataSender: InpTimerInterval must be > 0");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_statsStart = (InpUseStatsStartDate && InpStatsStartDate > 0) ? InpStatsStartDate : 0;
   g_lastCheck  = TimeCurrent();
   g_ddToday.maxDD = 0.0; g_ddToday.when = g_lastCheck; g_ddToday.lots = 0.0;
   g_ddWeek.maxDD  = 0.0; g_ddWeek.when  = g_lastCheck; g_ddWeek.lots  = 0.0;
   g_ddTotal.maxDD = 0.0; g_ddTotal.when = g_lastCheck; g_ddTotal.lots = 0.0;

   if(InpUseGlobalVars)
      LoadState();

   SetupDashboard();

   RefreshLabels(g_lastCheck, true);

   // อ่าน history ครั้งแรกแบบเต็ม (ครั้งเดียวตอนเปิด) + ส่งทันที
   SyncHistory(true);
   UpdatePositions();
   UpdateDDState(TimeCurrent(), (TimeCurrent() >= g_statsStart));
   SendAccountData();
   RefreshLabels(TimeCurrent(), true);

   g_lastSendMs = GetTickCount();
   EventSetTimer(1);   // timer เดียว: realtime DD + UI, ส่ง server ตามรอบใน OnTimer

   Print("MT5_DataSender v2.00 ready | send every ", InpTimerInterval, "s | dashboard=", InpShowDashboard);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   SaveState();
   DestroyDashboard();
   ChartRedraw(0);
  }

void OnTimer()
  {
   datetime now = TimeCurrent();

   UpdatePositions();                       // ถูก: เฉพาะ positions ที่เปิดอยู่
   HandleRollover(now);

   bool statsStarted = (now >= g_statsStart);
   UpdateDDState(now, statsStarted);

   RefreshLabels(now, false);               // วาดใหม่เมื่อข้อความเปลี่ยนเท่านั้น

   uint ms = GetTickCount();
   if((uint)(ms - g_lastSendMs) >= (uint)(InpTimerInterval * 1000))
     {
      g_lastSendMs = ms;

      // full resync เป็นรอบ (กันข้อมูลคลาดเคลื่อนจากการที่ history ถูกโหลดย้อนหลัง)
      bool needFull = (InpFullResyncMinutes > 0) &&
                      (g_lastFullSync <= 0 || (now - g_lastFullSync) >= (InpFullResyncMinutes * 60));

      SyncHistory(needFull);
      SendAccountData();
      SaveState();
      RefreshLabels(now, true);
     }
  }

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == g_btnReset)
     {
      ResetAllDD();
      ObjectSetInteger(0, g_btnReset, OBJPROP_STATE, false);
      ChartRedraw(0);
     }
  }
//+------------------------------------------------------------------+
