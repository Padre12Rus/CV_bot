#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram бот для преобразования резюме в Word документ.
Переписан на aiogram (v3): обрабатывает PDF/DOCX и возвращает структурированный DOCX.
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.types.error_event import ErrorEvent
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Пути проекта и импорт конвертера
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from parser.pdf_to_docx import ConversionConfig, ResumeConverter
except ImportError as exc:
    logger.error("Не удалось импортировать parser.pdf_to_docx: %s", exc)
    sys.exit(1)

# Настройки шаблонов
JSON_TEMPLATE = str(PROJECT_ROOT / "parser" / "template" / "example.json")
DOCX_TEMPLATE = str(PROJECT_ROOT / "parser" / "template" / "example_cv_docx.docx")

# Токен Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
    sys.exit(1)

# Кэш последних файлов пользователей (для пересоздания)
LAST_FILES = {}
# Ожидание комментария для пересоздания: user_id -> {"file_id":..., "file_name":...}
PENDING_REGENERATE = {}


def build_menu_keyboard(can_regenerate: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🤖 Статус AI", callback_data="menu_status"),
            InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu_help"),
        ]
    ]
    if can_regenerate:
        buttons.append(
            [InlineKeyboardButton(text="🔁 Пересоздать последний файл", callback_data="regenerate")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_after_finish_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Пересоздать", callback_data="regenerate"),
                InlineKeyboardButton(text="🤖 Статус AI", callback_data="menu_status"),
            ],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu_help")],
        ]
    )


async def cmd_start(message: Message) -> None:
    """Обработчик команды /start"""
    welcome_message = (
        "👋 Привет! Я бот для преобразования резюме в Word документ.\n\n"
        "📤 Отправь файл с резюме (лучше PDF или DOCX, но можно и другие) — я превращу его в структурированный DOCX.\n\n"
        "Процесс обработки:\n"
        "1️⃣ Извлечение содержимого\n"
        "2️⃣ Структурирование данных через AI\n"
        "3️⃣ Создание Word документа\n\n"
        "⏱️ Обработка может занять до пары минут — пожалуйста, подожди."
    )
    await message.answer(
        welcome_message,
        reply_markup=build_menu_keyboard(can_regenerate=message.from_user.id in LAST_FILES),
    )


async def cmd_help(message: Message) -> None:
    """Обработчик /help"""
    help_text = (
        "📖 Как работает бот:\n\n"
        "1. Отправь файл с резюме (предпочтительно PDF/DOCX)\n"
        "2. Дождись завершения цепочки (1–2 минуты)\n"
        "3. Получи готовый DOCX в ответе\n\n"
        "⚠️ Файл должен содержать текст (не только изображения)\n"
        "📝 Бот сам структурирует данные через AI\n\n"
        "💡 Команда /status показывает информацию о доступных AI моделях."
    )
    await message.answer(help_text)


