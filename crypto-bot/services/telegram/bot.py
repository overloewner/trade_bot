import asyncio
import logging
from typing import List, Dict, Any
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import config
from services.telegram.handlers import register_all_handlers
from services.telegram.alert_types import AlertType, AlertRequest, CandleAlertData, GasCrossingAlertData
from utils.queue import message_queue, Priority
from cache.memory import cache
from models.database import db_manager

logger = logging.getLogger(__name__)


class AlertFormatter:
    """Форматировщик алертов"""
    
    @staticmethod
    def format_candle_alert(data: CandleAlertData) -> str:
        """Форматирование свечного алерта"""
        direction_icon = "🟢" if data.direction == "up" else "🔴"
        return f"{direction_icon} {data.symbol} {data.interval}: {abs(data.percent_change):.2f}% (${data.price})"
    
    @staticmethod
    def format_gas_crossing_alert(data: GasCrossingAlertData) -> str:
        """Форматирование алерта пересечения газа"""
        direction_icon = "📈" if data.direction == "up" else "📉"
        return (
            f"{direction_icon} <b>Газ алерт!</b>\n\n"
            f"Цена газа пересекла ваш порог:\n"
            f"🎯 Порог: {data.threshold} Gwei\n"
            f"📍 Текущая цена: {data.current_price} Gwei\n"
            f"📊 Изменение: {data.previous_price} → {data.current_price} Gwei"
        )


class TelegramBot:
    """Основной класс Telegram бота"""
    
    def __init__(self):
        # Инициализация бота
        self.bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML
            )
        )
        
        # Инициализация диспетчера
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # Устанавливаем бота в очередь сообщений
        message_queue.set_bot(self.bot)
        
        # Регистрируем обработчики
        register_all_handlers(self.dp)
        
        # Форматировщик алертов
        self.formatter = AlertFormatter()
        
        self.running = False
    
    async def start(self):
        """Запуск бота"""
        logger.info("Starting Telegram bot...")
        
        try:
            # Инициализация БД
            await db_manager.init()
            logger.info("Database initialized")
            
            # Загрузка данных в кеш
            await cache.load_from_db(db_manager)
            logger.info("Cache loaded from database")
            
            # Запуск автономной очереди сообщений
            await message_queue.start_processing()
            logger.info("Message queue processing started")
            
            # Информация о боте
            bot_info = await self.bot.get_me()
            logger.info(f"Bot started: @{bot_info.username}")
            
            # Установка команд бота
            await self.set_bot_commands()
            
            self.running = True
            
            # Запуск polling
            await self.dp.start_polling(
                self.bot,
                allowed_updates=["message", "callback_query"]
            )
            
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
    
    async def stop(self):
        """Остановка бота"""
        logger.info("Stopping Telegram bot...")
        
        self.running = False
        
        # Остановка обработки очереди
        await message_queue.stop_processing()
        
        # Закрытие БД
        await db_manager.close()
        
        # Закрытие бота
        await self.bot.session.close()
        
        logger.info("Telegram bot stopped")
    
    async def set_bot_commands(self):
        """Установка команд бота в меню"""
        from aiogram.types import BotCommand
        
        commands = [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="status", description="Моя статистика"),
            BotCommand(command="preset", description="Управление пресетами"),
            BotCommand(command="gas", description="Настройка газ алертов")
        ]
        
        await self.bot.set_my_commands(commands)
    
    # === МЕТОДЫ ДЛЯ ОТПРАВКИ АЛЕРТОВ ===
    
    async def send_alerts_bulk(self, alerts: List[AlertRequest]) -> None:
        """Массовая отправка алертов"""
        logger.info(f"Processing {len(alerts)} alerts for sending")
        
        # Группируем алерты по пользователям и типам
        user_alerts: Dict[int, List[str]] = {}
        
        for alert in alerts:
            user_id = alert.user_id
            
            # Форматируем алерт в зависимости от типа
            if alert.alert_type == AlertType.CANDLE:
                formatted_text = self.formatter.format_candle_alert(alert.data)
            elif alert.alert_type == AlertType.GAS_CROSSING:
                formatted_text = self.formatter.format_gas_crossing_alert(alert.data)
            else:
                logger.error(f"Unknown alert type: {alert.alert_type}")
                continue
            
            # Добавляем к пользователю
            if user_id not in user_alerts:
                user_alerts[user_id] = []
            user_alerts[user_id].append(formatted_text)
        
        # Отправляем через очередь
        for user_id, alert_texts in user_alerts.items():
            # Преобразуем приоритет
            priority = self._convert_priority(alerts[0].priority)
            
            # Отправляем через очередь
            await message_queue.add_formatted_alerts(user_id, alert_texts, priority)
    
    async def send_gas_alert(self, user_id: int, data: GasCrossingAlertData) -> None:
        """Отправка газового алерта"""
        alert = AlertRequest(
            user_id=user_id,
            alert_type=AlertType.GAS_CROSSING,
            data=data,
            priority="high"
        )
        await self.send_alerts_bulk([alert])
    
    async def send_message(self, user_id: int, text: str, priority: str = "normal", **kwargs) -> None:
        """Отправка обычного сообщения"""
        msg_priority = self._convert_priority(priority)
        await message_queue.add_message(
            user_id=user_id,
            content=text,
            priority=msg_priority,
            **kwargs
        )
    
    def _convert_priority(self, priority_str: str) -> Priority:
        """Конвертация строкового приоритета в enum"""
        priority_map = {
            "low": Priority.LOW,
            "normal": Priority.NORMAL,
            "high": Priority.HIGH,
            "urgent": Priority.URGENT
        }
        return priority_map.get(priority_str, Priority.NORMAL)
    
    # === МЕТОДЫ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ ===
    
    async def send_alert(self, user_id: int, text: str, **kwargs):
        """Отправка алерта пользователю (обратная совместимость)"""
        await self.send_message(user_id, text, priority="high", **kwargs)
    
    async def broadcast_message(self, user_ids: list[int], text: str, **kwargs):
        """Массовая рассылка сообщений"""
        success_count = 0
        fail_count = 0
        
        for user_id in user_ids:
            try:
                await self.send_message(user_id, text, **kwargs)
                success_count += 1
                
                # Небольшая задержка чтобы не перегрузить очередь
                await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                fail_count += 1
        
        logger.info(f"Broadcast completed: {success_count} success, {fail_count} failed")
        return success_count, fail_count


# Singleton instance
telegram_bot = TelegramBot()