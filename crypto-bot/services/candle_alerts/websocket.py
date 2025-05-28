import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
import aiohttp
from collections import defaultdict

from config.settings import config
from services.binanceAPI.service import binance_api
logger = logging.getLogger(__name__)


class BinanceWebSocketManager:
    """Менеджер WebSocket подключений к Binance"""
    
    def __init__(self, candle_callback: Callable):
        self.candle_callback = candle_callback
        self.connections: List[aiohttp.ClientWebSocketResponse] = []
        self.sessions: List[aiohttp.ClientSession] = []
        self.running = False
        self.reconnect_tasks = []
        self.all_streams = []
        # Статистика
        self.stats = {
            'messages_received': 0,
            'reconnects': 0,
            'errors': 0,
            'last_message_time': None
        }
        self._generate_all_streams
        # Все возможные стримы
        
        logger.info(f"Generated {len(self.all_streams)} streams")
    
    async def _generate_all_streams(self):
        """Генерация всех возможных стримов на основе реальных данных"""
        try:
            # Получаем все символы из API
            all_symbols = await binance_api.get_all_symbols()
            
            if not all_symbols:
                logger.error("No symbols received from Binance API")
                return
                
            # Генерируем стримы для всех комбинаций символ/интервал
            streams = []
            for symbol in all_symbols:
                for interval in config.SUPPORTED_INTERVALS:
                    streams.append(f"{symbol.lower()}@kline_{interval}")
            
            # Разбиваем на группы
            stream_groups = []
            for i in range(0, len(streams), config.MAX_STREAMS_PER_CONNECTION):
                group = streams[i:i + config.MAX_STREAMS_PER_CONNECTION]
                stream_groups.append(group)
            
            self.all_streams = stream_groups
            logger.info(f"Generated {len(self.all_streams)} stream groups with {len(streams)} total streams")
            
        except Exception as e:
            logger.error(f"Error generating streams: {e}")
            raise
    
    async def start(self):
        """Запуск всех WebSocket соединений"""
        if self.running:
            return
        
        self.running = True
        logger.info("Starting WebSocket connections...")
        
        # Создаем соединения для каждой группы стримов
        for i, stream_group in enumerate(self.all_streams):
            asyncio.create_task(self._connect_group(i, stream_group))
            # Небольшая задержка между подключениями
            await asyncio.sleep(0.5)
        
        logger.info(f"Started {len(self.all_streams)} WebSocket connection tasks")
    
    async def stop(self):
        """Остановка всех соединений"""
        logger.info("Stopping WebSocket connections...")
        self.running = False
        
        # Отменяем задачи переподключения
        for task in self.reconnect_tasks:
            task.cancel()
        
        # Закрываем все соединения
        for ws in self.connections:
            if not ws.closed:
                await ws.close()
        
        # Закрываем сессии
        for session in self.sessions:
            await session.close()
        
        self.connections.clear()
        self.sessions.clear()
        
        logger.info("All WebSocket connections stopped")
    
    async def _connect_group(self, group_id: int, streams: List[str]):
        """Подключение группы стримов"""
        while self.running:
            try:
                session = aiohttp.ClientSession()
                self.sessions.append(session)
                
                # Формируем URL для множественных стримов
                stream_names = "/".join(streams)
                url = f"{config.BINANCE_WS_URL}/stream?streams={stream_names}"
                
                logger.info(f"Connecting WebSocket group {group_id} with {len(streams)} streams...")
                
                async with session.ws_connect(url) as ws:
                    self.connections.append(ws)
                    logger.info(f"WebSocket group {group_id} connected")
                    
                    # Обработка сообщений
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._process_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error in group {group_id}: {ws.exception()}")
                            self.stats['errors'] += 1
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.warning(f"WebSocket group {group_id} closed")
                            break
                
            except Exception as e:
                logger.error(f"Error in WebSocket group {group_id}: {e}")
                self.stats['errors'] += 1
            
            if self.running:
                # Переподключение
                self.stats['reconnects'] += 1
                logger.info(f"Reconnecting WebSocket group {group_id} in {config.RECONNECT_DELAY} seconds...")
                await asyncio.sleep(config.RECONNECT_DELAY)
    
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
            'total_connections': len(self.connections)
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья соединений"""
        active = 0
        closed = 0
        
        for ws in self.connections:
            if ws.closed:
                closed += 1
            else:
                active += 1
        
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


class BinanceRESTClient:
    """Клиент для REST API Binance"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_all_symbols(self) -> List[str]:
        """Получение всех торговых пар"""
        try:
            async with self.session.get(f"{config.BINANCE_REST_URL}/fapi/v1/exchangeInfo") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Фильтруем только USDT пары со статусом TRADING
                    symbols = [
                        s['symbol'] for s in data['symbols']
                        if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'
                    ]
                    
                    return symbols
                else:
                    logger.error(f"Failed to get symbols: {resp.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            return []
    
    async def get_top_symbols_by_volume(self, limit: int = 100) -> List[str]:
        """Получение топ символов по объему"""
        try:
            async with self.session.get(f"{config.BINANCE_REST_URL}/fapi/v1/ticker/24hr") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Фильтруем USDT пары
                    usdt_pairs = [
                        item for item in data
                        if item['symbol'].endswith('USDT')
                    ]
                    
                    # Сортируем по объему
                    usdt_pairs.sort(
                        key=lambda x: float(x['quoteVolume']),
                        reverse=True
                    )
                    
                    # Возвращаем символы
                    return [pair['symbol'] for pair in usdt_pairs[:limit]]
                else:
                    logger.error(f"Failed to get tickers: {resp.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error getting top symbols: {e}")
            return []