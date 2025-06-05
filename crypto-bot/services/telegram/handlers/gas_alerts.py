from aiogram import types, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from services.telegram.keyboards import Keyboards
from models.database import db_manager
from cache.memory import cache
from services.gas_alerts.service import gas_alert_service
from config.settings import config

logger = logging.getLogger(__name__)


class GasStates(StatesGroup):
    """FSM состояния для газ алертов"""
    waiting_for_threshold = State()


async def gas_set(callback: types.CallbackQuery, state: FSMContext):
    """Начало установки газ пресета"""
    await callback.message.edit_text(
        "<b>⛽ Установка порога газа</b>\n\n"
        "Выберите или введите порог цены газа в Gwei.\n"
        "Вы получите уведомление когда цена пересечет этот порог.",
        reply_markup=Keyboards.gas_threshold_presets(),
        parse_mode="HTML"
    )
    await callback.answer()


async def gas_preset(callback: types.CallbackQuery, state: FSMContext):
    """Выбор порога из пресетов"""
    threshold = float(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Сохраняем в БД
    success = await db_manager.set_gas_alert(user_id, threshold)
    
    if not success:
        await callback.answer("❌ Ошибка при сохранении", show_alert=True)
        return
    
    # Обновляем кеш
    await cache.set_gas_alert(user_id, threshold)
    
    # Добавляем в сервис
    await gas_alert_service.add_preset(user_id, threshold)
    
    await callback.message.edit_text(
        f"✅ <b>Газ пресет установлен!</b>\n\n"
        f"Порог: {threshold} Gwei\n"
        f"Вы получите уведомление когда цена газа пересечет этот порог.",
        reply_markup=Keyboards.gas_alerts_menu(True, threshold),
        parse_mode="HTML"
    )
    await callback.answer()


async def gas_manual(callback: types.CallbackQuery, state: FSMContext):
    """Ручной ввод порога"""
    await callback.message.edit_text(
        "<b>✏️ Ввод порога газа</b>\n\n"
        "Введите порог в Gwei (например: 15.5):",
        reply_markup=Keyboards.cancel_button("gas_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(GasStates.waiting_for_threshold)
    await callback.answer()


async def process_manual_threshold(message: types.Message, state: FSMContext):
    """Обработка ручного ввода порога"""
    try:
        threshold = float(message.text.strip().replace(',', '.'))
        
        if threshold < config.GAS_MIN_THRESHOLD or threshold > config.GAS_MAX_THRESHOLD:
            await message.answer(
                f"❌ Порог должен быть от {config.GAS_MIN_THRESHOLD} до {config.GAS_MAX_THRESHOLD} Gwei",
                reply_markup=Keyboards.cancel_button("gas_alerts")
            )
            return
        
        user_id = message.from_user.id
        
        # Сохраняем в БД
        success = await db_manager.set_gas_alert(user_id, threshold)
        
        if not success:
            await message.answer(
                "❌ Ошибка при сохранении. Попробуйте позже.",
                reply_markup=Keyboards.back_button("gas_alerts")
            )
            await state.clear()
            return
        
        # Обновляем кеш
        await cache.set_gas_alert(user_id, threshold)
        
        # Добавляем в сервис
        await gas_alert_service.add_preset(user_id, threshold)
        
        await state.clear()
        
        await message.answer(
            f"✅ <b>Газ пресет установлен!</b>\n\n"
            f"Порог: {threshold} Gwei\n"
            f"Вы получите уведомление когда цена газа пересечет этот порог.",
            reply_markup=Keyboards.gas_alerts_menu(True, threshold),
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer(
            "❌ Введите корректное число",
            reply_markup=Keyboards.cancel_button("gas_alerts")
        )


async def gas_disable(callback: types.CallbackQuery):
    """Удаление газ пресета"""
    user_id = callback.from_user.id
    
    # УДАЛЯЕМ из БД полностью
    success = await db_manager.delete_gas_alert(user_id)
    
    if not success:
        await callback.answer("❌ Ошибка при удалении", show_alert=True)
        return
    
    # Удаляем из кеша
    await cache.remove_gas_alert(user_id)
    
    # Удаляем из сервиса
    await gas_alert_service.remove_preset(user_id)
    
    await callback.message.edit_text(
        "✅ <b>Газ пресет удален</b>\n\n"
        "Вы больше не будете получать уведомления о цене газа.",
        reply_markup=Keyboards.gas_alerts_menu(False),
        parse_mode="HTML"
    )
    await callback.answer()


async def gas_chart(callback: types.CallbackQuery):
    """Показ информации о газе"""
    await callback.answer()
    
    # Получаем текущую цену из сервиса (из памяти)
    current_price = gas_alert_service.get_current_gas_price()
    
    if current_price is None:
        await callback.message.answer(
            "📊 Цена газа пока недоступна.\n"
            "Данные начнут собираться после запуска бота."
        )
        return
    
    # Показываем текущую цену
    await callback.message.answer(
        f"📊 <b>Информация о газе Ethereum</b>\n\n"
        f"💰 Текущая цена: {current_price} Gwei\n"
        f"🕐 Обновляется каждые {config.GAS_CHECK_INTERVAL} секунд",
        parse_mode="HTML"
    )


def register_gas_alerts_handlers(dp: Dispatcher):
    """Регистрация обработчиков газ алертов"""
    
    # Установка пресета
    dp.callback_query.register(gas_set, F.data == "gas_set")
    dp.callback_query.register(gas_preset, F.data.startswith("gas_") & F.data.split("_")[1].replace(".", "").isdigit())
    dp.callback_query.register(gas_manual, F.data == "gas_manual")
    dp.message.register(process_manual_threshold, GasStates.waiting_for_threshold)
    
    # Управление пресетом
    dp.callback_query.register(gas_disable, F.data == "gas_disable")
    dp.callback_query.register(gas_chart, F.data == "gas_chart")