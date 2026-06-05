#property copyright "NikoFXjefe"
#property link      "https://nikofxjefe.no"
#property version   "5.03"
#property strict
#property description "FXJEFE_Algo_AI v5.03 — Unified Engine v5.03, Kelly 2.0 (0.77 regime), pip-fix, signal-file reader, halt, spread/flash/time stops"

// Include necessary MQL5 libraries
#include <Trade\Trade.mqh>
#include <Trade\SymbolInfo.mqh>
#include <Trade\PositionInfo.mqh>
#include <Files\FilePipe.mqh>      // FIX: was merged onto same line as PositionInfo.mqh
// Math\Stat\Math.mqh removed — CalcRV uses manual std-dev (no external dependency)

//==================== FXJEFE UNIFIED FEATURE ENGINE v5.03 =====================
// Shared implementations so Predict333.mq5, GenerateFeatures333.mq5 and this
// EA compute HMA / Supertrend / DPO byte-identically. DO NOT MODIFY per file.
//   • HMA  = WMA( 2*WMA(n/2) - WMA(n), round(sqrt(n)) )  (full 3-stage Hull)
//   • ST   = hl2 ± mult*ATR  with regime state driven by close[1]
//            (returns the PRICE LEVEL — not a regime flag)
//   • DPO  = close[period/2+1] − SMA(period) (displacement DPO, no iCustom)
// ----------------------------------------------------------------------------
double UnifiedCalcHMA(string symbol, ENUM_TIMEFRAMES tf, int period, int shift=0)
{
   int n = period;
   if(n < 2) return iClose(symbol, tf, shift);
   int half = n / 2;
   int m    = (int)(MathSqrt((double)n) + 0.5);   // WMA(sqrt(n)) length (n=9 → 3)
   if(m < 1) m = 1;
   int len  = n + m;
   double p[]; ArraySetAsSeries(p, true);
   if(CopyClose(symbol, tf, shift, len, p) < len) return iClose(symbol, tf, shift);

   double diff[]; ArrayResize(diff, m);
   for(int j = 0; j < m; j++)
   {
      double wf = 0.0, sf = 0.0, ws = 0.0, ss = 0.0;
      for(int i = 0; i < half; i++) { double w = (double)(half - i); wf += p[j + i]*w; sf += w; }
      for(int i = 0; i < n;    i++) { double w = (double)(n    - i); ws += p[j + i]*w; ss += w; }
      double f = (sf > 0) ? wf / sf : p[j];
      double s = (ss > 0) ? ws / ss : p[j];
      diff[j]  = 2.0 * f - s;
   }
   double hma = 0.0, sh = 0.0;
   for(int j = 0; j < m; j++) { double w = (double)(m - j); hma += diff[j]*w; sh += w; }
   return (sh > 0) ? hma / sh : diff[0];
}

// Per-symbol Supertrend state (one row per dynamicPairList index)
double g_unified_st_prev[32];
bool   g_unified_st_up[32];

double UnifiedCalcSupertrend(int idx, string symbol, ENUM_TIMEFRAMES tf,
                             int period, double mult, int atr_hdl, int shift=0)
{
   if(idx < 0 || idx >= 32) return iClose(symbol, tf, shift);
   double h_arr[], l_arr[], c_arr[], atr_buf[];
   ArraySetAsSeries(h_arr,true); ArraySetAsSeries(l_arr,true);
   ArraySetAsSeries(c_arr,true); ArraySetAsSeries(atr_buf,true);
   if(CopyHigh(symbol, tf, shift, 2, h_arr) < 2 ||
      CopyLow (symbol, tf, shift, 2, l_arr) < 2 ||
      CopyClose(symbol,tf, shift, 2, c_arr) < 2 ||
      atr_hdl == INVALID_HANDLE ||
      CopyBuffer(atr_hdl, 0, shift, 1, atr_buf) < 1)
      return iClose(symbol, tf, shift);
   double hl2   = (h_arr[0] + l_arr[0]) / 2.0;
   double upper = hl2 + mult * atr_buf[0];
   double lower = hl2 - mult * atr_buf[0];
   if(g_unified_st_prev[idx] == 0.0)                         { g_unified_st_prev[idx] = lower; g_unified_st_up[idx] = true; }
   else if( g_unified_st_up[idx] && c_arr[1] < g_unified_st_prev[idx]) { g_unified_st_up[idx] = false; g_unified_st_prev[idx] = upper; }
   else if(!g_unified_st_up[idx] && c_arr[1] > g_unified_st_prev[idx]) { g_unified_st_up[idx] = true;  g_unified_st_prev[idx] = lower; }
   else                                                                { g_unified_st_prev[idx] = g_unified_st_up[idx] ? lower : upper; }
   return g_unified_st_up[idx] ? lower : upper;
}

double UnifiedCalcDPO(string symbol, ENUM_TIMEFRAMES tf, int period, int shift=0)
{
   int disp = period / 2 + 1;
   int lookback = period + disp + 1;
   double p[]; ArraySetAsSeries(p, true);
   if(CopyClose(symbol, tf, shift, lookback, p) < lookback) return 0.0;
   double sma = 0.0;
   for(int i = 0; i < period; i++) sma += p[i];
   sma /= (double)period;
   if(disp >= ArraySize(p)) return 0.0;
   return p[disp] - sma;
}
//==================== END UNIFIED FEATURE ENGINE v5.03 ========================

// Enums for configuration
enum ENUM_AccountSize { Acct_Custom = 0, Acct_1K = 1000, Acct_5K = 5000, Acct_10K = 10000, Acct_100K = 100000 };
enum ENUM_PHASE_TYPE { Phase_1, Phase_2, Phase_3, Phase_Live };
enum ENUM_SIGNAL_MODE { AI_Only = 0, Strategies_Only = 1, Both = 2 };

// Structs for organizing data
struct PhaseRules {
   double profitTarget_Pct;
   double dailyDD_Pct;
   double totalDD_Pct;
   double riskPct;
   int minTradingDays;
};

struct FXJEFE_CandidateTrade {
   string pair;
   string strategyName;
   ENUM_ORDER_TYPE orderType;
   double lotSize;
   double openPrice;
   double stopLoss;
   double takeProfit;
   double momentumScore;
};

// Input parameters
input ENUM_AccountSize AccountSize = Acct_Custom;     // Account size (Custom=use actual balance)
input double CustomAccountSize = 0.0;                 // Custom account size (0=read from broker)
input ENUM_PHASE_TYPE PhaseType = Phase_Live;         // Phase (Live=no profit target/DD halt)
input double RiskPercent = 0.5;                       // Risk per trade (%) — reduced from 1.0 for live
input double PostTargetRiskPct = 0.5;                 // Risk after target reached
input double TotalProfitTargetPct = 0.0;              // Profit target % (0=disabled)
input int MinTradingDays = 0;                         // Minimum trading days (0=disabled)
input bool InputAllowTrading = true;                  // Enable/disable trading
input bool UseMicroBreakout = true;                   // Micro breakout strategy
input bool UsePullbackTrend = true;                   // Pullback trend strategy
input bool UseICTKillZone = true;                     // ICT kill zone strategy
input bool UsePO3 = true;                             // PO3 strategy
input bool UsePsychLevels = true;                     // Psychological levels strategy
input bool UseStatArbitrage = true;                   // Statistical arbitrage strategy
input bool UseCarryTrade = true;                      // Carry trade strategy
input bool UseAISignals = true;                       // AI signal integration
input ENUM_SIGNAL_MODE SignalMode = Both;             // Signal mode: AI, Strategies, or Both
input string AI_API_URL = "http://127.0.0.1:8080/predict";        // AI predict endpoint
input string AI_SENTIMENT_URL = "http://127.0.0.1:8080/predict/sentiment"; // Sentiment endpoint
input string API_Key = "";                            // API key (if required)
input string SecurityKey = "NikoFXjefeGrok2025";      // Security key for EA
input int MaxOpenTrades = 2;                          // Maximum simultaneous trades
input int MaxDailyTrades = 5;                         // Maximum trades per day
input bool UseMaxDailyTrades = true;                  // Enable daily trade limit
input double MaxPairExposure_Pct = 30.0;              // Max exposure per pair (%)
input double MaxLeverage = 100.0;                     // Max leverage (1:100) — reduced from 500.0 for live
input double MaxVaR_Pct = 2.3;                       // Maximum Value at Risk
input double MaxES_Pct = 7.0;                         // Maximum Expected Shortfall
input double CircuitBreakerDrop_Pct = 5.0;            // Circuit breaker trigger (%)
input int ATR_Period = 14;                            // ATR period
input int EMA_Fast_Period = 12;                       // Fast EMA period
input int EMA_Slow_Period = 26;                       // Slow EMA period
input int RSI_Period = 14;                            // RSI period
input int BB_Period = 20;                             // Bollinger Bands period
input double BB_Deviation = 2.0;                      // Bollinger Bands deviation
input int VWAP_Period = 48;                           // VWAP period (M15 bars)
input double VWAP_Bands_Multiplier = 2.0;             // VWAP bands multiplier
input int Stochastic_K = 5;                           // Stochastic K period
input int Stochastic_D = 3;                           // Stochastic D period
input int Stochastic_Slow = 3;                        // Stochastic slowing
input int MACD_Fast = 12;                             // MACD fast EMA
input int MACD_Slow = 26;                             // MACD slow EMA
input int MACD_Signal = 9;                            // MACD signal line
input double MaxSlippagePips = 100.0;                 // Maximum slippage in pips
// Trade-management defaults pushed 2026-05-18 to let winners run (avg win was
// $23 vs $52 avg loss — closing 50% at +20pips clipped most of the profit).
input double PartialExitPips = 40.0;                  // TP1 (was 20). +100% farther — winner breathes before clip.
input double TP2Pips = 80.0;                          // TP2 (was 40). +100% farther — runs into trend extension.
input double TPBEPips = 10.0;                         // Breakeven offset for SL
input int FirstSessionStart = 0;                      // First trading session start (GMT)
input int FirstSessionEnd = 24;                       // First trading session end (GMT)
input int SecondSessionStart = 13;                    // Second trading session start (GMT)
input int SecondSessionEnd = 17;                      // Second trading session end (GMT)
input int NewsWindowHours = 2;                        // News event window (hours)
input bool NoSundayTrading = false;                   // Disable Sunday trading
input int AmsterdamTimeShift = -1;                    // Time shift for Amsterdam
input bool UseCSVLogging = true;                      // Enable CSV logging
input string CSVDirectory = "MQL5\\Files";            // CSV logging directory
input bool UseAPILogging = true;                      // Enable API logging
input string APIPipeName = "FXJEFE_API_Pipe";         // API pipe name
input double MaxCorrelation = 0.3;                    // Maximum correlation threshold
input bool LabelSignals = true;                       // Label signals in logs
input double PipThreshold = 10.0;                     // Pip threshold for signals
input double MinAIConfidence = 0.77;                   // 0.77 gate — matches golden server regime
input double TrailingStopATRMult = 2.5;                // Trailing SL ATR mult (was 1.5). Wider gives winners room.
input double BreakevenTriggerATRMult = 1.0;            // Move SL to BE after price moves ATR * this
input double BreakevenOffsetPips = 2.0;                // Offset above entry for breakeven SL (covers fees/slippage)
input double PartialClosePercent = 33.0;               // % to close at TP1 (was 50). Keep 67% open for the run.
input int ConsecLossPause = 3;                         // Pause trading after N consecutive losses
input int ConsecLossPauseHours = 4;                    // Hours to pause after consecutive losses
input double SessionMultAsian = 0.5;                   // Lot multiplier for Asian session (low liquidity)
input double SessionMultLondon = 1.0;                  // Lot multiplier for London session
input double SessionMultNY = 1.0;                      // Lot multiplier for NY session
input double SessionMultWeekend = 0.7;                 // Lot multiplier for weekend crypto trading
input double RoundNumberPct = 0.005;                   // Skip trades within this % of round numbers
input bool UseRoundNumberFilter = true;                // Enable round number avoidance
input bool UseConsecLossBreaker = true;                // Enable consecutive loss circuit breaker
input bool UseSessionSizing = true;                    // Enable session-based lot sizing
input bool UseMultiTFConfirm = true;                   // Enable multi-timeframe confirmation
input double MaxTradeRiskPct = 20.0;                   // Max risk per trade (% of balance, for micro accounts)
input bool BypassSessionFilter = false;                // TESTING ONLY: bypass all day/session/hour filters

// ── Kelly 2.0 — recalibrated for 0.77 win-rate regime (2026-04-22) ─────────
input bool   UseKellySizing         = true;   // Scale lots by Kelly fraction × AI confidence
input double Kelly_FractionalCap    = 0.20;   // Hard cap on Kelly fraction (was 0.25 for 0.98 regime)
input double Kelly_RecentWinRate    = 0.77;   // Expected win rate feeding Kelly — matches 0.77 regime
input double Kelly_PerTradeCapPct   = 2.0;    // Hard ceiling on per-trade risk % — never exceed
input double Kelly_AvgRR            = 1.5;    // Assumed reward:risk ratio (matches AI TP setter)
input double TargetWinRate          = 0.77;   // Informational — documents the regime target

// ── Prop-account PF protection (added 2026-05-18 after PF 0.38 incident) ──
// These layer ON TOP of the existing 3.33% daily-DD halt — they fire EARLIER
// to stop bleed before the daily limit is hit. Tune via Inputs panel; no
// recompile needed when changing the values.
input double PropDailyLimit         = 1178.63; // Broker's stated daily loss limit ($)
input double PropEarlyPausePct      = 0.40;    // Pause new trades when today's loss > limit*this (0.40 = 40%)
input double PropBalanceFloor       = 22394.06; // Hard equity floor — EA detaches itself if breached
input double PropMinWinnerRR        = 2.5;    // RR floor (was 2.0). Demand bigger reward setups only.
input bool   PropRequireWinnerFlag  = true;    // Require enforce_winner=true from server's TradeOutcomeEngineer

// ── Trade hygiene filters ──────────────────────────────────────────────────
input double MaxSpreadMultiplier    = 3.0;    // Skip entries if spread > avg*this
input double FlashCrashATRMult      = 5.0;    // Detect single-bar move > ATR*this → block new opens
input int    FlashCrashCooldownMin  = 30;     // Minutes to block new opens after flash detection
input int    MaxHoldHours           = 48;     // Time-stop hrs (was 24). Doubled so trend-day winners aren't cut.
input bool   UseSignalFileReader    = true;   // Prefer per-symbol JSON files written by Predict333
input string SignalInDir            = "FXJEFE\\signals";      // Where Predict333 writes its JSON
input string GlobalHaltFlagFile     = "data\\global_halt.flag"; // CentralRiskEngine halt flag

// Global variables
// Pair list — EA validates each symbol on init and removes unavailable ones
// Blacklisted 2026-05-06: EURUSD (loss-only churn), XRPUSD (not on FundingPips)
string dynamicPairList[] = {"USDJPY","XAUUSD","AUDUSD","GBPUSD","USDCAD","BTCUSD"};
int totalPairs = 6;

// M15 strategy indicator handles (used by strategy logic)
int atrHandles[], emaFastHandles[], emaSlowHandles[], rsiHandles[], bbHandles[];
int stochasticHandles[], macdHandles[], adxHandles[];

// M15 strategy cached values
double cachedATR[], cachedEMAFast[], cachedEMASlow[], cachedRSI[];
double cachedBBUpper[], cachedBBLower[];
double cachedStochK[], cachedStochD[], cachedMACD[], cachedMACDSignal[];
double cachedVWAP[], cachedVWAPUpper[], cachedVWAPLower[];
double cachedADX[];

// GARCH volatility (used by strategy logic)
double garchVolatility[];
double garchAlpha = 0.08, garchBeta = 0.88, garchOmega = 0.000007;  // tuned: persistence=0.96, safer on live 1:100x

