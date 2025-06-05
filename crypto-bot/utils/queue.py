import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
from enum import Enum

from config.settings import config

logger = logging.getLogger(__name__)


class Priority(Enum):
    """Приоритеты сообщений"""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    URGENT = 0


@dataclass
class Message:
    """Сообщение в очереди"""
    priority: int
    timestamp: datetime
    user_id: int
    content: str
    reply_markup: Optional[Any] = None
    parse_mode: str = "HTML"
    
    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = self.priority.value


class MessageQueue:
    """Очередь сообщений с планировщиком отправки каждую секунду"""
    
    def __init__(self, bot_instance=None):
        self.bot = bot_instance
        
        # Очередь алертов по пользователям: user_id -> [alert_strings]
        self.alert_batches: Dict[int, List[str]] = defaultdict(list)
        
        # Обычные сообщения: [Message]
        self.message_queue: List[Message] = []
        
        self.processing = False
        self._lock = asyncio.Lock()
        
        # Rate limiting: 30 сообщений в минуту
        self._send_times = deque(maxlen=config.QUEUE_MAX_MESSAGES_PER_MINUTE)  # Храним время последних 30 отправок
        
        # Планировщик отправки
        self._scheduler_task = None
        
        # Статистика
        self.stats = {
            'messages_sent': 0,
            'alerts_sent': 0,
            'errors': 0,
            'rate_limited': 0
        }
    
    def set_bot(self, bot_instance):
        """Установка инстанса бота"""
        self.bot = bot_instance
    
    async def add_message(self, user_id: int, content: str, 
                         priority: Priority = Priority.NORMAL,
                         reply_markup: Optional[Any] = None,
                         parse_mode: str = "HTML") -> None:
        """Добавление обычного сообщения в очередь"""
        async with self._lock:
            message = Message(
                priority=priority,
                timestamp=datetime.now(),
                user_id=user_id,
                content=content,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            self.message_queue.append(message)
            
        logger.info(f"Added regular message for user {user_id}")
    
    async def add_alerts_bulk(self, alerts: List[Tuple[int, Dict[str, Any]]],
                             priority: Priority = Priority.NORMAL) -> None:
        """Массовое добавление алертов"""
        logger.info(f"Adding {len(alerts)} alerts to queue")
        
        users_to_send_immediately = []
        
        async with self._lock:
            # Группируем по пользователям
            user_alerts = defaultdict(list)
            for user_id, alert_data in alerts:
                # Форматируем алерт в строку
                alert_text = self._format_single_alert(alert_data)
                user_alerts[user_id].append(alert_text)
            
            # Добавляем в батчи и проверяем лимиты
            for user_id, alert_texts in user_alerts.items():
                self.alert_batches[user_id].extend(alert_texts)
                logger.debug(f"Added {len(alert_texts)} alerts for user {user_id}, total: {len(self.alert_batches[user_id])}")
                
                # Если достигли лимита - помечаем для немедленной отправки
                if len(self.alert_batches[user_id]) >= config.MAX_ALERTS_PER_MESSAGE:
                    users_to_send_immediately.append(user_id)
        
        # Отправляем немедленно пользователей с полными батчами
        for user_id in users_to_send_immediately:
            await self._send_user_alerts_immediately(user_id)

    def _format_single_alert(self, alert_data: Dict[str, Any]) -> str:
        """Форматирование одного алерта"""
        direction = alert_data['direction']
        symbol = alert_data['symbol']
        interval = alert_data['interval']
        percent_change = abs(alert_data['percent_change'])
        price = alert_data['price']
        
        return f"{direction} {symbol} {interval}: {percent_change:.2f}% (${price})"
    
    def _can_send_message(self) -> bool:
        """Проверка можем ли отправить сообщение (rate limit 30/минуту)"""
        now = datetime.now()
        
        # Удаляем отправки старше 1 минуты
        while self._send_times and (now - self._send_times[0]) > timedelta(seconds=config.QUEUE_RATE_LIMIT_WINDOW):
            self._send_times.popleft()
        
        # Можем отправить если отправили меньше 30 сообщений за последнюю минуту
        return len(self._send_times) < config.QUEUE_MAX_MESSAGES_PER_MINUTE
    
    async def start_processing(self) -> None:
        """Запуск планировщика обработки"""
        if self.processing:
            return
        
        self.processing = True
        
        # Запускаем планировщик который работает каждую секунду
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        logger.info("Message queue scheduler started - checking every 1 second, max 30/minute")
    
    async def stop_processing(self) -> None:
        """Остановка обработки"""
        self.processing = False
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Message queue scheduler stopped")
    
    async def _scheduler_loop(self):
        """Планировщик - проверяет каждую секунду, отправляет если можно"""
        logger.info("Scheduler loop started - checking every 1 second")
        
        while self.processing:
            try:
                # Проверяем каждую секунду
                await asyncio.sleep(1.0)
                
                # Проверяем можем ли отправить (rate limit)
                if not self._can_send_message():
                    logger.debug("Rate limited - cannot send message")
                    self.stats['rate_limited'] += 1
                    continue
                
                # Проверяем есть ли что отправлять и отправляем
                if await self._has_pending_messages():
                    await self._send_next_message()
                    
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _has_pending_messages(self) -> bool:
        """Проверка есть ли сообщения для отправки"""
        async with self._lock:
            # Проверяем алерты
            for user_alerts in self.alert_batches.values():
                if user_alerts:
                    return True
            
            # Проверяем обычные сообщения
            if self.message_queue:
                return True
                
            return False
    
    async def _send_next_message(self):
        """Отправка следующего сообщения из очереди"""
        if not self.bot:
            return
            
        message_to_send = None
        
        async with self._lock:
            # Приоритет 1: Обычные сообщения (команды, интерфейс)
            if self.message_queue:
                # Сортируем по приоритету
                self.message_queue.sort(key=lambda m: (m.priority, m.timestamp))
                message_to_send = self.message_queue.pop(0)
                
            # Приоритет 2: Алерты (если нет обычных сообщений)
            elif self.alert_batches:
                # Берем первого пользователя с алертами
                user_id = next(iter(self.alert_batches.keys()))
                user_alerts = self.alert_batches[user_id]
                
                if user_alerts:
                    # Берем до MAX_ALERTS_PER_MESSAGE алертов
                    alerts_to_send = user_alerts[:config.MAX_ALERTS_PER_MESSAGE]
                    self.alert_batches[user_id] = user_alerts[config.MAX_ALERTS_PER_MESSAGE:]
                    
                    # Если алертов больше нет, удаляем пользователя
                    if not self.alert_batches[user_id]:
                        del self.alert_batches[user_id]
                    
                    # Формируем сообщение
                    content = "🚨 <b>Алерты:</b>\n" + "\n".join(alerts_to_send)
                    
                    message_to_send = Message(
                        priority=Priority.HIGH.value,
                        timestamp=datetime.now(),
                        user_id=user_id,
                        content=content,
                        parse_mode="HTML"
                    )
        
        # Отправляем сообщение
        if message_to_send:
            try:
                logger.info(f"Sending message to user {message_to_send.user_id}")
                
                await self.bot.send_message(
                    chat_id=message_to_send.user_id,
                    text=message_to_send.content,
                    reply_markup=message_to_send.reply_markup,
                    parse_mode=message_to_send.parse_mode
                )
                
                # Записываем время отправки для rate limiting
                self._send_times.append(datetime.now())
                
                self.stats['messages_sent'] += 1
                logger.info(f"Message sent successfully to user {message_to_send.user_id}")
                
            except Exception as e:
                logger.error(f"Error sending message to {message_to_send.user_id}: {e}")
                self.stats['errors'] += 1
                
                # Возвращаем сообщение в очередь если это не критическая ошибка
                if "bot was blocked" not in str(e).lower():
                    async with self._lock:
                        self.message_queue.insert(0, message_to_send)
    
    async def flush_all_alerts(self) -> None:
        """Отправка всех накопленных алертов (при остановке)"""
        logger.info("Flushing all remaining alerts...")
        
        while await self._has_pending_messages():
            if self._can_send_message():
                await self._send_next_message()
                await asyncio.sleep(1.0)  # Соблюдаем интервал
            else:
                break  # Достигли лимита
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики очереди"""
        pending_alerts = sum(len(alerts) for alerts in self.alert_batches.values())
        
        return {
            **self.stats,
            'pending_messages': len(self.message_queue),
            'pending_alerts': pending_alerts,
            'users_with_alerts': len(self.alert_batches),
            'rate_limit_remaining': 30 - len(self._send_times)
        }
    
    async def get_user_queue_size(self, user_id: int) -> int:
        """Получение размера очереди для пользователя"""
        async with self._lock:
            user_messages = len([m for m in self.message_queue if m.user_id == user_id])
            user_alerts = len(self.alert_batches.get(user_id, []))
            return user_messages + user_alerts
    
    async def add_formatted_alerts(self, user_id: int, alert_texts: List[str], 
                                  priority: Priority = Priority.HIGH) -> None:
        """Добавление уже отформатированных алертов"""
        logger.info(f"Adding {len(alert_texts)} formatted alerts for user {user_id}")
        
        async with self._lock:
            # Добавляем алерты
            self.alert_batches[user_id].extend(alert_texts)
            logger.debug(f"Total alerts for user {user_id}: {len(self.alert_batches[user_id])}")
        
        # Проверяем лимит для немедленной отправки (без блокировки)
        if len(self.alert_batches[user_id]) >= config.MAX_ALERTS_PER_MESSAGE:
            await self._send_user_alerts_immediately(user_id)
    
    async def _send_user_alerts_immediately(self, user_id: int):
        """Немедленная отправка алертов пользователю при достижении лимита"""
        if not self.bot:
            return
        
        # Проверяем rate limit
        if not self._can_send_message():
            logger.debug(f"Rate limited - cannot send immediate alerts to user {user_id}")
            return
        
        async with self._lock:
            user_alerts = self.alert_batches.get(user_id, [])
            if len(user_alerts) >= config.MAX_ALERTS_PER_MESSAGE:
                # Берем полный батч
                alerts_to_send = user_alerts[:config.MAX_ALERTS_PER_MESSAGE]
                self.alert_batches[user_id] = user_alerts[config.MAX_ALERTS_PER_MESSAGE:]
                
                # Если алертов больше нет, удаляем пользователя
                if not self.alert_batches[user_id]:
                    del self.alert_batches[user_id]
                
                # Формируем сообщение
                content = "🚨 <b>Алерты:</b>\n" + "\n".join(alerts_to_send)
        
        # Отправляем немедленно (вне блокировки)
        if 'alerts_to_send' in locals():
            try:
                logger.info(f"Sending immediate full batch ({len(alerts_to_send)} alerts) to user {user_id}")
                
                await self.bot.send_message(
                    chat_id=user_id,
                    text=content,
                    parse_mode="HTML"
                )
                
                # Записываем время отправки для rate limiting
                self._send_times.append(datetime.now())
                
                self.stats['messages_sent'] += 1
                logger.info(f"Immediate batch sent successfully to user {user_id}")
                
            except Exception as e:
                logger.error(f"Error sending immediate batch to {user_id}: {e}")
                self.stats['errors'] += 1
                
                # Возвращаем алерты обратно в очередь при ошибке
                if "bot was blocked" not in str(e).lower():
                    async with self._lock:
                        self.alert_batches[user_id] = alerts_to_send + self.alert_batches.get(user_id, [])


# Глобальный инстанс
message_queue = MessageQueue()