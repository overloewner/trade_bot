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
    waiting_for_volume = State()
    waiting_for_manual_pairs = State()
    selecting_interval = State()
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
        "Введите название для пресета (до 30 символов):",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_name)
async def callback_pairs_selection(callback: types.CallbackQuery):
    """Возврат к меню выбора пар"""
    await callback.message.edit_text(
        "<b>📊 Выбор торговых пар</b>\n\n"
        "Выберите способ добавления пар:",
        reply_markup=Keyboards.pairs_selection_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_preset_create_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к вводу имени пресета"""
    await state.clear()
    await preset_create(callback, state)


async def process_preset_name(message: types.Message, state: FSMContext):
    """Обработка названия пресета"""
    name = message.text.strip()
    
    # Валидация длины
    if len(name) > 30:
        await message.answer(
            "❌ Название слишком длинное. Максимум 30 символов.",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    if len(name) < 1:
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
        reply_markup=Keyboards.pairs_selection_menu(),
        parse_mode="HTML"
    )


async def callback_pairs_volume_menu(callback: types.CallbackQuery):
    """Показ меню выбора по объему"""
    await callback.message.edit_text(
        "<b>💰 Выбор пар по объему</b>\n\n"
        "Выберите вариант:",
        reply_markup=Keyboards.pairs_volume_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_pairs_specific_menu(callback: types.CallbackQuery):
    """Показ меню выбора конкретных пар"""
    await callback.message.edit_text(
        "<b>📝 Выбор конкретных пар</b>\n\n"
        "Выберите вариант:",
        reply_markup=Keyboards.pairs_specific_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


async def preset_pairs_volume(callback: types.CallbackQuery, state: FSMContext):
    """Выбор по объему - ввод объема"""
    await callback.message.edit_text(
        "<b>💰 Ввод минимального объема</b>\n\n"
        "Введите минимальный объем в USDT (например: 1000000):",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_volume)
    await callback.answer()


async def process_volume_input(message: types.Message, state: FSMContext):
    """Обработка ввода объема"""
    try:
        volume = float(message.text.strip().replace(',', ''))
        
        if volume <= 0:
            await message.answer(
                "❌ Объем должен быть положительным числом.",
                reply_markup=Keyboards.cancel_button("candle_alerts")
            )
            return
        
        # Получаем все пары и фильтруем по объему
        # Здесь нужно будет добавить метод в binance API для получения пар с объемом
        # Пока используем топ-100 как заглушку
        pairs = symbols_cache.get_top_symbols(100)
        
        if not pairs:
            await message.answer(
                "❌ Символы не загружены. Попробуйте позже.",
                reply_markup=Keyboards.back_button("candle_alerts")
            )
            return
        
        # Ограничиваем по лимиту
        selected_pairs = pairs[:config.MAX_PAIRS_PER_PRESET]
        await state.update_data(pairs=selected_pairs)
        
        # Показываем выбранные пары
        await show_selected_pairs(message, selected_pairs)
        
        # Переходим к выбору интервала
        await show_interval_selection(message, state)
        
    except ValueError:
        await message.answer(
            "❌ Введите корректное число",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )


async def preset_pairs_top10(callback: types.CallbackQuery, state: FSMContext):
    """Выбор топ 10 пар по объему"""
    await callback.answer("Загружаю топ 10 пар...")
    
    pairs = symbols_cache.get_top_symbols(10)
    
    if not pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    await state.update_data(pairs=pairs)
    
    # Показываем выбранные пары
    await callback.message.edit_text(
        f"✅ Выбрано топ {len(pairs)} пар по объему:\n" +
        ", ".join(pairs),
        parse_mode="HTML"
    )
    
    # Переходим к выбору интервала
    await show_interval_selection(callback.message, state)


async def preset_pairs_top100(callback: types.CallbackQuery, state: FSMContext):
    """Выбор топ 100 пар по объему"""
    await callback.answer("Загружаю топ 100 пар...")
    
    pairs = symbols_cache.get_top_symbols(100)
    
    if not pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    await state.update_data(pairs=pairs[:config.MAX_PAIRS_PER_PRESET])
    
    # Показываем выбранные пары
    await callback.message.edit_text(
        f"✅ Выбрано {len(pairs)} пар из топ-100:\n" +
        ", ".join(pairs[:10]) +
        (f"\n...и еще {len(pairs) - 10}" if len(pairs) > 10 else ""),
        parse_mode="HTML"
    )
    
    # Переходим к выбору интервала
    await show_interval_selection(callback.message, state)


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


async def preset_pairs_top5(callback: types.CallbackQuery, state: FSMContext):
    """Выбор топ 5 пар"""
    await callback.answer("Загружаю топ 5 пар...")
    
    pairs = symbols_cache.get_top_symbols(5)
    
    if not pairs:
        await callback.message.edit_text(
            "❌ Символы не загружены. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        return
    
    await state.update_data(pairs=pairs)
    
    # Показываем выбранные пары
    await callback.message.edit_text(
        f"✅ Выбрано топ {len(pairs)} пар:\n" +
        ", ".join(pairs),
        parse_mode="HTML"
    )
    
    # Переходим к выбору интервала
    await show_interval_selection(callback.message, state)


async def process_manual_pairs(message: types.Message, state: FSMContext):
    """Обработка ручного ввода пар"""
    text = message.text.upper().strip()
    
    # Парсим пары - ищем все что похоже на криптопары
    # Поддерживаем разные разделители: запятая, пробел, точка с запятой
    raw_pairs = re.split(r'[,\s;]+', text)
    
    # Фильтруем и валидируем
    pairs = []
    invalid_pairs = []
    
    for pair in raw_pairs:
        pair = pair.strip()
        if not pair:
            continue
            
        # Проверяем формат - должен заканчиваться на USDT
        if pair.endswith('USDT') and len(pair) > 4:
            pairs.append(pair)
        else:
            invalid_pairs.append(pair)
    
    # Убираем дубликаты
    pairs = list(set(pairs))
    
    if not pairs:
        error_msg = "❌ Не найдено ни одной валидной пары.\n\n"
        error_msg += "Пары должны заканчиваться на USDT.\n"
        error_msg += "Пример: BTCUSDT, ETHUSDT\n\n"
        
        if invalid_pairs:
            error_msg += f"Некорректные пары: {', '.join(invalid_pairs[:5])}"
            if len(invalid_pairs) > 5:
                error_msg += f" и еще {len(invalid_pairs) - 5}"
        
        await message.answer(
            error_msg,
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
    not_found_pairs = [p for p in pairs if p not in valid_pairs]
    
    if not valid_pairs:
        await message.answer(
            "❌ Ни одна из введенных пар не найдена в списке поддерживаемых.\n\n" +
            f"Проверьте правильность написания: {', '.join(pairs[:5])}",
            reply_markup=Keyboards.cancel_button("candle_alerts")
        )
        return
    
    # Если есть несуществующие пары, предупреждаем
    if not_found_pairs:
        warning_msg = f"⚠️ Некоторые пары не найдены и были исключены:\n"
        warning_msg += ", ".join(not_found_pairs[:5])
        if len(not_found_pairs) > 5:
            warning_msg += f" и еще {len(not_found_pairs) - 5}"
        await message.answer(warning_msg)
    
    # Сохраняем пары
    await state.update_data(pairs=valid_pairs)
    
    # Показываем выбранные пары
    await show_selected_pairs(message, valid_pairs)
    
    # Переходим к выбору интервала
    await show_interval_selection(message, state)


async def show_selected_pairs(message: types.Message, pairs: List[str]):
    """Показ выбранных пар"""
    await message.answer(
        f"✅ Выбрано {len(pairs)} пар:\n" +
        ", ".join(pairs[:10]) +
        (f"\n...и еще {len(pairs) - 10}" if len(pairs) > 10 else "")
    )


async def show_interval_selection(message: types.Message, state: FSMContext):
    """Показ выбора интервала"""
    await message.answer(
        "<b>⏱ Выбор интервала</b>\n\n"
        "Выберите интервал для отслеживания:",
        reply_markup=Keyboards.interval_selection(),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.selecting_interval)


async def interval_selected(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора интервала"""
    interval = callback.data.split("_")[1]
    
    # Сохраняем интервал (только один)
    await state.update_data(intervals=[interval])
    
    # Переходим к выбору процента
    await callback.message.edit_text(
        "<b>📈 Процент изменения</b>\n\n"
        "При каком изменении цены отправлять уведомление?",
        reply_markup=Keyboards.percent_presets(),
        parse_mode="HTML"
    )
    
    await callback.answer()


async def percent_preset(callback: types.CallbackQuery, state: FSMContext):
    """Выбор процента из пресетов"""
    # Парсим процент из callback_data вида "percent_0.5"
    percent_str = callback.data.replace("percent_", "")
    percent = float(percent_str)
    
    # Сохраняем процент
    await state.update_data(percent_change=percent)
    
    # Создаем пресет
    await create_preset_final(callback, state)


async def percent_manual(callback: types.CallbackQuery, state: FSMContext):
    """Ручной ввод процента"""
    await callback.message.edit_text(
        "<b>✏️ Ввод процента</b>\n\n"
        "Введите процент изменения (от 0.1 до 100):",
        reply_markup=Keyboards.cancel_button("candle_alerts"),
        parse_mode="HTML"
    )
    
    await state.set_state(PresetStates.waiting_for_manual_percent)
    await callback.answer()


async def process_manual_percent(message: types.Message, state: FSMContext):
    """Обработка ручного ввода процента"""
    try:
        # Убираем знак процента и заменяем запятую
        percent_text = message.text.strip().replace(',', '.').replace('%', '')
        percent = float(percent_text)
        
        # Валидация диапазона
        if percent < 0.1 or percent > 100:
            await message.answer(
                "❌ Процент должен быть от 0.1 до 100",
                reply_markup=Keyboards.cancel_button("candle_alerts")
            )
            return
        
        # Сохраняем процент
        await state.update_data(percent_change=percent)
        
        # Создаем пресет
        await create_preset_final(message, state)
        
    except ValueError:
        await message.answer(
            "❌ Введите корректное число\n"
            "Пример: 1.5 или 1,5 или 1.5%",
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
    
    # Создаем пресет в БД СРАЗУ АКТИВНЫМ  
    preset_id = await db_manager.create_preset(
        user_id=user_id,
        name=data['name'],
        pairs=data['pairs'],
        intervals=data['intervals'],
        percent_change=data['percent_change'],
        is_active=True  # Сразу активный
    )
    
    if not preset_id:
        await reply_func(
            "❌ Ошибка при создании пресета. Попробуйте позже.",
            reply_markup=Keyboards.back_button("candle_alerts")
        )
        await state.clear()
        return
    
    # Добавляем в кеш как активный
    preset = PresetData(
        id=preset_id,
        user_id=user_id,
        name=data['name'],
        pairs=data['pairs'],
        intervals=data['intervals'],
        percent_change=data['percent_change'],
        is_active=True  # Активный
    )
    await cache.add_preset(preset)
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем успех
    await reply_func(
        f"✅ <b>Пресет создан и активирован!</b>\n\n"
        f"📌 Название: {data['name']}\n"
        f"💰 Пар: {len(data['pairs'])}\n"
        f"⏱ Интервал: {data['intervals'][0]}\n"
        f"📊 Порог: {data['percent_change']}%\n\n"
        f"Вы будете получать уведомления при изменении цены.",
        reply_markup=Keyboards.preset_actions(preset_id, True),
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
    
    # Показываем только один интервал
    interval = preset['intervals'][0] if preset['intervals'] else "Не задан"
    
    text = (
        f"<b>📊 Пресет: {preset['name']}</b>\n\n"
        f"Статус: {status}\n"
        f"Пар: {len(preset['pairs'])}\n"
        f"Интервал: {interval}\n"
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
    
    # Навигация по меню
    dp.callback_query.register(callback_pairs_volume_menu, F.data == "pairs_volume_menu")
    dp.callback_query.register(callback_pairs_specific_menu, F.data == "pairs_specific_menu")
    dp.callback_query.register(callback_pairs_selection, F.data == "pairs_selection")
    dp.callback_query.register(callback_preset_create_back, F.data == "preset_create_back")
    
    # Выбор пар по объему
    dp.callback_query.register(preset_pairs_volume, F.data == "pairs_volume")
    dp.message.register(process_volume_input, PresetStates.waiting_for_volume)
    dp.callback_query.register(preset_pairs_top10, F.data == "pairs_top10")
    dp.callback_query.register(preset_pairs_top100, F.data == "pairs_top100")
    
    # Выбор конкретных пар
    dp.callback_query.register(preset_pairs_manual, F.data == "pairs_manual")
    dp.callback_query.register(preset_pairs_top5, F.data == "pairs_top5")
    dp.message.register(process_manual_pairs, PresetStates.waiting_for_manual_pairs)
    
    # Выбор интервала
    dp.callback_query.register(interval_selected, F.data.startswith("interval_") & ~F.data.contains("done") & ~F.data.contains("all") & ~F.data.contains("none"))
    
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