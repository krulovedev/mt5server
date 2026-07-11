//+------------------------------------------------------------------+
//|  MT5_DataSender.mq5                                              |
//|  ส่งข้อมูล Account ไปยัง Server ทุก 1 นาที                       |
//|  ออกแบบให้ใช้ CPU/RAM น้อยที่สุด                                  |
//+------------------------------------------------------------------+
#property copyright "MT5 Monitor"
#property version   "1.00"
#property strict

//--- Input Parameters
input string   ServerURL      = "http://127.0.0.1:8000/api/data";  // Server URL
input string   AccountAlias   = "Account_01";   // ชื่อ Account (Alias)
input double   InitialBalance = 10000.0;         // ทุนเริ่มต้น (USD)
input int      SendInterval   = 60;              // ช่วงเวลาส่ง (วินาที)
input string   SecretKey      = "mysecretkey";   // Secret Key สำหรับ Auth
input bool     SendOnTick     = false;           // ส่งทุก Tick (ไม่แนะนำ)

//--- Global Variables
datetime g_lastSendTime = 0;
int      g_sendCount    = 0;
bool     g_initialized  = false;
double   g_peakBalance  = 0.0;   // Peak balance สำหรับคำนวณ Balance DD
double   g_peakEquity   = 0.0;   // Peak equity  สำหรับคำนวณ Equity DD

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   // ตรวจสอบ WebRequest Permission
   // ต้องเพิ่ม URL ใน Tools > Options > Expert Advisors > Allow WebRequest
   
   Print("MT5 DataSender เริ่มต้น | Account: ", AccountAlias, 
         " | Server: ", ServerURL);
   
   g_lastSendTime = 0; // ส่งทันทีเมื่อเริ่ม
   g_initialized  = true;
   
   // ใช้ Timer แทน OnTick เพื่อประหยัด CPU
   if(!SendOnTick)
      EventSetTimer(SendInterval);
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("MT5 DataSender หยุดทำงาน | ส่งข้อมูลไปแล้ว: ", g_sendCount, " ครั้ง");
}

//+------------------------------------------------------------------+
//| Timer function - ทำงานทุก SendInterval วินาที (ประหยัด CPU)      |
//+------------------------------------------------------------------+
void OnTimer()
{
   SendAccountData();
}

//+------------------------------------------------------------------+
//| OnTick - ใช้เฉพาะเมื่อ SendOnTick = true                         |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!SendOnTick) return;
   
   datetime currentTime = TimeCurrent();
   if(currentTime - g_lastSendTime >= SendInterval)
      SendAccountData();
}

