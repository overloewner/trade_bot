import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
import aiohttp
from cache.symbols_cache import symbols_cache
from config.settings import config

logger = logging.getLogger(__name__)


class BinanceWebSocketManager:
    """Менеджер WebSocket подключений к Binance - только WebSocket логика"""
    
    def __init__(self, candle_callback: Callable):
        self.candle_callback = candle_callback
        self.connections: List[aiohttp.ClientWebSocketResponse] = []
        self.sessions: List[aiohttp.ClientSession] = []
        self.running = False
        self.reconnect_tasks = []
        self.stream_groups = []
        
        # Статистика
        self.stats = {
            'messages_received': 0,
            'reconnects': 0,
            'errors': 0,
            'last_message_time': None
        }
    
    def _generate_streams(self):
        """Генерация стримов на основе символов из кеша"""
        all_symbols = symbols_cache.get_all_symbols()
        
        if not all_symbols:
            logger.error("No symbols available in cache")
            return
            
        logger.info(f"Generating streams for {len(all_symbols)} symbols")
            
        # Генерируем стримы для всех комбинаций символ/интервал
        streams = []
        for symbol in all_symbols:
            for interval in config.SUPPORTED_INTERVALS:
                stream_name = f"{symbol.lower()}@kline_{interval}"
                streams.append(stream_name)
        
        # Разбиваем на группы по конфигу
        stream_groups = []
        for i in range(0, len(streams), config.MAX_STREAMS_PER_CONNECTION):
            group = streams[i:i + config.MAX_STREAMS_PER_CONNECTION]
            stream_groups.append(group)
        
        self.stream_groups = stream_groups
        logger.info(f"Generated {len(self.stream_groups)} stream groups with {len(streams)} total streams")
            
    async def _test_single_stream(self, symbol: str, interval: str) -> bool:
        """Тестирование одного стрима"""
        try:
            test_session = aiohttp.ClientSession()
            stream_name = f"{symbol.lower()}@kline_{interval}"
            url = f"{config.BINANCE_WS_URL}/ws/{stream_name}"
            
            async with test_session.ws_connect(url, timeout=aiohttp.ClientTimeout(total=5)) as ws:
                # Ждем одно сообщение для проверки
                msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                await test_session.close()
                return msg.type == aiohttp.WSMsgType.TEXT
                
        except Exception as e:
            logger.debug(f"Stream {stream_name} test failed: {e}")
            return False
        finally:
            if test_session and not test_session.closed:
                await test_session.close()
    
    async def start(self):
        """Запуск всех WebSocket соединений"""
        if self.running:
            return
        
        self.running = True
        logger.info("Starting WebSocket connections...")
        
        # Генерируем стримы на основе кеша
        self._generate_streams()
        
        if not self.stream_groups:
            logger.error("No stream groups to connect to")
            return
        
        # Создаем соединения для каждой группы стримов
        for i, stream_group in enumerate(self.stream_groups):
            task = asyncio.create_task(self._connect_group(i, stream_group))
            self.reconnect_tasks.append(task)
            # Небольшая задержка между подключениями
            await asyncio.sleep(0.5)
        
        logger.info(f"Started {len(self.stream_groups)} WebSocket connection tasks")
    
    async def stop(self):
        """Остановка всех соединений"""
        logger.info("Stopping WebSocket connections...")
        self.running = False
        
        # Отменяем задачи переподключения
        for task in self.reconnect_tasks:
            task.cancel()
        
        # Ждем завершения задач
        if self.reconnect_tasks:
            await asyncio.gather(*self.reconnect_tasks, return_exceptions=True)
        
        # Закрываем все соединения
        for ws in self.connections:
            if not ws.closed:
                await ws.close()
        
        # Закрываем сессии
        for session in self.sessions:
            await session.close()
        
        self.connections.clear()
        self.sessions.clear()
        self.reconnect_tasks.clear()
        
        logger.info("All WebSocket connections stopped")
    
    async def _connect_group(self, group_id: int, streams: List[str]):
        """Подключение группы стримов"""
        retries = 0
        max_retries = config.RECONNECT_MAX_ATTEMPTS
        
        while self.running and retries < max_retries:
            session = None
            try:
                session = aiohttp.ClientSession()
                
                # Формируем URL для множественных стримов
                stream_names = "/".join(streams)
                url = f"{config.BINANCE_WS_URL}/stream?streams={stream_names}"
                
                logger.info(f"Connecting WebSocket group {group_id} with {len(streams)} streams... (attempt {retries + 1})")
                
                async with session.ws_connect(
                    url, 
                    timeout=aiohttp.ClientTimeout(total=30),
                    heartbeat=30
                ) as ws:
                    self.sessions.append(session)
                    self.connections.append(ws)
                    logger.info(f"WebSocket group {group_id} connected successfully")
                    
                    retries = 0  # Сбрасываем счетчик при успешном подключении
                    
                    # Обработка сообщений
                    async for msg in ws:
                        if not self.running:
                            break
                            
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._process_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error in group {group_id}: {ws.exception()}")
                            self.stats['errors'] += 1
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.warning(f"WebSocket group {group_id} closed")
                            break
                
            except aiohttp.ClientResponseError as e:
                logger.error(f"HTTP error in WebSocket group {group_id}: {e}")
                self.stats['errors'] += 1
                retries += 1
            except Exception as e:
                logger.error(f"Error in WebSocket group {group_id}: {e}")
                self.stats['errors'] += 1
                retries += 1
            
            finally:
                # Очищаем соединение из списков
                if session and session in self.sessions:
                    self.sessions.remove(session)
                if session:
                    await session.close()
            
            if self.running and retries < max_retries:
                # Переподключение с экспоненциальной задержкой
                delay = min(config.RECONNECT_DELAY * (2 ** retries), 60)
                self.stats['reconnects'] += 1
                logger.info(f"Reconnecting WebSocket group {group_id} in {delay} seconds...")
                await asyncio.sleep(delay)
        
        if retries >= max_retries:
            logger.error(f"WebSocket group {group_id} failed after {max_retries} attempts")
    
    async def _process_message(self, raw_data: str):
        """Обработка сообщения от Binance"""
        try:
            data = json.loads(raw_data)
            
            # Binance отправляет данные в формате: {"stream": "btcusdt@kline_1m", "data": {...}}
            if 'data' in data:
                kline_data = data['data']
                
                # Извлекаем информацию о свече
                if kline_data.get('e') == 'kline':
                    candle = self._parse_kline(kline_data)
                    
                    # Отправляем в обработчик
                    await self.candle_callback(candle)
                    
                    # Обновляем статистику
                    self.stats['messages_received'] += 1
                    self.stats['last_message_time'] = datetime.now()
            
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
            self.stats['errors'] += 1
    
    def _parse_kline(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсинг данных свечи"""
        kline = data['k']
        
        return {
            'symbol': data['s'],
            'interval': kline['i'],
            'open_time': kline['t'],
            'close_time': kline['T'],
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v']),
            'quote_volume': float(kline['q']),
            'trades': kline['n'],
            'is_closed': kline['x'],  # Свеча закрыта?
            'timestamp': datetime.now()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            **self.stats,
            'active_connections': len([ws for ws in self.connections if not ws.closed]),
            'total_connections': len(self.connections),
            'stream_groups': len(self.stream_groups)
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья соединений"""
        active = len([ws for ws in self.connections if not ws.closed])
        closed = len([ws for ws in self.connections if ws.closed])
        
        health = {
            'healthy': active > 0,
            'active_connections': active,
            'closed_connections': closed,
            'last_message_age': None
        }
        
        if self.stats['last_message_time']:
            age = (datetime.now() - self.stats['last_message_time']).total_seconds()
            health['last_message_age'] = age
            health['healthy'] = health['healthy'] and age < 60  # Нездорово если нет сообщений больше минуты
        
        return health