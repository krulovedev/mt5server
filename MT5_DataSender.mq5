//+------------------------------------------------------------------+
//|                                              MT5_DataSender.mq5  |
//|                                      Copyright 2026, MT5Monitor  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, MT5Monitor"
#property link      ""
#property version   "1.50"

input string   InpServerURL      = "http://127.0.0.1:8000/api/data"; // Server URL
input string   InpAccountAlias   = "MyAccount_01";                   // Account Alias
input string   InpSecretKey      = "mysecretkey";                    // Secret Key
input double   InpInitialBalance = 10000.0;                          // ทุนเริ่มต้น (Initial Balance)
input int      InpTimerInterval  = 60;                               // ส่งข้อมูลทุกๆ (วินาที)

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpTimerInterval <= 0)
     {
      Print("Timer interval must be greater than 0");
      return(INIT_PARAMETERS_INCORRECT);
     }
   
   EventSetTimer(InpTimerInterval);
   Print("MT5 Data Sender initialized. Sending every ", InpTimerInterval, " seconds.");
   
   // Send immediately once on startup
   SendAccountData();
   
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Print("MT5 Data Sender deinitialized.");
  }

//+------------------------------------------------------------------+
//| Timer function                                                   |
//+------------------------------------------------------------------+
void OnTimer()
  {
   SendAccountData();
  }

//+------------------------------------------------------------------+
//| คำนวณยอดถอนเงินทั้งหมด (Withdrawal)                                   |
//+------------------------------------------------------------------+
double GetTotalWithdrawal()
  {
   double total_withdrawal = 0.0;
   
   // ดึงประวัติทั้งหมดตั้งแต่เริ่มจนถึงปัจจุบัน
   if(HistorySelect(0, TimeCurrent()))
     {
      int total_deals = HistoryDealsTotal();
      for(int i = 0; i < total_deals; i++)
        {
         ulong deal_ticket = HistoryDealGetTicket(i);
         if(deal_ticket > 0)
           {
            long deal_type = HistoryDealGetInteger(deal_ticket, DEAL_TYPE);
            // ตรวจสอบ Deal ประเภท Balance
            if(deal_type == DEAL_TYPE_BALANCE) 
              {
               double deal_profit = HistoryDealGetDouble(deal_ticket, DEAL_PROFIT);
               // ถ้ายอดเป็นลบ (ติดลบ) หมายถึงการถอนเงิน
               if(deal_profit < 0.0)
                 {
                  // แปลงค่าติดลบเป็นค่าบวกสะสม
                  total_withdrawal += MathAbs(deal_profit);
                 }
              }
           }
        }
     }
     
   return total_withdrawal;
  }