// FIX: Extended cached features for the AI model (M1, matching training data)
// These are updated once per M15 bar via ComputeExtendedFeatures()
double cachedROC[], cachedCCI[], cachedWilliams[], cachedMomentum[];
double cachedRealizedVol[], cachedChaikinVol[], cachedRVI[];
double cachedOBV[], cachedVolumeDelta[], cachedADLine[], cachedVolOsc[];
double cachedSupertrend[], cachedHMA[], cachedIchimokuTenkan[];
double cachedSAR[], cachedDPO[], cachedSpread[], cachedSentiment[];

// Lag-1 buffers for the 43-feature server contract (added 2026-05-18).
// Each holds the PREVIOUS call's value of the corresponding feature, indexed
// by pair idx. Updated at the end of each ApiCall so the next call's payload
// can include *_lag1 fields. Seeded to 0 on first call per pair.
double g_lag1_price[],     g_lag1_atr[],          g_lag1_ema_diff[];
double g_lag1_rsi[],       g_lag1_garch_vol[],    g_lag1_macd_diff[];
double g_lag1_bb_position[], g_lag1_roc[],        g_lag1_momentum[];
double g_lag1_realized_vol[], g_lag1_adx[],       g_lag1_supertrend[];
double g_lag1_dpo[],       g_lag1_sentiment[];

double g_maxBalance, g_dailyStartEquity, g_initialBalance, g_lastEquityCheck;
datetime g_lastEquityTime, last_api_call[], g_lastTradeTime, lastHistoryCheck = 0;
int g_lastDealCount, g_consecutiveLosses, g_dailyTradesCount;
bool g_apiPipeOpen = false;
bool g_timerRunning = false;
datetime g_consecLossPauseUntil = 0;                   // Pause trading until this time
int h1EmaHandles[];                                    // H1 EMA handles for multi-TF confirm
CTrade trade;
CSymbolInfo symbolInfo;
CPositionInfo positionInfo;
CFilePipe apiPipe;
double lastPrice[];
datetime lastTime[];
string last_good_signal[];
datetime last_good_signal_time[];
double last_ai_confidence[];                           // AI confidence per pair (used as momentumScore)
bool indicatorsInitialized = false;
bool tradingEnabled = InputAllowTrading;
double g_totalProfitTarget = 0.0;
double g_dailyProfit = 0.0;
datetime g_lastDayReset = 0;
int g_tradingDaysCount = 0;
bool g_tradingDayActive = false;
string g_tradingDays[];
double g_maxDailyLoss = 0.0;   // set properly in OnInit from 3.33% of initial balance
bool g_profitTargetReached = false;
double tokyoHigh[], tokyoLow[];
datetime lastKillZoneStart[];
double firstHigh[], firstLow[];
double g_previousDayEquity;

// Security check function
bool CheckSecurityKey() {
   if (SecurityKey != "NikoFXjefeGrok2025") {
      Print("Security Key mismatch. EA disabled.");
      return false;
   }
   return true;
}

// Utility functions
string ArrayToStringCustom(string &arr[]) {
   string result = "";
   for (int i = 0; i < ArraySize(arr); i++) {
      result += arr[i];
      if (i < ArraySize(arr) - 1) result += ", ";
   }
   return result;
}

double GetMomentumScore(string pair, int idx) {
   if (idx < 0 || idx >= totalPairs || ArraySize(cachedRSI) <= idx) return 0.5;
   return (cachedRSI[idx] > 75 || cachedRSI[idx] < 25) ? 0.9 : 0.5;
}

bool NewBar(ENUM_TIMEFRAMES tf) {
   static datetime lastBar = 0;
   datetime currentBar = iTime(Symbol(), tf, 0);
   if (currentBar != lastBar) {
      lastBar = currentBar;
      return true;
   }
   return false;
}

int ArraySearchString(string &arr[], string value) {
   for (int i = 0; i < ArraySize(arr); i++) {
      if (arr[i] == value) return i;
   }
   return -1;
}

double CalculateLotSize(string pair, double &slPrice, double openPrice, ENUM_ORDER_TYPE orderType) {
   double balance;
   if (AccountSize == Acct_Custom && CustomAccountSize > 0.0)
      balance = CustomAccountSize;
   else if (AccountSize != Acct_Custom)
      balance = (double)AccountSize;
   else
      balance = AccountInfoDouble(ACCOUNT_BALANCE);

   double riskAmount = balance * (RiskPercent / 100.0);
   double pipValue   = SymbolInfoDouble(pair, SYMBOL_TRADE_TICK_VALUE);
   double point      = SymbolInfoDouble(pair, SYMBOL_POINT);
   int    digits     = (int)SymbolInfoInteger(pair, SYMBOL_DIGITS);
   double brokerMin  = SymbolInfoDouble(pair, SYMBOL_VOLUME_MIN);
   double maxLot     = SymbolInfoDouble(pair, SYMBOL_VOLUME_MAX);
   double stepLot    = SymbolInfoDouble(pair, SYMBOL_VOLUME_STEP);

   // Hard minimum 0.1 lot — skip pair if margin cannot support it
   double hardMin = NormalizeDouble(MathMax(brokerMin, 0.10), 2);

   if (point == 0 || pipValue == 0) return 0.0;
   double slDistance = MathAbs(openPrice - slPrice) / point;
   if (slDistance == 0) return 0.0;

   // Risk-based calculation
   double lotSize = riskAmount / (slDistance * pipValue);
   // Snap to step grid from hardMin upward
   int steps = (int)MathFloor((lotSize - hardMin) / stepLot);
   lotSize = hardMin + MathMax(0, steps) * stepLot;
   // Enforce bounds and fix floating-point precision ("invalid volume" fix)
   lotSize = NormalizeDouble(MathMax(hardMin, MathMin(maxLot, lotSize)), 2);

   double maxAcceptableRisk = balance * (MaxTradeRiskPct / 100.0);
   double minLotRisk        = hardMin * slDistance * pipValue;

   if (lotSize <= hardMin && minLotRisk > maxAcceptableRisk) {
      // Tighten SL so that hardMin risk fits within MaxTradeRiskPct of balance
      double affordableDist = maxAcceptableRisk / (hardMin * pipValue);
      if (affordableDist < 1) {
         Print("SKIP: ", pair, " un-tradeable (0.1 lot 1-pt risk $",
               DoubleToString(hardMin * pipValue, 2), " > max $",
               DoubleToString(maxAcceptableRisk, 2), " on $", DoubleToString(balance, 2), ")");
         return 0.0;
      }
      double oldSL = slPrice;
      if (orderType == ORDER_TYPE_BUY)
         slPrice = NormalizeDouble(openPrice - affordableDist * point, digits);
      else
         slPrice = NormalizeDouble(openPrice + affordableDist * point, digits);
      lotSize = hardMin;
      Print("SL CLAMPED: ", pair, " SL ", DoubleToString(oldSL, digits),
            " -> ", DoubleToString(slPrice, digits),
            " (risk $", DoubleToString(minLotRisk, 2), " -> $",
            DoubleToString(maxAcceptableRisk, 2), " on $", DoubleToString(balance, 2), ")");
   }
   else if (lotSize <= hardMin && minLotRisk > riskAmount) {
      Print("MIN-LOT: ", pair, " 0.1 lot risk $", DoubleToString(minLotRisk, 2),
            " (", DoubleToString(minLotRisk / balance * 100.0, 1), "% vs intended ",
            DoubleToString(RiskPercent, 1), "%)");
   }

   // ── Margin check: skip pair if 0.1 lot won't fit in free margin ──────
   double marginRequired = 0;
   if (OrderCalcMargin(orderType, pair, lotSize, openPrice, marginRequired)) {
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if (marginRequired > freeMargin * 0.80) {
         // Try the hard minimum (0.1) as last resort
         if (lotSize > hardMin) {
            lotSize = hardMin;
            if (!OrderCalcMargin(orderType, pair, lotSize, openPrice, marginRequired)) {
               Print("MARGIN SKIP: Cannot calculate margin for ", pair);
               return 0.0;
            }
         }
         if (marginRequired > freeMargin * 0.80) {
            Print("MARGIN SKIP: ", pair, " 0.1 lot needs $", DoubleToString(marginRequired, 2),
                  " margin, only $", DoubleToString(freeMargin, 2), " free. Skipping.");
            return 0.0;
         }
      }
   }

   Print("Symbol: ", pair,
         " Min: ", DoubleToString(hardMin, 2),
         " Max: ", DoubleToString(maxLot, 2),
         " Step: ", DoubleToString(stepLot, 2),
         " Lot: ", DoubleToString(lotSize, 2),
         " Bal: $", DoubleToString(balance, 2));
   return lotSize;
}

double CalculateTrueLeverage(double additionalLots, string pair) {
   double marginUsed = AccountInfoDouble(ACCOUNT_MARGIN);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if (!symbolInfo.Name(pair)) return 0.0;
   double contractSize = symbolInfo.ContractSize();
   double tickValue = symbolInfo.TickValue();
   double additionalMargin = additionalLots * contractSize * SymbolInfoDouble(pair, SYMBOL_BID) / tickValue;
   return (marginUsed + additionalMargin) / equity;
}

double GetDynamicSlippage(string sym, int idx) {
   if (idx < 0 || idx >= totalPairs || ArraySize(cachedATR) <= idx) {
      Print("Invalid index ", idx, " for slippage in ", sym);
      return MaxSlippagePips;
   }
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   double atrPips = cachedATR[idx] / point;
   double slippage = MathMin(MaxSlippagePips * 10, atrPips * 2.5);
   Print("Slippage for ", sym, ": ", slippage, " points (ATR: ", atrPips, ")");
   return slippage;
}

bool CheckLiquidity(string pair) {
   Print("Assuming sufficient liquidity for ", pair);
   return true;
}

double GetAdjustedCarryRate(string pair) {
   double swapLong = SymbolInfoDouble(pair, SYMBOL_SWAP_LONG);
   double swapShort = SymbolInfoDouble(pair, SYMBOL_SWAP_SHORT);
   MqlDateTime timeStruct;
   TimeToStruct(TimeCurrent(), timeStruct);
   if (timeStruct.day_of_week == 3) { // Triple swaps on Wednesday
      swapLong *= 3.0;
      swapShort *= 3.0;
   }
   return (swapLong > swapShort) ? swapLong : swapShort;
}

void CalculateVWAP(int idx, string symbol) {
   if (idx < 0 || idx >= totalPairs || ArraySize(cachedVWAP) <= idx) return;
   double high[], low[], close[];
   long volumes[];
   ArraySetAsSeries(high, true); ArraySetAsSeries(low, true);
   ArraySetAsSeries(close, true); ArraySetAsSeries(volumes, true);
   if (CopyHigh(symbol, PERIOD_M15, 0, VWAP_Period, high) < VWAP_Period ||
       CopyLow(symbol, PERIOD_M15, 0, VWAP_Period, low) < VWAP_Period ||
       CopyClose(symbol, PERIOD_M15, 0, VWAP_Period, close) < VWAP_Period ||
       CopyTickVolume(symbol, PERIOD_M15, 0, VWAP_Period, volumes) < VWAP_Period) return;
   double sumPriceVolume = 0.0, sumVolume = 0.0;
   double typicalPrices[]; ArrayResize(typicalPrices, VWAP_Period);
   for (int i = 0; i < VWAP_Period; i++) {
      double typicalPrice = (high[i] + low[i] + close[i]) / 3.0;
      sumPriceVolume += typicalPrice * (double)volumes[i];
      sumVolume += (double)volumes[i];
      typicalPrices[i] = typicalPrice;
   }
   if (sumVolume > 0) {
      cachedVWAP[idx] = sumPriceVolume / sumVolume;
      double sumVariance = 0.0;
      for (int i = 0; i < VWAP_Period; i++)
         sumVariance += MathPow(typicalPrices[i] - cachedVWAP[idx], 2) * (double)volumes[i];
      double std_dev = MathSqrt(sumVariance / sumVolume);
      cachedVWAPUpper[idx] = cachedVWAP[idx] + VWAP_Bands_Multiplier * std_dev;
      cachedVWAPLower[idx] = cachedVWAP[idx] - VWAP_Bands_Multiplier * std_dev;
   }
}

void ValidateDynamicPairList() {
   for (int i = ArraySize(dynamicPairList) - 1; i >= 0; i--) {
      if (!SymbolInfoDouble(dynamicPairList[i], SYMBOL_BID)) {
         Print("Removing invalid symbol: ", dynamicPairList[i]);
         ArrayRemove(dynamicPairList, i);
      }
   }
   totalPairs = ArraySize(dynamicPairList);
   if (totalPairs == 0) {
      Print("No valid symbols in dynamicPairList. EA will not trade.");
      tradingEnabled = false;
   }
}

void ArrayRemove(string &arr[], int index) {
   int size = ArraySize(arr);
   if (index < 0 || index >= size) return;
   string temp[];
   ArrayResize(temp, size - 1);
   for (int i = 0; i < index; i++) temp[i] = arr[i];
   for (int i = index + 1; i < size; i++) temp[i - 1] = arr[i];
   ArrayCopy(arr, temp);
}

// ── Per-symbol trading-hours check ───────────────────────────────────────────
// Forex:  allowed 07:45-12:15 UTC, 13:45-15:15 UTC, 16:45-20:15 UTC
//         (night 21:00-06:00 + ±45 min session-transition buffers excluded)
// Crypto: allowed all weekday hours except ±45 min session transitions
//         London-open(07:00), NY-open(13:00), London-close(16:00), NY-close(21:00)
// Sunday:  always blocked; Friday ≥ 21:00 UTC: blocked
bool IsTradingAllowedForSymbol(string sym) {
   if (BypassSessionFilter) return true;    // testing override
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt);
   int h = dt.hour, m = dt.min;
   int tod = h * 60 + m;                    // minutes-of-day in UTC

   // Weekend guards
   if (dt.day_of_week == 0) return false;   // Sunday always off
   if (dt.day_of_week == 5 && h >= 21) return false; // Friday close

   bool isCrypto = (StringFind(sym,"BTC")>=0 || StringFind(sym,"ETH")>=0 ||
                    StringFind(sym,"XRP")>=0 || StringFind(sym,"LTC")>=0);

   // Forex-only: hard night block 21:00-07:00 UTC
   if (!isCrypto && (h >= 21 || h < 7)) return false;

   // ±45 min buffers around session open/close times (UTC minutes-of-day)
   // London open 07:00 = 420, NY open 13:00 = 780,
   // London close 16:00 = 960, NY close 21:00 = 1260
   int boundaries[4] = {420, 780, 960, 1260};
   int buf = 45;
   for (int i = 0; i < 4; i++) {
      int diff = tod - boundaries[i];
      if (diff < -720) diff += 1440;
      if (diff >  720) diff -= 1440;
      if (MathAbs(diff) <= buf) return false;  // inside buffer window
   }
   return true;
}

// Legacy no-arg wrapper — used in the timer for global enable check
bool IsTradingAllowedNow() {
   if (BypassSessionFilter) return true;    // testing override
   MqlDateTime dt; TimeToStruct(TimeGMT(), dt);
   if (dt.day_of_week == 0) return false;
   if (dt.day_of_week == 5 && dt.hour >= 21) return false;
   return true;   // per-symbol check done in ScanAllStrategies
}

// ── Flash-crash / spread filter state (one slot per dynamic pair) ─────────
datetime g_flashCrashUntil[];        // block new opens until this time
double   g_recentSpreadAvg[];        // EMA of recent spread in points

