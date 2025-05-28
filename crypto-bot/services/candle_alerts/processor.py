import asyncio
import logging
from typing import Dict, List, Any, Tuple
from datetime import datetime
from collections import defaultdict
import concurrent.futures

from cache.memory import cache, AlertRecord
from utils.queue import message_queue, Priority
from config.settings import config

logger = logging.getLogger(__name__)


class CandleProcessor:
    """Обработчик свечей и генератор алертов"""
    
    def __init__(self):
        self.candle_queue = asyncio.Queue(maxsize=config.CANDLE_QUEUE_SIZE)
        self.processing = False
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=config.WORKER_THREADS)
        
        # Кеш последних цен для расчета изменений
        self.price_cache: Dict[str, Dict[str, float]] = defaultdict(dict)
        
        # Статистика
        self.stats = {
            'candles_processed': 0,
            'alerts_generated': 0,
            'queue_size': 0,
            'processing_time_ms': 0
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
        
        # Закрываем thread pool
        self.thread_pool.shutdown(wait=True)
        
        logger.info("Candle processor stopped")
    
    async def add_candle(self, candle: Dict[str, Any]):
        """Добавление свечи в очередь обработки"""
        try:
            # Добавляем только закрытые свечи
            if not candle.get('is_closed', False):
                return
            
            await self.candle_queue.put(candle)
            self.stats['queue_size'] = self.candle_queue.qsize()
            
        except asyncio.QueueFull:
            logger.warning("Candle queue is full, dropping candle")
    
    async def _process_loop(self, worker_id: int):
        """Основной цикл обработки свечей"""
        logger.info(f"Worker {worker_id} started")
        
        while self.processing:
            try:
                # Получаем батч свечей для обработки
                batch = []
                
                # Ждем первую свечу
                try:
                    candle = await asyncio.wait_for(
                        self.candle_queue.get(),
                        timeout=1.0
                    )
                    batch.append(candle)
                except asyncio.TimeoutError:
                    continue
                
                # Добавляем остальные свечи из очереди (до BATCH_PROCESS_SIZE)
                while len(batch) < config.BATCH_PROCESS_SIZE and not self.candle_queue.empty():
                    try:
                        candle = self.candle_queue.get_nowait()
                        batch.append(candle)
                    except asyncio.QueueEmpty:
                        break
                
                # Обрабатываем батч
                if batch:
                    start_time = datetime.now()
                    await self._process_batch(batch)
                    
                    # Обновляем статистику
                    processing_time = (datetime.now() - start_time).total_seconds() * 1000
                    self.stats['processing_time_ms'] = processing_time
                    self.stats['candles_processed'] += len(batch)
                    
                    # Помечаем задачи как выполненные
                    for _ in batch:
                        self.candle_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in worker {worker_id}: {e}")
                await asyncio.sleep(1)
    
    async def _process_batch(self, candles: List[Dict[str, Any]]):
        """Обработка батча свечей"""
        # Группируем свечи по символу и интервалу для эффективности
        grouped = defaultdict(list)
        for candle in candles:
            key = (candle['symbol'], candle['interval'])
            grouped[key].append(candle)
        
        # Обрабатываем каждую группу
        alerts_to_send = []
        
        for (symbol, interval), group_candles in grouped.items():
            # Берем последнюю свечу из группы
            candle = group_candles[-1]
            
            # Рассчитываем процент изменения
            percent_change = self._calculate_percent_change(candle)
            
            if percent_change is None:
                continue
            
            # Обновляем кеш цен
            self.price_cache[symbol][interval] = candle['close']
            
            # Получаем подписанных пользователей
            subscribed_users = await cache.get_subscribed_users(symbol, interval)
            
            if not subscribed_users:
                continue
            
            # Проверяем пороги и генерируем алерты
            for user_id, presets in subscribed_users.items():
                for preset in presets:
                    # Проверяем порог
                    if abs(percent_change) >= preset.percent_change:
                        # Проверяем дедупликацию
                        if await cache.should_send_alert(user_id, symbol, interval):
                            alert = {
                                'user_id': user_id,
                                'symbol': symbol,
                                'interval': interval,
                                'percent_change': percent_change,
                                'price': candle['close'],
                                'preset_name': preset.name,
                                'timestamp': datetime.now()
                            }
                            alerts_to_send.append((user_id, alert))
                            
                            # Записываем алерт
                            await cache.record_alert(AlertRecord(
                                user_id=user_id,
                                symbol=symbol,
                                interval=interval,
                                timestamp=datetime.now(),
                                percent_change=percent_change
                            ))
        
        # Отправляем алерты
        if alerts_to_send:
            self.stats['alerts_generated'] += len(alerts_to_send)
            await message_queue.add_alerts_bulk(alerts_to_send, Priority.HIGH)
    
    def _calculate_percent_change(self, candle: Dict[str, Any]) -> float:
        """Расчет процента изменения свечи"""
        try:
            # Рассчитываем изменение от открытия к закрытию
            open_price = candle['open']
            close_price = candle['close']
            
            if open_price == 0:
                return None
            
            percent_change = ((close_price - open_price) / open_price) * 100
            return round(percent_change, 2)
            
        except Exception as e:
            logger.error(f"Error calculating percent change: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            **self.stats,
            'queue_size': self.candle_queue.qsize(),
            'price_cache_size': sum(len(intervals) for intervals in self.price_cache.values())
        }
    
    async def health_check(self) -> Dict[str, bool]:
        """Проверка здоровья обработчика"""
        return {
            'processing': self.processing,
            'queue_healthy': self.candle_queue.qsize() < config.CANDLE_QUEUE_SIZE * 0.8,
            'workers_healthy': self.thread_pool._threads
        }