//+------------------------------------------------------------------+
//| ฟังก์ชันหลัก: รวบรวมและส่งข้อมูล                                 |
//+------------------------------------------------------------------+
void SendAccountData()
{
   // --- รวบรวมข้อมูล Account ---
   double balance      = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity       = AccountInfoDouble(ACCOUNT_EQUITY);
   double margin       = AccountInfoDouble(ACCOUNT_MARGIN);
   double freeMargin   = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double marginLevel  = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
   double profit       = AccountInfoDouble(ACCOUNT_PROFIT);
   double credit       = AccountInfoDouble(ACCOUNT_CREDIT);
   
   // --- คำนวณ Drawdown (Peak-to-Trough) ---
   // อัพเดท Peak
   if(balance > g_peakBalance || g_peakBalance == 0.0) g_peakBalance = balance;
   if(equity  > g_peakEquity  || g_peakEquity  == 0.0) g_peakEquity  = equity;
   
   // Balance DD จาก Peak Balance
   double drawdownAmt  = g_peakBalance - balance;
   double drawdownPct  = (g_peakBalance > 0) ? (drawdownAmt / g_peakBalance * 100.0) : 0.0;
   if(drawdownPct < 0) drawdownPct = 0.0;  // ไม่แสดงค่าลบ (ตอนทำ new high)
   
   // Equity DD จาก Peak Equity (floating loss)
   double equityDD = (g_peakEquity > 0) ? ((g_peakEquity - equity) / g_peakEquity * 100.0) : 0.0;
   if(equityDD < 0) equityDD = 0.0;
   
   // --- ข้อมูล Broker & Account ---
   long   accountNum   = AccountInfoInteger(ACCOUNT_LOGIN);
   string broker       = AccountInfoString(ACCOUNT_COMPANY);
   string currency     = AccountInfoString(ACCOUNT_CURRENCY);
   string server       = AccountInfoString(ACCOUNT_SERVER);
   int    leverage     = (int)AccountInfoInteger(ACCOUNT_LEVERAGE);
   
   // --- ข้อมูล Open Positions ---
   int    openOrders   = PositionsTotal();
   int    buyOrders    = 0;
   int    sellOrders   = 0;
   double totalLots    = 0.0;
   double buyLots      = 0.0;
   double sellLots     = 0.0;
   for(int i = 0; i < openOrders; i++)
   {
      if(PositionSelectByTicket(PositionGetTicket(i)))
      {
         double lots = PositionGetDouble(POSITION_VOLUME);
         totalLots += lots;
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         {
            buyOrders++;
            buyLots += lots;
         }
         else
         {
            sellOrders++;
            sellLots += lots;
         }
      }
   }
   
   // --- Timestamp ---
   datetime serverTime = TimeTradeServer();
   string   timeStr    = TimeToString(serverTime, TIME_DATE|TIME_SECONDS);
   // แปลงเป็น ISO format
   StringReplace(timeStr, ".", "-");
   StringReplace(timeStr, " ", "T");
   
   // --- สร้าง JSON payload ---
   string json = StringFormat(
      "{"
      "\"secret\":\"%s\","
      "\"alias\":\"%s\","
      "\"account_number\":%d,"
      "\"broker\":\"%s\","
      "\"server\":\"%s\","
      "\"currency\":\"%s\","
      "\"leverage\":%d,"
      "\"balance\":%.2f,"
      "\"equity\":%.2f,"
      "\"margin\":%.2f,"
      "\"free_margin\":%.2f,"
      "\"margin_level\":%.2f,"
      "\"profit\":%.2f,"
      "\"credit\":%.2f,"
      "\"initial_balance\":%.2f,"
      "\"drawdown_amount\":%.2f,"
      "\"drawdown_pct\":%.4f,"
      "\"equity_drawdown_pct\":%.4f,"
      "\"open_orders\":%d,"
      "\"buy_orders\":%d,"
      "\"sell_orders\":%d,"
      "\"total_lots\":%.2f,"
      "\"buy_lots\":%.2f,"
      "\"sell_lots\":%.2f,"
      "\"timestamp\":\"%s\""
      "}",
      SecretKey,
      AccountAlias,
      accountNum,
      broker,
      server,
      currency,
      leverage,
      balance,
      equity,
      margin,
      freeMargin,
      marginLevel,
      profit,
      credit,
      InitialBalance,
      drawdownAmt,
      drawdownPct,
      equityDD,
      openOrders,
      buyOrders,
      sellOrders,
      totalLots,
      buyLots,
      sellLots,
      timeStr
   );
   
   // --- ส่งข้อมูลผ่าน HTTP POST ---
   char   postData[];
   char   result[];
   string resultHeaders;
   
   StringToCharArray(json, postData, 0, StringLen(json));
   
   string headers = "Content-Type: application/json\r\n";
   
   int res = WebRequest(
      "POST",
      ServerURL,
      headers,
      5000,       // Timeout 5 วินาที
      postData,
      result,
      resultHeaders
   );
   
   if(res == 200)
   {
      g_sendCount++;
      g_lastSendTime = TimeCurrent();
      // Comment เบาๆ บน Chart
      Comment(StringFormat(
         "MT5 Monitor | %s\n"
         "ส่งสำเร็จ: %d ครั้ง | ล่าสุด: %s\n"
         "Balance: %.2f | Peak: %.2f | Bal DD: %.2f%%\n"
         "Equity:  %.2f | Peak: %.2f | Eq  DD: %.2f%%\n"
         "Orders: %d (Buy:%d Sell:%d) | Lots: %.2f",
         AccountAlias, g_sendCount, TimeToString(g_lastSendTime, TIME_MINUTES|TIME_SECONDS),
         balance, g_peakBalance, drawdownPct,
         equity,  g_peakEquity,  equityDD,
         openOrders, buyOrders, sellOrders, totalLots
      ));
   }
   else if(res == -1)
   {
      int err = GetLastError();
      Print("WebRequest Error: ", err, 
            " - ตรวจสอบว่าเพิ่ม URL ใน Tools>Options>Expert Advisors");
   }
   else
   {
      Print("Server Response Code: ", res, " | กรุณาตรวจสอบ Server");
   }
}
//+------------------------------------------------------------------+
