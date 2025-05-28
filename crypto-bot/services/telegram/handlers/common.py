from aiogram import types, Dispatcher, F
from aiogram.fsm.context import FSMContext
import logging

from services.telegram.keyboards import Keyboards
from cache.memory import cache

logger = logging.getLogger(__name__)


async def cancel_action(callback: types.CallbackQuery, state: FSMContext):
    """Универсальная отмена действия"""
    # Очищаем состояние
    await state.clear()
    
    # Определяем куда вернуться
    action = callback.data.split("_")[1]
    
    if action == "candle":
        from .start import show_candle_alerts_menu
        await show_candle_alerts_menu(callback)
    elif action == "gas":
        from .start import show_gas_alerts_menu
        await show_gas_alerts_menu(callback)
    else:
        from .start import callback_main_menu
        await callback_main_menu(callback)


async def unknown_command(message: types.Message):
    """Обработка неизвестных команд"""
    await message.answer(
        "❓ Неизвестная команда.\n"
        "Используйте /help для справки или /start для главного меню."
    )


async def unknown_callback(callback: types.CallbackQuery):
    """Обработка неизвестных callback"""
    logger.warning(f"Unknown callback: {callback.data}")
    await callback.answer("❌ Неизвестное действие", show_alert=True)


async def error_handler(update: types.Update, exception: Exception):
    """Глобальный обработчик ошибок"""
    logger.error(f"Update {update} caused error {exception}")
    
    # Определяем пользователя
    user_id = None
    if update.message:
        user_id = update.message.from_user.id
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
    
    if user_id:
        # Пытаемся отправить сообщение об ошибке
        try:
            error_text = (
                "❌ Произошла ошибка при обработке запроса.\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
            
            if update.message:
                await update.message.answer(error_text)
            elif update.callback_query:
                await update.callback_query.answer(error_text, show_alert=True)
        except:
            pass


async def maintenance_mode(message: types.Message):
    """Режим обслуживания"""
    await message.answer(
        "🔧 <b>Бот находится на обслуживании</b>\n\n"
        "Пожалуйста, попробуйте позже.",
        parse_mode="HTML"
    )


def register_common_handlers(dp: Dispatcher):
    """Регистрация общих обработчиков"""
    
    # Отмена действий
    dp.callback_query.register(cancel_action, F.data.startswith("cancel_"))
    
    # Неизвестные команды (должно быть в конце)
    dp.message.register(unknown_command)
    dp.callback_query.register(unknown_callback)