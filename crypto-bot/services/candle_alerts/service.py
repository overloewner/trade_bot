import asyncio
import logging
from typing import Dict, Any

from services.candle_alerts.websocket import BinanceWebSocketManager
from services.candle_alerts.processor import CandleProcessor
from config.settings import config
from services.binanceAPI.service import binance_api

logger = logging.getLogger(__name__)


class CandleAlertService:
    """Основной сервис свечных алертов"""
    
    def __init__(self):
        self.processor = CandleProcessor()
        self.ws_manager = BinanceWebSocketManager(self.processor.add_candle)
        self.running = False
        
        # Задача мониторинга
        self.monitor_task = None
    
    async def start(self):
        """Запуск сервиса"""
        if self.running:
            return
        
        logger.info("Starting Candle Alert Service...")
        
        try:
            # Обновляем список символов
            await binance_api._fetch_all_futures_symbols
            
            # Запускаем обработчик свечей
            await self.processor.start()
            
            # Запускаем WebSocket подключения
            await self.ws_manager.start()
            
            # Запускаем мониторинг
            self.monitor_task = asyncio.create_task(self._monitor_loop())
            
            self.running = True
            logger.info("Candle Alert Service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start Candle Alert Service: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Остановка сервиса"""
        logger.info("Stopping Candle Alert Service...")
        
        self.running = False
        
        # Отменяем мониторинг
        if self.monitor_task:
            self.monitor_task.cancel()
        
        # Останавливаем WebSocket
        await self.ws_manager.stop()
        
        # Останавливаем обработчик
        await self.processor.stop()
        
        logger.info("Candle Alert Service stopped")
    
    
    async def _monitor_loop(self):
        """Цикл мониторинга состояния сервиса"""
        while self.running:
            try:
                await asyncio.sleep(config.HEALTH_CHECK_INTERVAL)
                
                # Проверяем здоровье компонентов
                ws_health = await self.ws_manager.health_check()
                processor_health = await self.processor.health_check()
                
                # Логируем проблемы
                if not ws_health['healthy']:
                    logger.warning(f"WebSocket unhealthy: {ws_health}")
                
                if not processor_health['processing']:
                    logger.error("Processor stopped unexpectedly")
                    # Пытаемся перезапустить
                    await self.processor.start()
                
                # Логируем статистику
                if self.running:
                    stats = self.get_stats()
                    logger.info(f"Service stats: {stats}")
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики сервиса"""
        return {
            'running': self.running,
            'websocket': self.ws_manager.get_stats(),
            'processor': self.processor.get_stats()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        ws_health = await self.ws_manager.health_check()
        processor_health = await self.processor.health_check()
        
        return {
            'healthy': self.running and ws_health['healthy'] and processor_health['processing'],
            'components': {
                'websocket': ws_health,
                'processor': processor_health
            }
        }


# Singleton instance
candle_alert_service = CandleAlertService()