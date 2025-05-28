import os
from typing import List, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Централизованная конфигурация приложения"""
    
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # Binance
    BINANCE_WS_URL: str = "wss://fstream.binance.com/ws"
    BINANCE_REST_URL: str = "https://fapi.binance.com"
    MAX_STREAMS_PER_CONNECTION: int = 750
    RECONNECT_DELAY: int = 5
    RECONNECT_MAX_ATTEMPTS: int = 10
    
    # Gas tracking
    ETHERSCAN_API_KEY: str = os.getenv("ETHERSCAN_API_KEY", "")
    ETHERSCAN_API_URL: str = "https://api.etherscan.io/api"
    GAS_CHECK_INTERVAL: int = 60  # секунд
    GAS_HISTORY_SIZE: int = 1440  # 24 часа
    
    # User limits
    MAX_PRESETS_PER_USER: int = 10
    MAX_PAIRS_PER_PRESET: int = 50
    MAX_ALERTS_PER_MESSAGE: int = 50
    
    # Performance
    CANDLE_QUEUE_SIZE: int = 10000
    ALERT_QUEUE_SIZE: int = 5000
    BATCH_PROCESS_SIZE: int = 500
    WORKER_THREADS: int = 4
    
    # Rate limits
    TELEGRAM_RATE_LIMIT: int = 30  # messages per second
    ALERT_DEDUP_WINDOW: int = 60  # секунд
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://localhost/crypto_bot")
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    
    # Cache
    CACHE_TTL: int = 3600  # 1 час
    ALERT_HISTORY_SIZE: int = 10000
    
    # Monitoring
    METRICS_PORT: int = 9090
    HEALTH_CHECK_INTERVAL: int = 30
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Supported intervals
    SUPPORTED_INTERVALS: List[str] = field(default_factory=lambda: ["1m", "5m", "15m", "30m", "1h", "4h"])
    
    # Percentage thresholds
    MIN_PERCENT_CHANGE: float = 0.1
    MAX_PERCENT_CHANGE: float = 100.0
    
    @classmethod
    def validate(cls) -> None:
        """Валидация обязательных параметров"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN не установлен")
        if not cls.ETHERSCAN_API_KEY:
            raise ValueError("ETHERSCAN_API_KEY не установлен")
        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL не установлен")


config = Config()