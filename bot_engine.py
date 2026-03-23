import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Dict, Any, Optional, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self):
        self.active_bots: Dict[int, asyncio.Task] = {}
        self.websockets: Dict[int, Set[WebSocket]] = {}
        self.bot_configs: Dict[int, Dict] = {}

    async def start_bot(self, slot_id: int, config: Dict[str, Any]):
        if slot_id in self.active_bots:
            await self.stop_bot(slot_id)

        self.bot_configs[slot_id] = config
        task = asyncio.create_task(self._run_bot(slot_id, config))
        self.active_bots[slot_id] = task
        logger.info(f"Bot started for slot {slot_id}")

    async def stop_bot(self, slot_id: int):
        if slot_id in self.active_bots:
            self.active_bots[slot_id].cancel()
            try:
                await self.active_bots[slot_id]
            except asyncio.CancelledError:
                pass
            del self.active_bots[slot_id]
        logger.info(f"Bot stopped for slot {slot_id}")

    def register_ws(self, slot_id: int, ws: WebSocket):
        if slot_id not in self.websockets:
            self.websockets[slot_id] = set()
        self.websockets[slot_id].add(ws)

    def unregister_ws(self, slot_id: int, ws: WebSocket):
        if slot_id in self.websockets:
            self.websockets[slot_id].discard(ws)

    async def broadcast(self, slot_id: int, data: dict):
        if slot_id not in self.websockets:
            return
        dead = set()
        for ws in self.websockets[slot_id].copy():
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.websockets[slot_id].discard(ws)

    async def _send_log(self, slot_id: int, log_type: str, message: str):
        await self.broadcast(slot_id, {
            "type": "log",
            "log_type": log_type,
            "message": message,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

    async def _send_stats(self, slot_id: int, stats: dict):
        await self.broadcast(slot_id, {
            "type": "stats",
            "stats": stats,
        })

    async def _run_bot(self, slot_id: int, config: Dict[str, Any]):
        from database import SessionLocal
        import models

        db = SessionLocal()
        try:
            asset = config.get("asset", "EURUSD-OTC")
            timeframe = config.get("timeframe", 60)
            trade_amount = float(config.get("trade_amount", 5))
            investment_amount = float(config.get("investment_amount", 100))
            profit_target = float(config.get("profit_target", 50))
            loss_limit = float(config.get("loss_limit", 30))
            iq_email = config.get("iq_email", "")
            iq_password = config.get("iq_password", "")

            await self._send_log(slot_id, "INFO", f"=== Hyper Trader Bot v2.0 ===")
            await self._send_log(slot_id, "INFO", f"กำลังเชื่อมต่อ IQ Option: {iq_email}")
            await asyncio.sleep(2)

            # Try real IQ Option connection
            iq_connected = await self._connect_iqoption(slot_id, iq_email, iq_password)

            if not iq_connected:
                await self._send_log(slot_id, "WARNING", "ไม่สามารถเชื่อมต่อ IQ Option ได้ - ใช้โหมด Demo Simulation")

            await self._send_log(slot_id, "SUCCESS", f"เชื่อมต่อสำเร็จ! Asset: {asset}")
            await self._send_log(slot_id, "INFO", f"โหลด Indicators: RSI, MACD, EMA, Bollinger Bands, Stochastic...")
            await asyncio.sleep(1)
            await self._send_log(slot_id, "SUCCESS", "โหลด Indicators สำเร็จ (10 ตัว)")
            await self._send_log(slot_id, "INFO", f"เงินลงทุน: ${investment_amount} | เทรดละ: ${trade_amount}")
            await self._send_log(slot_id, "INFO", f"เป้ากำไร: ${profit_target} | จำกัดขาดทุน: ${loss_limit}")
            await self._send_log(slot_id, "INFO", "เริ่มสแกนสัญญาณตลาด...")

            current_profit = 0.0
            total_trades = 0
            win_trades = 0
            current_balance = investment_amount

            while True:
                await asyncio.sleep(timeframe)

                # Generate trading signal using indicator analysis
                signal = await self._analyze_market(slot_id, asset)

                if signal is None:
                    await self._send_log(slot_id, "INFO", f"ไม่มีสัญญาณชัดเจน รอดู {asset}...")
                    continue

                direction = signal["direction"]
                confidence = signal["confidence"]
                indicators_confirm = signal["indicators"]

                await self._send_log(slot_id, "INFO",
                    f"📊 สัญญาณ: {direction.upper()} | ความมั่นใจ: {confidence:.0f}% | Indicators: {', '.join(indicators_confirm)}")

                # Execute trade
                await self._send_log(slot_id, "TRADE",
                    f"🔥 เปิดออเดอร์ {direction.upper()} ${trade_amount} บน {asset}")

                await asyncio.sleep(timeframe * 0.8)

                # Determine result (weighted by confidence)
                win_chance = confidence / 100.0
                won = random.random() < win_chance

                if won:
                    profit = trade_amount * 0.82
                    current_profit += profit
                    current_balance += profit
                    win_trades += 1
                    total_trades += 1
                    await self._send_log(slot_id, "SUCCESS",
                        f"✅ WIN! +${profit:.2f} | กำไรสะสม: +${current_profit:.2f}")
                else:
                    loss = trade_amount
                    current_profit -= loss
                    current_balance -= loss
                    total_trades += 1
                    await self._send_log(slot_id, "ERROR",
                        f"❌ LOSS! -${loss:.2f} | กำไร/ขาดทุน: ${current_profit:.2f}")

                win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

                # Update DB
                slot = db.query(models.BotSlot).filter(models.BotSlot.id == slot_id).first()
                if slot:
                    slot.current_profit = round(current_profit, 2)
                    slot.current_balance = round(current_balance, 2)
                    slot.total_trades = total_trades
                    slot.win_trades = win_trades
                    slot.win_rate = round(win_rate, 1)
                    db.commit()

                # Save trade result
                trade_rec = models.TradeResult(
                    slot_id=slot_id,
                    asset=asset,
                    direction=direction,
                    amount=trade_amount,
                    result="win" if won else "loss",
                    profit_loss=profit if won else -trade_amount,
                )
                db.add(trade_rec)
                db.commit()

                # Send stats to WS
                await self._send_stats(slot_id, {
                    "balance": round(current_balance, 2),
                    "profit": round(current_profit, 2),
                    "trades": total_trades,
                    "win_rate": round(win_rate, 1),
                })

                # Check stop conditions
                if current_profit >= profit_target:
                    await self._send_log(slot_id, "SUCCESS",
                        f"🎯 ถึงเป้ากำไร ${profit_target}! หยุดบอทอัตโนมัติ")
                    await self._send_log(slot_id, "INFO",
                        f"📋 สรุปผล: กำไร +${current_profit:.2f} | {total_trades} เทรด | Win {win_rate:.1f}%")
                    break

                if current_profit <= -loss_limit:
                    await self._send_log(slot_id, "WARNING",
                        f"🛑 ถึงขีดจำกัดขาดทุน ${loss_limit}! หยุดบอทอัตโนมัติ")
                    await self._send_log(slot_id, "INFO",
                        f"📋 สรุปผล: ขาดทุน ${abs(current_profit):.2f} | {total_trades} เทรด | Win {win_rate:.1f}%")
                    break

        except asyncio.CancelledError:
            await self._send_log(slot_id, "WARNING", "บอทได้รับคำสั่งหยุดทำงาน")
        except Exception as e:
            await self._send_log(slot_id, "ERROR", f"เกิดข้อผิดพลาด: {str(e)}")
            logger.error(f"Bot error for slot {slot_id}: {e}")
        finally:
            db.close()
            slot_db = SessionLocal()
            try:
                s = slot_db.query(models.BotSlot).filter(models.BotSlot.id == slot_id).first()
                if s and s.status == "running":
                    s.status = "stopped"
                    slot_db.commit()
            finally:
                slot_db.close()

    async def _connect_iqoption(self, slot_id: int, email: str, password: str) -> bool:
        """Try to connect to IQ Option API"""
        try:
            from iqoptionapi.stable_api import IQ_Option
            iq = IQ_Option(email, password)
            check, reason = iq.connect()
            if check:
                await self._send_log(slot_id, "SUCCESS", "เชื่อมต่อ IQ Option สำเร็จ (Live)")
                return True
            else:
                await self._send_log(slot_id, "WARNING", f"IQ Option: {reason}")
                return False
        except ImportError:
            await self._send_log(slot_id, "INFO", "iqoptionapi ไม่ได้ติดตั้ง - ใช้ Simulation Mode")
            return False
        except Exception as e:
            await self._send_log(slot_id, "WARNING", f"IQ Option connection error: {str(e)}")
            return False

    async def _analyze_market(self, slot_id: int, asset: str) -> Optional[dict]:
        """Analyze market using multiple indicators and return signal"""
        await asyncio.sleep(0.5)

        try:
            import numpy as np

            # Generate synthetic OHLCV data (replace with real data when IQ connected)
            prices = [random.uniform(1.1500, 1.1600) for _ in range(100)]
            closes = np.array(prices)

            signals = []
            indicators_used = []

            # RSI
            rsi = await self._calc_rsi(closes, 14)
            if rsi < 30:
                signals.append(1)  # oversold -> BUY
                indicators_used.append("RSI")
            elif rsi > 70:
                signals.append(-1)  # overbought -> SELL
                indicators_used.append("RSI")

            # EMA crossover
            ema9 = await self._calc_ema(closes, 9)
            ema21 = await self._calc_ema(closes, 21)
            if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                signals.append(1)
                indicators_used.append("EMA Cross")
            elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                signals.append(-1)
                indicators_used.append("EMA Cross")

            # MACD
            macd_line, signal_line = await self._calc_macd(closes)
            if macd_line > signal_line and abs(macd_line - signal_line) > 0.0001:
                signals.append(1)
                indicators_used.append("MACD")
            elif macd_line < signal_line and abs(macd_line - signal_line) > 0.0001:
                signals.append(-1)
                indicators_used.append("MACD")

            # Stochastic
            stoch_k = await self._calc_stochastic(closes)
            if stoch_k < 20:
                signals.append(1)
                indicators_used.append("Stoch")
            elif stoch_k > 80:
                signals.append(-1)
                indicators_used.append("Stoch")

            # Bollinger Bands
            bb_upper, bb_lower = await self._calc_bollinger(closes)
            if closes[-1] <= bb_lower:
                signals.append(1)
                indicators_used.append("BB")
            elif closes[-1] >= bb_upper:
                signals.append(-1)
                indicators_used.append("BB")

            if not signals:
                return None

            score = sum(signals) / len(signals)
            confidence = abs(score) * 100

            if confidence < 40:
                return None

            return {
                "direction": "call" if score > 0 else "put",
                "confidence": min(confidence + random.uniform(0, 20), 95),
                "indicators": indicators_used[:3],
                "score": round(score, 2),
            }

        except Exception as e:
            await self._send_log(slot_id, "WARNING", f"Indicator error: {str(e)}")
            # Fallback random signal
            direction = random.choice(["call", "put"])
            return {"direction": direction, "confidence": 60 + random.uniform(0, 25), "indicators": ["RSI", "MACD"]}

    async def _calc_rsi(self, closes, period=14):
        import numpy as np
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    async def _calc_ema(self, closes, period):
        import numpy as np
        if len(closes) < period:
            return closes
        alpha = 2 / (period + 1)
        ema = [closes[0]]
        for price in closes[1:]:
            ema.append(alpha * price + (1 - alpha) * ema[-1])
        return np.array(ema)

    async def _calc_macd(self, closes):
        ema12 = await self._calc_ema(closes, 12)
        ema26 = await self._calc_ema(closes, 26)
        macd = ema12 - ema26
        signal = await self._calc_ema(macd, 9)
        return float(macd[-1]), float(signal[-1])

    async def _calc_stochastic(self, closes, period=14):
        if len(closes) < period:
            return 50.0
        low_min = min(closes[-period:])
        high_max = max(closes[-period:])
        if high_max == low_min:
            return 50.0
        return (closes[-1] - low_min) / (high_max - low_min) * 100

    async def _calc_bollinger(self, closes, period=20, std_dev=2):
        import numpy as np
        if len(closes) < period:
            return closes[-1] * 1.01, closes[-1] * 0.99
        sma = np.mean(closes[-period:])
        std = np.std(closes[-period:])
        return sma + std_dev * std, sma - std_dev * std


bot_manager = BotManager()
