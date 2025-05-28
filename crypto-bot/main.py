#!/usr/bin/env python3
"""
Crypto Bot - Многопользовательский Telegram бот для мониторинга криптовалют
"""

import asyncio
import logging
import signal
import sys
import os
from typing import Optional

# Исправление кодировки для Windows
if os.name == 'nt':  # Windows
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

from config.settings import config
from services.telegram.bot import telegram_bot
from services.candle_alerts import candle_alert_service
from services.gas_alerts import gas_alert_service
from utils.queue import message_queue

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('crypto_bot.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# Подавляем лишние логи
logging.getLogger('aiogram').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)


class CryptoBot:
    """Главный класс приложения"""
    
    def __init__(self):
        self.running = False
        self.services = {
            'telegram': telegram_bot,
            'candle_alerts': candle_alert_service,
            'gas_alerts': gas_alert_service
        }
    
    async def start(self):
        """Запуск всех сервисов"""
        logger.info("Starting Crypto Bot...")
        
        # Валидация конфигурации
        try:
            config.validate()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            sys.exit(1)
        
        self.running = True
        
        try:
            # Запускаем сервисы
            logger.info("Starting services...")
            
            # Сначала запускаем Telegram бота (он инициализирует БД и кеш)
            telegram_task = asyncio.create_task(telegram_bot.start())
            
            # Ждем немного для инициализации
            await asyncio.sleep(2)
            
            # Запускаем остальные сервисы
            await candle_alert_service.start()
            await gas_alert_service.start()
            
            logger.info("All services started successfully")
            
            # Ждем завершения
            await telegram_task
            
        except Exception as e:
            logger.error(f"Error starting services: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Остановка всех сервисов"""
        logger.info("Stopping Crypto Bot...")
        
        self.running = False
        
        # Останавливаем сервисы в обратном порядке
        try:
            await gas_alert_service.stop()
            await candle_alert_service.stop()
            await telegram_bot.stop()
        except Exception as e:
            logger.error(f"Error stopping services: {e}")
        
        logger.info("Crypto Bot stopped")
    
    async def health_check(self):
        """Проверка здоровья всех сервисов"""
        health_status = {}
        
        for name, service in self.services.items():
            if hasattr(service, 'health_check'):
                try:
                    health_status[name] = await service.health_check()
                except Exception as e:
                    health_status[name] = {
                        'healthy': False,
                        'error': str(e)
                    }
        
        # Общий статус
        all_healthy = all(
            status.get('healthy', False) 
            for status in health_status.values()
        )
        
        return {
            'healthy': all_healthy,
            'services': health_status
        }
    
    def print_stats(self):
        """Вывод статистики"""
        logger.info("=== Service Statistics ===")
        
        # Статистика Telegram бота
        logger.info("Telegram Bot: Running")
        
        # Статистика свечных алертов
        candle_stats = candle_alert_service.get_stats()
        logger.info(f"Candle Alerts: {candle_stats}")
        
        # Статистика газ алертов
        gas_stats = gas_alert_service.get_stats()
        logger.info(f"Gas Alerts: {gas_stats}")
        
        # Статистика очереди сообщений
        queue_stats = message_queue.get_stats()
        logger.info(f"Message Queue: {queue_stats}")


# Глобальный инстанс
bot_app: Optional[CryptoBot] = None


async def main():
    """Главная функция"""
    global bot_app
    
    bot_app = CryptoBot()
    
    # Обработчики сигналов
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        if bot_app and bot_app.running:
            asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot_app.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


async def shutdown():
    """Graceful shutdown"""
    logger.info("Shutting down...")
    
    if bot_app:
        await bot_app.stop()
    
    # Отменяем все задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # Останавливаем event loop
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)