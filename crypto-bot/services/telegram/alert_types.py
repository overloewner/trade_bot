from enum import Enum
from typing import Dict, Any
from dataclasses import dataclass


class AlertType(Enum):
    """Типы алертов в системе"""
    CANDLE = "candle"
    GAS_CROSSING = "gas_crossing"


@dataclass
class CandleAlertData:
    """Данные для свечного алерта"""
    symbol: str
    interval: str
    percent_change: float
    price: float
    preset_name: str
    direction: str  # "up" или "down"


@dataclass
class GasCrossingAlertData:
    """Данные для алерта пересечения газа"""
    threshold: float
    current_price: float
    previous_price: float
    direction: str  # "up" или "down"


@dataclass
class AlertRequest:
    """Запрос на отправку алерта"""
    user_id: int
    alert_type: AlertType
    data: Any  # CandleAlertData или GasCrossingAlertData
    priority: str = "normal"  # "normal", "high", "urgent"