from aiogram import types, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
import logging

from services.telegram.keyboards import Keyboards
from models.database import db_manager
from cache.memory import cache
from utils.queue import message_queue, Priority
from config.settings import config

logger = logging.getLogger(__name__)


async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    # Очищаем состояние
    await state.clear()
    await cache.clear_user_state(user_id)
    
    # Создаем пользователя в БД если его нет
    await db_manager.create_user(user_id)
    
    # Приветственное сообщение
    welcome_text = (
        f"Привет, {message.from_user.first_name}!\n\n"
        "Я бот для мониторинга криптовалют. Вот что я умею:\n\n"
        "Свечные алерты - уведомления об изменении цены\n"
        "Газ алерты - уведомления о снижении цены газа в Ethereum\n\n"
        "Выберите, что вас интересует:"
    )
    
    await message.answer(
        welcome_text,
        reply_markup=Keyboards.main_menu(),
        parse_mode="HTML"
    )


async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = (
        "Помощь по использованию бота\n\n"
        "Свечные алерты:\n"
        "• Создавайте пресеты с выбором пар и интервалов\n"
        "• Устанавливайте процент изменения для уведомления\n"
        "• Активируйте/деактивируйте пресеты в любое время\n"
        f"• Максимум {config.MAX_PRESETS_PER_USER} пресетов на пользователя\n\n"
        
        "Газ алерты:\n"
        "• Установите порог цены газа в Gwei\n"
        "• Получайте уведомления когда газ опустится ниже порога\n"
        "• Смотрите график изменения цены газа\n\n"
        
        "Команды:\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/status - Ваша статистика\n"
        "/preset - Управление пресетами\n"
        "/gas - Настройка газ алертов\n\n"
        
        "Поддержка: @your_support_contact"
    )
    
    await message.answer(
        help_text,
        reply_markup=Keyboards.back_button(),
        parse_mode="HTML"
    )


async def cmd_status(message: types.Message):
    """Обработчик команды /status"""
    user_id = message.from_user.id
    
    # Получаем статистику пользователя
    stats = await cache.get_user_stats(user_id)
    
    status_text = (
        "Ваша статистика:\n\n"
        f"Пресетов создано: {stats['total_presets']}\n"
        f"Активных пресетов: {stats['active_presets']}\n"
        f"Газ алерт: {'Включен' if stats['has_gas_alert'] else 'Выключен'}\n"
    )
    
    if stats['has_gas_alert'] and stats['gas_threshold']:
        status_text += f"└ Порог: {stats['gas_threshold']} Gwei\n"
    
    await message.answer(
        status_text,
        reply_markup=Keyboards.back_button(),
        parse_mode="HTML"
    )


async def cmd_preset(message: types.Message):
    """Быстрый доступ к пресетам"""
    await show_candle_alerts_menu(message)


async def cmd_gas(message: types.Message):
    """Быстрый доступ к газ алертам"""
    await show_gas_alerts_menu(message)


async def callback_main_menu(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    welcome_text = (
        "Главное меню\n\n"
        "Выберите, что вас интересует:"
    )
    
    await callback.message.edit_text(
        welcome_text,
        reply_markup=Keyboards.main_menu(),
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_help(callback: types.CallbackQuery):
    """Показ справки через callback"""
    help_text = (
        "Помощь по использованию бота\n\n"
        "Свечные алерты:\n"
        "• Создавайте пресеты с выбором пар и интервалов\n"
        "• Устанавливайте процент изменения для уведомления\n"
        "• Активируйте/деактивируйте пресеты в любое время\n"
        f"• Максимум {config.MAX_PRESETS_PER_USER} пресетов на пользователя\n\n"
        
        "Газ алерты:\n"
        "• Установите порог цены газа в Gwei\n"
        "• Получайте уведомления когда газ опустится ниже порога\n"
        "• Смотрите график изменения цены газа\n\n"
        
        "Поддержка: @your_support_contact"
    )
    
    await callback.message.edit_text(
        help_text,
        reply_markup=Keyboards.back_button(),
        parse_mode="HTML"
    )
    await callback.answer()


async def callback_stats(callback: types.CallbackQuery):
    """Показ статистики через callback"""
    user_id = callback.from_user.id
    
    # Получаем статистику пользователя
    stats = await cache.get_user_stats(user_id)
    
    status_text = (
        "Ваша статистика:\n\n"
        f"Пресетов создано: {stats['total_presets']}\n"
        f"Активных пресетов: {stats['active_presets']}\n"
        f"Газ алерт: {'Включен' if stats['has_gas_alert'] else 'Выключен'}\n"
    )
    
    if stats['has_gas_alert'] and stats['gas_threshold']:
        status_text += f"└ Порог: {stats['gas_threshold']} Gwei\n"
    
    await callback.message.edit_text(
        status_text,
        reply_markup=Keyboards.back_button(),
        parse_mode="HTML"
    )
    await callback.answer()


# Вспомогательные функции для других модулей
async def show_candle_alerts_menu(message_or_callback):
    """Показ меню свечных алертов"""
    text = (
        "Свечные алерты\n\n"
        "Создавайте пресеты для отслеживания изменений цен.\n"
        "Выберите действие:"
    )
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text,
            reply_markup=Keyboards.candle_alerts_menu(),
            parse_mode="HTML"
        )
    else:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=Keyboards.candle_alerts_menu(),
            parse_mode="HTML"
        )
        await message_or_callback.answer()


async def show_gas_alerts_menu(message_or_callback):
    """Показ меню газ алертов"""
    if isinstance(message_or_callback, types.Message):
        user_id = message_or_callback.from_user.id
    else:
        user_id = message_or_callback.from_user.id
    
    # Получаем информацию о газ алерте
    gas_alert = await db_manager.get_gas_alert(user_id)
    has_alert = gas_alert is not None and gas_alert.get('is_active', False)
    threshold = gas_alert.get('threshold_gwei') if gas_alert else None
    
    text = (
        "Газ алерты\n\n"
        "Получайте уведомления когда цена газа в Ethereum "
        "опустится ниже заданного порога.\n\n"
    )
    
    if has_alert:
        text += f"Алерты включены\nПорог: {threshold} Gwei"
    else:
        text += "Алерты выключены"
    
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(
            text,
            reply_markup=Keyboards.gas_alerts_menu(has_alert, threshold),
            parse_mode="HTML"
        )
    else:
        await message_or_callback.message.edit_text(
            text,
            reply_markup=Keyboards.gas_alerts_menu(has_alert, threshold),
            parse_mode="HTML"
        )
        await message_or_callback.answer()


def register_start_handlers(dp: Dispatcher):
    """Регистрация обработчиков старта"""
    # Команды
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(cmd_preset, Command("preset"))
    dp.message.register(cmd_gas, Command("gas"))
    
    # Callback-и
    dp.callback_query.register(callback_main_menu, lambda c: c.data == "main_menu")
    dp.callback_query.register(callback_help, lambda c: c.data == "help")
    dp.callback_query.register(callback_stats, lambda c: c.data == "stats")
    dp.callback_query.register(
        lambda c: show_candle_alerts_menu(c), 
        lambda c: c.data == "candle_alerts"
    )
    dp.callback_query.register(
        lambda c: show_gas_alerts_menu(c), 
        lambda c: c.data == "gas_alerts"
    )