// Classic Kelly: f* = (p*b - q) / b   where p=win rate, q=1-p, b=avg win:loss ratio
// Returns a DOWNWARD multiplier in [0.25, 1.0] applied to the risk-based lot.
// Low confidence → lower multiplier; insufficient edge → capped; high conf + good edge → 1.0.
double CalculateKellyMultiplier(double aiConfidence) {
   if(!UseKellySizing) return 1.0;
   double p = Kelly_RecentWinRate;
   double q = 1.0 - p;
   double b = (Kelly_AvgRR > 0.0) ? Kelly_AvgRR : 1.0;
   double f_star = (p * b - q) / b;                    // raw Kelly fraction
   if(f_star <= 0.0) return 0.25;                      // negative edge → smallest allowed size
   double kelly_f = MathMin(f_star, Kelly_FractionalCap);
   double frac_of_cap = kelly_f / Kelly_FractionalCap; // in (0, 1]

   // Confidence scaler — 0.70 gate → 0.0, perfect 1.0 → 1.0 (linear between)
   double conf_scale = (aiConfidence <= MinAIConfidence) ? 0.0
                      : (aiConfidence - MinAIConfidence) / MathMax(1.0 - MinAIConfidence, 1e-6);
   if(conf_scale > 1.0) conf_scale = 1.0;

   // Combined multiplier: never below 25% (so we still trade small at the gate), never above 100%
   double mult = frac_of_cap * (0.5 + 0.5 * conf_scale);
   if(mult < 0.25) mult = 0.25;
   if(mult > 1.0)  mult = 1.0;
   return mult;
}

// Reads CentralRiskEngine halt flag from Common Files (same path Predict333 uses).
bool IsGlobalHaltActive() {
   if(!FileIsExist(GlobalHaltFlagFile, FILE_COMMON)) return false;
   int h = FileOpen(GlobalHaltFlagFile, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h == INVALID_HANDLE) return false;
   string content = "";
   while(!FileIsEnding(h)) content += FileReadString(h);
   FileClose(h);
   return (StringFind(content, "\"halted\":true") >= 0 ||
           StringFind(content, "\"halted\": true") >= 0);
}

// Parses per-symbol JSON signal file written by Predict333 into a candidate signal.
// Returns true and fills signal/conf/price/sl/atr on success, false if missing/stale/malformed.
bool ReadSignalFromFile(string sym, string &outSignal, double &outConf, double &outPrice,
                       double &outSL, double &outATR) {
   outSignal = "hold"; outConf = 0.0; outPrice = 0.0; outSL = 0.0; outATR = 0.0;
   string path = SignalInDir + "\\" + sym + ".json";
   if(!FileIsExist(path, FILE_COMMON)) return false;
   int h = FileOpen(path, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h == INVALID_HANDLE) return false;
   string body = "";
   while(!FileIsEnding(h)) body += FileReadString(h);
   FileClose(h);
   if(StringLen(body) < 10) return false;

   // Minimal JSON scraper — same style as Predict333's parser
   int p = StringFind(body, "\"signal\":");
   if(p >= 0) {
      int s = StringFind(body, "\"", p+9) + 1;
      int e = StringFind(body, "\"", s);
      if(e > s) outSignal = StringSubstr(body, s, e-s);
   }
   p = StringFind(body, "\"confidence\":");
   if(p >= 0) {
      int s = p + 13; while(s<StringLen(body) && StringSubstr(body,s,1)==" ") s++;
      int c = StringFind(body,",",s); int b = StringFind(body,"}",s);
      int e = (c>=0 && c<b)?c:b;
      if(e>s) outConf = StringToDouble(StringSubstr(body,s,e-s));
   }
   p = StringFind(body, "\"price\":");
   if(p >= 0) {
      int s = p + 8; int c = StringFind(body,",",s); int b = StringFind(body,"}",s);
      int e = (c>=0 && c<b)?c:b;
      if(e>s) outPrice = StringToDouble(StringSubstr(body,s,e-s));
   }
   p = StringFind(body, "\"stop_loss\":");
   if(p >= 0) {
      int s = p + 12; int c = StringFind(body,",",s); int b = StringFind(body,"}",s);
      int e = (c>=0 && c<b)?c:b;
      if(e>s) outSL = StringToDouble(StringSubstr(body,s,e-s));
   }
   p = StringFind(body, "\"atr\":");
   if(p >= 0) {
      int s = p + 6; int c = StringFind(body,",",s); int b = StringFind(body,"}",s);
      int e = (c>=0 && c<b)?c:b;
      if(e>s) outATR = StringToDouble(StringSubstr(body,s,e-s));
   }
   // Staleness check — ignore signals older than 15 M15 bars (≈ 225 minutes)
   int tsPos = StringFind(body, "\"timestamp\":");
   if(tsPos >= 0) {
      int s = tsPos + 12; int c = StringFind(body,",",s); int b = StringFind(body,"}",s);
      int e = (c>=0 && c<b)?c:b;
      if(e>s) {
         long ts = StringToInteger(StringSubstr(body,s,e-s));
         if(ts > 0 && (TimeCurrent() - (datetime)ts) > 225*60) {
            Print("Stale signal file for ", sym, " (", (int)((TimeCurrent()-(datetime)ts)/60), " min old)");
            return false;
         }
      }
   }
   return (outSignal == "buy" || outSignal == "sell" || outSignal == "hold");
}

// Returns true if current spread is abnormally wide (news/thin-book protection).
bool IsSpreadTooWide(string sym, int idx) {
   double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(pt <= 0) return false;
   double now = (SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID)) / pt;
   if(idx < 0 || idx >= ArraySize(g_recentSpreadAvg)) return false;
   double avg = g_recentSpreadAvg[idx];
   if(avg <= 0.0) { g_recentSpreadAvg[idx] = now; return false; }
   // EMA with alpha=0.05 (slow smoothing, resistant to bursts)
   g_recentSpreadAvg[idx] = 0.95 * avg + 0.05 * now;
   if(now > avg * MaxSpreadMultiplier && now > 3.0) {
      Print("SPREAD BLOCK: ", sym, " spread=", DoubleToString(now,1),
            " points > avg ", DoubleToString(avg,1), " × ", DoubleToString(MaxSpreadMultiplier,1));
      return true;
   }
   return false;
}

// Detects a single-bar violent move (> FlashCrashATRMult × ATR). On trigger,
// sets a per-symbol cooldown so new opens are blocked for FlashCrashCooldownMin minutes.
bool IsFlashCrashActive(string sym, int idx) {
   if(idx < 0 || idx >= ArraySize(g_flashCrashUntil)) return false;
   if(TimeCurrent() < g_flashCrashUntil[idx]) return true;
   double atr = (idx < ArraySize(cachedATR)) ? cachedATR[idx] : 0.0;
   if(atr <= 0.0) return false;
   double h[], l[]; ArraySetAsSeries(h,true); ArraySetAsSeries(l,true);
   if(CopyHigh(sym, PERIOD_M15, 0, 1, h) < 1 || CopyLow(sym, PERIOD_M15, 0, 1, l) < 1) return false;
   double range = h[0] - l[0];
   if(range > atr * FlashCrashATRMult) {
      g_flashCrashUntil[idx] = TimeCurrent() + FlashCrashCooldownMin * 60;
      Print("FLASH CRASH: ", sym, " bar range ", DoubleToString(range,5),
            " > ATR*", DoubleToString(FlashCrashATRMult,1),
            " — blocking new opens ", FlashCrashCooldownMin, " min");
      return true;
   }
   return false;
}

// Convert "pips" (as the user understands them) to broker POINTS for comparison.
//   • 5-digit forex (EURUSD 1.23456) → 1 pip = 10 points
//   • 3-digit JPY   (USDJPY 123.456) → 1 pip = 10 points
//   • 2-digit gold  (XAUUSD 1800.12) → 1 pip = 10 points
//   • 4/2-digit legacy → 1 pip = 1  point
// This prevents the classic "TP1 fires at 2 pips instead of 20" bug.
double PipsToPoints(string sym, double pips) {
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double mult = (digits == 3 || digits == 5 || digits == 2 || digits == 6) ? 10.0 : 1.0;
   // Crypto often has >2 digits but tiny "pip" meaning; treat >=2 decimal like forex-5-dig
   if(StringFind(sym,"BTC")>=0 || StringFind(sym,"ETH")>=0 ||
      StringFind(sym,"XRP")>=0 || StringFind(sym,"LTC")>=0) mult = 1.0;
   return pips * mult;
}

void UpdateGARCHVolatility() {
   for (int i = 0; i < totalPairs; i++) {
      double price = SymbolInfoDouble(dynamicPairList[i], SYMBOL_BID);
      if (lastPrice[i] > 0) {
         double ret = MathLog(price / lastPrice[i]);
         double garch_var = garchOmega + garchAlpha * ret * ret + garchBeta * garchVolatility[i] * garchVolatility[i];
         garchVolatility[i] = MathSqrt(MathMax(garch_var, 1e-8));  // MathMax prevents zero/negative variance
      }
      lastPrice[i] = price;
   }
}

void MultiPartialExit() {
   for (int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if (!PositionSelectByTicket(ticket)) continue;

      string sym   = PositionGetString(POSITION_SYMBOL);
      int    type  = (int)PositionGetInteger(POSITION_TYPE);
      double op    = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double pts   = SymbolInfoDouble(sym, SYMBOL_POINT);
      int    digs  = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
      double currentPrice = (type == POSITION_TYPE_BUY)
                            ? SymbolInfoDouble(sym, SYMBOL_BID)
                            : SymbolInfoDouble(sym, SYMBOL_ASK);

      // ── 0. TIME-BASED STOP ───────────────────────────────────────
      // Close positions that have been open too long without meaningful
      // progress (hasn't hit TP1). Frees capital for fresher setups.
      if (MaxHoldHours > 0 && openTime > 0 && vol > 0) {
         int ageSec = (int)(TimeCurrent() - openTime);
         if (ageSec > MaxHoldHours * 3600) {
            double ageProfitPts = (type == POSITION_TYPE_BUY) ? (currentPrice - op) / pts
                                                              : (op - currentPrice) / pts;
            double tp1Pts_t = PipsToPoints(sym, PartialExitPips);
            if (ageProfitPts < tp1Pts_t) {
               if (trade.PositionClose(ticket))
                  Print("TIME STOP: #", ticket, " ", sym, " open ", ageSec/3600,
                        "h without TP1 — closed (profit=", DoubleToString(ageProfitPts,1), " pts)");
               continue; // go next ticket
            }
         }
      }

      // Look up ATR for this symbol
      int idx = ArraySearchString(dynamicPairList, sym);
      double atr = (idx >= 0 && cachedATR[idx] > 0) ? cachedATR[idx] : 0;

      // Profit measured in POINTS (broker's smallest price step)
      double profitPoints = (type == POSITION_TYPE_BUY) ? (currentPrice - op) / pts
                                                        : (op - currentPrice) / pts;
      // Convert pip-denominated inputs to the same units for correct comparison
      double tp1Points = PipsToPoints(sym, PartialExitPips);
      double tp2Points = PipsToPoints(sym, TP2Pips);
      double beOffsetPts = PipsToPoints(sym, BreakevenOffsetPips);

      // ── 1. PARTIAL CLOSE at TP1 ──────────────────────────────────
      // Close PartialClosePercent (default 50%) of position at TP1 level,
      // then move SL to breakeven + offset to cover slippage/fees.
      if (profitPoints >= tp1Points && profitPoints < tp2Points && vol > 0) {
         double stepLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
         double closeVolume = MathFloor(vol * PartialClosePercent / 100.0 / stepLot) * stepLot;
         if (closeVolume < stepLot) closeVolume = stepLot;
         if (closeVolume > vol) closeVolume = vol;
         if (closeVolume >= SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN)) {
            if (trade.PositionClosePartial(ticket, closeVolume)) {
               // Move SL to breakeven + offset (covers spread/fees/slippage)
               double beSL = (type == POSITION_TYPE_BUY)
                             ? NormalizeDouble(op + beOffsetPts * pts, digs)
                             : NormalizeDouble(op - beOffsetPts * pts, digs);
               // Only tighten SL, never widen
               bool shouldMove = (type == POSITION_TYPE_BUY) ? (beSL > sl) : (beSL < sl || sl == 0);
               if (shouldMove) trade.PositionModify(ticket, beSL, tp);
               Print("TP1 partial close: ", DoubleToString(closeVolume, 2), " lots of #", ticket,
                     ", SL→BE+", DoubleToString(BreakevenOffsetPips, 1), " pips");
            }
         }
      }
      // TP2: close half of remaining position
      else if (profitPoints >= tp2Points && vol > 0) {
         double stepLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
         double closeVolume = MathFloor(vol / 2.0 / stepLot) * stepLot;
         if (closeVolume < stepLot) closeVolume = stepLot;
         if (closeVolume > vol) closeVolume = vol;
         if (closeVolume >= SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN)) {
            if (trade.PositionClosePartial(ticket, closeVolume)) {
               Print("TP2 partial close: ", DoubleToString(closeVolume, 2), " lots of #", ticket);
            }
         }
      }

      // ── 2. BREAKEVEN SL ──────────────────────────────────────────
      // When price moves ATR * BreakevenTriggerATRMult in our favor,
      // lock in profit by moving SL to entry + offset (covers fees/slippage).
      if (atr > 0) {
         double beThreshold = atr * BreakevenTriggerATRMult;
         double profitDistance = (type == POSITION_TYPE_BUY) ? (currentPrice - op) : (op - currentPrice);

         if (profitDistance >= beThreshold) {
            double beSL = (type == POSITION_TYPE_BUY)
                          ? NormalizeDouble(op + beOffsetPts * pts, digs)
                          : NormalizeDouble(op - beOffsetPts * pts, digs);
            bool shouldMove = (type == POSITION_TYPE_BUY) ? (beSL > sl) : (beSL < sl || sl == 0);
            if (shouldMove) {
               if (trade.PositionModify(ticket, beSL, tp))
                  Print("Breakeven SL: #", ticket, " SL→", DoubleToString(beSL, digs));
            }
         }
      }

      // ── 3. TRAILING STOP ─────────────────────────────────────────
      // Once in profit, trail SL at ATR * TrailingStopATRMult behind price.
      // Only tightens — never moves SL further from price.
      if (atr > 0) {
         double trailDist = atr * TrailingStopATRMult;
         double profitDistance = (type == POSITION_TYPE_BUY) ? (currentPrice - op) : (op - currentPrice);

         // Only trail once we're at least trailDist in profit (avoids trailing on noise)
         if (profitDistance > trailDist) {
            double newSL;
            if (type == POSITION_TYPE_BUY) {
               newSL = NormalizeDouble(currentPrice - trailDist, digs);
               // Only move SL up, never down
               if (newSL > sl) {
                  if (trade.PositionModify(ticket, newSL, tp))
                     Print("Trailing SL: #", ticket, " SL→", DoubleToString(newSL, digs),
                           " (price=", DoubleToString(currentPrice, digs), ")");
               }
            } else {
               newSL = NormalizeDouble(currentPrice + trailDist, digs);
               // Only move SL down, never up
               if (newSL < sl || sl == 0) {
                  if (trade.PositionModify(ticket, newSL, tp))
                     Print("Trailing SL: #", ticket, " SL→", DoubleToString(newSL, digs),
                           " (price=", DoubleToString(currentPrice, digs), ")");
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Strategy signal functions                                        |
//+------------------------------------------------------------------+
bool HasMicroBreakoutSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UseMicroBreakout) return false;
   double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
   double filter = 0.3 * cachedATR[idx];
   MqlDateTime timeStruct; TimeToStruct(TimeCurrent(), timeStruct);
   int hour = timeStruct.hour;
   if (hour >= 8 && hour < 17) {
      if (tokyoHigh[idx] == 0 || tokyoLow[idx] == 0) return false;
      if (currentPrice > tokyoHigh[idx] + filter) {
         c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
         c.stopLoss = tokyoLow[idx]; c.takeProfit = currentPrice + (currentPrice - tokyoLow[idx]) * 2;
         c.strategyName = "MicroBreakout"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      } else if (currentPrice < tokyoLow[idx] - filter) {
         c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
         c.stopLoss = tokyoHigh[idx]; c.takeProfit = currentPrice - (tokyoHigh[idx] - currentPrice) * 2;
         c.strategyName = "MicroBreakout"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   }
   return false;
}

bool HasPullbackTrendSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UsePullbackTrend) return false;
   double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
   if (cachedEMAFast[idx] > cachedEMASlow[idx] && cachedADX[idx] > 30) {
      if (currentPrice <= cachedBBLower[idx]) {
         c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
         c.stopLoss = currentPrice - cachedATR[idx] * 2; c.takeProfit = currentPrice + cachedATR[idx] * 3;
         c.strategyName = "PullbackTrend"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   } else if (cachedEMAFast[idx] < cachedEMASlow[idx] && cachedADX[idx] > 30) {
      if (currentPrice >= cachedBBUpper[idx]) {
         c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
         c.stopLoss = currentPrice + cachedATR[idx] * 2; c.takeProfit = currentPrice - cachedATR[idx] * 3;
         c.strategyName = "PullbackTrend"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   }
   return false;
}

bool HasICTKillZoneSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UseICTKillZone) return false;
   MqlDateTime timeStruct; TimeToStruct(TimeCurrent(), timeStruct);
   int hour = timeStruct.hour;
   if ((hour >= 6 && hour < 10) || (hour >= 11 && hour < 15)) {
      double prevHigh = iHigh(pair, PERIOD_M15, 1); double prevLow = iLow(pair, PERIOD_M15, 1);
      double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
      if (currentPrice > prevHigh) {
         c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
         c.stopLoss = prevLow - cachedATR[idx]; c.takeProfit = currentPrice + 2 * cachedATR[idx];
         c.strategyName = "ICTKillZone"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      } else if (currentPrice < prevLow) {
         c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
         c.stopLoss = prevHigh + cachedATR[idx]; c.takeProfit = currentPrice - 2 * cachedATR[idx];
         c.strategyName = "ICTKillZone"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   }
   return false;
}

bool HasPO3Signal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UsePO3) return false;
   MqlDateTime timeStruct; TimeToStruct(TimeCurrent(), timeStruct);
   int hour = timeStruct.hour;
   if (hour >= 7 && hour < 10) {
      double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
      if (currentPrice > firstHigh[idx]) {
         c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
         c.stopLoss = firstLow[idx]; c.takeProfit = currentPrice + 1.5 * cachedATR[idx];
         c.strategyName = "PO3"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      } else if (currentPrice < firstLow[idx]) {
         c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
         c.stopLoss = firstHigh[idx]; c.takeProfit = currentPrice - 1.5 * cachedATR[idx];
         c.strategyName = "PO3"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   }
   return false;
}

bool HasPsychLevelsSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UsePsychLevels) return false;
   double psychLevel = MathRound(SymbolInfoDouble(pair, SYMBOL_BID) / 0.01) * 0.01;
   double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
   if (MathAbs(currentPrice - psychLevel) <= 0.5 * cachedATR[idx]) {
      if (cachedRSI[idx] < 25) {
         c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
         c.stopLoss = currentPrice - 2 * cachedATR[idx]; c.takeProfit = currentPrice + 3 * cachedATR[idx];
         c.strategyName = "PsychLevels"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      } else if (cachedRSI[idx] > 75) {
         c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
         c.stopLoss = currentPrice + 2 * cachedATR[idx]; c.takeProfit = currentPrice - 3 * cachedATR[idx];
         c.strategyName = "PsychLevels"; c.momentumScore = GetMomentumScore(pair, idx);
         c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
         return true;
      }
   }
   return false;
}

