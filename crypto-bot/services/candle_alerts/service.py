"""Candle alerts service - main orchestrator."""

import asyncio
from typing import Dict, Any
from .websocket import BinanceWebSocketManager
from .processor import candle_processor
from cache.memory import memory_cache
from models.database import db_manager
import structlog
from config.settings import Config

logger = structlog.get_logger()


class CandleAlertsService:
    """Main service for candle alerts functionality."""
    
    def __init__(self):
        self.ws_manager = BinanceWebSocketManager(self._handle_candle_message)
        self.running = False
        
    async def start(self) -> None:
        """Start the candle alerts service."""
        if self.running:
            logger.warning("Candle alerts service already running")
            return
        
        self.running = True
        logger.info("Starting candle alerts service")
        
        try:
            # Load active presets from database
            await memory_cache.load_from_database(db_manager)
            
            # Get required streams based on active subscriptions
            required_streams = memory_cache.get_all_required_streams()
            
            if required_streams:
                # Start WebSocket connections
                await self.ws_manager.start_connections(required_streams)
                logger.info(f"Started WebSocket connections for {len(required_streams)} streams")
            else:
                logger.info("No active subscriptions, starting with all streams")
                await self.ws_manager.start_connections()
            
            # Start candle processor
            await candle_processor.start_processing()
            
            logger.info("Candle alerts service started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start candle alerts service: {e}")
            self.running = False
            raise
    
    async def stop(self) -> None:
        """Stop the candle alerts service."""
        if not self.running:
            return
        
        logger.info("Stopping candle alerts service")
        self.running = False
        
        try:
            # Stop processor
            await candle_processor.stop_processing()
            
            # Stop WebSocket connections
            await self.ws_manager.stop()
            
            logger.info("Candle alerts service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping candle alerts service: {e}")
    
    def _handle_candle_message(self, candle_data: Dict[str, Any]) -> None:
        """Handle candle message from WebSocket."""
        candle_processor.handle_candle_message(candle_data)
    
    async def reload_subscriptions(self) -> None:
        """Reload subscriptions from database and update WebSocket streams."""
        try:
            logger.info("Reloading subscriptions")
            
            # Clear current cache
            memory_cache.active_subscriptions.clear()
            memory_cache.preset_mapping.clear()
            
            # Load fresh data from database
            await memory_cache.load_from_database(db_manager)
            
            # Get new required streams
            new_streams = memory_cache.get_all_required_streams()
            
            # Update WebSocket connections
            await self.ws_manager.update_streams(new_streams)
            
            logger.info(f"Reloaded subscriptions: {len(new_streams)} streams")
            
        except Exception as e:
            logger.error(f"Failed to reload subscriptions: {e}")
            raise
    
    async def add_preset_subscription(self, preset: Dict[str, Any]) -> None:
        """Add new preset to active subscriptions."""
        try:
            # Add to memory cache
            await memory_cache.add_preset_to_cache(preset)
            
            # Check if we need to update WebSocket streams
            current_streams = self.ws_manager.active_streams
            required_streams = memory_cache.get_all_required_streams()
            
            if not required_streams.issubset(current_streams):
                logger.info("New streams required, updating WebSocket connections")
                await self.ws_manager.update_streams(required_streams)
            
        except Exception as e:
            logger.error(f"Failed to add preset subscription: {e}")
            raise
    
    async def remove_preset_subscription(self, preset_id: int) -> None:
        """Remove preset from active subscriptions."""
        try:
            # Remove from memory cache
            await memory_cache.remove_preset_from_cache(preset_id)
            
            # Optionally optimize streams (remove unused ones)
            # For simplicity, we keep all streams active to avoid frequent reconnections
            
        except Exception as e:
            logger.error(f"Failed to remove preset subscription: {e}")
            raise
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        return {
            'running': self.running,
            'websocket_stats': self.ws_manager.get_connection_stats(),
            'processor_stats': candle_processor.get_processing_stats(),
            'cache_stats': {
                'active_subscriptions': len(memory_cache.active_subscriptions),
                'preset_mappings': len(memory_cache.preset_mapping),
                'candle_buffer_size': len(memory_cache.candle_buffer)
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        health = {
            'status': 'healthy',
            'issues': []
        }
        
        # Check if service is running
        if not self.running:
            health['status'] = 'unhealthy'
            health['issues'].append('Service not running')
        
        # Check WebSocket connections
        ws_stats = self.ws_manager.get_connection_stats()
        if ws_stats['active_connections'] == 0:
            health['status'] = 'degraded'
            health['issues'].append('No active WebSocket connections')
        
        # Check processor
        if not candle_processor.processing:
            health['status'] = 'degraded'
            health['issues'].append('Candle processor not running')
        
        # Check buffer size (potential backlog)
        buffer_size = len(memory_cache.candle_buffer)
        if buffer_size > Config.CANDLE_QUEUE_SIZE * 0.8:
            health['status'] = 'degraded'
            health['issues'].append(f'High buffer usage: {buffer_size}')
        
        return health


# Global service instance
candle_alerts_service = CandleAlertsService()