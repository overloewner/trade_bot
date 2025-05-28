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
                InlineKeyboardButton("📊 Свечные алерты", callback_data="candle_alerts"),
                InlineKeyboardButton("⛽ Газ алерты", callback_data="gas_alerts")
            ],
            [
                InlineKeyboardButton("📈 Статистика", callback_data="stats"),
                InlineKeyboardButton("❓ Помощь", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def candle_alerts_menu() -> InlineKeyboardMarkup:
        """Меню свечных алертов"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Создать пресет", callback_data="preset_create"),
                InlineKeyboardButton("📋 Мои пресеты", callback_data="preset_list")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
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
                    button_text, 
                    callback_data=f"preset_view_{preset['id']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("➕ Создать новый", callback_data="preset_create"),
            InlineKeyboardButton("🔙 Назад", callback_data="candle_alerts")
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
                    toggle_text, 
                    callback_data=f"preset_{toggle_action}_{preset_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Изменить", 
                    callback_data=f"preset_edit_{preset_id}"
                ),
                InlineKeyboardButton(
                    "🗑 Удалить", 
                    callback_data=f"preset_delete_{preset_id}"
                )
            ],
            [
                InlineKeyboardButton("🔙 К списку", callback_data="preset_list")
            ]
        ]
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def preset_delete_confirm(preset_id: int) -> InlineKeyboardMarkup:
        """Подтверждение удаления пресета"""
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Да, удалить", 
                    callback_data=f"preset_delete_confirm_{preset_id}"
                ),
                InlineKeyboardButton(
                    "❌ Отмена", 
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
                    "🏆 Топ 100 по объему", 
                    callback_data="pairs_top100"
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Топ по объему 24ч", 
                    callback_data="pairs_volume"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Ввести вручную", 
                    callback_data="pairs_manual"
                )
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data="candle_alerts")
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
                interval, 
                callback_data=f"interval_toggle_{interval}"
            ) for interval in intervals_row1
        ])
        
        keyboard.append([
            InlineKeyboardButton(
                interval, 
                callback_data=f"interval_toggle_{interval}"
            ) for interval in intervals_row2
        ])
        
        keyboard.append([
            InlineKeyboardButton("✅ Все", callback_data="interval_all"),
            InlineKeyboardButton("❌ Очистить", callback_data="interval_none")
        ])
        
        keyboard.append([
            InlineKeyboardButton("➡️ Далее", callback_data="interval_done"),
            InlineKeyboardButton("❌ Отмена", callback_data="candle_alerts")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def percent_presets() -> InlineKeyboardMarkup:
        """Пресеты процентов"""
        keyboard = [
            [
                InlineKeyboardButton("0.5%", callback_data="percent_0.5"),
                InlineKeyboardButton("1%", callback_data="percent_1"),
                InlineKeyboardButton("2%", callback_data="percent_2")
            ],
            [
                InlineKeyboardButton("3%", callback_data="percent_3"),
                InlineKeyboardButton("5%", callback_data="percent_5"),
                InlineKeyboardButton("10%", callback_data="percent_10")
            ],
            [
                InlineKeyboardButton("✏️ Ввести вручную", callback_data="percent_manual")
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data="candle_alerts")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def gas_alerts_menu(has_alert: bool, threshold: Optional[float] = None) -> InlineKeyboardMarkup:
        """Меню газовых алертов"""
        keyboard = []
        
        if has_alert:
            keyboard.append([
                InlineKeyboardButton(
                    f"⚙️ Изменить ({threshold} Gwei)", 
                    callback_data="gas_set"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    "🔴 Отключить", 
                    callback_data="gas_disable"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    "🟢 Включить алерты", 
                    callback_data="gas_set"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("📊 График газа", callback_data="gas_chart"),
            InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def gas_threshold_presets() -> InlineKeyboardMarkup:
        """Пресеты порогов газа"""
        keyboard = [
            [
                InlineKeyboardButton("10 Gwei", callback_data="gas_10"),
                InlineKeyboardButton("15 Gwei", callback_data="gas_15"),
                InlineKeyboardButton("20 Gwei", callback_data="gas_20")
            ],
            [
                InlineKeyboardButton("25 Gwei", callback_data="gas_25"),
                InlineKeyboardButton("30 Gwei", callback_data="gas_30"),
                InlineKeyboardButton("50 Gwei", callback_data="gas_50")
            ],
            [
                InlineKeyboardButton("✏️ Ввести вручную", callback_data="gas_manual")
            ],
            [
                InlineKeyboardButton("❌ Отмена", callback_data="gas_alerts")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    @staticmethod
    def back_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
        """Кнопка назад"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔙 Назад", callback_data=callback_data)]
        ])
    
    @staticmethod
    def cancel_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
        """Кнопка отмены"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("❌ Отмена", callback_data=callback_data)]
        ])
    
    @staticmethod
    def confirmation(action: str, data: str) -> InlineKeyboardMarkup:
        """Универсальное подтверждение"""
        keyboard = [
            [
                InlineKeyboardButton("✅ Да", callback_data=f"confirm_{action}_{data}"),
                InlineKeyboardButton("❌ Нет", callback_data=f"cancel_{action}_{data}")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)