bool HasStatArbitrageSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UseStatArbitrage) return false;
   double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
   if (currentPrice < cachedBBLower[idx] && currentPrice < cachedVWAP[idx]) {
      c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
      c.stopLoss = currentPrice - 2 * cachedATR[idx]; c.takeProfit = cachedBBUpper[idx];
      c.strategyName = "StatArbitrage"; c.momentumScore = GetMomentumScore(pair, idx);
      c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
      return true;
   } else if (currentPrice > cachedBBUpper[idx] && currentPrice > cachedVWAP[idx]) {
      c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
      c.stopLoss = currentPrice + 2 * cachedATR[idx]; c.takeProfit = cachedBBLower[idx];
      c.strategyName = "StatArbitrage"; c.momentumScore = GetMomentumScore(pair, idx);
      c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
      return true;
   }
   return false;
}

bool HasCarryTradeSignal(string pair, int idx, FXJEFE_CandidateTrade &c) {
   if (!UseCarryTrade) return false;
   double swapLong = SymbolInfoDouble(pair, SYMBOL_SWAP_LONG);
   double swapShort = SymbolInfoDouble(pair, SYMBOL_SWAP_SHORT);
   double currentPrice = SymbolInfoDouble(pair, SYMBOL_BID);
   double carryRate = GetAdjustedCarryRate(pair);
   if (swapLong > 0 && currentPrice > cachedEMASlow[idx] && carryRate > 0.1) {
      c.pair = pair; c.orderType = ORDER_TYPE_BUY; c.openPrice = currentPrice;
      c.stopLoss = cachedEMASlow[idx] - cachedATR[idx]; c.takeProfit = currentPrice + 2 * cachedATR[idx];
      c.strategyName = "CarryTrade"; c.momentumScore = GetMomentumScore(pair, idx);
      c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
      return true;
   } else if (swapShort > 0 && currentPrice < cachedEMASlow[idx] && carryRate > 0.1) {
      c.pair = pair; c.orderType = ORDER_TYPE_SELL; c.openPrice = currentPrice;
      c.stopLoss = cachedEMASlow[idx] + cachedATR[idx]; c.takeProfit = currentPrice - 2 * cachedATR[idx];
      c.strategyName = "CarryTrade"; c.momentumScore = GetMomentumScore(pair, idx);
      c.lotSize = CalculateLotSize(pair, c.stopLoss, c.openPrice, c.orderType);
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| FetchSentiment — GET /predict/sentiment?symbol=BASE             |
//+------------------------------------------------------------------+
double FetchSentiment(string symbol)
{
   string base = symbol;
   StringReplace(base, ".r", "");
   StringReplace(base, ".R", "");
   string url = AI_SENTIMENT_URL + "?symbol=" + base;
   char dummy[], result[];
   string result_headers;
   int res = WebRequest("GET", url, "", 5000, dummy, result, result_headers);
   if(res == 200)
   {
      string resp = CharArrayToString(result, 0, -1, CP_UTF8);
      int pos = StringFind(resp, "\"sentiment\":");
      if(pos >= 0)
      {
         string val = StringSubstr(resp, pos + 13);
         StringReplace(val, "}", "");
         StringTrimRight(val);
         return StringToDouble(val);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
//| ComputeExtendedFeatures — updates all M1 model feature caches    |
//| Called once per M15 bar for each symbol                         |
//+------------------------------------------------------------------+
void ComputeExtendedFeatures(int idx, string sym)
{
   if(idx < 0 || idx >= totalPairs) return;

   // ROC
   { double p[]; ArraySetAsSeries(p, true);
     if(CopyClose(sym, PERIOD_M1, 0, 15, p) >= 15 && p[14] != 0)
        cachedROC[idx] = ((p[0] - p[14]) / p[14]) * 100.0;
   }
   // CCI (M1)
   { double b[]; ArraySetAsSeries(b, true);
     int h = iCCI(sym, PERIOD_M1, 14, PRICE_TYPICAL);
     if(CopyBuffer(h, 0, 0, 1, b) > 0) cachedCCI[idx] = b[0];
     IndicatorRelease(h);
   }
   // Williams %R (M1)
   { double b[]; ArraySetAsSeries(b, true);
     int h = iWPR(sym, PERIOD_M1, 14);
     if(CopyBuffer(h, 0, 0, 1, b) > 0) cachedWilliams[idx] = b[0];
     IndicatorRelease(h);
   }
   // Momentum
   { double p[]; ArraySetAsSeries(p, true);
     if(CopyClose(sym, PERIOD_M1, 0, 15, p) >= 15)
        cachedMomentum[idx] = p[0] - p[14];
   }
   // Realized Volatility (M1 log returns)
   { double closes[]; ArraySetAsSeries(closes, true);
     if(CopyClose(sym, PERIOD_M1, 0, 15, closes) >= 15)
     {
        double returns[]; ArrayResize(returns, 14);
        bool ok = true;
        for(int j = 0; j < 14; j++) {
           if(closes[j+1] <= 0) { ok = false; break; }
           returns[j] = MathLog(closes[j] / closes[j+1]);
        }
        if(ok) {
           // Manual std-dev (replaces MathStandardDeviation — no Math\Stat\Math.mqh needed)
           double _mean = 0.0;
           for(int _k = 0; _k < 14; _k++) _mean += returns[_k];
           _mean /= 14.0;
           double _var = 0.0;
           for(int _k = 0; _k < 14; _k++) _var += (returns[_k] - _mean) * (returns[_k] - _mean);
           _var /= 14.0;
           cachedRealizedVol[idx] = MathSqrt(_var) * MathSqrt(252.0 * 60.0);
        }
     }
   }
   // Chaikin Volatility (M1)
   { double h1[], l1[], h2[], l2[];
     ArraySetAsSeries(h1,true); ArraySetAsSeries(l1,true);
     ArraySetAsSeries(h2,true); ArraySetAsSeries(l2,true);
     if(CopyHigh(sym, PERIOD_M1, 0,  14, h1) >= 14 && CopyLow(sym, PERIOD_M1, 0,  14, l1) >= 14 &&
        CopyHigh(sym, PERIOD_M1, 14, 14, h2) >= 14 && CopyLow(sym, PERIOD_M1, 14, 14, l2) >= 14)
     {
        double range = 0.0, prev_range = 0.0;
        for(int j = 0; j < 14; j++) { range += h1[j]-l1[j]; prev_range += h2[j]-l2[j]; }
        if(prev_range > 0) cachedChaikinVol[idx] = ((range - prev_range) / prev_range) * 100.0;
     }
   }
   // RVI (M1)
   { double close[], open[];
     ArraySetAsSeries(close, true); ArraySetAsSeries(open, true);
     if(CopyClose(sym, PERIOD_M1, 0, 14, close) >= 14 && CopyOpen(sym, PERIOD_M1, 0, 14, open) >= 14)
     {
        double co_sum = 0.0, sq_sum = 0.0;
        for(int j = 0; j < 14; j++) { co_sum += close[j]-open[j]; sq_sum += MathPow(close[j],2); }
        double denom = MathSqrt(sq_sum / 14.0);
        if(denom > 0) cachedRVI[idx] = (co_sum / 14.0) / denom;
     }
   }
   // OBV (M1, last bar delta)
   { double closes[]; long tvol[];
     ArraySetAsSeries(closes, true); ArraySetAsSeries(tvol, true);
     if(CopyClose(sym, PERIOD_M1, 0, 2, closes) >= 2 && CopyTickVolume(sym, PERIOD_M1, 0, 1, tvol) >= 1)
     {
        double prev = cachedOBV[idx];
        if(closes[0] > closes[1])      cachedOBV[idx] = prev + (double)tvol[0];
        else if(closes[0] < closes[1]) cachedOBV[idx] = prev - (double)tvol[0];
     }
   }
   // Volume Delta (M1)
   { long tvol[]; ArraySetAsSeries(tvol, true);
     if(CopyTickVolume(sym, PERIOD_M1, 0, 1, tvol) >= 1)
     {
        double pc = iClose(sym, PERIOD_M1, 0) - iOpen(sym, PERIOD_M1, 0);
        cachedVolumeDelta[idx] = pc >= 0 ? (double)tvol[0] : -(double)tvol[0];
     }
   }
   // AD Line (M1, running sum)
   { double c = iClose(sym,PERIOD_M1,0), h = iHigh(sym,PERIOD_M1,0), l = iLow(sym,PERIOD_M1,0);
     long tvol[]; ArraySetAsSeries(tvol, true);
     if(CopyTickVolume(sym, PERIOD_M1, 0, 1, tvol) >= 1)
     {
        double mfm = (h==l) ? 0.0 : ((c-l)-(h-c))/(h-l);
        cachedADLine[idx] += mfm * (double)tvol[0];
     }
   }
   // Volume Oscillator (M1)
   { long tvol[]; ArraySetAsSeries(tvol, true);
     if(CopyTickVolume(sym, PERIOD_M1, 0, 14, tvol) >= 14)
     {
        double sma5 = 0.0, sma14 = 0.0;
        for(int j = 0; j < 5;  j++) sma5  += (double)tvol[j];
        for(int j = 0; j < 14; j++) sma14 += (double)tvol[j];
        sma5 /= 5.0; sma14 /= 14.0;
        if(sma14 > 0) cachedVolOsc[idx] = (sma5 - sma14) / sma14;
     }
   }
   // Supertrend (Unified v5.03 — hl2 bands, price-level output on M15 to match Predict333)
   cachedSupertrend[idx] = UnifiedCalcSupertrend(idx, sym, PERIOD_M15, 10, 3.0, atrHandles[idx], 0);
   // HMA (Unified v5.03 — full 3-stage, M15 to match Predict333)
   cachedHMA[idx] = UnifiedCalcHMA(sym, PERIOD_M15, 9, 0);
   // Ichimoku Tenkan (M1, period=9)
   { double high[], low[]; ArraySetAsSeries(high, true); ArraySetAsSeries(low, true);
     if(CopyHigh(sym, PERIOD_M1, 0, 9, high) >= 9 && CopyLow(sym, PERIOD_M1, 0, 9, low) >= 9)
     {
        double hmax = high[0], lmin = low[0];
        for(int j = 1; j < 9; j++) { if(high[j] > hmax) hmax = high[j]; if(low[j] < lmin) lmin = low[j]; }
        cachedIchimokuTenkan[idx] = (hmax + lmin) / 2.0;
     }
   }
   // SAR (M1)
   { double b[]; ArraySetAsSeries(b, true);
     int h = iSAR(sym, PERIOD_M1, 0.02, 0.2);
     if(CopyBuffer(h, 0, 0, 1, b) > 0) cachedSAR[idx] = b[0];
     IndicatorRelease(h);
   }
   // DPO (Unified v5.03 — period=20, displacement=11, M15 to match Predict333)
   cachedDPO[idx] = UnifiedCalcDPO(sym, PERIOD_M15, 20, 0);
   // Spread
   { double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
     double bid = SymbolInfoDouble(sym, SYMBOL_BID);
     double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
     cachedSpread[idx] = pt > 0 ? (ask - bid) / pt : 0.0;
   }
   // Sentiment from server
   cachedSentiment[idx] = FetchSentiment(sym);
}

//+------------------------------------------------------------------+
//| CallAIAPI — full-feature call to golden model server              |
//| Sends all 28 config features + garch_vol so golden server can    |
//| route to xgb_6 (6-feat), ensemble_9 (9-feat), rf_28 (28-feat)   |
//+------------------------------------------------------------------+
string CallAIAPI(string symbol, int idx) {
   // M15 model: refresh every bar (900 s)
   if (TimeCurrent() - last_api_call[idx] < 900) {
      return last_good_signal[idx];
   }
   if (idx < 0 || idx >= totalPairs) {
      Print("Invalid index ", idx, " for ", symbol);
      return "hold";
   }

   double price      = SymbolInfoDouble(symbol, SYMBOL_BID);
   double atr        = (ArraySize(cachedATR)      > idx && cachedATR[idx]      > 0) ? cachedATR[idx]      : 0.001;
   double ema_diff   = (ArraySize(cachedEMAFast)  > idx && ArraySize(cachedEMASlow) > idx)
                       ? cachedEMAFast[idx] - cachedEMASlow[idx] : 0.0;
   double rsi        = (ArraySize(cachedRSI)      > idx) ? cachedRSI[idx]      : 50.0;
   double macd_diff  = (ArraySize(cachedMACD)     > idx && ArraySize(cachedMACDSignal) > idx)
                       ? cachedMACD[idx] - cachedMACDSignal[idx] : 0.0;
   double garch_vol  = (ArraySize(garchVolatility)> idx) ? garchVolatility[idx]: 0.0;
   double vwap       = (ArraySize(cachedVWAP)     > idx && cachedVWAP[idx]     > 0) ? cachedVWAP[idx]     : price;
   double bb_range   = (ArraySize(cachedBBUpper)  > idx && ArraySize(cachedBBLower) > idx)
                       ? (cachedBBUpper[idx] - cachedBBLower[idx]) : 0.0;
   double bb_pos     = (bb_range > 0 && ArraySize(cachedBBLower) > idx)
                       ? (price - cachedBBLower[idx]) / bb_range : 0.5;

   // Full 28-feature JSON — golden server extracts 6/9/28 subsets per model
   string json = "{";
   json += "\"symbol\":\""       + symbol                                + "\",";
   json += "\"timeframe\":\"M15\",";
   json += "\"price\":"          + DoubleToString(price,     5)          + ",";
   json += "\"atr\":"            + DoubleToString(atr,       8)          + ",";
   json += "\"ema_diff\":"       + DoubleToString(ema_diff,  8)          + ",";
   json += "\"rsi\":"            + DoubleToString(rsi,       4)          + ",";
   json += "\"macd_diff\":"      + DoubleToString(macd_diff, 8)          + ",";
   json += "\"garch_vol\":"      + DoubleToString(garch_vol, 8)          + ",";
   json += "\"vwap\":"           + DoubleToString(vwap,      5)          + ",";
   json += "\"price_vwap_diff\":"+ DoubleToString(price - vwap, 8)       + ",";
   json += "\"bb_position\":"    + DoubleToString(bb_pos,    6)          + ",";
   json += "\"roc\":"            + DoubleToString((ArraySize(cachedROC)>idx)?cachedROC[idx]:0.0,      6) + ",";
   json += "\"stochastic\":"     + DoubleToString((ArraySize(cachedStochK)>idx)?cachedStochK[idx]:50.0, 4) + ",";
   json += "\"cci\":"            + DoubleToString((ArraySize(cachedCCI)>idx)?cachedCCI[idx]:0.0,      4) + ",";
   json += "\"williams\":"       + DoubleToString((ArraySize(cachedWilliams)>idx)?cachedWilliams[idx]:-50.0, 4) + ",";
   json += "\"momentum\":"       + DoubleToString((ArraySize(cachedMomentum)>idx)?cachedMomentum[idx]:0.0, 8) + ",";
   json += "\"realized_vol\":"   + DoubleToString((ArraySize(cachedRealizedVol)>idx)?cachedRealizedVol[idx]:0.0, 8) + ",";
   json += "\"chaikin_vol\":"    + DoubleToString((ArraySize(cachedChaikinVol)>idx)?cachedChaikinVol[idx]:0.0, 6) + ",";
   json += "\"adx\":"            + DoubleToString((ArraySize(cachedADX)>idx)?cachedADX[idx]:0.0,      4) + ",";
   json += "\"rvi\":"            + DoubleToString((ArraySize(cachedRVI)>idx)?cachedRVI[idx]:0.0,      6) + ",";
   json += "\"obv\":"            + DoubleToString((ArraySize(cachedOBV)>idx)?cachedOBV[idx]:0.0,      2) + ",";
   json += "\"volume_delta\":"   + DoubleToString((ArraySize(cachedVolumeDelta)>idx)?cachedVolumeDelta[idx]:0.0, 2) + ",";
   json += "\"ad_line\":"        + DoubleToString((ArraySize(cachedADLine)>idx)?cachedADLine[idx]:0.0, 2) + ",";
   json += "\"vol_osc\":"        + DoubleToString((ArraySize(cachedVolOsc)>idx)?cachedVolOsc[idx]:0.0, 6) + ",";
   json += "\"supertrend\":"     + DoubleToString((ArraySize(cachedSupertrend)>idx)?cachedSupertrend[idx]:0.0, 4) + ",";
   json += "\"hma\":"            + DoubleToString((ArraySize(cachedHMA)>idx)?cachedHMA[idx]:price,    5) + ",";
   json += "\"ichimoku_tenkan\":"+ DoubleToString((ArraySize(cachedIchimokuTenkan)>idx)?cachedIchimokuTenkan[idx]:price, 5) + ",";
   json += "\"sar\":"            + DoubleToString((ArraySize(cachedSAR)>idx)?cachedSAR[idx]:price,    5) + ",";
   json += "\"dpo\":"            + DoubleToString((ArraySize(cachedDPO)>idx)?cachedDPO[idx]:0.0,      8) + ",";
   json += "\"spread\":"         + DoubleToString((ArraySize(cachedSpread)>idx)?cachedSpread[idx]:0.0, 2) + ",";
   // Sentiment is the LAST base feature; close with comma instead of } to append lag-1 block.
   double curSentiment = (ArraySize(cachedSentiment)>idx)?cachedSentiment[idx]:0.0;
   json += "\"sentiment\":"      + DoubleToString(curSentiment, 4) + ",";

   // ─── 14 lag-1 columns (43-feature contract) ──────────────────────────
   // These complete the server's "full" feature set. The values are the
   // previous call's reading per pair, saved at the end of this function.
   // On the first call per symbol the lag values are 0.0 (seed). Server's
   // 43-feat tuned models (xgb_43_tuned/rf_43_tuned/mlp_43_tuned) consume
   // these. Models requiring 29 features ignore the extras.
   // ──────────────────────────────────────────────────────────────────────
   json += "\"price_lag1\":"        + DoubleToString(g_lag1_price[idx],         5) + ",";
   json += "\"atr_lag1\":"          + DoubleToString(g_lag1_atr[idx],           8) + ",";
   json += "\"ema_diff_lag1\":"     + DoubleToString(g_lag1_ema_diff[idx],      8) + ",";
   json += "\"rsi_lag1\":"          + DoubleToString(g_lag1_rsi[idx],           4) + ",";
   json += "\"garch_vol_lag1\":"    + DoubleToString(g_lag1_garch_vol[idx],     8) + ",";
   json += "\"macd_diff_lag1\":"    + DoubleToString(g_lag1_macd_diff[idx],     8) + ",";
   json += "\"bb_position_lag1\":"  + DoubleToString(g_lag1_bb_position[idx],   6) + ",";
   json += "\"roc_lag1\":"          + DoubleToString(g_lag1_roc[idx],           6) + ",";
   json += "\"momentum_lag1\":"     + DoubleToString(g_lag1_momentum[idx],      8) + ",";
   json += "\"realized_vol_lag1\":" + DoubleToString(g_lag1_realized_vol[idx],  8) + ",";
   json += "\"adx_lag1\":"          + DoubleToString(g_lag1_adx[idx],           4) + ",";
   json += "\"supertrend_lag1\":"   + DoubleToString(g_lag1_supertrend[idx],    4) + ",";
   json += "\"dpo_lag1\":"          + DoubleToString(g_lag1_dpo[idx],           8) + ",";
   json += "\"sentiment_lag1\":"    + DoubleToString(g_lag1_sentiment[idx],     4) + "}";

   // Save the current call's values so the NEXT call uses them as lag-1.
   g_lag1_price[idx]        = price;
   g_lag1_atr[idx]          = atr;
   g_lag1_ema_diff[idx]     = ema_diff;
   g_lag1_rsi[idx]          = rsi;
   g_lag1_garch_vol[idx]    = garch_vol;
   g_lag1_macd_diff[idx]    = macd_diff;
   g_lag1_bb_position[idx]  = bb_pos;
   g_lag1_roc[idx]          = (ArraySize(cachedROC)>idx)?cachedROC[idx]:0.0;
   g_lag1_momentum[idx]     = (ArraySize(cachedMomentum)>idx)?cachedMomentum[idx]:0.0;
   g_lag1_realized_vol[idx] = (ArraySize(cachedRealizedVol)>idx)?cachedRealizedVol[idx]:0.0;
   g_lag1_adx[idx]          = (ArraySize(cachedADX)>idx)?cachedADX[idx]:0.0;
   g_lag1_supertrend[idx]   = (ArraySize(cachedSupertrend)>idx)?cachedSupertrend[idx]:0.0;
   g_lag1_dpo[idx]          = (ArraySize(cachedDPO)>idx)?cachedDPO[idx]:0.0;
   g_lag1_sentiment[idx]    = curSentiment;

   Print("JSON sent to API for ", symbol, " (43-feat payload, +14 lag1): price=", DoubleToString(price,5),
         " rsi=", DoubleToString(rsi,1), " atr=", DoubleToString(atr,6));

   string headers = "Content-Type: application/json\r\n";
   char post[];
   int jsonLength = StringLen(json);
   ArrayResize(post, jsonLength);
   StringToCharArray(json, post, 0, jsonLength, CP_UTF8);

   char result[];
   string response_headers;
   int maxRetries = 3;
   for (int retry = 0; retry < maxRetries; retry++) {
      int res = WebRequest("POST", AI_API_URL, headers, 10000, post, result, response_headers);
      string response = CharArrayToString(result, 0, -1, CP_UTF8);
      if (res == 200) {
         last_api_call[idx] = TimeCurrent();
         Print("API response for ", symbol, ": ", response);

         // Parse confidence from JSON: "confidence":0.XX
         double confidence = 0.0;
         int confPos = StringFind(response, "\"confidence\":");
         if (confPos >= 0) {
            string confStr = StringSubstr(response, confPos + 14);
            int comma = StringFind(confStr, ",");
            int brace = StringFind(confStr, "}");
            int endPos = (comma >= 0 && comma < brace) ? comma : brace;
            if (endPos > 0) confStr = StringSubstr(confStr, 0, endPos);
            confidence = StringToDouble(confStr);
         }

         // Parse signal
         string rawSignal = "hold";
         if (StringFind(response, "\"buy\"") >= 0)       rawSignal = "buy";
         else if (StringFind(response, "\"sell\"") >= 0) rawSignal = "sell";

         // -------- STRICT WINNER-ONLY FILTER (2026-05-18) ---------------
         // The server now returns enforce_winner/winner_rr/winner_ev/
         // winner_selected from the TradeOutcomeEngineer. Only accept a
         // trade when ALL of these clear, plus the legacy MinAIConfidence
         // floor. This is the prop-account PF protection — we were
         // bleeding at PF 0.38 on 91 trades because the old filter only
         // checked raw confidence.
         //
         // Backward compatibility: if the server doesn't return these
         // fields (older /predict), fall back to the original confidence
         // check so the EA keeps working against any server version.
         // ---------------------------------------------------------------
         bool   enforceWinner = (StringFind(response, "\"enforce_winner\":true")  >= 0);
         bool   winnerSelected = (StringFind(response, "\"winner_selected\":true") >= 0);
         double winnerRR = 0.0, winnerEV = 0.0, futureGate = MinAIConfidence;

         int rrPos = StringFind(response, "\"winner_rr\":");
         if (rrPos >= 0) {
            string rrStr = StringSubstr(response, rrPos + 12);
            int rrEnd = StringFind(rrStr, ","); if (rrEnd < 0) rrEnd = StringFind(rrStr, "}");
            if (rrEnd > 0) winnerRR = StringToDouble(StringSubstr(rrStr, 0, rrEnd));
         }
         int evPos = StringFind(response, "\"winner_ev\":");
         if (evPos >= 0) {
            string evStr = StringSubstr(response, evPos + 12);
            int evEnd = StringFind(evStr, ","); if (evEnd < 0) evEnd = StringFind(evStr, "}");
            if (evEnd > 0) winnerEV = StringToDouble(StringSubstr(evStr, 0, evEnd));
         }
         int fgPos = StringFind(response, "\"future_gate\":");
         if (fgPos >= 0) {
            string fgStr = StringSubstr(response, fgPos + 14);
            int fgEnd = StringFind(fgStr, ","); if (fgEnd < 0) fgEnd = StringFind(fgStr, "}");
            if (fgEnd > 0) futureGate = StringToDouble(StringSubstr(fgStr, 0, fgEnd));
         }

         bool serverReturnsWinnerFields = (rrPos >= 0);  // detects new server

         if (rawSignal != "hold") {
            if (serverReturnsWinnerFields) {
               // New server with TradeOutcomeEngineer — strict winner-only.
               // Inputs PropMinWinnerRR + PropRequireWinnerFlag let you
               // tune the strictness from the EA panel without recompile.
               bool winnerOK = (!PropRequireWinnerFlag) || (enforceWinner && winnerSelected);
               if (!winnerOK || winnerRR < PropMinWinnerRR || confidence < 0.55) {
                  Print("WINNER REJECT [", symbol, "] sig=", rawSignal,
                        " conf=", DoubleToString(confidence, 3),
                        " rr=",   DoubleToString(winnerRR, 2),
                        " ev=",   DoubleToString(winnerEV, 5),
                        " gate=", DoubleToString(futureGate, 3),
                        " enforce=", (enforceWinner ? "1" : "0"));
                  rawSignal = "hold";
               } else {
                  Print("WINNER ACCEPT [", symbol, "] sig=", rawSignal,
                        " conf=", DoubleToString(confidence, 3),
                        " rr=",   DoubleToString(winnerRR, 2),
                        " ev=",   DoubleToString(winnerEV, 5),
                        " gate=", DoubleToString(futureGate, 3),
                        " WINNER SELECTED — PF PROTECTED");
               }
            } else {
               // Legacy server — fall back to original confidence-only check
               if (confidence < MinAIConfidence) {
                  Print("Signal ", rawSignal, " rejected for ", symbol,
                        ": confidence ", DoubleToString(confidence, 2),
                        " < ", DoubleToString(MinAIConfidence, 2));
                  rawSignal = "hold";
               }
            }
         }

         last_good_signal[idx]    = rawSignal;
         last_good_signal_time[idx] = TimeCurrent();
         // Store confidence so ScanAllStrategies can rank AI candidates
         if (ArraySize(last_ai_confidence) > idx)
            last_ai_confidence[idx] = (rawSignal != "hold") ? confidence : 0.0;
         return last_good_signal[idx];
      } else {
         Print("API call failed for ", symbol, ". HTTP: ", res, ", Error: ", GetLastError(), ". Retry ", retry+1, "/", maxRetries);
         Sleep(1000);
      }
   }
   Print("API call failed for ", symbol, " after ", maxRetries, " attempts. Using last signal: ", last_good_signal[idx]);
   return last_good_signal[idx];
}

//+------------------------------------------------------------------+
//| LogFeatures — logs basic M15 indicators for local strategy use   |
//+------------------------------------------------------------------+
void LogFeatures() {
   if (!UseCSVLogging) { Print("CSV logging disabled."); return; }
   string file_path = "FXJEFE_Features.csv";
   string log_file_path = "FXJEFE_log.txt";
   int csvHandle = FileOpen(file_path, FILE_READ | FILE_WRITE | FILE_CSV | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if (csvHandle == INVALID_HANDLE) {
      csvHandle = FileOpen(file_path, FILE_READ | FILE_WRITE | FILE_CSV | FILE_COMMON, ',');
      if (csvHandle == INVALID_HANDLE) {
         Print("Failed to open CSV: ", file_path, " Error: ", GetLastError()); return;
      }
      Print("Opened CSV in common folder: ", file_path);
   } else {
      Print("Opened CSV: ", file_path);
   }
   int logHandle = FileOpen(log_file_path, FILE_READ | FILE_WRITE | FILE_TXT | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if (logHandle != INVALID_HANDLE) FileSeek(logHandle, 0, SEEK_END);

   FileSeek(csvHandle, 0, SEEK_END);
   if (FileTell(csvHandle) == 0) {
      // FIX: header now matches all 27 model features + price + extras
      FileWrite(csvHandle,
         "time,symbol,price,"
         "atr,ema_diff,rsi,macd_diff,vwap,price_vwap_diff,bb_position,"
         "roc,stochastic,cci,williams,momentum,realized_vol,chaikin_vol,"
         "adx,rvi,obv,volume_delta,ad_line,vol_osc,supertrend,hma,"
         "ichimoku_tenkan,sar,dpo,spread,sentiment,signal");
      Print("Wrote CSV header.");
   }

   int rowsWritten = 0;
   for (int i = 0; i < totalPairs; i++) {
      string sym = dynamicPairList[i];
      if (!SymbolInfoDouble(sym, SYMBOL_BID)) { Print("Invalid symbol: ", sym, ". Skipping."); continue; }
      double price       = SymbolInfoDouble(sym, SYMBOL_BID);
      double ema_diff    = MathIsValidNumber(cachedEMAFast[i]) && MathIsValidNumber(cachedEMASlow[i])
                              ? cachedEMAFast[i] - cachedEMASlow[i] : 0.0;
      double macd_diff   = MathIsValidNumber(cachedMACD[i]) && MathIsValidNumber(cachedMACDSignal[i])
                              ? cachedMACD[i] - cachedMACDSignal[i] : 0.0;
      double pv_diff     = cachedVWAP[i] > 0 ? price - cachedVWAP[i] : 0.0;
      double bb_pos      = (cachedBBUpper[i] > cachedBBLower[i])
                              ? (price - cachedBBLower[i]) / (cachedBBUpper[i] - cachedBBLower[i]) : 0.5;
      string timestamp   = TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES | TIME_SECONDS);
      string signal      = last_good_signal[i];

      Print("Writing for ", sym, ": price=", price, ", atr=", cachedATR[i], ", signal=", signal);

      // FIX: all 27 model feature columns written in correct order
      FileWrite(csvHandle,
         timestamp, sym, DoubleToString(price, 5),
         DoubleToString(cachedATR[i], 8),           DoubleToString(ema_diff, 8),
         DoubleToString(cachedRSI[i], 2),            DoubleToString(macd_diff, 8),
         DoubleToString(cachedVWAP[i], 5),           DoubleToString(pv_diff, 5),
         DoubleToString(bb_pos, 5),
         DoubleToString(cachedROC[i], 4),            DoubleToString(cachedStochK[i], 2),
         DoubleToString(cachedCCI[i], 2),            DoubleToString(cachedWilliams[i], 2),
         DoubleToString(cachedMomentum[i], 8),       DoubleToString(cachedRealizedVol[i], 8),
         DoubleToString(cachedChaikinVol[i], 4),
         DoubleToString(cachedADX[i], 2),            DoubleToString(cachedRVI[i], 8),
         DoubleToString(cachedOBV[i], 0),            DoubleToString(cachedVolumeDelta[i], 0),
         DoubleToString(cachedADLine[i], 0),         DoubleToString(cachedVolOsc[i], 4),
         DoubleToString(cachedSupertrend[i], 2),     DoubleToString(cachedHMA[i], 5),
         DoubleToString(cachedIchimokuTenkan[i], 5), DoubleToString(cachedSAR[i], 5),
         DoubleToString(cachedDPO[i], 8),            DoubleToString(cachedSpread[i], 2),
         DoubleToString(cachedSentiment[i], 4),      signal);
      rowsWritten++;
      Print("Wrote features for ", sym, " to ", file_path);

      if (logHandle != INVALID_HANDLE) {
         string logEntry = timestamp + " Features for " + sym + ": price=" + DoubleToString(price, 5) +
                           ", atr=" + DoubleToString(cachedATR[i], 8) + ", signal=" + signal;
         FileWrite(logHandle, logEntry);
      }
   }

   FileFlush(csvHandle); FileClose(csvHandle);
   Print("Closed CSV. Rows written: ", rowsWritten);
   if (logHandle != INVALID_HANDLE) { FileFlush(logHandle); FileClose(logHandle); }
}

void LogTradeOpen(const FXJEFE_CandidateTrade &tradeData) {
   if (!UseCSVLogging) return;
   string file_path = "FXJEFE_trades.csv";
   int handle = FileOpen(file_path, FILE_CSV | FILE_WRITE | FILE_READ | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if (handle == INVALID_HANDLE) handle = FileOpen(file_path, FILE_CSV | FILE_WRITE | FILE_READ | FILE_COMMON, ',');
   if (handle != INVALID_HANDLE) {
      FileSeek(handle, 0, SEEK_END);
      if (FileTell(handle) == 0)
         FileWrite(handle, "positionId,timestamp,symbol,strategy,orderType,volume,price,sl,tp");
      string orderTypeStr = (tradeData.orderType == ORDER_TYPE_BUY) ? "BUY" : "SELL";
      ulong ticket = trade.ResultOrder();
      FileWrite(handle, ticket, TimeToString(TimeCurrent()), tradeData.pair, tradeData.strategyName,
                orderTypeStr, DoubleToString(tradeData.lotSize, 2), DoubleToString(tradeData.openPrice, 5),
                DoubleToString(tradeData.stopLoss, 5), DoubleToString(tradeData.takeProfit, 5));
      FileClose(handle);
   }
}

void LogTradeOutcome(ulong dealTicket, string symbol, string strategy, double profit) {
   if (!UseCSVLogging) return;
   string file_path = "FXJEFE_trades_outcomes.csv";
   int handle = FileOpen(file_path, FILE_CSV | FILE_WRITE | FILE_READ | FILE_SHARE_READ | FILE_SHARE_WRITE, ',');
   if (handle == INVALID_HANDLE) handle = FileOpen(file_path, FILE_CSV | FILE_WRITE | FILE_READ | FILE_COMMON, ',');
   if (handle != INVALID_HANDLE) {
      FileSeek(handle, 0, SEEK_END);
      if (FileTell(handle) == 0)
         FileWrite(handle, "dealTicket,timestamp,symbol,strategy,profit");
      FileWrite(handle, dealTicket, TimeToString(TimeCurrent()), symbol, strategy, DoubleToString(profit, 2));
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Enhanced trade filters                                           |
//+------------------------------------------------------------------+

// Consecutive loss circuit breaker: pause trading after N losses in a row
bool IsConsecLossPaused() {
   if (!UseConsecLossBreaker) return false;
   if (g_consecutiveLosses >= ConsecLossPause) {
      if (g_consecLossPauseUntil == 0) {
         g_consecLossPauseUntil = TimeCurrent() + ConsecLossPauseHours * 3600;
         Print("CIRCUIT BREAKER: ", g_consecutiveLosses, " consecutive losses. Pausing until ",
               TimeToString(g_consecLossPauseUntil, TIME_DATE | TIME_MINUTES));
      }
      if (TimeCurrent() < g_consecLossPauseUntil) return true;
      // Pause expired, reset
      g_consecLossPauseUntil = 0;
      g_consecutiveLosses = 0;
      Print("Circuit breaker lifted. Resuming trading.");
   }
   return false;
}

// Session-based lot sizing multiplier
double GetSessionLotMultiplier() {
   if (!UseSessionSizing) return 1.0;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hour = dt.hour;
   int dow = dt.day_of_week;

   // Weekend (Saturday/Sunday) - crypto only
   if (dow == 0 || dow == 6) return SessionMultWeekend;

   // Asian session: 00:00-07:59 UTC
   if (hour >= 0 && hour < 8) return SessionMultAsian;

   // London session: 08:00-12:59 UTC
   if (hour >= 8 && hour < 13) return SessionMultLondon;

   // NY overlap + US session: 13:00-16:59 UTC
   if (hour >= 13 && hour < 17) return SessionMultNY;

   // Late US / pre-Asian: 17:00-23:59 UTC
   return SessionMultAsian;
}

// Round number avoidance: skip trades near psychological levels
bool IsNearRoundNumber(string sym, double price) {
   if (!UseRoundNumberFilter) return false;
   if (price <= 0) return false;

   double roundLevel = 0;
   // Determine round number interval based on price magnitude
   if (price > 10000)       roundLevel = 5000;    // BTC: 80000, 85000, 90000
   else if (price > 1000)   roundLevel = 500;     // ETH: 1500, 2000, 2500
   else if (price > 100)    roundLevel = 50;      // XAU: 2000, 2050
   else if (price > 10)     roundLevel = 5;       // JPY: 150, 155
   else                     roundLevel = 0.05;    // EUR: 1.05, 1.10

   double nearest = MathRound(price / roundLevel) * roundLevel;
   double distPct = MathAbs(price - nearest) / price;

   if (distPct < RoundNumberPct) {
      Print("Round number filter: ", sym, " price ", DoubleToString(price, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
            " too close to ", DoubleToString(nearest, 2), " (", DoubleToString(distPct * 100, 2), "%)");
      return true;
   }
   return false;
}

// Multi-timeframe confirmation: check H1 EMA direction
// Returns 1 for bullish H1, -1 for bearish H1, 0 for neutral
int GetH1TrendDirection(string sym, int idx) {
   if (!UseMultiTFConfirm) return 0;  // disabled = no filter
   if (idx < 0 || idx >= totalPairs) return 0;
   if (h1EmaHandles[idx] == INVALID_HANDLE) return 0;

   double ema[2];
   if (CopyBuffer(h1EmaHandles[idx], 0, 0, 2, ema) < 2) return 0;

   // EMA rising = bullish, falling = bearish
   if (ema[0] > ema[1]) return 1;   // current > previous = uptrend
   if (ema[0] < ema[1]) return -1;  // current < previous = downtrend
   return 0;
}

// Check if trade direction aligns with H1 trend
bool PassesMultiTFFilter(string sym, int idx, ENUM_ORDER_TYPE orderType) {
   if (!UseMultiTFConfirm) return true;
   int h1Trend = GetH1TrendDirection(sym, idx);
   if (h1Trend == 0) return true;  // no data = pass

   // Buy must align with bullish H1, sell with bearish H1
   if (orderType == ORDER_TYPE_BUY && h1Trend < 0) {
      Print("Multi-TF filter: ", sym, " BUY rejected - H1 trend is bearish");
      return false;
   }
   if (orderType == ORDER_TYPE_SELL && h1Trend > 0) {
      Print("Multi-TF filter: ", sym, " SELL rejected - H1 trend is bullish");
      return false;
   }
   return true;
}

double CalculatePairCorrelation(string pair1, string pair2, int period) {
   double prices1[], prices2[];
   ArraySetAsSeries(prices1, true); ArraySetAsSeries(prices2, true);
   if (CopyClose(pair1, PERIOD_M15, 0, period, prices1) < period ||
       CopyClose(pair2, PERIOD_M15, 0, period, prices2) < period) return 0.0;
   double mean1 = 0.0, mean2 = 0.0;
   for(int i = 0; i < period; i++) { mean1 += prices1[i]; mean2 += prices2[i]; }
   mean1 /= period; mean2 /= period;
   double cov = 0.0, var1 = 0.0, var2 = 0.0;
   for(int i = 0; i < period; i++) {
      double d1 = prices1[i] - mean1, d2 = prices2[i] - mean2;
      cov += d1 * d2; var1 += d1 * d1; var2 += d2 * d2;
   }
   if(var1 == 0.0 || var2 == 0.0) return 0.0;
   return cov / (MathSqrt(var1) * MathSqrt(var2));
}

bool CheckCorrelationLimit(FXJEFE_CandidateTrade &candidate) {
   for (int i = 0; i < PositionsTotal(); i++) {
      if (positionInfo.SelectByTicket(PositionGetTicket(i))) {
         string existingPair = positionInfo.Symbol();
         if (existingPair != candidate.pair) {
            double corr = CalculatePairCorrelation(candidate.pair, existingPair, 20);
            if (MathAbs(corr) > MaxCorrelation) {
               Print("Trade rejected: High correlation (", corr, ") between ", candidate.pair, " and ", existingPair);
               return false;
            }
         }
      }
   }
   return true;
}

void ScanAllStrategies(FXJEFE_CandidateTrade &candidates[]) {
   ArrayResize(candidates, 0);

   // Circuit breaker: skip all scanning if paused after consecutive losses
   if (IsConsecLossPaused()) return;

   for (int i = 0; i < totalPairs; i++) {
      string sym = dynamicPairList[i];

      // Skip if broker has closed this symbol for trading right now
      ENUM_SYMBOL_TRADE_MODE tradeMode = (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
      if (tradeMode != SYMBOL_TRADE_MODE_FULL && tradeMode != SYMBOL_TRADE_MODE_LONGONLY &&
          tradeMode != SYMBOL_TRADE_MODE_SHORTONLY) continue;

      // Skip if outside allowed trading hours for this symbol (night / session transitions)
      if (!IsTradingAllowedForSymbol(sym)) continue;

      if (!CheckLiquidity(sym)) continue;

      // Round number filter: skip if price is too close to psychological level
      double currentBid = SymbolInfoDouble(sym, SYMBOL_BID);
      if (IsNearRoundNumber(sym, currentBid)) continue;

      // Trade-hygiene gates (wide spread, flash-crash cooldown)
      if (IsSpreadTooWide(sym, i)) continue;
      if (IsFlashCrashActive(sym, i)) continue;

      FXJEFE_CandidateTrade c;
      if (SignalMode == Strategies_Only || SignalMode == Both) {
         if (HasMicroBreakoutSignal(sym, i, c) && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasPullbackTrendSignal(sym, i, c) && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasICTKillZoneSignal(sym, i, c)   && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasPO3Signal(sym, i, c)            && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasPsychLevelsSignal(sym, i, c)   && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasStatArbitrageSignal(sym, i, c) && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         if (HasCarryTradeSignal(sym, i, c)    && c.lotSize > 0 && CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
      }
      if (SignalMode == AI_Only || SignalMode == Both) {
         string aiSignal = "hold";
         double fileConf = 0.0, filePrice = 0.0, fileSL = 0.0, fileATR = 0.0;
         bool   fromFile = false;
         // Prefer the JSON file written by Predict333 (decoupled, no WebRequest per bar)
         if (UseAISignals && UseSignalFileReader &&
             ReadSignalFromFile(sym, aiSignal, fileConf, filePrice, fileSL, fileATR))
         {
            fromFile = true;
            if (ArraySize(last_ai_confidence) > i) last_ai_confidence[i] = fileConf;
            // Apply the 0.70 gate here too (defense in depth)
            if (aiSignal != "hold" && fileConf < MinAIConfidence) {
               Print("SIG-FILE gate: ", sym, " conf=", DoubleToString(fileConf,4),
                     " < ", DoubleToString(MinAIConfidence,2));
               aiSignal = "hold";
            }
         }
         // Fallback to direct WebRequest if file is missing or reader disabled
         if (!fromFile && UseAISignals) aiSignal = CallAIAPI(sym, i);

         if (aiSignal != "hold") {
            c.pair = sym; c.strategyName = fromFile ? "AI_Signal(file)" : "AI_Signal(http)";
            c.orderType  = (aiSignal == "buy") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
            c.openPrice  = (c.orderType == ORDER_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
            double atrForSL = (fromFile && fileATR > 0.0) ? fileATR : cachedATR[i];
            c.stopLoss   = (c.orderType == ORDER_TYPE_BUY) ? c.openPrice - atrForSL * 2 : c.openPrice + atrForSL * 2;
            // If the server sent an explicit SL and it's tighter than ATR*2, respect it
            if (fromFile && fileSL > 0.0) {
               if (c.orderType == ORDER_TYPE_BUY  && fileSL > c.stopLoss && fileSL < c.openPrice) c.stopLoss = fileSL;
               if (c.orderType == ORDER_TYPE_SELL && fileSL < c.stopLoss && fileSL > c.openPrice) c.stopLoss = fileSL;
            }
            c.takeProfit = (c.orderType == ORDER_TYPE_BUY) ? c.openPrice + atrForSL * 3 : c.openPrice - atrForSL * 3;
            c.lotSize    = CalculateLotSize(sym, c.stopLoss, c.openPrice, c.orderType);
            // Recalculate TP proportionally if SL was clamped (maintain Kelly_AvgRR R:R)
            double slDist = MathAbs(c.openPrice - c.stopLoss);
            c.takeProfit = (c.orderType == ORDER_TYPE_BUY) ? c.openPrice + slDist * Kelly_AvgRR : c.openPrice - slDist * Kelly_AvgRR;
            if (c.lotSize <= 0) { Print("Skipping AI trade ", sym, ": lot=0 (micro protection)"); continue; }
            double aiConf = (fromFile ? fileConf
                            : (ArraySize(last_ai_confidence) > i && last_ai_confidence[i] > 0
                                  ? last_ai_confidence[i] : 0.65));
            c.momentumScore = aiConf;
            if (CheckCorrelationLimit(c) && PassesMultiTFFilter(sym, i, c.orderType)) ArrayAppend(candidates, c);
         }
      }
   }
}

void ArrayAppend(FXJEFE_CandidateTrade &arr[], FXJEFE_CandidateTrade &item) {
   int size = ArraySize(arr); ArrayResize(arr, size + 1); arr[size] = item;
}

void VerifySymbolSpecs(string pair, double lotSize) {
   Print("Symbol: ", pair, " Min: ", SymbolInfoDouble(pair, SYMBOL_VOLUME_MIN),
         " Max: ", SymbolInfoDouble(pair, SYMBOL_VOLUME_MAX),
         " Step: ", SymbolInfoDouble(pair, SYMBOL_VOLUME_STEP),
         " Lot: ", lotSize);
}

void PickAndOpenBestTrades(FXJEFE_CandidateTrade &candidates[]) {
   int size = ArraySize(candidates);
   for (int i = 0; i < size - 1; i++) {
      for (int j = 0; j < size - i - 1; j++) {
         if (candidates[j].momentumScore < candidates[j+1].momentumScore) {
            FXJEFE_CandidateTrade temp = candidates[j]; candidates[j] = candidates[j+1]; candidates[j+1] = temp;
         }
      }
   }
   int tradesToOpen = MathMin(ArraySize(candidates), MaxOpenTrades - PositionsTotal());
   double sessionMult = GetSessionLotMultiplier();

   for (int i = 0; i < tradesToOpen; i++) {
      string cpair = candidates[i].pair;

      // Re-check market is open before sending (may have closed since scan)
      ENUM_SYMBOL_TRADE_MODE tm = (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(cpair, SYMBOL_TRADE_MODE);
      if (tm != SYMBOL_TRADE_MODE_FULL && tm != SYMBOL_TRADE_MODE_LONGONLY &&
          tm != SYMBOL_TRADE_MODE_SHORTONLY) {
         Print("SKIP: ", cpair, " market closed at execution time");
         continue;
      }

      // Apply session-based lot sizing and enforce 0.1 minimum + normalize
      double stepLot = SymbolInfoDouble(cpair, SYMBOL_VOLUME_STEP);
      double brokerMin = SymbolInfoDouble(cpair, SYMBOL_VOLUME_MIN);
      double hardMin   = NormalizeDouble(MathMax(brokerMin, 0.10), 2);
      // Kelly 2.0 multiplier (driven by AI confidence + recent-win-rate assumption)
      double kellyMult = CalculateKellyMultiplier(candidates[i].momentumScore);
      candidates[i].lotSize *= sessionMult * kellyMult;
      // Enforce Kelly_PerTradeCapPct — never risk more than this % of balance on one trade
      {
         double bal = AccountInfoDouble(ACCOUNT_BALANCE);
         double pv  = SymbolInfoDouble(cpair, SYMBOL_TRADE_TICK_VALUE);
         double pt  = SymbolInfoDouble(cpair, SYMBOL_POINT);
         double slPts = (pt > 0) ? MathAbs(candidates[i].openPrice - candidates[i].stopLoss) / pt : 0.0;
         if (bal > 0 && pv > 0 && slPts > 0) {
            double maxLotByCap = (bal * Kelly_PerTradeCapPct / 100.0) / (slPts * pv);
            if (candidates[i].lotSize > maxLotByCap) {
               Print("Kelly cap: ", cpair, " lot ", DoubleToString(candidates[i].lotSize,2),
                     " -> ", DoubleToString(maxLotByCap,2), " (", DoubleToString(Kelly_PerTradeCapPct,1), "% per-trade cap)");
               candidates[i].lotSize = maxLotByCap;
            }
         }
      }
      candidates[i].lotSize = NormalizeDouble(
         MathMax(hardMin, MathFloor(candidates[i].lotSize / stepLot) * stepLot), 2);
      Print("Sizing: ", cpair, " session=", DoubleToString(sessionMult,2),
            " kelly=", DoubleToString(kellyMult,2),
            " conf=", DoubleToString(candidates[i].momentumScore,3),
            " finalLot=", DoubleToString(candidates[i].lotSize,2));

      if (candidates[i].lotSize <= 0) continue;  // micro protection filtered this out
      VerifySymbolSpecs(cpair, candidates[i].lotSize);
      double leverage = CalculateTrueLeverage(candidates[i].lotSize, candidates[i].pair);
      if (leverage > MaxLeverage) candidates[i].lotSize *= MaxLeverage / leverage;
      double slippage = GetDynamicSlippage(candidates[i].pair, ArraySearchString(dynamicPairList, candidates[i].pair));
      trade.SetDeviationInPoints((long)(slippage / SymbolInfoDouble(candidates[i].pair, SYMBOL_POINT)));
      if (trade.PositionOpen(candidates[i].pair, candidates[i].orderType, candidates[i].lotSize,
                             candidates[i].openPrice, candidates[i].stopLoss, candidates[i].takeProfit,
                             candidates[i].strategyName)) {
         g_dailyTradesCount++;
         g_tradingDayActive = true;
         if (sessionMult < 1.0)
            Print("Session sizing: lot reduced by ", DoubleToString((1.0 - sessionMult) * 100, 0), "% (mult=", DoubleToString(sessionMult, 2), ")");
         LogTradeOpen(candidates[i]);
      }
   }
}

double CalculateVaR() {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double totalRisk = 0.0;
   for (int i = 0; i < PositionsTotal(); i++) {
      if (positionInfo.SelectByTicket(PositionGetTicket(i))) {
         string sym = positionInfo.Symbol();
         int idx = ArraySearchString(dynamicPairList, sym);
         if (idx >= 0) totalRisk += positionInfo.Volume() * cachedATR[idx] * SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      }
   }
   return (totalRisk / equity) * 100.0;
}

void CheckRiskLimits() {
   double var = CalculateVaR();
   if (var > MaxVaR_Pct) { Print("VaR limit exceeded: ", var, "% > ", MaxVaR_Pct, "%"); tradingEnabled = false; }
}

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit() {
   if (!CheckSecurityKey()) return INIT_FAILED;
   ValidateDynamicPairList();
   string currentSymbol = Symbol();
   int idx = ArraySearchString(dynamicPairList, currentSymbol);
   if (idx == -1)
      Print("Current symbol ", currentSymbol, " not in dynamicPairList. EA will monitor all pairs via timer.");

   // Resize M15 strategy arrays
   ArrayResize(atrHandles, totalPairs);      ArrayResize(emaFastHandles, totalPairs);  ArrayResize(emaSlowHandles, totalPairs);
   ArrayResize(rsiHandles, totalPairs);      ArrayResize(bbHandles, totalPairs);       ArrayResize(stochasticHandles, totalPairs);
   ArrayResize(macdHandles, totalPairs);     ArrayResize(adxHandles, totalPairs);
   ArrayResize(cachedATR, totalPairs);       ArrayResize(cachedEMAFast, totalPairs);   ArrayResize(cachedEMASlow, totalPairs);
   ArrayResize(cachedRSI, totalPairs);       ArrayResize(cachedBBUpper, totalPairs);   ArrayResize(cachedBBLower, totalPairs);
   ArrayResize(cachedStochK, totalPairs);    ArrayResize(cachedStochD, totalPairs);    ArrayResize(cachedMACD, totalPairs);
   ArrayResize(cachedMACDSignal, totalPairs); ArrayResize(cachedVWAP, totalPairs);     ArrayResize(cachedVWAPUpper, totalPairs);
   ArrayResize(cachedVWAPLower, totalPairs); ArrayResize(cachedADX, totalPairs);       ArrayResize(garchVolatility, totalPairs);

   // FIX: Resize all extended model feature arrays
   ArrayResize(cachedROC, totalPairs);           ArrayResize(cachedCCI, totalPairs);
   ArrayResize(cachedWilliams, totalPairs);       ArrayResize(cachedMomentum, totalPairs);
   ArrayResize(cachedRealizedVol, totalPairs);    ArrayResize(cachedChaikinVol, totalPairs);
   ArrayResize(cachedRVI, totalPairs);            ArrayResize(cachedOBV, totalPairs);
   ArrayResize(cachedVolumeDelta, totalPairs);    ArrayResize(cachedADLine, totalPairs);
   ArrayResize(cachedVolOsc, totalPairs);         ArrayResize(cachedSupertrend, totalPairs);
   ArrayResize(cachedHMA, totalPairs);            ArrayResize(cachedIchimokuTenkan, totalPairs);
   ArrayResize(cachedSAR, totalPairs);            ArrayResize(cachedDPO, totalPairs);
   ArrayResize(cachedSpread, totalPairs);         ArrayResize(cachedSentiment, totalPairs);

   // Lag-1 buffers (43-feat payload upgrade 2026-05-18)
   ArrayResize(g_lag1_price, totalPairs);         ArrayResize(g_lag1_atr, totalPairs);
   ArrayResize(g_lag1_ema_diff, totalPairs);      ArrayResize(g_lag1_rsi, totalPairs);
   ArrayResize(g_lag1_garch_vol, totalPairs);     ArrayResize(g_lag1_macd_diff, totalPairs);
   ArrayResize(g_lag1_bb_position, totalPairs);   ArrayResize(g_lag1_roc, totalPairs);
   ArrayResize(g_lag1_momentum, totalPairs);      ArrayResize(g_lag1_realized_vol, totalPairs);
   ArrayResize(g_lag1_adx, totalPairs);           ArrayResize(g_lag1_supertrend, totalPairs);
   ArrayResize(g_lag1_dpo, totalPairs);           ArrayResize(g_lag1_sentiment, totalPairs);
   ArrayInitialize(g_lag1_price, 0.0);            ArrayInitialize(g_lag1_atr, 0.0);
   ArrayInitialize(g_lag1_ema_diff, 0.0);         ArrayInitialize(g_lag1_rsi, 0.0);
   ArrayInitialize(g_lag1_garch_vol, 0.0);        ArrayInitialize(g_lag1_macd_diff, 0.0);
   ArrayInitialize(g_lag1_bb_position, 0.0);      ArrayInitialize(g_lag1_roc, 0.0);
   ArrayInitialize(g_lag1_momentum, 0.0);         ArrayInitialize(g_lag1_realized_vol, 0.0);
   ArrayInitialize(g_lag1_adx, 0.0);              ArrayInitialize(g_lag1_supertrend, 0.0);
   ArrayInitialize(g_lag1_dpo, 0.0);              ArrayInitialize(g_lag1_sentiment, 0.0);

   // Resize H1 EMA handles for multi-TF confirmation
   ArrayResize(h1EmaHandles, totalPairs);

   // Resize auxiliary arrays
   ArrayResize(last_api_call, totalPairs);  ArrayResize(lastPrice, totalPairs);    ArrayResize(lastTime, totalPairs);
   ArrayResize(last_good_signal, totalPairs); ArrayResize(last_good_signal_time, totalPairs);
   ArrayResize(last_ai_confidence, totalPairs);
   ArrayResize(tokyoHigh, totalPairs);      ArrayResize(tokyoLow, totalPairs);
   ArrayResize(lastKillZoneStart, totalPairs); ArrayResize(firstHigh, totalPairs); ArrayResize(firstLow, totalPairs);
   // Trade-hygiene filter state
   ArrayResize(g_flashCrashUntil, totalPairs);
   ArrayResize(g_recentSpreadAvg, totalPairs);

   for (int i = 0; i < totalPairs; i++) {
      cachedATR[i]=0.0; cachedEMAFast[i]=0.0; cachedEMASlow[i]=0.0; cachedRSI[i]=50.0;
      cachedBBUpper[i]=0.0; cachedBBLower[i]=0.0; cachedStochK[i]=0.0; cachedStochD[i]=0.0;
      cachedMACD[i]=0.0; cachedMACDSignal[i]=0.0; cachedVWAP[i]=0.0; cachedVWAPUpper[i]=0.0;
      cachedVWAPLower[i]=0.0; garchVolatility[i]=0.0; cachedADX[i]=0.0;
      cachedROC[i]=0.0; cachedCCI[i]=0.0; cachedWilliams[i]=-50.0; cachedMomentum[i]=0.0;
      cachedRealizedVol[i]=0.0; cachedChaikinVol[i]=0.0; cachedRVI[i]=0.0;
      cachedOBV[i]=0.0; cachedVolumeDelta[i]=0.0; cachedADLine[i]=0.0; cachedVolOsc[i]=0.0;
      cachedSupertrend[i]=0.0; cachedHMA[i]=0.0; cachedIchimokuTenkan[i]=0.0;
      cachedSAR[i]=0.0; cachedDPO[i]=0.0; cachedSpread[i]=0.0; cachedSentiment[i]=0.0;
      last_api_call[i]=0; lastPrice[i]=0.0; lastTime[i]=0; last_good_signal[i]="hold";
      last_good_signal_time[i]=0; last_ai_confidence[i]=0.0; tokyoHigh[i]=0.0; tokyoLow[i]=0.0;
      lastKillZoneStart[i]=0; firstHigh[i]=0.0; firstLow[i]=0.0;
      g_flashCrashUntil[i]=0; g_recentSpreadAvg[i]=0.0;
   }
   // Reset Unified Supertrend state (size-32 static arrays, not per-pair arrays)
   for(int _i = 0; _i < 32; _i++) { g_unified_st_prev[_i] = 0.0; g_unified_st_up[_i] = true; }

   // Init M15 indicator handles
   for (int i = 0; i < totalPairs; i++) {
      string sym = dynamicPairList[i];
      atrHandles[i]         = iATR(sym, PERIOD_M15, ATR_Period);
      emaFastHandles[i]     = iMA(sym, PERIOD_M15, EMA_Fast_Period, 0, MODE_EMA, PRICE_CLOSE);
      emaSlowHandles[i]     = iMA(sym, PERIOD_M15, EMA_Slow_Period, 0, MODE_EMA, PRICE_CLOSE);
      rsiHandles[i]         = iRSI(sym, PERIOD_M15, RSI_Period, PRICE_CLOSE);
      bbHandles[i]          = iBands(sym, PERIOD_M15, BB_Period, 0, BB_Deviation, PRICE_CLOSE);
      stochasticHandles[i]  = iStochastic(sym, PERIOD_M15, Stochastic_K, Stochastic_D, Stochastic_Slow, MODE_SMA, STO_LOWHIGH);
      macdHandles[i]        = iMACD(sym, PERIOD_M15, MACD_Fast, MACD_Slow, MACD_Signal, PRICE_CLOSE);
      adxHandles[i]         = iADX(sym, PERIOD_M15, 14);
      // H1 EMA for multi-timeframe confirmation
      h1EmaHandles[i] = iMA(sym, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);

      if (atrHandles[i]==INVALID_HANDLE || emaFastHandles[i]==INVALID_HANDLE || emaSlowHandles[i]==INVALID_HANDLE ||
          rsiHandles[i]==INVALID_HANDLE || bbHandles[i]==INVALID_HANDLE || stochasticHandles[i]==INVALID_HANDLE ||
          macdHandles[i]==INVALID_HANDLE || adxHandles[i]==INVALID_HANDLE) {
         Print("WARNING: Failed M15 indicators for ", sym, " (Error: ", GetLastError(), ") — removing from pair list");
         ArrayRemove(dynamicPairList, i);
         totalPairs = ArraySize(dynamicPairList);
         // Re-init needed: resize arrays and restart loop
         ArrayResize(atrHandles, totalPairs);      ArrayResize(emaFastHandles, totalPairs);  ArrayResize(emaSlowHandles, totalPairs);
         ArrayResize(rsiHandles, totalPairs);      ArrayResize(bbHandles, totalPairs);       ArrayResize(stochasticHandles, totalPairs);
         ArrayResize(macdHandles, totalPairs);     ArrayResize(adxHandles, totalPairs);      ArrayResize(h1EmaHandles, totalPairs);
         i--;  // retry this index (now holds next symbol)
         continue;
      }
      if (h1EmaHandles[i]==INVALID_HANDLE) {
         Print("Warning: H1 EMA handle failed for ", sym, " - multi-TF filter disabled for this pair");
      }
   }

   if (totalPairs == 0) {
      Print("ERROR: No valid pairs with indicator data. EA cannot run.");
      return INIT_FAILED;
   }
   Print("Initialized ", totalPairs, " pairs successfully.");

   // Determine initial balance: Custom > Enum > Broker
   if (AccountSize == Acct_Custom) {
      if (CustomAccountSize > 0)
         g_initialBalance = CustomAccountSize;
      else
         g_initialBalance = AccountInfoDouble(ACCOUNT_BALANCE);  // read from broker
      Print("Custom account size: $", DoubleToString(g_initialBalance, 2),
            " | Broker leverage: 1:", (int)AccountInfoInteger(ACCOUNT_LEVERAGE));
   } else {
      g_initialBalance = (double)AccountSize;
      if (MathAbs(AccountInfoDouble(ACCOUNT_BALANCE) - g_initialBalance) > 1.0)
         Print("Warning: Account balance $", DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
               " differs from AccountSize $", DoubleToString(g_initialBalance, 2));
   }

   // Phase_Live: no forced profit target or DD halt (user manages risk manually)
   if (PhaseType == Phase_Live) {
      g_totalProfitTarget = 0.0;
      Print("LIVE MODE: No profit target, no forced DD halt. Manual risk management.");
   } else {
      g_totalProfitTarget = g_initialBalance * (TotalProfitTargetPct / 100.0);
   }
   g_previousDayEquity  = g_initialBalance;
   g_maxDailyLoss       = g_previousDayEquity * 0.0333;  // 3.33% daily safety stop
   g_maxBalance         = AccountInfoDouble(ACCOUNT_BALANCE);
   g_dailyStartEquity   = AccountInfoDouble(ACCOUNT_EQUITY);
   g_lastEquityCheck    = g_dailyStartEquity;
   g_lastEquityTime     = g_lastDayReset = TimeCurrent();
   g_dailyProfit        = 0.0;
   g_tradingDaysCount   = 0;
   ArrayResize(g_tradingDays, 0);
   EventSetTimer(60);

   // Force initial M15 cache fill
   for (int i = 0; i < totalPairs; i++) {
      string sym = dynamicPairList[i];
      double temp[1];
      if (CopyBuffer(atrHandles[i],         0, 0, 1, temp) > 0) cachedATR[i]        = temp[0];
      if (CopyBuffer(emaFastHandles[i],      0, 0, 1, temp) > 0) cachedEMAFast[i]   = temp[0];
      if (CopyBuffer(emaSlowHandles[i],      0, 0, 1, temp) > 0) cachedEMASlow[i]   = temp[0];
      if (CopyBuffer(rsiHandles[i],          0, 0, 1, temp) > 0) cachedRSI[i]       = temp[0];
      if (CopyBuffer(bbHandles[i],           1, 0, 1, temp) > 0) cachedBBUpper[i]   = temp[0];
      if (CopyBuffer(bbHandles[i],           2, 0, 1, temp) > 0) cachedBBLower[i]   = temp[0];
      if (CopyBuffer(stochasticHandles[i],   0, 0, 1, temp) > 0) cachedStochK[i]    = temp[0];
      if (CopyBuffer(stochasticHandles[i],   1, 0, 1, temp) > 0) cachedStochD[i]    = temp[0];
      if (CopyBuffer(macdHandles[i],         0, 0, 1, temp) > 0) cachedMACD[i]      = temp[0];
      if (CopyBuffer(macdHandles[i],         1, 0, 1, temp) > 0) cachedMACDSignal[i]= temp[0];
      if (CopyBuffer(adxHandles[i],          0, 0, 1, temp) > 0) cachedADX[i]       = temp[0];
      CalculateVWAP(i, sym);
      ComputeExtendedFeatures(i, sym);   // FIX: init M1 model features
   }
   indicatorsInitialized = true;
   Print("All indicators initialized on startup.");
   LogFeatures();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   for (int i = 0; i < totalPairs; i++) {
      IndicatorRelease(atrHandles[i]);  IndicatorRelease(emaFastHandles[i]); IndicatorRelease(emaSlowHandles[i]);
      IndicatorRelease(rsiHandles[i]);  IndicatorRelease(bbHandles[i]);      IndicatorRelease(stochasticHandles[i]);
      IndicatorRelease(macdHandles[i]); IndicatorRelease(adxHandles[i]);
   }
   EventKillTimer();
   if (g_apiPipeOpen) apiPipe.Close();
}

void OnTimer() {
   if (g_timerRunning) return;
   g_timerRunning = true;
   if (!TerminalInfoInteger(TERMINAL_CONNECTED)) { g_timerRunning = false; return; }
   double currentEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   // ───── Prop-account PF protection (added 2026-05-18) ──────────────────
   // Two layers above and beyond the existing 3.33% daily DD stop:
   //   (1) Balance floor — detach the EA entirely if equity drops below the
   //       broker's hard threshold ($22,394.06 by default). Prevents auto-
   //       liquidation by violating the prop firm's max loss rule.
   //   (2) Early pause — disable new trades when today's loss exceeds
   //       PropEarlyPausePct (40%) of the broker's stated daily limit.
   //       Existing open positions are NOT closed here — only new entries
   //       are blocked. The 3.33% rule below still closes everything if
   //       loss continues.
   // ──────────────────────────────────────────────────────────────────────
   if (currentEquity < PropBalanceFloor) {
      Print("PROP BALANCE FLOOR BREACHED: equity $",
            DoubleToString(currentEquity, 2),
            " < floor $", DoubleToString(PropBalanceFloor, 2),
            " — EA detaching to prevent prop-rule violation");
      tradingEnabled = false;
      ExpertRemove();
      g_timerRunning = false;
      return;
   }
   double todayLoss = (g_dailyStartEquity > 0) ? (g_dailyStartEquity - currentEquity) : 0.0;
   if (todayLoss > PropDailyLimit * PropEarlyPausePct) {
      if (tradingEnabled) {
         Print("PROP EARLY PAUSE: today's loss $",
               DoubleToString(todayLoss, 2),
               " > ", DoubleToString(PropEarlyPausePct * 100, 0), "% of daily limit $",
               DoubleToString(PropDailyLimit, 2),
               " — new trades blocked (open positions remain managed)");
      }
      tradingEnabled = false;
   }
   MqlDateTime timeStruct; TimeToStruct(TimeCurrent(), timeStruct);
   datetime currentDay = TimeCurrent() - (timeStruct.hour * 3600 + timeStruct.min * 60 + timeStruct.sec);

   if (currentDay > g_lastDayReset) {
      g_previousDayEquity = currentEquity;
      g_maxDailyLoss      = g_previousDayEquity * 0.0333;  // Stop at 3.33% daily DD
      g_dailyStartEquity  = currentEquity;
      g_lastDayReset      = currentDay;
      if (g_tradingDayActive) {
         string dayStr = TimeToString(currentDay, TIME_DATE);
         if (ArraySearchString(g_tradingDays, dayStr) == -1) {
            int sz = ArraySize(g_tradingDays); ArrayResize(g_tradingDays, sz + 1);
            g_tradingDays[sz] = dayStr; g_tradingDaysCount++;
         }
      }
      g_tradingDayActive  = false;
      g_dailyTradesCount  = 0;
      tradingEnabled      = true;
   } else {
      g_dailyProfit = currentEquity - g_dailyStartEquity;
   }

   // Phase_Live: log DD but don't halt trading (user manages risk)
   // Challenge phases: halt on DD limits
   // 3.33% daily DD stop applies to ALL modes (FTMO safety + live protection)
   if (g_dailyProfit <= -g_maxDailyLoss) {
      tradingEnabled = false;
      Print("DAILY DD STOP: 3.33% daily limit reached ($", DoubleToString(-g_dailyProfit, 2),
            " loss today). Closing ALL positions and halting trading.");
      // Close all open positions immediately — do NOT leave them running
      for (int _i = PositionsTotal() - 1; _i >= 0; _i--) {
         ulong _t = PositionGetTicket(_i);
         if (!PositionSelectByTicket(_t)) continue;
         string _s = PositionGetString(POSITION_SYMBOL);
         ENUM_SYMBOL_TRADE_MODE _tm = (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(_s, SYMBOL_TRADE_MODE);
         if (_tm == SYMBOL_TRADE_MODE_FULL || _tm == SYMBOL_TRADE_MODE_LONGONLY ||
             _tm == SYMBOL_TRADE_MODE_SHORTONLY) {
            if (trade.PositionClose(_t))
               Print("DD stop closed: #", _t, " ", _s);
            else
               Print("DD stop FAILED to close: #", _t, " ", _s, " error=", GetLastError());
         }
      }
      g_timerRunning = false; return;
   }
   if (PhaseType != Phase_Live) {
      // FTMO/prop-firm: 10% total drawdown from initial balance
      double totalDrawdown = g_initialBalance - currentEquity;
      if (totalDrawdown >= g_initialBalance * 0.10) {
         tradingEnabled = false;
         Print("TOTAL DD STOP: 10% max drawdown reached ($", DoubleToString(totalDrawdown, 2),
               " from $", DoubleToString(g_initialBalance, 2), "). Trading halted.");
         g_timerRunning = false; return;
      }
   } else {
      // Live mode: warn at 10% total drawdown but keep trading
      double totalDrawdown = g_initialBalance - currentEquity;
      if (totalDrawdown >= g_initialBalance * 0.10)
         Print("WARNING: 10% total drawdown ($", DoubleToString(totalDrawdown, 2), "). Live mode — still trading.");
   }
   if (g_totalProfitTarget > 0 && currentEquity >= g_initialBalance + g_totalProfitTarget && !g_profitTargetReached) {
      g_profitTargetReached = true;
      for (int i = PositionsTotal() - 1; i >= 0; i--) {
         if (positionInfo.SelectByTicket(PositionGetTicket(i))) trade.PositionClose(PositionGetTicket(i));
      }
   }

   if (NewBar(PERIOD_M15)) {
      TimeToStruct(TimeCurrent(), timeStruct);
      if (timeStruct.hour == 0 && timeStruct.min < 15) {
         for (int i = 0; i < totalPairs; i++) {
            tokyoHigh[i] = iHigh(dynamicPairList[i], PERIOD_M15, 0);
            tokyoLow[i]  = iLow(dynamicPairList[i],  PERIOD_M15, 0);
         }
      }
      if (timeStruct.hour == 7 && timeStruct.min < 15) {
         for (int i = 0; i < totalPairs; i++) {
            firstHigh[i] = iHigh(dynamicPairList[i], PERIOD_M15, 0);
            firstLow[i]  = iLow(dynamicPairList[i],  PERIOD_M15, 0);
         }
      }
      for (int i = 0; i < totalPairs; i++) {
         if (iBars(dynamicPairList[i], PERIOD_M15) < 50) continue;
         string sym = dynamicPairList[i];
         double temp[1];
         if (CopyBuffer(atrHandles[i],         0, 0, 1, temp) > 0) cachedATR[i]         = temp[0]; else Print("Failed ATR ", sym);
         if (CopyBuffer(emaFastHandles[i],      0, 0, 1, temp) > 0) cachedEMAFast[i]    = temp[0]; else Print("Failed EMA Fast ", sym);
         if (CopyBuffer(emaSlowHandles[i],      0, 0, 1, temp) > 0) cachedEMASlow[i]    = temp[0]; else Print("Failed EMA Slow ", sym);
         if (CopyBuffer(rsiHandles[i],          0, 0, 1, temp) > 0) cachedRSI[i]        = temp[0]; else Print("Failed RSI ", sym);
         if (CopyBuffer(bbHandles[i],           1, 0, 1, temp) > 0) cachedBBUpper[i]    = temp[0]; else Print("Failed BB Upper ", sym);
         if (CopyBuffer(bbHandles[i],           2, 0, 1, temp) > 0) cachedBBLower[i]    = temp[0]; else Print("Failed BB Lower ", sym);
         if (CopyBuffer(stochasticHandles[i],   0, 0, 1, temp) > 0) cachedStochK[i]     = temp[0]; else Print("Failed Stoch K ", sym);
         if (CopyBuffer(stochasticHandles[i],   1, 0, 1, temp) > 0) cachedStochD[i]     = temp[0]; else Print("Failed Stoch D ", sym);
         if (CopyBuffer(macdHandles[i],         0, 0, 1, temp) > 0) cachedMACD[i]       = temp[0]; else Print("Failed MACD ", sym);
         if (CopyBuffer(macdHandles[i],         1, 0, 1, temp) > 0) cachedMACDSignal[i] = temp[0]; else Print("Failed MACD Signal ", sym);
         if (CopyBuffer(adxHandles[i],          0, 0, 1, temp) > 0) cachedADX[i]        = temp[0]; else Print("Failed ADX ", sym);
         CalculateVWAP(i, sym);
         ComputeExtendedFeatures(i, sym);   // FIX: update M1 model features each bar
      }
      UpdateGARCHVolatility();
      indicatorsInitialized = true;
      Print("Indicators updated for all pairs.");
      LogFeatures();
      CheckRiskLimits();
      if (tradingEnabled && IsTradingAllowedNow() && !IsGlobalHaltActive()) {
         int total = PositionsTotal();
         if (total < MaxOpenTrades && (!UseMaxDailyTrades || g_dailyTradesCount < MaxDailyTrades)) {
            FXJEFE_CandidateTrade cands[];
            ScanAllStrategies(cands);
            if (ArraySize(cands) > 0) PickAndOpenBestTrades(cands);
         }
      } else if (IsGlobalHaltActive()) {
         Print("CENTRAL RISK HALT — skipping scan/open cycle");
      }
   }
   MultiPartialExit();
   g_timerRunning = false;
}

void OnTradeTransaction(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result) {
   if (trans.type == TRADE_TRANSACTION_DEAL_ADD && (trans.deal_type == DEAL_TYPE_BUY || trans.deal_type == DEAL_TYPE_SELL)) {
      if (positionInfo.SelectByTicket(trans.position)) {
         double profit = positionInfo.Profit() + positionInfo.Swap() + positionInfo.Commission();
         LogTradeOutcome(trans.deal, positionInfo.Symbol(), positionInfo.Comment(), profit);
      }
   }
}