//+------------------------------------------------------------------+
//| สร้างและส่งข้อมูล                                                     |
//+------------------------------------------------------------------+
void SendAccountData()
  {
   // Basic Info
   long   account_number = AccountInfoInteger(ACCOUNT_LOGIN);
   string broker         = AccountInfoString(ACCOUNT_COMPANY);
   string server         = AccountInfoString(ACCOUNT_SERVER);
   string currency       = AccountInfoString(ACCOUNT_CURRENCY);
   long   leverage       = AccountInfoInteger(ACCOUNT_LEVERAGE);
   
   // Financial Info
   double balance        = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity         = AccountInfoDouble(ACCOUNT_EQUITY);
   double margin         = AccountInfoDouble(ACCOUNT_MARGIN);
   double free_margin    = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double margin_level   = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   double profit         = AccountInfoDouble(ACCOUNT_PROFIT);
   double credit         = AccountInfoDouble(ACCOUNT_CREDIT);
   
   // Orders & Lots Info
   int    open_orders    = 0;
   int    buy_orders     = 0;
   int    sell_orders    = 0;
   double total_lots     = 0.0;
   double buy_lots       = 0.0;
   double sell_lots      = 0.0;
   
   int total_positions = PositionsTotal();
   for(int i = 0; i < total_positions; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
        {
         open_orders++;
         double pos_vol = PositionGetDouble(POSITION_VOLUME);
         long   pos_type = PositionGetInteger(POSITION_TYPE);
         
         total_lots += pos_vol;
         
         if(pos_type == POSITION_TYPE_BUY)
           {
            buy_orders++;
            buy_lots += pos_vol;
           }
         else if(pos_type == POSITION_TYPE_SELL)
           {
            sell_orders++;
            sell_lots += pos_vol;
           }
        }
     }
     
   // Withdrawal calculation (ฟังก์ชันที่เราเพิ่มเข้ามา)
   double withdrawal = GetTotalWithdrawal();
   
   // Drawdown calculation
   double peak_balance = MathMax(InpInitialBalance, balance);
   double drawdown_amount = 0.0;
   double drawdown_pct = 0.0;
   
   if(peak_balance > balance)
     {
      drawdown_amount = peak_balance - balance;
      drawdown_pct = (drawdown_amount / peak_balance) * 100.0;
     }
     
   double equity_dd_pct = 0.0;
   if(balance > 0)
     {
      if (equity < balance)
         equity_dd_pct = ((balance - equity) / balance) * 100.0;
     }
     
   // Construct JSON
   string json = "{";
   json += "\"secret\":\"" + InpSecretKey + "\",";
   json += "\"alias\":\"" + InpAccountAlias + "\",";
   json += "\"account_number\":" + IntegerToString(account_number) + ",";
   
   // Escape strings to prevent JSON errors
   StringReplace(broker, "\"", "\\\"");
   StringReplace(server, "\"", "\\\"");
   StringReplace(currency, "\"", "\\\"");
   
   json += "\"broker\":\"" + broker + "\",";
   json += "\"server\":\"" + server + "\",";
   json += "\"currency\":\"" + currency + "\",";
   json += "\"leverage\":" + IntegerToString(leverage) + ",";
   
   json += "\"balance\":" + DoubleToString(balance, 2) + ",";
   json += "\"equity\":" + DoubleToString(equity, 2) + ",";
   json += "\"margin\":" + DoubleToString(margin, 2) + ",";
   json += "\"free_margin\":" + DoubleToString(free_margin, 2) + ",";
   json += "\"margin_level\":" + DoubleToString(margin_level, 2) + ",";
   json += "\"profit\":" + DoubleToString(profit, 2) + ",";
   json += "\"credit\":" + DoubleToString(credit, 2) + ",";
   json += "\"initial_balance\":" + DoubleToString(InpInitialBalance, 2) + ",";
   
   json += "\"drawdown_amount\":" + DoubleToString(drawdown_amount, 2) + ",";
   json += "\"drawdown_pct\":" + DoubleToString(drawdown_pct, 4) + ",";
   json += "\"equity_drawdown_pct\":" + DoubleToString(equity_dd_pct, 4) + ",";
   
   json += "\"open_orders\":" + IntegerToString(open_orders) + ",";
   json += "\"buy_orders\":" + IntegerToString(buy_orders) + ",";
   json += "\"sell_orders\":" + IntegerToString(sell_orders) + ",";
   
   json += "\"total_lots\":" + DoubleToString(total_lots, 2) + ",";
   json += "\"buy_lots\":" + DoubleToString(buy_lots, 2) + ",";
   json += "\"sell_lots\":" + DoubleToString(sell_lots, 2) + ",";
   json += "\"withdrawal\":" + DoubleToString(withdrawal, 2) + ",";
   
   // Current MT5 time (Local to Server)
   datetime current_time = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(current_time, dt);
   string time_str = StringFormat("%04d-%02d-%02dT%02d:%02d:%02d", dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);
   
   json += "\"timestamp\":\"" + time_str + "\"";
   json += "}";
   
   // Prepare WebRequest payload
   char post_data[];
   char result_data[];
   string result_headers;
   
   StringToCharArray(json, post_data, 0, WHOLE_ARRAY, CP_UTF8);
   
   // ลบตัวอักษร Null terminator (0) ที่เกิดจาก StringToCharArray เพื่อให้เป็น JSON ที่สมบูรณ์
   if (ArraySize(post_data) > 0)
      ArrayResize(post_data, ArraySize(post_data) - 1);
   
   string headers = "Content-Type: application/json\r\n";
   
   // ส่งข้อมูล (Timeout 5 วินาที)
   int res = WebRequest("POST", InpServerURL, headers, 5000, post_data, result_data, result_headers);
   
   if(res == 200 || res == 201)
     {
      // สำเร็จ
      // Print("Data sent successfully");
     }
   else
     {
      Print("Failed to send data to ", InpServerURL, ". Error code: ", res, ", GetLastError: ", GetLastError());
      if (res == -1 && GetLastError() == 4014)
        {
         Print("ERROR: WebRequest not allowed. Please add '", InpServerURL, "' to Tools > Options > Expert Advisors > Allow WebRequest");
        }
     }
  }
//+------------------------------------------------------------------+
