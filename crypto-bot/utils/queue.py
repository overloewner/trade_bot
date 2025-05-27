"""Message queue utilities."""

import asyncio
import heapq
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field
from config.settings import Config
import structlog

logger = structlog.get_logger()


@dataclass
class Alert:
    """Alert message structure."""
    user_id: int
    symbol: str
    interval: str
    percent_change: float
    price: float
    timestamp: datetime
    priority: int = field(default=0)
    
    def __lt__(self, other):
        """For priority queue ordering (higher priority first)."""
        return self.priority > other.priority


@dataclass
class BatchedMessage:
    """Batched message for sending."""
    user_id: int
    alerts: List[Alert]
    created_at: datetime = field(default_factory=datetime.now)


class MessageQueue:
    """High-performance message queue with batching and prioritization."""
    
    def __init__(self):
        # Priority queue for alerts (higher percentage changes get priority)
        self.alert_queue: List[Alert] = []
        
        # Pending alerts per user for batching
        self.user_pending_alerts: Dict[int, List[Alert]] = defaultdict(list)
        
        # Batch send queue
        self.batch_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        
        # Gas alerts queue (separate for different handling)
        self.gas_alert_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        
        # Statistics
        self.stats = {
            'alerts_queued': 0,
            'alerts_sent': 0,
            'batches_created': 0,
            'queue_size': 0
        }
    
    def add_price_alert(self, user_id: int, symbol: str, interval: str, 
                       percent_change: float, price: float) -> None:
        """Add price alert to queue with priority."""
        # Calculate priority based on percentage change magnitude
        priority = min(int(abs(percent_change) * 10), 100)
        
        alert = Alert(
            user_id=user_id,
            symbol=symbol,
            interval=interval,
            percent_change=percent_change,
            price=price,
            timestamp=datetime.now(),
            priority=priority
        )
        
        # Add to priority queue
        heapq.heappush(self.alert_queue, alert)
        self.stats['alerts_queued'] += 1
        
        logger.debug(f"Added alert for {symbol} {interval} {percent_change:.2f}% (priority: {priority})")
    
    async def add_gas_alert(self, user_ids: List[int], current_price: float, 
                           threshold: float) -> None:
        """Add gas price alert."""
        gas_alert = {
            'user_ids': user_ids,
            'current_price': current_price,
            'threshold': threshold,
            'timestamp': datetime.now()
        }
        
        try:
            await self.gas_alert_queue.put(gas_alert)
        except asyncio.QueueFull:
            logger.warning("Gas alert queue full, dropping alert")
    
    async def process_alerts(self) -> None:
        """Process alerts and create batches."""
        while True:
            try:
                # Process price alerts
                await self._process_price_alerts()
                
                # Create batches for users with pending alerts
                await self._create_batches()
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error processing alerts: {e}")
                await asyncio.sleep(1)
    
    async def _process_price_alerts(self) -> None:
        """Process price alerts from priority queue."""
        batch_size = min(Config.BATCH_PROCESS_SIZE, len(self.alert_queue))
        
        for _ in range(batch_size):
            if not self.alert_queue:
                break
            
            alert = heapq.heappop(self.alert_queue)
            
            # Group by user for batching
            self.user_pending_alerts[alert.user_id].append(alert)
            
            # If user has enough alerts, create batch immediately
            if len(self.user_pending_alerts[alert.user_id]) >= Config.ALERT_BATCH_SIZE:
                await self._create_batch_for_user(alert.user_id)
    
    async def _create_batches(self) -> None:
        """Create batches for users with pending alerts."""
        current_time = datetime.now()
        users_to_batch = []
        
        # Find users with old pending alerts (force batching after 30 seconds)
        for user_id, alerts in self.user_pending_alerts.items():
            if alerts and (current_time - alerts[0].timestamp).total_seconds() > 30:
                users_to_batch.append(user_id)
        
        # Create batches for these users
        for user_id in users_to_batch:
            await self._create_batch_for_user(user_id)
    
    async def _create_batch_for_user(self, user_id: int) -> None:
        """Create batch message for specific user."""
        if user_id not in self.user_pending_alerts or not self.user_pending_alerts[user_id]:
            return
        
        alerts = self.user_pending_alerts[user_id][:Config.ALERT_BATCH_SIZE]
        self.user_pending_alerts[user_id] = self.user_pending_alerts[user_id][Config.ALERT_BATCH_SIZE:]
        
        # Clean up empty lists
        if not self.user_pending_alerts[user_id]:
            del self.user_pending_alerts[user_id]
        
        # Sort alerts by priority for better presentation
        alerts.sort(key=lambda x: x.priority, reverse=True)
        
        batch = BatchedMessage(user_id=user_id, alerts=alerts)
        
        try:
            await self.batch_queue.put(batch)
            self.stats['batches_created'] += 1
        except asyncio.QueueFull:
            logger.warning(f"Batch queue full, dropping batch for user {user_id}")
    
    async def get_batch_message(self) -> Optional[BatchedMessage]:
        """Get next batch message to send."""
        try:
            return await asyncio.wait_for(self.batch_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None
    
    async def get_gas_alert(self) -> Optional[Dict]:
        """Get next gas alert to send."""
        try:
            return await asyncio.wait_for(self.gas_alert_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return None
    
    def format_alert_message(self, batch: BatchedMessage) -> str:
        """Format batch of alerts into readable message."""
        if not batch.alerts:
            return ""
        
        # Group alerts by symbol for better readability
        symbol_groups = defaultdict(list)
        for alert in batch.alerts:
            symbol_groups[alert.symbol].append(alert)
        
        message_parts = ["🚨 **Crypto Alerts** 🚨\n"]
        
        for symbol, alerts in symbol_groups.items():
            message_parts.append(f"\n**{symbol}**:")
            
            for alert in alerts:
                direction = "📈" if alert.percent_change > 0 else "📉"
                message_parts.append(
                    f"{direction} {alert.interval}: {alert.percent_change:+.2f}% "
                    f"(${alert.price:.4f})"
                )
        
        message_parts.append(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
        
        return "\n".join(message_parts)
    
    def format_gas_alert_message(self, gas_alert: Dict) -> str:
        """Format gas alert message."""
        current_price = gas_alert['current_price']
        threshold = gas_alert['threshold']
        
        return (
            f"⛽ **Gas Alert** ⛽\n\n"
            f"Gas price dropped to **{current_price:.1f} Gwei**\n"
            f"Your threshold: {threshold:.1f} Gwei\n\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        self.stats['queue_size'] = len(self.alert_queue)
        return self.stats.copy()
    
    def clear_user_alerts(self, user_id: int) -> None:
        """Clear all pending alerts for user."""
        if user_id in self.user_pending_alerts:
            cleared_count = len(self.user_pending_alerts[user_id])
            del self.user_pending_alerts[user_id]
            logger.debug(f"Cleared {cleared_count} pending alerts for user {user_id}")


# Global message queue instance
message_queue = MessageQueue()