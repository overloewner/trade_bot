import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import config
from services.telegram.handlers import register_all_handlers
from utils.queue import message_queue
from cache.memory import cache
from models.database import db_manager

logger = logging.getLogger(__name__)


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
            
            # Запуск обработки очереди сообщений
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
    
    async def send_alert(self, user_id: int, text: str, **kwargs):
        """Отправка алерта пользователю"""
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                **kwargs
            )
        except Exception as e:
            logger.error(f"Error sending alert to {user_id}: {e}")
            
            # Если пользователь заблокировал бота, деактивируем его
            if "bot was blocked" in str(e).lower():
                # TODO: Деактивировать пользователя в БД
                pass
    
    async def broadcast_message(self, user_ids: list[int], text: str, **kwargs):
        """Массовая рассылка сообщений"""
        success_count = 0
        fail_count = 0
        
        for user_id in user_ids:
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    **kwargs
                )
                success_count += 1
                
                # Небольшая задержка чтобы не превысить лимиты
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                fail_count += 1
        
        logger.info(f"Broadcast completed: {success_count} success, {fail_count} failed")
        return success_count, fail_count


# Singleton instance
telegram_bot = TelegramBot()