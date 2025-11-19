#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram бот для преобразования резюме в Word документ.
Принимает PDF и DOCX файлы, обрабатывает их и возвращает структурированный DOCX.
"""

import os
import sys
import tempfile
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загрузка переменных из .env файла
load_dotenv()

# Импортируем функции из parser.pdf_to_docx
try:
    # Добавляем корневую директорию проекта в путь
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    from parser.pdf_to_docx import step1_pdf_to_md, step1_docx_to_md, step2_md_to_json, step3_json_to_docx
except ImportError as e:
    print(f"Ошибка: не удалось импортировать функции из parser.pdf_to_docx: {e}")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена бота из .env файла
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
    logger.error("Создайте файл .env в корне проекта и добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
    sys.exit(1)

# Пути к шаблонам (относительно корневой директории проекта)
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
JSON_TEMPLATE = str(PROJECT_ROOT / "parser" / "template" / "example.json")
DOCX_TEMPLATE = str(PROJECT_ROOT / "parser" / "template" / "example_cv_docx.docx")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = (
        "👋 Привет! Я бот для преобразования резюме в Word документ.\n\n"
        "📤 Просто отправь мне PDF или DOCX файл с резюме, и я преобразую его в структурированный DOCX формат.\n\n"
        "Процесс обработки:\n"
        "1️⃣ Извлечение текста из файла\n"
        "2️⃣ Структурирование данных через AI\n"
        "3️⃣ Создание Word документа\n\n"
        "⏱️ Обработка может занять некоторое время, пожалуйста, подожди.\n\n"
        "ℹ️ Если у тебя файл в формате DOC, пожалуйста, конвертируй его в DOCX перед отправкой."
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "📖 Справка по использованию бота:\n\n"
        "1. Отправь PDF или DOCX файл с резюме\n"
        "2. Дождись обработки (может занять 1-2 минуты)\n"
        "3. Получи готовый DOCX файл с тем же именем\n\n"
        "⚠️ Убедись, что файл содержит текст (не только изображения)\n"
        "📝 Бот автоматически извлекает и структурирует данные из резюме\n\n"
        "ℹ️ Файлы в формате DOC не поддерживаются. Пожалуйста, конвертируй DOC в DOCX перед отправкой.\n\n"
        "💡 Используй команду /status для просмотра информации о моделях AI"
    )
    await update.message.reply_text(help_text)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /status - показывает информацию о моделях AI"""
    try:
        from parser.ai_provider import get_models_info, get_last_used_provider
        
        models_info = get_models_info()
        last_used = get_last_used_provider()
        
        status_text = "🤖 Информация о AI моделях:\n\n"
        
        # Информация о Gemini
        gemini_status = "✅" if models_info['gemini']['available'] else "❌"
        status_text += f"{gemini_status} **Gemini:**\n"
        status_text += f"   Модель: `{models_info['gemini']['model']}`\n"
        status_text += f"   Ключ: {'Установлен' if models_info['gemini']['api_key_set'] else 'Не установлен'}\n\n"
        
        # Информация о OpenRouter
        openrouter_status = "✅" if models_info['openrouter']['available'] else "❌"
        status_text += f"{openrouter_status} **OpenRouter:**\n"
        status_text += f"   Модель: `{models_info['openrouter']['model']}`\n"
        status_text += f"   Ключ: {'Установлен' if models_info['openrouter']['api_key_set'] else 'Не установлен'}\n\n"
        
        # Основной провайдер
        if models_info['primary_provider']:
            provider_name = "Gemini" if models_info['primary_provider'] == 'gemini' else "OpenRouter"
            status_text += f"🎯 **Основной провайдер:** {provider_name}\n"
        
        # Fallback
        if models_info['fallback_enabled']:
            status_text += "🔄 **Автоматическое переключение:** Включено\n"
        else:
            status_text += "⚠️ **Автоматическое переключение:** Отключено (установите оба ключа)\n"
        
        # Последняя использованная модель
        if last_used:
            provider_name = "Gemini" if last_used['provider'] == 'gemini' else "OpenRouter"
            status_text += f"\n📊 **Последняя использованная модель:**\n"
            status_text += f"   Провайдер: {provider_name}\n"
            status_text += f"   Модель: `{last_used['model']}`\n"
        else:
            status_text += "\n📊 **Последняя использованная модель:** Еще не использовалась\n"
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Ошибка при получении информации о моделях: {str(e)}"
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик PDF и DOCX документов"""
    document = update.message.document
    
    # Проверка типа файла
    file_name_lower = document.file_name.lower()
    is_pdf = file_name_lower.endswith('.pdf')
    is_docx = file_name_lower.endswith('.docx')
    is_doc = file_name_lower.endswith('.doc')
    
    # Если это DOC файл, просим пользователя конвертировать
    if is_doc:
        await update.message.reply_text(
            "❌ Файлы в формате DOC не поддерживаются.\n\n"
            "📝 Пожалуйста, конвертируй файл в DOCX перед отправкой.\n\n"
            "💡 Как конвертировать:\n"
            "• Открой файл в Microsoft Word и сохрани как DOCX\n"
            "• Или используй онлайн-конвертер (например, zamzar.com, convertio.co)"
        )
        return
    
    if not (is_pdf or is_docx):
        await update.message.reply_text(
            "❌ Пожалуйста, отправь PDF или DOCX файл. Другие форматы не поддерживаются."
        )
        return
    
    # Сохраняем оригинальное имя файла (без расширения)
    original_name = Path(document.file_name).stem
    
    # Отправка сообщения о начале обработки
    status_message = await update.message.reply_text(
        "📥 Файл получен! Начинаю обработку...\n"
        "⏳ Это может занять 1-2 минуты, пожалуйста, подожди."
    )
    
    # Создание временной директории для работы
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Скачивание файла
            input_file_path = os.path.join(temp_dir, document.file_name)
            file = await context.bot.get_file(document.file_id)
            await file.download_to_drive(custom_path=input_file_path)
            
            logger.info(f"Файл скачан: {input_file_path}")
            
            # Обновление статуса
            file_type = "PDF" if is_pdf else "DOCX"
            await status_message.edit_text(
                f"📥 Файл получен!\n"
                f"🔄 Шаг 1/3: Извлечение текста из {file_type}..."
            )
            
            # Шаг 1: PDF/DOCX -> MD
            md_path = os.path.join(temp_dir, "document.md")
            if is_pdf:
                step1_pdf_to_md(input_file_path, md_path, verbose=False)
            else:  # is_docx
                step1_docx_to_md(input_file_path, md_path, verbose=False)
            
            # Обновление статуса
            await status_message.edit_text(
                "✅ Шаг 1/3 завершен: Текст извлечен\n"
                "🔄 Шаг 2/3: Структурирование данных через AI..."
            )
            
            # Шаг 2: MD -> JSON
            json_path = os.path.join(temp_dir, "document.json")
            step2_md_to_json(
                md_path,
                json_path,
                JSON_TEMPLATE,
                api_key=None,  # Использует переменную окружения
                model=None,    # Использует модель по умолчанию
                verbose=False
            )
            
            # Получаем информацию о последней использованной модели
            try:
                from parser.ai_provider import get_last_used_provider
                last_used = get_last_used_provider()
                if last_used:
                    provider_name = "Gemini" if last_used['provider'] == 'gemini' else "OpenRouter"
                    model_info = f"\n🤖 Использована модель: {provider_name} ({last_used['model']})"
                else:
                    model_info = ""
            except:
                model_info = ""
            
            # Обновление статуса
            await status_message.edit_text(
                f"✅ Шаг 2/3 завершен: Данные структурированы{model_info}\n"
                "🔄 Шаг 3/3: Создание Word документа..."
            )
            
            # Шаг 3: JSON -> DOCX
            # Используем оригинальное имя файла для результата
            output_filename = f"{original_name}.docx"
            docx_path = os.path.join(temp_dir, output_filename)
            step3_json_to_docx(
                json_path,
                docx_path,
                DOCX_TEMPLATE,
                verbose=False
            )
            
            # Проверка существования файла
            if not os.path.exists(docx_path):
                raise FileNotFoundError("DOCX файл не был создан")
            
            # Отправка готового файла
            await status_message.edit_text("✅ Обработка завершена! Отправляю файл...")
            
            with open(docx_path, 'rb') as docx_file:
                await update.message.reply_document(
                    document=docx_file,
                    filename=output_filename,
                    caption=f"✅ Ваш файл готов! Вот преобразованное резюме: {output_filename}"
                )
            
            # Удаление статусного сообщения
            await status_message.delete()
            
            logger.info(f"Файл успешно обработан для пользователя {update.effective_user.id}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке файла: {e}", exc_info=True)
            error_message = (
                f"❌ Произошла ошибка при обработке файла:\n\n"
                f"`{str(e)}`\n\n"
                f"Пожалуйста, убедись, что:\n"
                f"• Файл содержит текст (не только изображения)\n"
                f"• Файл не поврежден\n"
                f"• Установлен GEMINI_API_KEY для работы AI"
            )
            try:
                await status_message.edit_text(error_message, parse_mode='Markdown')
            except:
                await update.message.reply_text(error_message, parse_mode='Markdown')


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.message:
        await update.message.reply_text(
            "❌ Произошла непредвиденная ошибка. Пожалуйста, попробуй еще раз."
        )


def main():
    """Основная функция запуска бота"""
    # Проверка наличия шаблонов
    if not os.path.exists(JSON_TEMPLATE):
        logger.error(f"Шаблон {JSON_TEMPLATE} не найден!")
        sys.exit(1)
    
    if not os.path.exists(DOCX_TEMPLATE):
        logger.error(f"Шаблон {DOCX_TEMPLATE} не найден!")
        sys.exit(1)
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    # Обработчик для всех документов (проверка типа файла внутри функции)
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_error_handler(error_handler)
    
    # Запуск бота
    logger.info("Бот запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

