"""Candle data processor for generating alerts."""

import asyncio
from typing import Dict, List, Any
from cache.memory import memory_cache
from utils.queue import message_queue
from config.settings import Config
import structlog

logger = structlog.get_logger()


class CandleProcessor:
    """Processes candle data and generates alerts."""
    
    def __init__(self):
        self.processing = False
        self.stats = {
            'candles_processed': 0,
            'alerts_generated': 0,
            'processing_errors': 0,
            'avg_processing_time_ms': 0
        }
    
    async def start_processing(self) -> None:
        """Start candle processing loop."""
        if self.processing:
            logger.warning("Candle processor already running")
            return
        
        self.processing = True
        logger.info("Starting candle processor")
        
        # Start processing task
        asyncio.create_task(self._processing_loop())
    
    async def stop_processing(self) -> None:
        """Stop candle processing."""
        logger.info("Stopping candle processor")
        self.processing = False
    
    async def _processing_loop(self) -> None:
        """Main processing loop."""
        while self.processing:
            try:
                # Get batch of candles to process
                candles = memory_cache.get_candles_batch(Config.BATCH_PROCESS_SIZE)
                
                if candles:
                    await self._process_candles_batch(candles)
                else:
                    # No candles to process, small delay
                    await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                self.stats['processing_errors'] += 1
                await asyncio.sleep(0.1)
    
    async def _process_candles_batch(self, candles: List[Dict[str, Any]]) -> None:
        """Process a batch of candles."""
        import time
        start_time = time.time()
        
        processed_count = 0
        alerts_generated = 0
        
        for candle in candles:
            try:
                alerts_count = await self._process_single_candle(candle)
                alerts_generated += alerts_count
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing candle for {candle.get('symbol', 'unknown')}: {e}")
                self.stats['processing_errors'] += 1
        
        # Update statistics
        processing_time = (time.time() - start_time) * 1000  # Convert to ms
        self.stats['candles_processed'] += processed_count
        self.stats['alerts_generated'] += alerts_generated
        
        # Update average processing time
        if processed_count > 0:
            avg_time_per_candle = processing_time / processed_count
            self.stats['avg_processing_time_ms'] = (
                (self.stats['avg_processing_time_ms'] * 0.9) + 
                (avg_time_per_candle * 0.1)
            )
        
        if processed_count > 0:
            logger.debug(
                f"Processed {processed_count} candles in {processing_time:.2f}ms, "
                f"generated {alerts_generated} alerts"
            )
    
    async def _process_single_candle(self, candle: Dict[str, Any]) -> int:
        """Process a single candle and generate alerts."""
        symbol = candle['symbol']
        interval = candle['interval']
        percent_change = candle['percent_change']
        close_price = candle['close_price']
        
        # Get subscribers for this symbol/interval
        subscribers = memory_cache.get_subscribers_for_symbol(symbol, interval)
        
        if not subscribers:
            return 0
        
        alerts_generated = 0
        
        # Check each subscriber's presets
        for user_id, user_presets in subscribers.items():
            for preset_id, threshold_percent in user_presets:
                # Check if percentage change meets threshold
                if abs(percent_change) >= threshold_percent:
                    # Check if we should send this alert (dedupe logic)
                    if memory_cache.should_send_alert(
                        user_id, symbol, interval, percent_change
                    ):
                        # Check user rate limit
                        if memory_cache.can_send_message_to_user(user_id):
                            # Add alert to queue
                            message_queue.add_price_alert(
                                user_id=user_id,
                                symbol=symbol,
                                interval=interval,
                                percent_change=percent_change,
                                price=close_price
                            )
                            alerts_generated += 1
                        else:
                            logger.debug(f"Rate limit exceeded for user {user_id}")
        
        return alerts_generated
    
    def handle_candle_message(self, candle_data: Dict[str, Any]) -> None:
        """Handle incoming candle message from WebSocket."""
        # Add candle to buffer for processing
        memory_cache.add_candle_to_buffer(candle_data)
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return {
            **self.stats,
            'processing': self.processing,
            'buffer_size': len(memory_cache.candle_buffer)
        }


# Global candle processor instance
candle_processor = CandleProcessor()