"""Configuration settings for crypto bot."""

import os
from typing import List, Dict, Any
from decouple import config


class Config:
    """Application configuration."""
    
    # Telegram
    BOT_TOKEN: str = config("BOT_TOKEN")
    
    # Binance
    BINANCE_WS_URL: str = "wss://fstream.binance.com/ws"
    BINANCE_API_URL: str = "https://fapi.binance.com"
    RECONNECT_DELAY: int = 5
    MAX_STREAMS_PER_CONNECTION: int = 1024
    
    # Gas tracking
    ETHERSCAN_API_KEY: str = config("ETHERSCAN_API_KEY")
    ETHERSCAN_API_URL: str = "https://api.etherscan.io/api"
    GAS_CHECK_INTERVAL: int = 60  # секунд
    
    # Limits
    MAX_PRESETS_PER_USER: int = 10
    MAX_PAIRS_PER_PRESET: int = 50
    CANDLE_QUEUE_SIZE: int = 10000
    ALERT_BATCH_SIZE: int = 50
    
    # Database
    DATABASE_URL: str = config("DATABASE_URL", default="postgresql://localhost/crypto_bot")
    
    # Performance
    WORKER_THREADS: int = 4
    BATCH_PROCESS_SIZE: int = 500
    
    # Rate limiting
    TELEGRAM_RATE_LIMIT: int = 30  # messages per second
    USER_RATE_LIMIT: int = 5  # messages per user per minute
    
    # Supported timeframes
    SUPPORTED_INTERVALS: List[str] = ["1m", "5m", "15m", "30m", "1h", "4h"]
    
    # Memory limits
    MAX_MEMORY_MB: int = 1024
    CANDLE_HISTORY_SIZE: int = 1440  # 24 hours of minutes
    ALERT_HISTORY_SIZE: int = 10000
    
    # Logging
    LOG_LEVEL: str = config("LOG_LEVEL", default="INFO")
    
    @classmethod
    def validate(cls) -> bool:
        """Validate configuration."""
        required_vars = ["BOT_TOKEN", "ETHERSCAN_API_KEY", "DATABASE_URL"]
        for var in required_vars:
            if not getattr(cls, var, None):
                raise ValueError(f"Missing required config: {var}")
        return True