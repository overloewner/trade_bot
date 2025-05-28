# services/telegram/handlers/__init__.py
from .start import register_start_handlers
from .candle_alerts import register_candle_alerts_handlers
from .gas_alerts import register_gas_alerts_handlers
from .common import register_common_handlers

__all__ = [
    'register_start_handlers',
    'register_candle_alerts_handlers', 
    'register_gas_alerts_handlers',
    'register_common_handlers'
]


def register_all_handlers(dp):
    """Регистрация всех обработчиков"""
    register_start_handlers(dp)
    register_candle_alerts_handlers(dp)
    register_gas_alerts_handlers(dp)
    register_common_handlers(dp)