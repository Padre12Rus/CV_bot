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
from aiogram.types import Message, FSInputFile
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


async def cmd_start(message: Message) -> None:
    """Обработчик команды /start"""
    welcome_message = (
        "👋 Привет! Я бот для преобразования резюме в Word документ.\n\n"
        "📤 Отправь PDF или DOCX файл с резюме — я превращу его в структурированный DOCX.\n\n"
        "Процесс обработки:\n"
        "1️⃣ Извлечение текста из файла\n"
        "2️⃣ Структурирование данных через AI\n"
        "3️⃣ Создание Word документа\n\n"
        "⏱️ Обработка может занять до пары минут — пожалуйста, подожди.\n\n"
        "ℹ️ Файлы DOC (старый формат) не поддерживаются, конвертируй их в DOCX."
    )
    await message.answer(welcome_message)


async def cmd_help(message: Message) -> None:
    """Обработчик /help"""
    help_text = (
        "📖 Как работает бот:\n\n"
        "1. Отправь PDF или DOCX файл с резюме\n"
        "2. Дождись завершения цепочки (1–2 минуты)\n"
        "3. Получи готовый DOCX в ответе\n\n"
        "⚠️ Файл должен содержать текст (не только изображения)\n"
        "📝 Бот сам структурирует данные через AI\n"
        "ℹ️ DOC файлы нужно предварительно конвертировать в DOCX\n\n"
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


async def handle_document(message: Message) -> None:
    """Главный обработчик документов"""
    if not message.document:
        return

    document = message.document
    file_name_lower = document.file_name.lower()
    is_pdf = file_name_lower.endswith(".pdf")
    is_docx = file_name_lower.endswith(".docx")
    is_doc = file_name_lower.endswith(".doc")

    if is_doc:
        await message.answer(
            "❌ Файлы в формате DOC не поддерживаются.\n\n"
            "📝 Пожалуйста, конвертируй файл в DOCX перед отправкой.\n\n"
            "💡 Например: открой файл в Word и сохрани как DOCX, либо используй онлайн-конвертер."
        )
        return

    if not (is_pdf or is_docx):
        await message.answer("❌ Отправь файл в формате PDF или DOCX.")
        return

    original_name = Path(document.file_name).stem
    status_message = await message.answer(
        "📥 Файл получен! Начинаю обработку...\n"
        "⏳ Это может занять 1–2 минуты, пожалуйста, подожди."
    )

    bot = message.bot

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            input_file_path = os.path.join(temp_dir, document.file_name)
            await bot.download(document, destination=input_file_path)
            logger.info("Файл скачан: %s", input_file_path)

            file_type = "PDF" if is_pdf else "DOCX"
            await status_message.edit_text(
                f"📥 Файл получен!\n"
                f"🔄 Шаг 1/3: Извлечение текста из {file_type}..."
            )

            output_filename = f"{original_name}.docx"
            md_path = os.path.join(temp_dir, "document.md")
            json_path = os.path.join(temp_dir, "document.json")
            docx_path = os.path.join(temp_dir, output_filename)

            config = ConversionConfig(
                input_file=input_file_path,
                input_kind="pdf" if is_pdf else "docx",
                output_file=docx_path,
                md_path=md_path,
                json_path=json_path,
                json_template=JSON_TEMPLATE,
                docx_template=DOCX_TEMPLATE,
                api_key=None,
                model=None,
                keep_intermediate=False,
            )

            converter = ResumeConverter(config, verbose=False)

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

            async for stage in converter.run_iter_async():
                if stage.name == "cleanup":
                    continue
                if stage.name == "step1" and stage.status == "completed":
                    await status_message.edit_text(
                        "✅ Шаг 1/3 завершен: текст извлечен\n"
                        "🔄 Шаг 2/3: Структурирование данных через AI..."
                    )
                elif stage.name == "step2" and stage.status == "completed":
                    model_info = _build_model_info()
                    await status_message.edit_text(
                        f"✅ Шаг 2/3 завершен: данные структурированы{model_info}\n"
                        "🔄 Шаг 3/3: Создание Word документа..."
                    )
                elif stage.name == "step3" and stage.status == "completed":
                    await status_message.edit_text(
                        "✅ Шаг 3/3 завершен: Word документ создан\n"
                        "📦 Подготавливаю файл к отправке..."
                    )

            result = converter.result
            if not result or not result.output_file:
                raise FileNotFoundError("DOCX файл не был создан")
            docx_path = result.output_file
            if not os.path.exists(docx_path):
                raise FileNotFoundError("DOCX файл не был создан")

            await status_message.edit_text("✅ Обработка завершена! Отправляю файл...")

            await message.answer_document(
                document=FSInputFile(docx_path, filename=output_filename),
                caption=f"✅ Ваш файл готов! Вот преобразованное резюме: {output_filename}",
            )

            await status_message.delete()
            logger.info("Файл успешно обработан для пользователя %s", message.from_user.id)

        except Exception as exc:
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
                await message.answer(error_message, parse_mode=ParseMode.MARKDOWN)


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
    dp.message.register(handle_document, F.document)
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
