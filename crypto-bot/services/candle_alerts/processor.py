import asyncio
import logging
from decimal import Decimal, getcontext
from typing import Dict, List, Any
from datetime import datetime

from cache.memory import cache, AlertRecord
from config.settings import config

logger = logging.getLogger(__name__)


class PriceAnalyzer:
    def __init__(self):
        getcontext().prec = config.DECIMAL_PRECISION
        self._zero = Decimal(0)
        
    def calculate_change(self, open_price: float, close_price: float) -> Decimal:
        open_dec = Decimal(str(open_price))
        if open_dec == self._zero:
            return self._zero
        close_dec = Decimal(str(close_price))
        return ((close_dec - open_dec) / open_dec) * 100


class CandleProcessor:
    """Обработчик свечей и генератор алертов"""
    
    def __init__(self):
        self.analyzer = PriceAnalyzer()
        self.candle_queue = asyncio.Queue(maxsize=config.CANDLE_QUEUE_SIZE)
        self.processing = False
        
        # Cooldown для дедупликации
        self._cooldown = {}
        self._cooldown_lock = asyncio.Lock()
        
        # Статистика
        self.stats = {
            'candles_processed': 0,
            'alerts_generated': 0,
            'queue_size': 0
        }
    
    async def start(self):
        """Запуск обработчика"""
        if self.processing:
            return
        
        self.processing = True
        logger.info("Starting candle processor...")
        
        # Запускаем обработчики
        for i in range(config.WORKER_THREADS):
            asyncio.create_task(self._process_loop(i))
        
        logger.info(f"Started {config.WORKER_THREADS} processing workers")
    
    async def stop(self):
        """Остановка обработчика"""
        logger.info("Stopping candle processor...")
        self.processing = False
        
        # Ждем обработки оставшихся свечей
        await self.candle_queue.join()
        
        logger.info("Candle processor stopped")
    
    async def add_candle(self, candle: Dict[str, Any]):
        """Добавление свечи в очередь обработки"""
        try:
            # Добавляем только закрытые свечи
            if not candle.get('is_closed', False):
                return
            
            logger.debug(f"Adding closed candle to queue: {candle['symbol']} {candle['interval']}")
            await self.candle_queue.put(candle)
            self.stats['queue_size'] = self.candle_queue.qsize()
            
        except asyncio.QueueFull:
            logger.warning("Candle queue is full, dropping candle")
    
    async def _process_loop(self, worker_id: int):
        """Основной цикл обработки свечей"""
        logger.info(f"Worker {worker_id} started")
        
        while self.processing:
            try:
                # Ждем свечу
                try:
                    candle = await asyncio.wait_for(
                        self.candle_queue.get(),
                        timeout=config.PROCESSOR_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Обрабатываем свечу
                await self._process_candle(candle)
                
                # Помечаем задачу как выполненную
                self.candle_queue.task_done()
                self.stats['candles_processed'] += 1
                
            except Exception as e:
                logger.error(f"Error in worker {worker_id}: {e}")
                await asyncio.sleep(1)
    
    async def _process_candle(self, candle: Dict[str, Any]):
        """Обработка одной свечи"""
        symbol = candle['symbol']
        interval = candle['interval']
        
        logger.debug(f"Processing candle: {symbol} {interval}")
        
        # Получаем подписанных пользователей из кеша
        subscribed_users = await cache.get_subscribed_users(symbol, interval)
        
        if not subscribed_users:
            logger.debug(f"No subscribers for {symbol} {interval}")
            return
        
        logger.info(f"Found {len(subscribed_users)} subscribers for {symbol} {interval}")
        
        # Рассчитываем процент изменения
        price_change = self.analyzer.calculate_change(
            candle['open'],
            candle['close']
        )
        
        logger.debug(f"{symbol} {interval} price change: {price_change}%")
        
        # Проверяем дедупликацию
        if not await self._should_send_alert(symbol, interval, price_change):
            logger.debug(f"Alert deduplicated for {symbol} {interval} {price_change}%")
            return
        
        # Генерируем алерты
        alerts_to_send = []
        
        for user_id, presets in subscribed_users.items():
            # Проверяем пресеты пока не найдем первый подходящий
            alert_sent = False
            
            for preset in presets:
                # Проверяем порог
                if abs(price_change) >= preset.percent_change:
                    logger.info(f"Alert triggered for user {user_id}: {symbol} {interval} {price_change}% >= {preset.percent_change}%")
                    
                    # Создаем алерт
                    from services.telegram.alert_types import AlertRequest, AlertType, CandleAlertData
                    
                    direction = "up" if price_change > 0 else "down"
                    
                    alert_data = CandleAlertData(
                        symbol=symbol,
                        interval=interval,
                        percent_change=float(price_change),
                        price=candle['close'],
                        preset_name=preset.name,
                        direction=direction
                    )
                    
                    alert = AlertRequest(
                        user_id=user_id,
                        alert_type=AlertType.CANDLE,
                        data=alert_data,
                        priority="high"
                    )
                    
                    alerts_to_send.append(alert)
                    
                    # Записываем алерт в историю
                    await cache.record_alert(AlertRecord(
                        user_id=user_id,
                        symbol=symbol,
                        interval=interval,
                        timestamp=datetime.now(),
                        percent_change=float(price_change)
                    ))
                    
                    # ОСТАНАВЛИВАЕМСЯ - не проверяем остальные пресеты этого пользователя
                    alert_sent = True
                    break
            
            if not alert_sent:
                logger.debug(f"No alerts triggered for user {user_id}: {abs(price_change)}% below all thresholds")
        
        # Отправляем алерты через Telegram сервис
        if alerts_to_send:
            from services.telegram.bot import telegram_bot
            await telegram_bot.send_alerts_bulk(alerts_to_send)
            
            self.stats['alerts_generated'] += len(alerts_to_send)
            logger.info(f"Sent {len(alerts_to_send)} unique alerts for {symbol} {interval}")
        else:
            logger.debug(f"No alerts to send for {symbol} {interval}")
    
    async def _should_send_alert(self, symbol: str, interval: str, price_change: Decimal) -> bool:
        """Проверка дедупликации алертов"""
        async with self._cooldown_lock:
            key = (symbol, interval, str(price_change))
            
            if key in self._cooldown:
                return False
            
            self._cooldown[key] = datetime.now()
            
            # Запускаем очистку cooldown
            asyncio.create_task(self._clear_cooldown(key))
            
            return True
    
    async def _clear_cooldown(self, key):
        """Очистка cooldown"""
        await asyncio.sleep(config.ALERT_DEDUP_WINDOW)
        async with self._cooldown_lock:
            self._cooldown.pop(key, None)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            **self.stats,
            'queue_size': self.candle_queue.qsize(),
            'cooldown_cache_size': len(self._cooldown)
        }
    
    async def health_check(self) -> Dict[str, bool]:
        """Проверка здоровья обработчика"""
        return {
            'processing': self.processing,
            'queue_healthy': self.candle_queue.qsize() < config.CANDLE_QUEUE_SIZE * 0.8
        }