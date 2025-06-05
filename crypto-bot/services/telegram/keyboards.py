from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Optional, Dict, Any

from config.settings import config


class Keyboards:
    """Все клавиатуры бота"""
    
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Главное меню"""
        keyboard = [
            [
                InlineKeyboardButton(text="📊 Свечные алерты", callback_data="candle_alerts"),
                InlineKeyboardButton(text="⛽ Газ алерты", callback_data="gas_alerts")
            ],
            [
                InlineKeyboardButton(text="📈 Статистика", callback_data="stats"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def candle_alerts_menu() -> InlineKeyboardMarkup:
        """Меню свечных алертов"""
        keyboard = [
            [
                InlineKeyboardButton(text="➕ Создать пресет", callback_data="preset_create"),
                InlineKeyboardButton(text="📋 Мои пресеты", callback_data="preset_list")
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def preset_list(presets: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        """Список пресетов пользователя"""
        keyboard = []
        
        for preset in presets:
            status = "✅" if preset['is_active'] else "❌"
            button_text = f"{status} {preset['name']}"
            keyboard.append([
                InlineKeyboardButton(
                    text=button_text, 
                    callback_data=f"preset_view_{preset['id']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(text="➕ Создать новый", callback_data="preset_create"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="candle_alerts")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def preset_actions(preset_id: int, is_active: bool) -> InlineKeyboardMarkup:
        """Действия с пресетом"""
        toggle_text = "🔴 Деактивировать" if is_active else "🟢 Активировать"
        toggle_action = "deactivate" if is_active else "activate"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    text=toggle_text, 
                    callback_data=f"preset_{toggle_action}_{preset_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", 
                    callback_data=f"preset_edit_{preset_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить", 
                    callback_data=f"preset_delete_{preset_id}"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 К списку", callback_data="preset_list")
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def preset_delete_confirm(preset_id: int) -> InlineKeyboardMarkup:
        """Подтверждение удаления пресета"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить", 
                    callback_data=f"preset_delete_confirm_{preset_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", 
                    callback_data=f"preset_view_{preset_id}"
                )
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def pairs_selection_method() -> InlineKeyboardMarkup:
        """Выбор метода выбора пар"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="🏆 Топ 100 по объему", 
                    callback_data="pairs_top100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Топ по объему 24ч", 
                    callback_data="pairs_volume"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌟 Все пары", 
                    callback_data="pairs_all"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную", 
                    callback_data="pairs_manual"
                )
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="candle_alerts")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def intervals_selection() -> InlineKeyboardMarkup:
        """Выбор интервалов"""
        keyboard = []
        
        # Интервалы в два ряда
        intervals_row1 = ["1m", "5m", "15m"]
        intervals_row2 = ["30m", "1h", "4h"]
        
        keyboard.append([
            InlineKeyboardButton(
                text=interval, 
                callback_data=f"interval_toggle_{interval}"
            ) for interval in intervals_row1
        ])
        
        keyboard.append([
            InlineKeyboardButton(
                text=interval, 
                callback_data=f"interval_toggle_{interval}"
            ) for interval in intervals_row2
        ])
        
        keyboard.append([
            InlineKeyboardButton(text="✅ Все", callback_data="interval_all"),
            InlineKeyboardButton(text="❌ Очистить", callback_data="interval_none")
        ])
        
        keyboard.append([
            InlineKeyboardButton(text="➡️ Далее", callback_data="interval_done"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="candle_alerts")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def percent_presets() -> InlineKeyboardMarkup:
        """Пресеты процентов"""
        keyboard = []
        
        # Первый ряд
        first_row = [
            InlineKeyboardButton(
                text=f"{preset}%", 
                callback_data=f"percent_{preset}"
            ) 
            for preset in config.PERCENT_PRESETS[:3]
        ]
        keyboard.append(first_row)
        
        # Второй ряд  
        second_row = [
            InlineKeyboardButton(
                text=f"{preset}%", 
                callback_data=f"percent_{preset}"
            ) 
            for preset in config.PERCENT_PRESETS[3:]
        ]
        keyboard.append(second_row)
        
        # Кнопки управления
        keyboard.append([
            InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="percent_manual"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="candle_alerts")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def gas_alerts_menu(has_alert: bool, threshold: Optional[float] = None) -> InlineKeyboardMarkup:
        """Меню газовых алертов"""
        keyboard = []
        
        if has_alert:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"⚙️ Изменить ({threshold} Gwei)", 
                    callback_data="gas_set"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    text="🔴 Отключить", 
                    callback_data="gas_disable"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    text="🟢 Включить алерты", 
                    callback_data="gas_set"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(text="📊 График газа", callback_data="gas_chart"),
            InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def gas_threshold_presets() -> InlineKeyboardMarkup:
        """Пресеты порогов газа"""
        keyboard = []
        
        # Первый ряд
        first_row = [
            InlineKeyboardButton(
                text=f"{preset} Gwei", 
                callback_data=f"gas_{preset}"
            ) 
            for preset in config.GAS_PRESETS[:3]
        ]
        keyboard.append(first_row)
        
        # Второй ряд
        second_row = [
            InlineKeyboardButton(
                text=f"{preset} Gwei", 
                callback_data=f"gas_{preset}"
            ) 
            for preset in config.GAS_PRESETS[3:]
        ]
        keyboard.append(second_row)
        
        # Кнопки управления
        keyboard.append([
            InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="gas_manual"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="gas_alerts")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def back_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
        """Кнопка назад"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]
        ])
    
    @staticmethod
    def cancel_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
        """Кнопка отмены"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=callback_data)]
        ])
    
    @staticmethod
    def confirmation(action: str, data: str) -> InlineKeyboardMarkup:
        """Универсальное подтверждение"""
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}_{data}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_{action}_{data}")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)