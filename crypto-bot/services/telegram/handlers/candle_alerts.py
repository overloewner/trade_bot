from aiogram import types, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import List, Dict, Any, Optional
import logging
import re

from services.telegram.keyboards import Keyboards
from models.database import db_manager
from cache.memory import cache, PresetData
from cache.symbols_cache import symbols_cache
from config.settings import config
from utils.queue import message_queue, Priority

logger = logging.getLogger(__name__)


class PresetStates(StatesGroup):
    """FSM состояния для создания пресета"""
    waiting_for_name = State()
    selecting_pairs = State()
    waiting_for_manual_pairs = State()
    selecting_intervals = State()
    selecting_percent = State()
    waiting_for_manual_percent = State()


async def preset_create(callback: types.CallbackQuery, state: FSMContext):
    """Начало создания пресета"""
    user_id = callback.from_user.id
    
    # Проверяем лимит пресетов
    user_stats = await cache.get_user_stats(user_id)
    if user_stats['total_presets'] >= config.MAX_PRESETS_PER_USER:
        await callback.answer(
            f"❌ Достигнут лимит в {config.MAX_PRESETS_PER_USER} пресетов",
            show_alert=True
        )
        return
    
    await callback.message.edit_text(
        "<b>🆕 Создание пресета</b>\n\n"
        "Введите название для пресета (до 100 символов):",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_name)
    await callback.answer()


