import os
from typing import List, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Централизованная конфигурация приложения"""
    
    # === TELEGRAM BOT ===
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # === BINANCE API ===
    BINANCE_WS_URL: str = "wss://fstream.binance.com"
    BINANCE_REST_URL: str = "https://fapi.binance.com"
    MAX_STREAMS_PER_CONNECTION: int = 750
    RECONNECT_DELAY: int = 5
    RECONNECT_MAX_ATTEMPTS: int = 10
    
    # === ETHERSCAN API ===
    ETHERSCAN_API_KEY: str = os.getenv("ETHERSCAN_API_KEY", "")
    ETHERSCAN_API_URL: str = "https://api.etherscan.io/api"
    
    # === GAS MONITORING ===
    GAS_CHECK_INTERVAL: int = 60  # секунд между проверками
    GAS_HISTORY_SIZE: int = 1440  # количество записей (24 часа при проверке каждую минуту)
    GAS_NOTIFICATION_COOLDOWN: int = 3600  # секунд между уведомлениями одному пользователю
    GAS_MIN_THRESHOLD: float = 0.1  # минимальный порог в Gwei
    GAS_MAX_THRESHOLD: float = 1000.0  # максимальный порог в Gwei
    
    # === USER LIMITS ===
    MAX_PRESETS_PER_USER: int = 10
    MAX_PAIRS_PER_PRESET: int = 250
    MAX_ALERTS_PER_MESSAGE: int = 50
    PRESET_NAME_MAX_LENGTH: int = 100
    
    # === PERFORMANCE & QUEUES ===
    CANDLE_QUEUE_SIZE: int = 10000
    ALERT_QUEUE_SIZE: int = 5000
    BATCH_PROCESS_SIZE: int = 500
    WORKER_THREADS: int = 4
    
    # === RATE LIMITS ===
    # Telegram API limits
    TELEGRAM_GLOBAL_RATE_LIMIT: int = 30  # messages per second
    TELEGRAM_CHAT_RATE_LIMIT: int = 20  # messages per minute per chat
    TELEGRAM_USER_RATE_LIMIT: int = 1  # messages per second per user
    TELEGRAM_BURST_SIZE: int = 40
    
    # Binance API limits
    BINANCE_RATE_LIMIT: int = 1200  # requests per minute
    BINANCE_RATE_PERIOD: float = 60.0  # seconds
    
    # Etherscan API limits
    ETHERSCAN_RATE_LIMIT: int = 5  # requests per second
    ETHERSCAN_RATE_PERIOD: float = 1.0  # seconds
    
    # === ALERT SYSTEM ===
    ALERT_DEDUP_WINDOW: int = 60  # секунд для дедупликации алертов
    ALERT_HISTORY_SIZE: int = 10000  # количество записей в истории
    
    # === DATABASE ===
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://localhost/crypto_bot")
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_MAX_QUERIES: int = 50000
    DB_CONNECTION_TIMEOUT: int = 600  # seconds
    
    # === CACHE ===
    CACHE_TTL: int = 3600  # 1 час
    SYMBOLS_CACHE_ENABLED: bool = True
    
    # === MONITORING & HEALTH ===
    METRICS_PORT: int = 9090
    HEALTH_CHECK_INTERVAL: int = 30  # секунд между проверками здоровья
    
    # === LOGGING ===
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: str = "crypto_bot.log"
    LOG_FILE_ENCODING: str = "utf-8"
    
    # === TRADING PAIRS & INTERVALS ===
    SUPPORTED_INTERVALS: List[str] = field(default_factory=lambda: ["1m", "5m", "15m", "30m", "1h", "4h"])
    
    # Фильтры для символов
    SYMBOL_FILTER_QUOTE: str = "USDT"  # только USDT пары
    SYMBOL_FILTER_STATUS: str = "TRADING"  # только торгуемые
    SYMBOL_FILTER_CONTRACT_TYPE: str = "PERPETUAL"  # только перпетуалы
    
    # Лимиты для топ символов
    TOP_SYMBOLS_BY_VOLUME_LIMIT: int = 100
    TOP_SYMBOLS_VOLUME_LIMIT: int = 50
    
    # === PERCENTAGE THRESHOLDS ===
    MIN_PERCENT_CHANGE: float = 0.1
    MAX_PERCENT_CHANGE: float = 100.0
    
    # Предустановленные проценты
    PERCENT_PRESETS: List[float] = field(default_factory=lambda: [0.5, 1.0, 2.0, 3.0, 5.0, 10.0])
    
    # Предустановленные пороги газа (Gwei)
    GAS_PRESETS: List[int] = field(default_factory=lambda: [10, 15, 20, 25, 30, 50])
    
    # === WEBSOCKET SETTINGS ===
    WS_HEARTBEAT_INTERVAL: int = 30  # seconds
    WS_CONNECTION_TIMEOUT: int = 30  # seconds
    WS_MESSAGE_TIMEOUT: int = 60  # seconds максимальный возраст последнего сообщения
    WS_RECONNECT_EXPONENTIAL_BASE: int = 2
    WS_RECONNECT_MAX_DELAY: int = 60  # seconds
    
    # === MESSAGE QUEUE SETTINGS ===
    QUEUE_PROCESSING_INTERVAL: float = 1.0  # seconds между проверками очереди
    QUEUE_MAX_MESSAGES_PER_MINUTE: int = 30
    QUEUE_RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # === PROCESSOR SETTINGS ===
    PROCESSOR_TIMEOUT: float = 1.0  # seconds timeout для получения свечи из очереди
    PROCESSOR_ERROR_SLEEP: float = 1.0  # seconds задержка при ошибке
    
    # === PRECISION SETTINGS ===
    DECIMAL_PRECISION: int = 8  # точность для Decimal вычислений
    
    # === ADAPTIVE RATE LIMITER ===
    ADAPTIVE_LIMITER_ADJUSTMENT_INTERVAL: float = 60.0  # seconds
    ADAPTIVE_LIMITER_ERROR_THRESHOLD: float = 0.1  # 10% ошибок
    ADAPTIVE_LIMITER_SUCCESS_THRESHOLD: float = 0.01  # 1% ошибок
    ADAPTIVE_LIMITER_MIN_SUCCESSES: int = 50
    ADAPTIVE_LIMITER_RATE_DECREASE_FACTOR: float = 0.8
    ADAPTIVE_LIMITER_RATE_INCREASE_FACTOR: float = 1.2
    
    # === NOTIFICATION SETTINGS ===
    # Cooldown между одинаковыми уведомлениями
    DUPLICATE_ALERT_COOLDOWN: int = 300  # 5 минут
    
    # === API TIMEOUT SETTINGS ===
    HTTP_REQUEST_TIMEOUT: int = 10  # seconds для обычных запросов
    WS_TEST_TIMEOUT: float = 3.0  # seconds для тестирования стримов
    WS_CONNECT_TIMEOUT: float = 5.0  # seconds для подключения к тестовому стриму
    
    # === ERROR HANDLING ===
    MAX_ERROR_RATE: float = 0.5  # максимальный процент ошибок для health check
    
    # === CHART SETTINGS ===
    CHART_FIGURE_SIZE: tuple = (10, 6)
    CHART_DPI: int = 100
    CHART_FACE_COLOR: str = '#1a1a1a'
    CHART_GRID_ALPHA: float = 0.2
    CHART_LINE_COLOR: str = '#00ff88'
    CHART_FILL_ALPHA: float = 0.3
    CHART_HOUR_INTERVAL: int = 4  # интервал меток на оси времени
    
    def validate(self) -> None:
        """Валидация обязательных параметров"""
        required_fields = [
            ("BOT_TOKEN", self.BOT_TOKEN),
            ("ETHERSCAN_API_KEY", self.ETHERSCAN_API_KEY),
            ("DATABASE_URL", self.DATABASE_URL)
        ]
        
        for field_name, field_value in required_fields:
            if not field_value:
                raise ValueError(f"{field_name} не установлен в переменных окружения")
        
        # Валидация численных значений
        if self.MAX_PRESETS_PER_USER <= 0:
            raise ValueError("MAX_PRESETS_PER_USER должен быть больше 0")
        
        if self.GAS_CHECK_INTERVAL <= 0:
            raise ValueError("GAS_CHECK_INTERVAL должен быть больше 0")
        
        if self.MIN_PERCENT_CHANGE >= self.MAX_PERCENT_CHANGE:
            raise ValueError("MIN_PERCENT_CHANGE должен быть меньше MAX_PERCENT_CHANGE")
        
        if self.GAS_MIN_THRESHOLD >= self.GAS_MAX_THRESHOLD:
            raise ValueError("GAS_MIN_THRESHOLD должен быть меньше GAS_MAX_THRESHOLD")
    
    def get_gas_presets_keyboard_data(self) -> List[tuple]:
        """Получение данных для клавиатуры газовых пресетов"""
        return [(str(preset), f"gas_{preset}") for preset in self.GAS_PRESETS]
    
    def get_percent_presets_keyboard_data(self) -> List[tuple]:
        """Получение данных для клавиатуры процентных пресетов"""
        return [(f"{preset}%", f"percent_{preset}") for preset in self.PERCENT_PRESETS]


config = Config()