"""Binance WebSocket connection manager."""

import asyncio
import json
import websockets
import aiohttp
from typing import List, Set, Dict, Optional, Callable, Any
from config.settings import Config
from utils.rate_limiter import binance_limiter
import structlog

logger = structlog.get_logger()


class BinanceWebSocketManager:
    """Manages multiple WebSocket connections to Binance."""
    
    def __init__(self, message_handler: Callable[[Dict], None]):
        self.message_handler = message_handler
        self.connections: List[websockets.WebSocketServerProtocol] = []
        self.active_streams: Set[str] = set()
        self.should_stop = False
        self.reconnect_delay = Config.RECONNECT_DELAY
        
    async def get_all_futures_symbols(self) -> List[str]:
        """Get all futures trading pairs from Binance."""
        try:
            await binance_limiter.acquire_api()
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{Config.BINANCE_API_URL}/fapi/v1/exchangeInfo") as response:
                    if response.status == 200:
                        data = await response.json()
                        symbols = []
                        
                        for symbol_info in data['symbols']:
                            if symbol_info['status'] == 'TRADING':
                                symbols.append(symbol_info['symbol'])
                        
                        logger.info(f"Retrieved {len(symbols)} active futures symbols")
                        return symbols[:400]  # Limit to top 400 pairs
                    else:
                        logger.error(f"Failed to get symbols: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Error fetching symbols: {e}")
            return []
    
    def generate_all_streams(self, symbols: List[str]) -> Set[str]:
        """Generate all possible kline streams for symbols."""
        streams = set()
        for symbol in symbols:
            for interval in Config.SUPPORTED_INTERVALS:
                stream = f"{symbol.lower()}@kline_{interval}"
                streams.add(stream)
        return streams
    
    async def start_connections(self, required_streams: Set[str] = None) -> None:
        """Start WebSocket connections for all streams."""
        if not required_streams:
            # Get all symbols and generate streams
            symbols = await self.get_all_futures_symbols()
            if not symbols:
                logger.error("No symbols retrieved, cannot start WebSocket connections")
                return
            
            all_streams = self.generate_all_streams(symbols)
        else:
            all_streams = required_streams
        
        self.active_streams = all_streams
        
        # Split streams across multiple connections (max 1024 per connection)
        stream_chunks = self._chunk_streams(list(all_streams), Config.MAX_STREAMS_PER_CONNECTION)
        
        logger.info(f"Starting {len(stream_chunks)} WebSocket connections for {len(all_streams)} streams")
        
        # Start connections
        tasks = []
        for i, streams in enumerate(stream_chunks):
            task = asyncio.create_task(self._maintain_connection(i, streams))
            tasks.append(task)
        
        # Wait for all connections to start
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def _chunk_streams(self, streams: List[str], chunk_size: int) -> List[List[str]]:
        """Split streams into chunks for multiple connections."""
        chunks = []
        for i in range(0, len(streams), chunk_size):
            chunks.append(streams[i:i + chunk_size])
        return chunks
    
    async def _maintain_connection(self, connection_id: int, streams: List[str]) -> None:
        """Maintain a single WebSocket connection with reconnection logic."""
        while not self.should_stop:
            try:
                await self._connect_and_listen(connection_id, streams)
            except Exception as e:
                logger.error(f"Connection {connection_id} error: {e}")
                
            if not self.should_stop:
                logger.info(f"Reconnecting connection {connection_id} in {self.reconnect_delay} seconds")
                await asyncio.sleep(self.reconnect_delay)
    
    async def _connect_and_listen(self, connection_id: int, streams: List[str]) -> None:
        """Connect to WebSocket and listen for messages."""
        # Build stream URL
        stream_params = "/".join(streams)
        ws_url = f"{Config.BINANCE_WS_URL}/{stream_params}"
        
        logger.info(f"Connecting to WebSocket {connection_id} with {len(streams)} streams")
        
        await binance_limiter.acquire_ws_connection()
        
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
            max_size=10**7,  # 10MB max message size
        ) as websocket:
            
            logger.info(f"WebSocket connection {connection_id} established")
            
            while not self.should_stop:
                try:
                    # Receive message with timeout
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                    
                    if message:
                        await self._handle_message(connection_id, message)
                        
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.ping()
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning(f"WebSocket connection {connection_id} closed")
                    break
                except Exception as e:
                    logger.error(f"Error in WebSocket {connection_id}: {e}")
                    break
    
    async def _handle_message(self, connection_id: int, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # Check if it's a kline message
            if 'stream' in data and 'data' in data:
                stream_data = data['data']
                if 'k' in stream_data:  # Kline data
                    kline = stream_data['k']
                    
                    # Only process closed candles
                    if kline['x']:  # x = is_closed
                        candle_data = {
                            'symbol': kline['s'],
                            'interval': kline['i'],
                            'open_price': float(kline['o']),
                            'close_price': float(kline['c']),
                            'high_price': float(kline['h']),
                            'low_price': float(kline['l']),
                            'volume': float(kline['v']),
                            'close_time': kline['T'],
                            'connection_id': connection_id
                        }
                        
                        # Calculate percentage change
                        percent_change = ((candle_data['close_price'] - candle_data['open_price']) / 
                                        candle_data['open_price']) * 100
                        candle_data['percent_change'] = percent_change
                        
                        # Pass to message handler
                        self.message_handler(candle_data)
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from connection {connection_id}")
        except Exception as e:
            logger.error(f"Error handling message from connection {connection_id}: {e}")
    
    async def update_streams(self, new_streams: Set[str]) -> None:
        """Update active streams (requires reconnection)."""
        if new_streams != self.active_streams:
            logger.info(f"Updating streams: {len(new_streams)} new streams")
            self.active_streams = new_streams
            
            # Stop current connections
            await self.stop()
            
            # Start with new streams
            await self.start_connections(new_streams)
    
    async def stop(self) -> None:
        """Stop all WebSocket connections."""
        logger.info("Stopping WebSocket connections")
        self.should_stop = True
        
        # Close all connections
        for connection in self.connections:
            if connection and not connection.closed:
                await connection.close()
        
        self.connections.clear()
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            'active_connections': len(self.connections),
            'active_streams': len(self.active_streams),
            'should_stop': self.should_stop,
            'reconnect_delay': self.reconnect_delay
        }