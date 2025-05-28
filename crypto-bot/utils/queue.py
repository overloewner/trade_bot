import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict, deque
import heapq
import logging
from enum import Enum

from config.settings import config
from utils.rate_limiter import telegram_limiter

logger = logging.getLogger(__name__)


class Priority(Enum):
    """Приоритеты сообщений"""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    URGENT = 0


@dataclass(order=True)
class Message:
    """Сообщение в очереди"""
    priority: int = field(compare=True)
    timestamp: datetime = field(compare=False)
    user_id: int = field(compare=False)
    content: str = field(compare=False)
    reply_markup: Optional[Any] = field(default=None, compare=False)
    parse_mode: str = field(default="HTML", compare=False)
    
    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = self.priority.value


@dataclass
class AlertBatch:
    """Батч алертов для отправки"""
    user_id: int
    alerts: List[Dict[str, Any]]
    priority: Priority = Priority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)


class MessageQueue:
    """Очередь сообщений с приоритетами и батчингом"""
    
    def __init__(self, bot_instance=None):
        self.bot = bot_instance
        self.user_queues: Dict[int, List[Message]] = defaultdict(list)
        self.alert_batches: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        self.processing = False
        self._lock = asyncio.Lock()
        
        # Статистика
        self.stats = {
            'messages_sent': 0,
            'batches_sent': 0,
            'errors': 0,
            'queue_size': 0
        }
    
    def set_bot(self, bot_instance):
        """Установка инстанса бота"""
        self.bot = bot_instance
    
    async def add_message(self, user_id: int, content: str, 
                         priority: Priority = Priority.NORMAL,
                         reply_markup: Optional[Any] = None,
                         parse_mode: str = "HTML") -> None:
        """Добавление сообщения в очередь"""
        async with self._lock:
            message = Message(
                priority=priority,
                timestamp=datetime.now(),
                user_id=user_id,
                content=content,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            heapq.heappush(self.user_queues[user_id], message)
            self.stats['queue_size'] += 1
    
    async def add_alert(self, user_id: int, alert: Dict[str, Any],
                       priority: Priority = Priority.NORMAL) -> None:
        """Добавление алерта для батчинга"""
        async with self._lock:
            self.alert_batches[user_id].append(alert)
            
            # Если достигли лимита батча, отправляем
            if len(self.alert_batches[user_id]) >= config.MAX_ALERTS_PER_MESSAGE:
                await self._flush_user_alerts(user_id, priority)
    
    async def add_alerts_bulk(self, alerts: List[Tuple[int, Dict[str, Any]]],
                             priority: Priority = Priority.NORMAL) -> None:
        """Массовое добавление алертов"""
        async with self._lock:
            # Группируем по пользователям
            user_alerts = defaultdict(list)
            for user_id, alert in alerts:
                user_alerts[user_id].append(alert)
            
            # Добавляем в батчи
            for user_id, user_alert_list in user_alerts.items():
                self.alert_batches[user_id].extend(user_alert_list)
                
                # Отправляем полные батчи
                while len(self.alert_batches[user_id]) >= config.MAX_ALERTS_PER_MESSAGE:
                    await self._flush_user_alerts(user_id, priority)
    
    async def _flush_user_alerts(self, user_id: int, priority: Priority) -> None:
        """Отправка накопленных алертов пользователю"""
        if not self.alert_batches[user_id]:
            return
        
        # Берем до MAX_ALERTS_PER_MESSAGE алертов
        alerts_to_send = self.alert_batches[user_id][:config.MAX_ALERTS_PER_MESSAGE]
        self.alert_batches[user_id] = self.alert_batches[user_id][config.MAX_ALERTS_PER_MESSAGE:]
        
        # Форматируем сообщение
        content = self._format_alerts(alerts_to_send)
        
        # Добавляем в очередь сообщений
        await self.add_message(user_id, content, priority)
    
    def _format_alerts(self, alerts: List[Dict[str, Any]]) -> str:
        """Форматирование алертов в одно сообщение"""
        lines = ["🔔 <b>Свечные алерты:</b>\n"]
        
        # Группируем по интервалам для читаемости
        by_interval = defaultdict(list)
        for alert in alerts:
            by_interval[alert['interval']].append(alert)
        
        for interval, interval_alerts in sorted(by_interval.items()):
            lines.append(f"\n<b>Интервал {interval}:</b>")
            for alert in interval_alerts[:10]:  # Максимум 10 на интервал
                symbol = alert['symbol']
                change = alert['percent_change']
                direction = "📈" if change > 0 else "📉"
                lines.append(
                    f"{direction} {symbol}: {change:+.2f}%"
                )
        
        # Если алертов слишком много, показываем сводку
        total_alerts = sum(len(alerts) for alerts in by_interval.values())
        if total_alerts > 30:
            lines.append(f"\n<i>...и еще {total_alerts - 30} алертов</i>")
        
        return "\n".join(lines)
    
    async def flush_all_alerts(self) -> None:
        """Отправка всех накопленных алертов"""
        async with self._lock:
            user_ids = list(self.alert_batches.keys())
            for user_id in user_ids:
                if self.alert_batches[user_id]:
                    await self._flush_user_alerts(user_id, Priority.NORMAL)
    
    async def start_processing(self) -> None:
        """Запуск обработки очереди"""
        if self.processing:
            return
        
        self.processing = True
        asyncio.create_task(self._process_loop())
        logger.info("Message queue processing started")
    
    async def stop_processing(self) -> None:
        """Остановка обработки"""
        self.processing = False
        await self.flush_all_alerts()
        logger.info("Message queue processing stopped")
    
    async def _process_loop(self) -> None:
        """Основной цикл обработки сообщений"""
        while self.processing:
            try:
                await self._process_batch()
                await asyncio.sleep(0.1)  # Небольшая пауза между батчами
            except Exception as e:
                logger.error(f"Error in message processing loop: {e}")
                await asyncio.sleep(1)
    
    async def _process_batch(self) -> None:
        """Обработка батча сообщений"""
        if not self.bot:
            return
        
        # Получаем приоритетные сообщения
        messages_to_send = await self._get_priority_messages(10)
        
        for message in messages_to_send:
            try:
                # Rate limiting
                await telegram_limiter.acquire_for_user(message.user_id)
                
                # Отправка
                await self.bot.send_message(
                    chat_id=message.user_id,
                    text=message.content,
                    reply_markup=message.reply_markup,
                    parse_mode=message.parse_mode
                )
                
                self.stats['messages_sent'] += 1
                
            except Exception as e:
                logger.error(f"Error sending message to {message.user_id}: {e}")
                self.stats['errors'] += 1
                
                # Возвращаем сообщение в очередь если это не критическая ошибка
                if "bot was blocked" not in str(e).lower():
                    await self.add_message(
                        message.user_id,
                        message.content,
                        Priority(message.priority),
                        message.reply_markup,
                        message.parse_mode
                    )
    
    async def _get_priority_messages(self, limit: int) -> List[Message]:
        """Получение сообщений с наивысшим приоритетом"""
        async with self._lock:
            all_messages = []
            
            # Собираем все сообщения из очередей пользователей
            for user_id, queue in self.user_queues.items():
                if queue:
                    all_messages.extend(queue)
            
            # Сортируем по приоритету
            all_messages.sort(key=lambda m: (m.priority, m.timestamp))
            
            # Берем первые limit сообщений
            messages_to_send = all_messages[:limit]
            
            # Удаляем их из очередей
            for message in messages_to_send:
                self.user_queues[message.user_id].remove(message)
                if not self.user_queues[message.user_id]:
                    del self.user_queues[message.user_id]
            
            self.stats['queue_size'] -= len(messages_to_send)
            
            return messages_to_send
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики очереди"""
        return {
            **self.stats,
            'users_in_queue': len(self.user_queues),
            'pending_alerts': sum(len(alerts) for alerts in self.alert_batches.values()),
            'total_pending': self.stats['queue_size'] + sum(len(alerts) for alerts in self.alert_batches.values())
        }
    
    async def get_user_queue_size(self, user_id: int) -> int:
        """Получение размера очереди для пользователя"""
        async with self._lock:
            return len(self.user_queues.get(user_id, [])) + len(self.alert_batches.get(user_id, []))


# Глобальный инстанс
message_queue = MessageQueue()