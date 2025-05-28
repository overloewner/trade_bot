# Промпт для создания минималистичного многопользовательского Telegram крипто-бота

## Общие требования

Создай минималистичный, но полнофункциональный многопользовательский Telegram бот для мониторинга криптовалют. Бот должен быть:

1. **Простым и чистым** - никакой избыточности, только необходимый функционал
2. **Высокопроизводительным** - работа полностью в памяти (RAM), БД только для персистентности
3. **Отказоустойчивым** - при перезапуске пользователи не должны заметить сбоя
4. **Масштабируемым** - архитектура должна позволять легко добавлять новые функции
5. **Изолированным** - сервисы должны быть независимыми друг от друга

## Архитектура

### Структура проекта
```
crypto-bot/
├── config/
│   └── settings.py          # Вся конфигурация в одном месте
├── services/
│   ├── telegram/
│   │   ├── bot.py          # Основной Telegram бот
│   │   ├── handlers/       # Обработчики команд
│   │   └── keyboards.py    # Клавиатуры
│   ├── candle_alerts/
│   │   ├── service.py      # Сервис свечных алертов
│   │   ├── websocket.py    # WebSocket подключение к Binance
│   │   └── processor.py    # Обработчик свечей
│   └── gas_alerts/
│       └── service.py      # Сервис газ алертов
├── models/
│   └── database.py         # Модели БД (минимум данных)
├── cache/
│   └── memory.py           # In-memory кеш
├── utils/
│   ├── rate_limiter.py    # Контроль лимитов
│   └── queue.py            # Очереди сообщений
└── main.py                 # Точка входа
```

## Сервис 1: Candle Alerts (Свечные алерты)

### Функционал
1. **Создание пресетов**:
   - Выбор пар: топ 100, по объему торгов, ручной выбор
   - Таймфреймы: 1m, 5m, 15m, 30m, 1h, 4h
   - Процент изменения: от 0.1% до 100%
   - Название пресета для удобства

2. **Управление пресетами**:
   - Активация/деактивация
   - Редактирование
   - Удаление
   - Просмотр статистики

### Техническая реализация

#### WebSocket подключение
```python
# При запуске подписываемся на ВСЕ возможные стримы
# ~400 пар × 6 таймфреймов = ~2400 стримов
# Binance позволяет до 1024 стримов на одно соединение
# Значит нужно 3 WebSocket соединения

class BinanceWebSocketManager:
    def __init__(self):
        self.connections = []  # 3 соединения
        self.all_streams = self._generate_all_streams()
        
    def _generate_all_streams(self):
        # Получаем все фьючерсные пары с Binance
        # Генерируем стримы: {symbol}@kline_{interval}
        pass
```

#### Обработка свечей
```python
class CandleProcessor:
    def __init__(self):
        self.candle_queue = asyncio.Queue(maxsize=10000)
        self.active_subscriptions = {}  # Структура для быстрого поиска
        
    async def process_candles_batch(self):
        # Обрабатываем свечи батчами по 100-500 штук
        # Многопоточная обработка для скорости
        pass
```

#### Структура активных подписок в памяти
```python
active_subscriptions = {
    "BTCUSDT": {
        "1m": {
            user_id_1: [preset_id_1, preset_id_2],
            user_id_2: [preset_id_3]
        },
        "5m": {
            user_id_1: [preset_id_4]
        }
    }
}
```

### Ограничения и оптимизация

1. **Binance лимиты**:
   - Max 1024 стрима на соединение
   - Реконнект при разрыве
   - Буферизация при высокой нагрузке

2. **Telegram лимиты**:
   - Max 30 сообщений в секунду для бота
   - Max 50 алертов в одном сообщении
   - Батчинг и throttling

3. **Оптимизация**:
   - Дедупликация алертов
   - Группировка по пользователям
   - Приоритетная очередь для важных алертов

## Сервис 2: Gas Alerts

### Функционал
1. Установка порога цены газа
2. Уведомления при достижении порога
3. История цен газа (в памяти, последние 24ч)