async def process_preset_name(message: types.Message, state: FSMContext):
    """Обработка названия пресета"""
    name = message.text.strip()
    
    if len(name) > config.PRESET_NAME_MAX_LENGTH:
        await message.answer(
            f"❌ Название слишком длинное. Максимум {config.PRESET_NAME_MAX_LENGTH} символов.",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    if not name:
        await message.answer(
            "❌ Название не может быть пустым.",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    # Сохраняем название
    await state.update_data(name=name)
    
    # Переходим к выбору пар
    await message.answer(
        "<b>📊 Выбор торговых пар</b>\n\n"
        "Выберите способ добавления пар:",
        reply_markup=Keyboards.pairs_selection_method(),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.selecting_pairs)


async def preset_pairs_top100(callback: types.CallbackQuery, state: FSMContext):
    """Выбор топ 100 пар из кеша"""
    await callback.answer("Загружаю топ 100 пар...")
    
    # Получаем пары из кеша памяти
    pairs = symbols_cache.get_top_symbols(100)
    
    if not pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены в кеш. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    # Сохраняем пары (ограничиваем по лимиту)
    selected_pairs = pairs[:config.MAX_PAIRS_PER_PRESET]
    await state.update_data(pairs=selected_pairs)
    
    # Показываем выбранные пары
    await callback.message.edit_text(
        f"✅ Выбрано {len(selected_pairs)} пар из топ-100:\n" +
        ", ".join(selected_pairs[:10]) +
        (f"\n...и еще {len(selected_pairs) - 10}" if len(selected_pairs) > 10 else ""),
        reply_markup=Keyboards.intervals_selection(),
        parse_mode="HTML"
    )
    
    # Переходим к выбору интервалов
    await state.set_state(PresetStates.selecting_intervals)
    await state.update_data(selected_intervals=[])


async def preset_pairs_volume(callback: types.CallbackQuery, state: FSMContext):
    """Выбор пар по объему из кеша"""
    await callback.answer("Загружаю пары по объему...")
    
    # Получаем топ 50 пар из кеша (они уже отсортированы по объему)
    pairs = symbols_cache.get_top_symbols(50)
    
    if not pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены в кеш. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    # Сохраняем пары
    selected_pairs = pairs[:config.MAX_PAIRS_PER_PRESET]
    await state.update_data(pairs=selected_pairs)
    
    # Показываем выбранные пары
    await callback.message.edit_text(
        f"✅ Выбрано {len(selected_pairs)} пар по объему:\n" +
        ", ".join(selected_pairs[:10]) +
        (f"\n...и еще {len(selected_pairs) - 10}" if len(selected_pairs) > 10 else ""),
        reply_markup=Keyboards.intervals_selection(),
        parse_mode="HTML"
    )
    
    # Переходим к выбору интервалов
    await state.set_state(PresetStates.selecting_intervals)
    await state.update_data(selected_intervals=[])


async def preset_pairs_all(callback: types.CallbackQuery, state: FSMContext):
    """Выбор всех пар из кеша"""
    await callback.answer("Загружаю все пары...")
    
    # Получаем все пары из кеша памяти
    all_pairs = symbols_cache.get_all_symbols()
    
    if not all_pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены в кеш. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    # Сохраняем все пары (ограничиваем по лимиту если нужно)
    if len(all_pairs) > config.MAX_PAIRS_PER_PRESET:
        selected_pairs = all_pairs[:config.MAX_PAIRS_PER_PRESET]
        await callback.message.edit_text(
            f"⚠️ Выбрано {config.MAX_PAIRS_PER_PRESET} пар из {len(all_pairs)} (лимит достигнут)\n\n"
            f"Первые пары: {', '.join(selected_pairs[:10])}{'...' if len(selected_pairs) > 10 else ''}",
            reply_markup=Keyboards.intervals_selection(),
            parse_mode="HTML"
        )
    else:
        selected_pairs = all_pairs
        await callback.message.edit_text(
            f"✅ Выбрано ВСЕ {len(selected_pairs)} пар:\n" +
            ", ".join(selected_pairs[:10]) +
            (f"\n...и еще {len(selected_pairs) - 10}" if len(selected_pairs) > 10 else ""),
            reply_markup=Keyboards.intervals_selection(),
            parse_mode="HTML"
        )
    
    await state.update_data(pairs=selected_pairs)
    
    # Переходим к выбору интервалов
    await state.set_state(PresetStates.selecting_intervals)
    await state.update_data(selected_intervals=[])


async def preset_pairs_manual(callback: types.CallbackQuery, state: FSMContext):
    """Ручной ввод пар"""
    await callback.message.edit_text(
        f"<b>✏️ Ручной ввод пар</b>\n\n"
        f"Введите пары через запятую или пробел.\n"
        f"Пример: BTCUSDT, ETHUSDT, BNBUSDT\n\n"
        f"Максимум {config.MAX_PAIRS_PER_PRESET} пар.",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_manual_pairs)
    await callback.answer()


async def process_manual_pairs(message: types.Message, state: FSMContext):
    """Обработка ручного ввода пар"""
    text = message.text.upper().strip()
    
    # Парсим пары
    pairs = re.findall(r'[A-Z]+USDT', text)
    pairs = list(set(pairs))  # Убираем дубликаты
    
    if not pairs:
        await message.answer(
            "❌ Не найдено ни одной валидной пары.\n"
            "Пары должны заканчиваться на USDT.",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    if len(pairs) > config.MAX_PAIRS_PER_PRESET:
        pairs = pairs[:config.MAX_PAIRS_PER_PRESET]
        await message.answer(
            f"⚠️ Взято первые {config.MAX_PAIRS_PER_PRESET} пар из введенных."
        )
    
    # Проверяем пары против кеша символов
    valid_pairs = symbols_cache.validate_symbols(pairs)
    
    if not valid_pairs:
        await message.answer(
            "❌ Ни одна из введенных пар не найдена в списке поддерживаемых.",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    # Сохраняем пары
    await state.update_data(pairs=valid_pairs)
    
    # Показываем выбранные пары
    await message.answer(
        f"✅ Выбрано {len(valid_pairs)} пар:\n" +
        ", ".join(valid_pairs[:10]) +
        (f"\n...и еще {len(valid_pairs) - 10}" if len(valid_pairs) > 10 else "")
    )
    
    # Переходим к выбору интервалов
    await show_intervals_selection(message, state)


async def show_intervals_selection(message: types.Message, state: FSMContext):
    """Показ выбора интервалов"""
    await message.answer(
        "<b>⏱ Выбор интервалов</b>\n\n"
        "Выберите интервалы для отслеживания:",
        reply_markup=Keyboards.intervals_selection(),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.selecting_intervals)
    await state.update_data(selected_intervals=[])


async def interval_toggle(callback: types.CallbackQuery, state: FSMContext):
    """Переключение интервала"""
    interval = callback.data.split("_")[2]
    data = await state.get_data()
    selected = data.get('selected_intervals', [])
    
    if interval in selected:
        selected.remove(interval)
        await callback.answer(f"❌ {interval} убран")
    else:
        selected.append(interval)
        await callback.answer(f"✅ {interval} добавлен")
    
    await state.update_data(selected_intervals=selected)


async def interval_all(callback: types.CallbackQuery, state: FSMContext):
    """Выбор всех интервалов"""
    await state.update_data(selected_intervals=config.SUPPORTED_INTERVALS.copy())
    await callback.answer("✅ Все интервалы выбраны")


async def interval_none(callback: types.CallbackQuery, state: FSMContext):
    """Очистка выбора интервалов"""
    await state.update_data(selected_intervals=[])
    await callback.answer("❌ Выбор очищен")


async def interval_done(callback: types.CallbackQuery, state: FSMContext):
    """Завершение выбора интервалов"""
    data = await state.get_data()
    selected = data.get('selected_intervals', [])
    
    if not selected:
        await callback.answer("❌ Выберите хотя бы один интервал", show_alert=True)
        return
    
    # Сохраняем интервалы
    await state.update_data(intervals=selected)
    
    # Переходим к выбору процента
    await callback.message.edit_text(
        "<b>📈 Процент изменения</b>\n\n"
        "При каком изменении цены отправлять уведомление?",
        reply_markup=Keyboards.percent_presets(),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.selecting_percent)
    await callback.answer()


async def percent_preset(callback: types.CallbackQuery, state: FSMContext):
    """Выбор процента из пресетов"""
    percent = float(callback.data.split("_")[1])
    
    # Сохраняем процент
    await state.update_data(percent_change=percent)
    
    # Создаем пресет
    await create_preset_final(callback, state)


async def percent_manual(callback: types.CallbackQuery, state: FSMContext):
    """Ручной ввод процента"""
    await callback.message.edit_text(
        f"<b>✏️ Ввод процента</b>\n\n"
        f"Введите процент изменения (от {config.MIN_PERCENT_CHANGE} до {config.MAX_PERCENT_CHANGE}):",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_manual_percent)
    await callback.answer()


async def process_manual_percent(message: types.Message, state: FSMContext):
    """Обработка ручного ввода процента"""
    try:
        percent = float(message.text.strip().replace(',', '.').replace('%', ''))
        
        if percent < config.MIN_PERCENT_CHANGE or percent > config.MAX_PERCENT_CHANGE:
            await message.answer(
                f"❌ Процент должен быть от {config.MIN_PERCENT_CHANGE} до {config.MAX_PERCENT_CHANGE}",
                reply_markup=Keyboards.cancel_button("candle_alerts")
            )
            return
        
        # Сохраняем процент
        await state.update_data(percent_change=percent)
        
        # Создаем пресет
        await create_preset_final(message, state)
        
    except ValueError:
        await message.answer(
            "❌ Введите корректное число",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )


async def create_preset_final(message_or_callback, state: FSMContext):
    """Финальное создание пресета"""
    data = await state.get_data()
    
    if isinstance(message_or_callback, types.Message):
        user_id = message_or_callback.from_user.id
        reply_func = message_or_callback.answer
    else:
        user_id = message_or_callback.from_user.id
        reply_func = message_or_callback.message.answer
        await message_or_callback.answer()
    
    # Создаем пресет в БД
    preset_id = await db_manager.create_preset(
        user_id=user_id,
        name=data['name'],
        pairs=data['pairs'],
        intervals=data['intervals'],
        percent_change=data['percent_change']
    )
    
    if not preset_id:
        await reply_func(
            "❌ Ошибка при создании пресета. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        await state.clear()
        return
    
    # Добавляем в кеш
    preset = PresetData(
        id=preset_id,
        user_id=user_id,
        name=data['name'],
        pairs=data['pairs'],
        intervals=data['intervals'],
        percent_change=data['percent_change'],
        is_active=False
    )
    await cache.add_preset(preset)
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем успех
    await reply_func(
        f"✅ <b>Пресет создан!</b>\n\n"
        f"📌 Название: {data['name']}\n"
        f"💰 Пар: {len(data['pairs'])}\n"
        f"⏱ Интервалов: {len(data['intervals'])}\n"
        f"📊 Порог: {data['percent_change']}%\n\n"
        f"Пресет создан в <b>неактивном</b> состоянии.\n"
        f"Активируйте его для получения уведомлений.",
        reply_markup=Keyboards.preset_actions(preset_id, False),
        parse_mode="HTML"
    )


async def preset_list(callback: types.CallbackQuery):
    """Показ списка пресетов"""
    user_id = callback.from_user.id
    
    # Получаем пресеты пользователя
    presets = await db_manager.get_user_presets(user_id)
    
    if not presets:
        await callback.message.edit_text(
            "<b>📋 Мои пресеты</b>\n\n"
            "У вас пока нет пресетов. Создайте первый!",
            reply_markup=Keyboards.candle_alerts_menu(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"<b>📋 Мои пресеты</b>\n\n"
        f"Всего пресетов: {len(presets)}",
        reply_markup=Keyboards.preset_list(presets),
        parse_mode="HTML"
    )
    await callback.answer()


async def preset_view(callback: types.CallbackQuery):
    """Просмотр пресета"""
    preset_id = int(callback.data.split("_")[2])
    
    # Получаем пресет
    preset = await db_manager.get_preset(preset_id)
    
    if not preset:
        await callback.answer("❌ Пресет не найден", show_alert=True)
        return
    
    # Форматируем информацию
    status = "✅ Активен" if preset['is_active'] else "❌ Неактивен"
    pairs_preview = ", ".join(preset['pairs'][:5])
    if len(preset['pairs']) > 5:
        pairs_preview += f" и еще {len(preset['pairs']) - 5}"
    
    text = (
        f"<b>📊 Пресет: {preset['name']}</b>\n\n"
        f"Статус: {status}\n"
        f"Пар: {len(preset['pairs'])}\n"
        f"Интервалы: {', '.join(preset['intervals'])}\n"
        f"Порог: {preset['percent_change']}%\n\n"
        f"<b>Пары:</b>\n{pairs_preview}"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=Keyboards.preset_actions(preset_id, preset['is_active']),
        parse_mode="HTML"
    )
    await callback.answer()


async def preset_activate(callback: types.CallbackQuery):
    """Активация пресета"""
    preset_id = int(callback.data.split("_")[2])
    
    # Обновляем в БД
    success = await db_manager.update_preset_status(preset_id, True)
    
    if not success:
        await callback.answer("❌ Ошибка при активации", show_alert=True)
        return
    
    # Обновляем в кеше
    await cache.update_preset_status(preset_id, True)
    
    await callback.answer("✅ Пресет активирован")
    
    # Обновляем сообщение
    await preset_view(callback)


async def preset_deactivate(callback: types.CallbackQuery):
    """Деактивация пресета"""
    preset_id = int(callback.data.split("_")[2])
    
    # Обновляем в БД
    success = await db_manager.update_preset_status(preset_id, False)
    
    if not success:
        await callback.answer("❌ Ошибка при деактивации", show_alert=True)
        return
    
    # Обновляем в кеше
    await cache.update_preset_status(preset_id, False)
    
    await callback.answer("✅ Пресет деактивирован")
    
    # Обновляем сообщение
    await preset_view(callback)


async def preset_delete(callback: types.CallbackQuery):
    """Запрос на удаление пресета"""
    preset_id = int(callback.data.split("_")[2])
    
    await callback.message.edit_text(
        "❓ <b>Удалить пресет?</b>\n\n"
        "Это действие нельзя отменить.",
        reply_markup=Keyboards.preset_delete_confirm(preset_id),
        parse_mode="HTML"
    )
    await callback.answer()


async def preset_delete_confirm(callback: types.CallbackQuery):
    """Подтверждение удаления пресета"""
    preset_id = int(callback.data.split("_")[3])
    
    # Удаляем из БД
    success = await db_manager.delete_preset(preset_id)
    
    if not success:
        await callback.answer("❌ Ошибка при удалении", show_alert=True)
        return
    
    # Удаляем из кеша
    await cache.remove_preset(preset_id)
    
    await callback.answer("✅ Пресет удален")
    
    # Возвращаемся к списку
    await preset_list(callback)


def register_candle_alerts_handlers(dp: Dispatcher):
    """Регистрация обработчиков свечных алертов"""
    
    # Создание пресета
    dp.callback_query.register(preset_create, F.data == "preset_create")
    dp.message.register(process_preset_name, PresetStates.waiting_for_name)
    
    # Выбор пар
    dp.callback_query.register(preset_pairs_top100, F.data == "pairs_top100")
    dp.callback_query.register(preset_pairs_volume, F.data == "pairs_volume")
    dp.callback_query.register(preset_pairs_all, F.data == "pairs_all")
    dp.callback_query.register(preset_pairs_manual, F.data == "pairs_manual")
    dp.message.register(process_manual_pairs, PresetStates.waiting_for_manual_pairs)
    
    # Выбор интервалов
    dp.callback_query.register(interval_toggle, F.data.startswith("interval_toggle_"))
    dp.callback_query.register(interval_all, F.data == "interval_all")
    dp.callback_query.register(interval_none, F.data == "interval_none")
    dp.callback_query.register(interval_done, F.data == "interval_done")
    
    # Выбор процента
    dp.callback_query.register(percent_preset, F.data.startswith("percent_") & ~F.data.contains("manual"))
    dp.callback_query.register(percent_manual, F.data == "percent_manual")
    dp.message.register(process_manual_percent, PresetStates.waiting_for_manual_percent)
    
    # Управление пресетами
    dp.callback_query.register(preset_list, F.data == "preset_list")
    dp.callback_query.register(preset_view, F.data.startswith("preset_view_"))
    dp.callback_query.register(preset_activate, F.data.startswith("preset_activate_"))
    dp.callback_query.register(preset_deactivate, F.data.startswith("preset_deactivate_"))
    dp.callback_query.register(preset_delete, F.data.startswith("preset_delete_") & ~F.data.contains("confirm"))
    dp.callback_query.register(preset_delete_confirm, F.data.startswith("preset_delete_confirm_"))