async def cmd_status(message: Message) -> None:
    """Показывает информацию о моделях AI"""
    try:
        from parser.ai_provider import get_models_info, get_last_used_provider

        models_info = get_models_info()
        last_used = get_last_used_provider()

        status_text = "🤖 Информация о AI моделях:\n\n"

        gemini_status = "✅" if models_info["gemini"]["available"] else "❌"
        status_text += f"{gemini_status} *Gemini:*\n"
        status_text += f"  Модель: `{models_info['gemini']['model']}`\n"
        status_text += (
            f"  Ключ: {'Установлен' if models_info['gemini']['api_key_set'] else 'Не установлен'}\n\n"
        )

        openrouter_status = "✅" if models_info["openrouter"]["available"] else "❌"
        status_text += f"{openrouter_status} *OpenRouter:*\n"
        status_text += f"  Модель: `{models_info['openrouter']['model']}`\n"
        status_text += (
            f"  Ключ: {'Установлен' if models_info['openrouter']['api_key_set'] else 'Не установлен'}\n\n"
        )

        if models_info["primary_provider"]:
            provider_name = "Gemini" if models_info["primary_provider"] == "gemini" else "OpenRouter"
            status_text += f"🎯 *Основной провайдер:* {provider_name}\n"

        status_text += (
            "🔄 *Автоматическое переключение:* "
            + ("Включено\n" if models_info["fallback_enabled"] else "Отключено (нужны оба ключа)\n")
        )

        if last_used:
            provider_name = "Gemini" if last_used["provider"] == "gemini" else "OpenRouter"
            status_text += "\n📊 *Последняя использованная модель:*\n"
            status_text += f"  Провайдер: {provider_name}\n"
            status_text += f"  Модель: `{last_used['model']}`\n"
        else:
            status_text += "\n📊 *Последняя использованная модель:* еще не использовалась\n"

        await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        logger.error("Ошибка при получении статуса: %s", exc, exc_info=True)
        await message.answer(
            f"❌ Ошибка при получении информации о моделях: {exc}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _process_file(
    bot: Bot,
    chat_id: int,
    file_id: str,
    file_name: str,
    reply_to_message_id: int | None = None,
    user_hint: str | None = None,
) -> None:
    """Общий пайплайн обработки файла (новый или пересоздание)."""
    file_name_lower = file_name.lower()
    suffix = Path(file_name_lower).suffix
    is_pdf = suffix == ".pdf"
    is_docx = suffix == ".docx"

    original_name = Path(file_name).stem
    status_message = await bot.send_message(
        chat_id,
        "📥 Файл получен! Готовлюсь к обработке...\n"
        "⏳ Это может занять 1–2 минуты, пожалуйста, подожди.",
        reply_to_message_id=reply_to_message_id,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            input_file_path = os.path.join(temp_dir, file_name)
            await bot.download(file_id, destination=input_file_path)
            logger.info("Файл скачан: %s", input_file_path)

            file_type = suffix.upper() if suffix else "FILE"

            output_filename = f"{original_name}.docx"
            md_path = os.path.join(temp_dir, "document.md")
            json_path = os.path.join(temp_dir, "document.json")
            docx_path = os.path.join(temp_dir, output_filename)

            config = ConversionConfig(
                input_file=input_file_path,
                # Для fallback-режима: если не PDF, используем docx как наиболее лояльный вариант
                input_kind="pdf" if is_pdf else ("docx" if is_docx else "pdf"),
                output_file=docx_path,
                md_path=md_path,
                json_path=json_path,
                json_template=JSON_TEMPLATE,
                docx_template=DOCX_TEMPLATE,
                api_key=None,
                model=None,
                keep_intermediate=False,
                use_direct_file_mode=True,
                skip_step1=True,
                skip_step2=False,
                skip_step3=False,
                user_hint=user_hint,
            )

            converter = ResumeConverter(config, verbose=False)

            status_state = {
                "progress": 0.05,
                "target": 0.05,
                "title": f"📥 Обработка резюме ({file_type})",
                "subtitle": "Получаю файл...",
                "done": False,
            }

            def _render_status() -> str:
                p = max(0.0, min(1.0, status_state["progress"]))
                bar_len = 20
                filled = int(bar_len * p)
                bar = "█" * filled + "░" * (bar_len - filled)
                return (
                    f"{status_state['title']}\n"
                    f"[{bar}] {int(p * 100)}%\n"
                    f"{status_state['subtitle']}"
                )

            async def _progress_loop():
                last_text = None
                try:
                    while not status_state["done"]:
                        if status_state["progress"] < status_state["target"]:
                            status_state["progress"] = min(
                                status_state["target"], status_state["progress"] + 0.03
                            )
                        text = _render_status()
                        if text != last_text:
                            try:
                                await status_message.edit_text(text)
                                last_text = text
                            except Exception:
                                pass
                        await asyncio.sleep(1.2)
                    status_state["progress"] = 1.0
                    status_state["target"] = 1.0
                    final_text = _render_status()
                    try:
                        await status_message.edit_text(final_text)
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    return

            def _set_status(target: float, subtitle: str):
                status_state["target"] = max(status_state["target"], min(1.0, target))
                status_state["subtitle"] = subtitle

            progress_task = asyncio.create_task(_progress_loop())

            def _build_model_info() -> str:
                try:
                    from parser.ai_provider import get_last_used_provider

                    last_used = get_last_used_provider()
                    if last_used:
                        provider_name = "Gemini" if last_used["provider"] == "gemini" else "OpenRouter"
                        return f"\n🤖 Использована модель: {provider_name} ({last_used['model']})"
                except Exception:
                    return ""
                return ""

            _set_status(0.25, f"Шаг 1/3: Принимаю файл ({file_type})")

            async for stage in converter.run_iter_async():
                if stage.name == "cleanup":
                    continue
                if stage.name == "step1":
                    if stage.status == "skipped":
                        _set_status(0.35, "Шаг 1/3: Подготовка не требуется (прямой режим)")
                    else:
                        _set_status(0.4, "Шаг 1/3 завершен: файл подготовлен")
                    _set_status(0.8, "Шаг 2/3: Структурирование данных через AI...")
                elif stage.name == "step2" and stage.status == "completed":
                    model_info = _build_model_info()
                    _set_status(0.9, f"Шаг 2/3 завершен: данные структурированы{model_info}")
                    _set_status(0.95, "Шаг 3/3: Создание Word документа...")
                elif stage.name == "step3" and stage.status == "completed":
                    _set_status(0.99, "Файл почти готов, упаковываю результат...")

            result = converter.result
            if not result or not result.output_file:
                raise FileNotFoundError("DOCX файл не был создан")
            docx_path = result.output_file
            if not os.path.exists(docx_path):
                raise FileNotFoundError("DOCX файл не был создан")

            status_state["done"] = True
            try:
                await progress_task
            except Exception:
                pass

            if user_hint:
                await status_message.edit_text("✅ Обработка завершена с учетом комментария! Отправляю файл...")
            else:
                await status_message.edit_text("✅ Обработка завершена! Отправляю файл...")

            await bot.send_document(
                chat_id,
                document=FSInputFile(docx_path, filename=output_filename),
                caption=f"✅ Ваш файл готов! Вот преобразованное резюме: {output_filename}",
            )

            await bot.send_message(
                chat_id,
                "Если результат нужно поменять — пересоздай файл или загрузи новый.",
                reply_markup=build_after_finish_keyboard(),
            )

            await status_message.delete()
            logger.info("Файл успешно обработан для пользователя %s", chat_id)

        except Exception as exc:
            status_state = locals().get("status_state", None)
            if status_state is not None:
                status_state["done"] = True
            progress_task = locals().get("progress_task", None)
            if progress_task:
                progress_task.cancel()
            logger.error("Ошибка при обработке файла: %s", exc, exc_info=True)
            error_message = (
                f"❌ Произошла ошибка при обработке файла:\n\n"
                f"`{exc}`\n\n"
                f"Пожалуйста, убедись, что:\n"
                f"• Файл содержит текст (не только изображения)\n"
                f"• Файл не поврежден\n"
                f"• Установлен GEMINI_API_KEY для работы AI"
            )
            try:
                await status_message.edit_text(error_message, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await bot.send_message(chat_id, error_message, parse_mode=ParseMode.MARKDOWN)

async def handle_document(message: Message) -> None:
    """Главный обработчик документов"""
    if not message.document:
        return

    document = message.document
    await _process_file(
        bot=message.bot,
        chat_id=message.chat.id,
        file_id=document.file_id,
        file_name=document.file_name,
        reply_to_message_id=message.message_id,
    )

    LAST_FILES[message.from_user.id] = {
        "file_id": document.file_id,
        "file_name": document.file_name,
    }


async def callback_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await cmd_help(callback.message)


async def callback_status(callback: CallbackQuery) -> None:
    await callback.answer()
    await cmd_status(callback.message)


async def callback_regenerate(callback: CallbackQuery) -> None:
    await callback.answer()
    info = LAST_FILES.get(callback.from_user.id)
    if not info:
        await callback.message.answer("⚠️ Нет сохраненного файла. Отправьте резюме заново.")
        return
    PENDING_REGENERATE[callback.from_user.id] = info
    await callback.message.answer(
        "✏️ Отправьте комментарий для нейросети (на что обратить внимание).\n"
        "Или нажмите кнопку ниже, чтобы пересоздать без комментария.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Без комментария", callback_data="regen_no_comment")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="regen_cancel")],
            ]
        ),
    )