### Реализация
```python
class GasAlertService:
    def __init__(self):
        self.gas_price_cache = deque(maxlen=1440)  # 24ч × 60мин
        self.user_alerts = {}  # user_id: threshold
        
    async def check_gas_price(self):
        # Проверяем каждую минуту
        # Источник: Etherscan API
        pass
```

## База данных (PostgreSQL)

### Минимальные таблицы
```sql
-- Пользователи
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Пресеты
CREATE TABLE presets (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    name VARCHAR(100),
    pairs TEXT[],  -- массив пар
    intervals TEXT[],  -- массив интервалов
    percent_change DECIMAL(5,2),
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Газ алерты
CREATE TABLE gas_alerts (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    threshold_gwei DECIMAL(10,2),
    is_active BOOLEAN DEFAULT true
);
```

## In-Memory кеш

```python
class MemoryCache:
    def __init__(self):
        self.user_states = {}  # FSM состояния
        self.active_presets = {}  # Активные пресеты
        self.candle_buffer = {}  # Буфер свечей
        self.alert_history = deque(maxlen=10000)  # История алертов
        
    async def load_from_db(self):
        # При старте загружаем активные пресеты из БД
        pass
```

## Обработка сообщений и лимитов

```python
class MessageQueue:
    def __init__(self):
        self.user_queues = {}  # Очередь для каждого пользователя
        self.global_rate_limiter = RateLimiter(30, 1)  # 30 msg/sec
        
    async def send_alerts_batch(self, user_id, alerts):
        # Группируем до 50 алертов в одно сообщение
        # Соблюдаем rate limits
        pass
```

## Конфигурация (config/settings.py)

```python
class Config:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Binance
    BINANCE_WS_URL = "wss://fstream.binance.com/ws"
    RECONNECT_DELAY = 5
    
    # Gas tracking
    ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
    GAS_CHECK_INTERVAL = 60  # секунд
    
    # Limits
    MAX_PRESETS_PER_USER = 10
    MAX_PAIRS_PER_PRESET = 50
    CANDLE_QUEUE_SIZE = 10000
    ALERT_BATCH_SIZE = 50
    
    # Database
    DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost/crypto_bot")
    
    # Performance
    WORKER_THREADS = 4
    BATCH_PROCESS_SIZE = 500
```

## Ключевые особенности реализации

1. **Инициализация**:
   - Загрузка активных пресетов из БД в память
   - Подписка на все возможные стримы Binance
   - Запуск фоновых задач обработки и сепвисов

2. **Graceful shutdown**:
   - Сохранение состояния в БД
   - Корректное закрытие WebSocket соединений
   - Отправка последних алертов из очереди

3. **Мониторинг и метрики**:
   - Задержка обработки
   - Размер очередей
   - Использование памяти

## Пример использования ботом

1. **/start** - Регистрация пользователя
2. **/preset** - Управление пресетами
   - Создать новый
   - Показать список
   - Активировать/деактивировать
3. **/gas** - Настройка газ алертов
4. **/status** - Статус подписок
5. **/help** - Помощь

## Важные нюансы

1. **Дедупликация**: Если пользователь подписан на BTCUSDT через несколько пресетов, он получит только одно уведомление

2. **Приоритизация**: Алерты с большим изменением цены имеют приоритет

3. **Умное батчирование**: Группировка алертов по парам и интервалам

4. **Кеширование**: Все активные данные в памяти, БД только для восстановления

5. **Изоляция сервисов**: Gas alerts и Candle alerts полностью независимы

## Требования к производительности

- Обработка 10,000+ свечей в секунду
- Задержка от получения свечи до отправки алерта < 1 сек
- Использование памяти < 1GB при 1000 активных пользователей
- Поддержка 10,000+ одновременных пользователей

## Дополнительные соображения

1. Использовать asyncio для всех I/O операций
2. Применить multiprocessing для CPU-intensive задач
3. Реализовать health checks для всех сервисов
4. Добавить Prometheus метрики для мониторинга
5. Использовать структурное логирование
6. Реализовать A/B тестирование для новых фич

Код должен быть:
- Типизированным (type hints везде)
- С docstrings для всех классов и методов
- Соответствовать PEP8
- Без магических чисел (все в конфиге)