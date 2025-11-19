#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Мастер-скрипт для преобразования PDF резюме в Word документ.
Выполняет всю цепочку: PDF -> MD -> JSON -> DOCX
"""

import sys
import os
import argparse
from pathlib import Path

# Функция для получения правильного пути к шаблону
def get_template_path(template_path):
    """
    Получает абсолютный путь к шаблону.
    Если путь относительный, ищет его относительно корня проекта или директории скрипта.
    
    Args:
        template_path (str): Путь к шаблону (может быть относительным или абсолютным)
        
    Returns:
        str: Абсолютный путь к шаблону
    """
    if os.path.isabs(template_path) and os.path.exists(template_path):
        return template_path
    
    # Пробуем относительно текущей директории
    if os.path.exists(template_path):
        return os.path.abspath(template_path)
    
    # Пробуем относительно директории скрипта
    script_dir = Path(__file__).parent.absolute()
    script_template = script_dir / template_path
    if script_template.exists():
        return str(script_template)
    
    # Пробуем относительно корня проекта (на уровень выше parser)
    project_root = script_dir.parent
    project_template = project_root / template_path
    if project_template.exists():
        return str(project_template)
    
    # Если ничего не найдено, возвращаем исходный путь (будет ошибка при проверке)
    return template_path

# Импортируем функции из других модулей пакета parser
# Поддержка как относительных импортов (при импорте как модуль), так и абсолютных (при прямом запуске)
try:
    from .pdf_to_md import extract_text_from_pdf, extract_text_from_docx, save_to_markdown
except ImportError:
    try:
        from pdf_to_md import extract_text_from_pdf, extract_text_from_docx, save_to_markdown
    except ImportError:
        print("Ошибка: не удалось импортировать функции из pdf_to_md")
        sys.exit(1)

try:
    from .md_to_json import (
        read_file as read_md_file,
        load_json_template,
        process_with_gemini,
        merge_with_template,
        save_json,
        get_api_key,
        DEFAULT_GEMINI_MODEL
    )
except ImportError:
    try:
        from md_to_json import (
            read_file as read_md_file,
            load_json_template,
            process_with_gemini,
            merge_with_template,
            save_json,
            get_api_key,
            DEFAULT_GEMINI_MODEL
        )
    except ImportError:
        print("Ошибка: не удалось импортировать функции из md_to_json")
        sys.exit(1)

try:
    from .json_to_docx import load_json, fill_document
except ImportError:
    try:
        from json_to_docx import load_json, fill_document
    except ImportError:
        print("Ошибка: не удалось импортировать функции из json_to_docx")
        sys.exit(1)


def step1_pdf_to_md(pdf_path, md_path=None, verbose=True):
    """
    Шаг 1: Преобразование PDF в Markdown.
    
    Args:
        pdf_path (str): Путь к PDF файлу
        md_path (str): Путь к выходному MD файлу (опционально)
        verbose (bool): Выводить ли информацию о процессе
        
    Returns:
        str: Путь к созданному MD файлу
    """
    if verbose:
        print("\n" + "="*60)
        print("ШАГ 1: Преобразование PDF -> Markdown")
        print("="*60)
    
    # Определение пути к выходному файлу
    if not md_path:
        pdf_file = Path(pdf_path)
        md_path = pdf_file.with_suffix('.md')
    
    if verbose:
        print(f"Входной файл: {pdf_path}")
        print(f"Выходной файл: {md_path}")
    
    # Извлечение текста
    text = extract_text_from_pdf(pdf_path)
    
    if not text.strip():
        print("⚠️  Предупреждение: не удалось извлечь текст из PDF файла.")
        print("Возможно, PDF файл содержит только изображения или защищен от копирования.")
    
    # Сохранение в Markdown
    save_to_markdown(text, md_path)
    
    if verbose:
        print(f"✅ Шаг 1 завершен: {md_path}")
    
    return str(md_path)


def step1_docx_to_md(docx_path, md_path=None, verbose=True):
    """
    Шаг 1: Преобразование DOCX в Markdown.
    
    Args:
        docx_path (str): Путь к DOCX файлу
        md_path (str): Путь к выходному MD файлу (опционально)
        verbose (bool): Выводить ли информацию о процессе
        
    Returns:
        str: Путь к созданному MD файлу
    """
    if verbose:
        print("\n" + "="*60)
        print("ШАГ 1: Преобразование DOCX -> Markdown")
        print("="*60)
    
    # Определение пути к выходному файлу
    if not md_path:
        docx_file = Path(docx_path)
        md_path = docx_file.with_suffix('.md')
    
    if verbose:
        print(f"Входной файл: {docx_path}")
        print(f"Выходной файл: {md_path}")
    
    # Извлечение текста
    text = extract_text_from_docx(docx_path)
    
    if not text.strip():
        print("⚠️  Предупреждение: не удалось извлечь текст из DOCX файла.")
        print("Возможно, DOCX файл пуст или поврежден.")
    
    # Сохранение в Markdown
    save_to_markdown(text, md_path)
    
    if verbose:
        print(f"✅ Шаг 1 завершен: {md_path}")
    
    return str(md_path)


def step2_md_to_json(md_path, json_path=None, json_template="parser/template/example.json", 
                     api_key=None, model=None, verbose=True):
    """
    Шаг 2: Преобразование Markdown в JSON.
    
    Args:
        md_path (str): Путь к MD файлу
        json_path (str): Путь к выходному JSON файлу (опционально)
        json_template (str): Путь к JSON шаблону
        api_key (str): API ключ Gemini (опционально)
        model (str): Имя модели (опционально)
        verbose (bool): Выводить ли информацию о процессе
        
    Returns:
        str: Путь к созданному JSON файлу
    """
    if verbose:
        print("\n" + "="*60)
        print("ШАГ 2: Преобразование Markdown -> JSON")
        print("="*60)
    
    # Получение правильного пути к шаблону
    json_template = get_template_path(json_template)
    
    # Проверка шаблона
    if not os.path.exists(json_template):
        # В библиотечном режиме (когда вызывается из бота) не завершаем процесс,
        # а сообщаем об ошибке через исключение.
        msg = f"Ошибка: шаблон '{json_template}' не найден."
        print(msg)
        raise FileNotFoundError(msg)
    
    # Определение пути к выходному файлу
    if not json_path:
        md_file = Path(md_path)
        json_path = md_file.with_suffix('.json')
    
    if verbose:
        print(f"Входной файл: {md_path}")
        print(f"Шаблон: {json_template}")
        print(f"Выходной файл: {json_path}")
    
    # Загрузка шаблона
    if verbose:
        print(f"Загрузка шаблона: {json_template}")
    json_template_data = load_json_template(json_template)
    
    # Чтение MD файла
    if verbose:
        print(f"Чтение файла: {md_path}")
    markdown_content = read_md_file(md_path)
    if verbose:
        print(f"Размер файла: {len(markdown_content)} символов")
    
    # Получение API ключа
    if not api_key:
        api_key = get_api_key()
    
    if not model:
        model = DEFAULT_GEMINI_MODEL
    
    # Обработка через API
    if verbose:
        print("Обработка через Gemini API...")
    extracted_data = process_with_gemini(
        markdown_content,
        json_template_data,
        api_key,
        model
    )
    
    # Объединение с шаблоном
    final_data = merge_with_template(extracted_data, json_template_data)
    
    # Сохранение результата
    save_json(final_data, json_path)
    
    if verbose:
        print(f"✅ Шаг 2 завершен: {json_path}")
        print(f"\n📊 Статистика извлеченных данных:")
        print(f"  - Опыт работы: {len(final_data.get('work_experience', []))} записей")
        print(f"  - Проекты: {len(final_data.get('project_experience', []))} записей")
        skills_count = len(final_data.get('general_info', {}).get('skills_and_tools', []))
        print(f"  - Навыки: {skills_count} записей")
    
    return str(json_path)


def step3_json_to_docx(json_path, docx_path=None, docx_template="parser/template/example_cv_docx.docx", verbose=True):
    """
    Шаг 3: Преобразование JSON в Word документ.
    
    Args:
        json_path (str): Путь к JSON файлу
        docx_path (str): Путь к выходному DOCX файлу (опционально)
        docx_template (str): Путь к шаблону Word
        verbose (bool): Выводить ли информацию о процессе
        
    Returns:
        str: Путь к созданному DOCX файлу
    """
    if verbose:
        print("\n" + "="*60)
        print("ШАГ 3: Преобразование JSON -> Word")
        print("="*60)
    
    # Получение правильного пути к шаблону
    docx_template = get_template_path(docx_template)
    
    # Проверка шаблона
    if not os.path.exists(docx_template):
        msg = f"Ошибка: шаблон '{docx_template}' не найден."
        print(msg)
        raise FileNotFoundError(msg)
    
    # Определение пути к выходному файлу
    if not docx_path:
        json_file = Path(json_path)
        docx_path = json_file.stem + "_filled.docx"
    
    if verbose:
        print(f"Входной файл: {json_path}")
        print(f"Шаблон: {docx_template}")
        print(f"Выходной файл: {docx_path}")
    
    # Загрузка JSON
    if verbose:
        print(f"Загрузка JSON: {json_path}")
    json_data = load_json(json_path)
    
    # Заполнение документа
    fill_document(docx_template, json_data, docx_path)
    
    if verbose:
        print(f"✅ Шаг 3 завершен: {docx_path}")
    
    return str(docx_path)


def main():
    """Основная функция."""
    parser = argparse.ArgumentParser(
        description="Преобразование PDF резюме в Word документ через всю цепочку (Gemini)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python pdf_to_docx.py resume.pdf
  python pdf_to_docx.py resume.pdf --output result.docx
  python pdf_to_docx.py resume.pdf --model gemini-1.5-flash
  python pdf_to_docx.py resume.pdf --keep-intermediate --output result.docx

Процесс:
  1. PDF -> Markdown (извлечение текста)
  2. Markdown -> JSON (структурирование через LLM)
  3. JSON -> Word (заполнение шаблона)

Промежуточные файлы (MD и JSON) сохраняются, если указан --keep-intermediate.
        """
    )
    
    parser.add_argument("pdf_file", help="Путь к PDF файлу с резюме")
    parser.add_argument(
        "--output", "-o",
        help="Путь к выходному Word файлу (по умолчанию: <имя_pdf>_filled.docx)"
    )
    parser.add_argument(
        "--json-template", "-jt",
        default="parser/template/example.json",
        help="Путь к JSON шаблону (по умолчанию: parser/template/example.json)"
    )
    parser.add_argument(
        "--docx-template", "-dt",
        default="parser/template/example_cv_docx.docx",
        help="Путь к Word шаблону (по умолчанию: parser/template/example_cv_docx.docx)"
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_GEMINI_MODEL,
        help=f"Имя модели Gemini (по умолчанию: {DEFAULT_GEMINI_MODEL})"
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API ключ (или используйте переменную GEMINI_API_KEY)"
    )
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Сохранить промежуточные файлы (MD и JSON)"
    )
    parser.add_argument(
        "--skip-step1",
        action="store_true",
        help="Пропустить шаг 1 (PDF -> MD), использовать существующий MD файл"
    )
    parser.add_argument(
        "--skip-step2",
        action="store_true",
        help="Пропустить шаг 2 (MD -> JSON), использовать существующий JSON файл"
    )
    parser.add_argument(
        "--skip-step3",
        action="store_true",
        help="Пропустить шаг 3 (JSON -> DOCX)"
    )
    
    args = parser.parse_args()
    
    # Проверка входного файла
    if not os.path.exists(args.pdf_file):
        print(f"Ошибка: файл '{args.pdf_file}' не найден.")
        sys.exit(1)
    
    # Определение базового имени для файлов
    pdf_file = Path(args.pdf_file)
    base_name = pdf_file.stem
    
    # Определение путей к промежуточным файлам
    md_path = base_name + ".md"
    json_path = base_name + ".json"
    
    # Определение пути к выходному файлу
    if args.output:
        docx_path = args.output
    else:
        docx_path = base_name + "_filled.docx"
    
    print("\n" + "="*60)
    print("ПРЕОБРАЗОВАНИЕ PDF -> DOCX")
    print("="*60)
    print(f"Входной файл: {args.pdf_file}")
    print(f"Выходной файл: {docx_path}")
    print("="*60)
    
    try:
        # Шаг 1: PDF -> MD
        if not args.skip_step1:
            md_path = step1_pdf_to_md(args.pdf_file, md_path, verbose=True)
        else:
            if not os.path.exists(md_path):
                print(f"Ошибка: файл '{md_path}' не найден (--skip-step1 указан, но файл отсутствует).")
                sys.exit(1)
            print(f"\n⏭️  Пропущен шаг 1, используется существующий файл: {md_path}")
        
        # Шаг 2: MD -> JSON
        if not args.skip_step2:
            json_path = step2_md_to_json(
                md_path,
                json_path,
                args.json_template,
                args.api_key,
                args.model,
                verbose=True
            )
        else:
            if not os.path.exists(json_path):
                print(f"Ошибка: файл '{json_path}' не найден (--skip-step2 указан, но файл отсутствует).")
                sys.exit(1)
            print(f"\n⏭️  Пропущен шаг 2, используется существующий файл: {json_path}")
        
        # Шаг 3: JSON -> DOCX
        if not args.skip_step3:
            docx_path = step3_json_to_docx(
                json_path,
                docx_path,
                args.docx_template,
                verbose=True
            )
        else:
            print(f"\n⏭️  Пропущен шаг 3")
        
        # Удаление промежуточных файлов, если не указано --keep-intermediate
        if not args.keep_intermediate:
            if not args.skip_step1 and os.path.exists(md_path):
                os.remove(md_path)
                print(f"\n🗑️  Удален промежуточный файл: {md_path}")
            if not args.skip_step2 and os.path.exists(json_path):
                os.remove(json_path)
                print(f"🗑️  Удален промежуточный файл: {json_path}")
        
        print("\n" + "="*60)
        print("✅ ПРЕОБРАЗОВАНИЕ ЗАВЕРШЕНО УСПЕШНО!")
        print("="*60)
        print(f"📄 Результат сохранен в: {docx_path}")
        if args.keep_intermediate:
            print(f"📝 Промежуточные файлы сохранены:")
            if not args.skip_step1:
                print(f"   - {md_path}")
            if not args.skip_step2:
                print(f"   - {json_path}")
        print("="*60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Преобразование прервано пользователем.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка при преобразовании: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

