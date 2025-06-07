import asyncio
import logging
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime

from cache.memory import cache, AlertRecord
from config.settings import config

logger = logging.getLogger(__name__)


class PriceAnalyzer:
    def calculate_change(self, open_price: float, close_price: float) -> float:
        """Расчет процента изменения с точностью до 4 знаков"""
        if open_price == 0:
            return 0.0
        
        # Простой расчет с float
        change = ((close_price - open_price) / open_price) * 100
        
        # Округляем до 4 знаков после запятой
        return round(change, 4)


class CandleProcessor:
    """Обработчик свечей и генератор алертов"""
    
    def __init__(self):
        self.analyzer = PriceAnalyzer()
        self.candle_queue = asyncio.Queue(maxsize=config.CANDLE_QUEUE_SIZE)
        self.processing = False
        
        # Cooldown для дедупликации
        self._cooldown = {}
        self._cooldown_lock = asyncio.Lock()
        
        # Хранение последних данных по биткоину для корреляции
        self.btc_data = {}  # interval -> {'price': float, 'change': float, 'timestamp': datetime}
        self._btc_lock = asyncio.Lock()
        
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
        
        # Рассчитываем процент изменения
        price_change = self.analyzer.calculate_change(
            candle['open'],
            candle['close']
        )
        
        # Обновляем данные биткоина если это BTCUSDT
        if symbol == 'BTCUSDT':
            async with self._btc_lock:
                self.btc_data[interval] = {
                    'price': candle['close'],
                    'change': price_change,
                    'timestamp': datetime.now()
                }
            logger.debug(f"Updated BTC data for {interval}: {price_change:.3f}%")
        
        # Получаем подписанных пользователей из кеша
        subscribed_users = await cache.get_subscribed_users(symbol, interval)
        
        if not subscribed_users:
            logger.debug(f"No subscribers for {symbol} {interval}")
            return
        
        logger.info(f"Found {len(subscribed_users)} subscribers for {symbol} {interval}")
        
        logger.debug(f"{symbol} {interval} price change: {price_change}%")
        
        # Проверяем дедупликацию
        if not await self._should_send_alert(symbol, interval, price_change):
            logger.debug(f"Alert deduplicated for {symbol} {interval} {price_change}%")
            return
        
        # Получаем корреляцию с биткоином
        btc_correlation = await self._get_btc_correlation(symbol, interval, price_change)
        
        # Генерируем готовые алерты
        alerts_to_send = []
        
        for user_id, presets in subscribed_users.items():
            # Проверяем пресеты пока не найдем первый подходящий
            alert_sent = False
            
            for preset in presets:
                # Проверяем порог
                if abs(price_change) >= preset.percent_change:
                    logger.info(f"Alert triggered for user {user_id}: {symbol} {interval} {price_change:.3f}% >= {preset.percent_change}%")
                    
                    # ФОРМАТИРУЕМ алерт с корреляцией
                    direction = "🟢" if price_change > 0 else "🔴"
                    alert_text = f"{direction} {symbol} {interval}: {abs(price_change):.3f}% (${candle['close']})"
                    
                    # Добавляем корреляцию с BTC если есть
                    if btc_correlation:
                        alert_text += f"\n{btc_correlation}"
                    
                    alerts_to_send.append((user_id, alert_text))
                    
                    # Записываем алерт в историю
                    await cache.record_alert(AlertRecord(
                        user_id=user_id,
                        symbol=symbol,
                        interval=interval,
                        timestamp=datetime.now(),
                        percent_change=price_change
                    ))
                    
                    # ОСТАНАВЛИВАЕМСЯ - не проверяем остальные пресеты этого пользователя
                    alert_sent = True
                    break
            
            if not alert_sent:
                logger.debug(f"No alerts triggered for user {user_id}: {abs(price_change):.3f}% below all thresholds")
        
        # Отправляем алерты через очередь
        if alerts_to_send:
            from utils.queue import message_queue
            await message_queue.add_alerts_bulk(alerts_to_send)
            
            self.stats['alerts_generated'] += len(alerts_to_send)
            logger.info(f"Sent {len(alerts_to_send)} unique alerts for {symbol} {interval}")
        else:
            logger.debug(f"No alerts to send for {symbol} {interval}")
    
    async def _get_btc_correlation(self, symbol: str, interval: str, price_change: float) -> Optional[str]:
        """Получение корреляции с биткоином"""
        # Если это сам биткоин - не показываем корреляцию
        if symbol == 'BTCUSDT':
            return None
        
        async with self._btc_lock:
            btc_info = self.btc_data.get(interval)
            
            if not btc_info:
                return None
            
            # Проверяем актуальность данных BTC (не старше 5 минут)
            if (datetime.now() - btc_info['timestamp']).total_seconds() > 300:
                return None
            
            btc_change = btc_info['change']
            
            # Рассчитываем разницу
            difference = price_change - btc_change
            
            # Определяем тип движения
            if abs(btc_change) < 0.1:  # BTC почти не двигается
                if abs(price_change) > 1.0:
                    return f"💥 BTC: {btc_change:+.3f}% (сильное движение)"
                else:
                    return f"➡️ BTC: {btc_change:+.3f}%"
            
            # Форматируем с разницей
            if difference > 0:
                # Монета растет сильнее BTC или падает слабее
                return f"🚀 BTC: {btc_change:+.3f}% (разница: {difference:+.3f}%)"
            elif difference < -1.0:
                # Монета растет слабее BTC или падает сильнее
                return f"⚠️ BTC: {btc_change:+.3f}% (разница: {difference:+.3f}%)"
            else:
                # Движение примерно одинаковое
                return f"🔄 BTC: {btc_change:+.3f}% (разница: {difference:+.3f}%)"
    
    async def _should_send_alert(self, symbol: str, interval: str, price_change: float) -> bool:
        """Проверка дедупликации алертов"""
        async with self._cooldown_lock:
            key = (symbol, interval, f"{price_change:.4f}")
            
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