async def callback_regen_no_comment(callback: CallbackQuery) -> None:
    await callback.answer()
    info = PENDING_REGENERATE.pop(callback.from_user.id, None) or LAST_FILES.get(callback.from_user.id)
    if not info:
        await callback.message.answer("⚠️ Нет сохраненного файла. Отправьте резюме заново.")
        return
    await _process_file(
        bot=callback.message.bot,
        chat_id=callback.message.chat.id,
        file_id=info["file_id"],
        file_name=info["file_name"],
        reply_to_message_id=callback.message.message_id,
    )


async def callback_regen_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    PENDING_REGENERATE.pop(callback.from_user.id, None)
    await callback.message.answer("Пересоздание отменено.")


async def handle_regenerate_comment(message: Message) -> None:
    info = PENDING_REGENERATE.pop(message.from_user.id, None)
    if not info:
        return
    comment = (message.text or "").strip()
    await message.answer("🔁 Пересоздаю с учетом комментария...")
    await _process_file(
        bot=message.bot,
        chat_id=message.chat.id,
        file_id=info["file_id"],
        file_name=info["file_name"],
        reply_to_message_id=message.message_id,
        user_hint=comment or None,
    )


async def on_error(event: ErrorEvent) -> None:
    """Глобальный обработчик ошибок aiogram"""
    logger.error("Update %s caused error %s", event.update, event.exception, exc_info=True)
    if event.update and event.update.message:
        await event.update.message.answer(
            "❌ Произошла непредвиденная ошибка. Пожалуйста, попробуйте еще раз."
        )


async def main() -> None:
    """Точка входа"""
    if not os.path.exists(JSON_TEMPLATE):
        logger.error("Шаблон %s не найден!", JSON_TEMPLATE)
        sys.exit(1)
    if not os.path.exists(DOCX_TEMPLATE):
        logger.error("Шаблон %s не найден!", DOCX_TEMPLATE)
        sys.exit(1)

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_status, Command("status"))
    dp.message.register(handle_regenerate_comment, F.text)
    dp.message.register(handle_document, F.document)
    dp.callback_query.register(callback_help, F.data == "menu_help")
    dp.callback_query.register(callback_status, F.data == "menu_status")
    dp.callback_query.register(callback_regenerate, F.data == "regenerate")
    dp.callback_query.register(callback_regen_no_comment, F.data == "regen_no_comment")
    dp.callback_query.register(callback_regen_cancel, F.data == "regen_cancel")
    dp.errors.register(on_error)

    logger.info("Бот запущен и готов к работе!")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
