from aiogram import types, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from datetime import datetime, timedelta
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import deque

from services.telegram.keyboards import Keyboards
from models.database import db_manager
from cache.memory import cache
from config.settings import config

logger = logging.getLogger(__name__)


class GasStates(StatesGroup):
    """FSM состояния для газ алертов"""
    waiting_for_threshold = State()


async def gas_set(callback: types.CallbackQuery, state: FSMContext):
    """Начало установки газ алерта"""
    await callback.message.edit_text(
        "<b>⛽ Установка порога газа</b>\n\n"
        "Выберите или введите порог цены газа в Gwei.\n"
        "Вы получите уведомление когда цена опустится ниже этого значения.",
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
    
    await callback.message.edit_text(
        f"✅ <b>Газ алерт установлен!</b>\n\n"
        f"Порог: {threshold} Gwei\n"
        f"Вы получите уведомление когда цена газа опустится ниже этого значения.",
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
        
        if threshold <= 0 or threshold > 1000:
            await message.answer(
                "❌ Порог должен быть от 0.1 до 1000 Gwei",
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
        
        await state.clear()
        
        await message.answer(
            f"✅ <b>Газ алерт установлен!</b>\n\n"
            f"Порог: {threshold} Gwei\n"
            f"Вы получите уведомление когда цена газа опустится ниже этого значения.",
            reply_markup=Keyboards.gas_alerts_menu(True, threshold),
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer(
            "❌ Введите корректное число",
            reply_markup=Keyboards.cancel_button("gas_alerts")
        )


async def gas_disable(callback: types.CallbackQuery):
    """Отключение газ алерта"""
    user_id = callback.from_user.id
    
    # Отключаем в БД
    success = await db_manager.disable_gas_alert(user_id)
    
    if not success:
        await callback.answer("❌ Ошибка при отключении", show_alert=True)
        return
    
    # Удаляем из кеша
    await cache.remove_gas_alert(user_id)
    
    await callback.message.edit_text(
        "✅ <b>Газ алерты отключены</b>\n\n"
        "Вы больше не будете получать уведомления о цене газа.",
        reply_markup=Keyboards.gas_alerts_menu(False),
        parse_mode="HTML"
    )
    await callback.answer()


async def gas_chart(callback: types.CallbackQuery):
    """Показ графика газа"""
    await callback.answer("Генерирую график...")
    
    try:
        # Получаем историю газа из сервиса (будет реализован)
        gas_history = get_gas_history()  # Заглушка
        
        if not gas_history:
            await callback.message.answer(
                "📊 История цен газа пока недоступна.\n"
                "Данные начнут собираться после запуска бота."
            )
            return
        
        # Создаем график
        chart_buffer = create_gas_chart(gas_history)
        
        # Отправляем график
        await callback.message.answer_photo(
            photo=chart_buffer,
            caption="📊 <b>График цены газа за последние 24 часа</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Error creating gas chart: {e}")
        await callback.message.answer(
            "❌ Ошибка при создании графика. Попробуйте позже."
        )


def create_gas_chart(gas_history: list) -> io.BytesIO:
    """Создание графика цены газа"""
    # Подготовка данных
    timestamps = [item['timestamp'] for item in gas_history]
    prices = [item['price'] for item in gas_history]
    
    # Создание графика
    plt.figure(figsize=(10, 6))
    plt.style.use('dark_background')
    
    # Основной график
    plt.plot(timestamps, prices, color='#00ff88', linewidth=2)
    
    # Заливка под графиком
    plt.fill_between(timestamps, prices, alpha=0.3, color='#00ff88')
    
    # Настройка осей
    plt.xlabel('Время', fontsize=12)
    plt.ylabel('Цена газа (Gwei)', fontsize=12)
    plt.title('Цена газа Ethereum за последние 24 часа', fontsize=14, pad=20)
    
    # Форматирование дат
    ax = plt.gca()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    plt.gcf().autofmt_xdate()
    
    # Сетка
    plt.grid(True, alpha=0.2)
    
    # Добавляем текущую цену
    current_price = prices[-1]
    plt.text(0.02, 0.95, f'Текущая цена: {current_price:.1f} Gwei',
             transform=ax.transAxes, fontsize=12,
             bbox=dict(boxstyle='round', facecolor='#00ff88', alpha=0.2))
    
    # Сохранение в буфер
    buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buffer, format='png', dpi=100, facecolor='#1a1a1a')
    buffer.seek(0)
    plt.close()
    
    return buffer


def get_gas_history() -> list:
    """Получение истории газа (заглушка)"""
    # В реальной реализации это будет брать данные из gas_service
    # Пока возвращаем пустой список
    return []


def register_gas_alerts_handlers(dp: Dispatcher):
    """Регистрация обработчиков газ алертов"""
    
    # Установка алерта
    dp.callback_query.register(gas_set, F.data == "gas_set")
    dp.callback_query.register(gas_preset, F.data.startswith("gas_") & F.data.split("_")[1].isdigit())
    dp.callback_query.register(gas_manual, F.data == "gas_manual")
    dp.message.register(process_manual_threshold, GasStates.waiting_for_threshold)
    
    # Управление алертом
    dp.callback_query.register(gas_disable, F.data == "gas_disable")
    dp.callback_query.register(gas_chart, F.data == "gas_chart")