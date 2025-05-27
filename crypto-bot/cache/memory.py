"""In-memory cache for high-performance operations."""

import asyncio
from collections import defaultdict, deque
from typing import Dict, List, Set, Any, Optional, Tuple
from datetime import datetime, timedelta
from config.settings import Config
import structlog

logger = structlog.get_logger()


class MemoryCache:
    """High-performance in-memory cache."""
    
    def __init__(self):
        # User states for finite state machine
        self.user_states: Dict[int, str] = {}
        
        # Active presets structure: {symbol: {interval: {user_id: [preset_ids]}}}
        self.active_subscriptions: Dict[str, Dict[str, Dict[int, List[int]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        
        # Reverse mapping: preset_id -> (user_id, symbol, interval, percent_change)
        self.preset_mapping: Dict[int, Tuple[int, str, str, float]] = {}
        
        # Candle buffer for processing
        self.candle_buffer: deque = deque(maxsize=Config.CANDLE_QUEUE_SIZE)
        
        # Alert history to prevent spam
        self.alert_history: deque = deque(maxsize=Config.ALERT_HISTORY_SIZE)
        
        # Gas price history (last 24 hours)
        self.gas_price_history: deque = deque(maxsize=Config.CANDLE_HISTORY_SIZE)
        
        # Gas alert thresholds: {user_id: threshold_gwei}
        self.gas_alerts: Dict[int, float] = {}
        
        # Rate limiting
        self.user_message_counts: Dict[int, deque] = defaultdict(
            lambda: deque(maxsize=Config.USER_RATE_LIMIT)
        )
        
        # Statistics
        self.stats = {
            'candles_processed': 0,
            'alerts_sent': 0,
            'active_users': 0,
            'active_presets': 0,
            'memory_usage_mb': 0
        }
    
    async def load_from_database(self, db_manager) -> None:
        """Load active data from database into memory."""
        try:
            # Load active presets
            presets = await db_manager.get_active_presets()
            for preset in presets:
                await self.add_preset_to_cache(preset)
            
            # Load gas alerts
            gas_alerts = await db_manager.get_gas_alerts()
            for alert in gas_alerts:
                self.gas_alerts[alert['user_id']] = float(alert['threshold_gwei'])
            
            logger.info(f"Loaded {len(presets)} presets and {len(gas_alerts)} gas alerts into cache")
            
        except Exception as e:
            logger.error(f"Failed to load data from database: {e}")
            raise
    
    async def add_preset_to_cache(self, preset: Dict[str, Any]) -> None:
        """Add preset to active subscriptions cache."""
        preset_id = preset['id']
        user_id = preset['user_id']
        pairs = preset['pairs']
        intervals = preset['intervals']
        percent_change = float(preset['percent_change'])
        
        for pair in pairs:
            for interval in intervals:
                self.active_subscriptions[pair][interval][user_id].append(preset_id)
                self.preset_mapping[preset_id] = (user_id, pair, interval, percent_change)
    
    async def remove_preset_from_cache(self, preset_id: int) -> None:
        """Remove preset from active subscriptions cache."""
        if preset_id not in self.preset_mapping:
            return
        
        user_id, symbol, interval, _ = self.preset_mapping[preset_id]
        
        # Remove from active subscriptions
        if (symbol in self.active_subscriptions and 
            interval in self.active_subscriptions[symbol] and
            user_id in self.active_subscriptions[symbol][interval]):
            
            preset_list = self.active_subscriptions[symbol][interval][user_id]
            if preset_id in preset_list:
                preset_list.remove(preset_id)
                
                # Clean empty structures
                if not preset_list:
                    del self.active_subscriptions[symbol][interval][user_id]
                    if not self.active_subscriptions[symbol][interval]:
                        del self.active_subscriptions[symbol][interval]
                        if not self.active_subscriptions[symbol]:
                            del self.active_subscriptions[symbol]
        
        # Remove from preset mapping
        del self.preset_mapping[preset_id]
    
    def get_subscribers_for_symbol(self, symbol: str, interval: str) -> Dict[int, List[Tuple[int, float]]]:
        """Get all subscribers for a symbol/interval with their preset configs."""
        subscribers = {}
        
        if symbol in self.active_subscriptions and interval in self.active_subscriptions[symbol]:
            for user_id, preset_ids in self.active_subscriptions[symbol][interval].items():
                user_presets = []
                for preset_id in preset_ids:
                    if preset_id in self.preset_mapping:
                        _, _, _, percent_change = self.preset_mapping[preset_id]
                        user_presets.append((preset_id, percent_change))
                if user_presets:
                    subscribers[user_id] = user_presets
        
        return subscribers
    
    def add_candle_to_buffer(self, candle_data: Dict[str, Any]) -> None:
        """Add candle to processing buffer."""
        if len(self.candle_buffer) >= Config.CANDLE_QUEUE_SIZE:
            logger.warning("Candle buffer full, dropping oldest candle")
        self.candle_buffer.append(candle_data)
    
    def get_candles_batch(self, batch_size: int = None) -> List[Dict[str, Any]]:
        """Get batch of candles for processing."""
        if batch_size is None:
            batch_size = Config.BATCH_PROCESS_SIZE
        
        batch = []
        for _ in range(min(batch_size, len(self.candle_buffer))):
            if self.candle_buffer:
                batch.append(self.candle_buffer.popleft())
        return batch
    
    def should_send_alert(self, user_id: int, symbol: str, interval: str, 
                         percent_change: float) -> bool:
        """Check if alert should be sent (dedupe logic)."""
        current_time = datetime.now()
        alert_key = f"{user_id}:{symbol}:{interval}:{abs(percent_change):.2f}"
        
        # Check recent alerts to prevent spam
        for alert_time, key in reversed(list(self.alert_history)):
            if current_time - alert_time > timedelta(minutes=5):
                break
            if key == alert_key:
                return False
        
        # Add to history
        self.alert_history.append((current_time, alert_key))
        return True
    
    def can_send_message_to_user(self, user_id: int) -> bool:
        """Check rate limit for user messages."""
        current_time = datetime.now()
        user_messages = self.user_message_counts[user_id]
        
        # Clean old messages (older than 1 minute)
        while user_messages and current_time - user_messages[0] > timedelta(minutes=1):
            user_messages.popleft()
        
        # Check limit
        if len(user_messages) >= Config.USER_RATE_LIMIT:
            return False
        
        # Add current message
        user_messages.append(current_time)
        return True
    
    def add_gas_price(self, price_gwei: float) -> None:
        """Add gas price to history."""
        current_time = datetime.now()
        self.gas_price_history.append((current_time, price_gwei))
    
    def get_gas_price_trend(self, minutes: int = 60) -> Optional[Tuple[float, float]]:
        """Get gas price trend over specified minutes."""
        if len(self.gas_price_history) < 2:
            return None
        
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(minutes=minutes)
        
        recent_prices = [price for time, price in self.gas_price_history 
                        if time >= cutoff_time]
        
        if len(recent_prices) < 2:
            return None
        
        return recent_prices[0], recent_prices[-1]  # oldest, newest
    
    def get_users_for_gas_threshold(self, current_price: float) -> List[int]:
        """Get users who should receive gas alerts."""
        return [user_id for user_id, threshold in self.gas_alerts.items() 
                if current_price <= threshold]
    
    def update_stats(self) -> None:
        """Update cache statistics."""
        self.stats['active_users'] = len(set(
            user_id for symbol_subs in self.active_subscriptions.values()
            for interval_subs in symbol_subs.values()
            for user_id in interval_subs.keys()
        ))
        self.stats['active_presets'] = len(self.preset_mapping)
    
    def get_all_required_streams(self) -> Set[str]:
        """Get all required WebSocket streams."""
        streams = set()
        for symbol, intervals in self.active_subscriptions.items():
            for interval in intervals.keys():
                streams.add(f"{symbol.lower()}@kline_{interval}")
        return streams
    
    def set_user_state(self, user_id: int, state: str) -> None:
        """Set user FSM state."""
        self.user_states[user_id] = state
    
    def get_user_state(self, user_id: int) -> Optional[str]:
        """Get user FSM state."""
        return self.user_states.get(user_id)
    
    def clear_user_state(self, user_id: int) -> None:
        """Clear user FSM state."""
        self.user_states.pop(user_id, None)


# Global cache instance
memory_cache = MemoryCache()