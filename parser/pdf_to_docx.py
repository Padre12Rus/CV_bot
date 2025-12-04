#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Мастер-скрипт для преобразования PDF резюме в Word документ.
Выполняет всю цепочку: PDF -> MD -> JSON -> DOCX
"""

import sys
import os
import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Literal, AsyncIterator


@dataclass
class ConversionConfig:
    """Параметры для конвертации резюме."""

    input_file: str
    input_kind: Literal["pdf", "docx"] = "pdf"
    output_file: Optional[str] = None
    md_path: Optional[str] = None
    json_path: Optional[str] = None
    json_template: str = "parser/template/example.json"
    docx_template: str = "parser/template/example_cv_docx.docx"
    api_key: Optional[str] = None
    model: Optional[str] = None
    keep_intermediate: bool = False
    skip_step1: bool = False
    skip_step2: bool = False
    skip_step3: bool = False
    # Новый режим: прямой проход файла через Gemini (без промежуточного MD)
    use_direct_file_mode: bool = False
    # Дополнительные пожелания пользователя к модели
    user_hint: Optional[str] = None


@dataclass
class ConversionStage:
    """Информация о завершенном этапе конвертации."""

    name: str
    status: str
    path: Optional[str] = None
    message: Optional[str] = None


@dataclass
class ConversionResult:
    """Результат выполнения всей цепочки конвертации."""

    input_file: str
    output_file: Optional[str]
    md_file: Optional[str]
    json_file: Optional[str]
    deleted_files: List[str]
    kept_intermediate: bool


class ResumeConverter:
    """Запускает конвертацию и отслеживает промежуточные файлы."""

    def __init__(self, config: ConversionConfig, verbose: bool = True):
        self.config = config
        self.verbose = verbose
        self._input_path = Path(config.input_file)

        if not self._input_path.exists():
            raise FileNotFoundError(f"Файл '{config.input_file}' не найден.")
        if config.input_kind not in ("pdf", "docx"):
            raise ValueError("Поддерживаются только входные типы 'pdf' и 'docx'.")

        self.md_path = config.md_path or str(self._input_path.with_suffix('.md'))
        self.json_path = config.json_path or str(self._input_path.with_suffix('.json'))
        default_docx = self._input_path.with_name(f"{self._input_path.stem}_filled.docx")
        self.docx_path = config.output_file or str(default_docx)

        self._created_files = {'md': False, 'json': False}
        self._removed_files: List[str] = []
        self.result: Optional[ConversionResult] = None

    def run_iter(self) -> Iterator[ConversionStage]:
        """Выполняет конвертацию и выдает этапы по мере завершения."""
        try:
            yield self._run_step1()
            yield self._run_step2()
            yield self._run_step3()
            cleanup_stage = self._cleanup()
            if cleanup_stage:
                yield cleanup_stage

            self.result = ConversionResult(
                input_file=str(self._input_path),
                output_file=None if self.config.skip_step3 else self.docx_path,
                md_file=self.md_path,
                json_file=self.json_path,
                deleted_files=list(self._removed_files),
                kept_intermediate=self.config.keep_intermediate
            )
        except Exception:
            self._cleanup_on_error()
            raise

    def run(self) -> ConversionResult:
        """Запускает конвертацию без промежуточных уведомлений."""
        for _ in self.run_iter():
            pass
        if not self.result:
            raise RuntimeError("Конвертация не вернула результат")
        return self.result

    async def run_iter_async(self) -> AsyncIterator[ConversionStage]:
        """Асинхронно выполняет конвертацию, отдавая этапы по мере завершения."""
        try:
            stage = await asyncio.to_thread(self._run_step1)
            yield stage

            stage = await asyncio.to_thread(self._run_step2)
            yield stage

            stage = await asyncio.to_thread(self._run_step3)
            yield stage

            cleanup_stage = await asyncio.to_thread(self._cleanup)
            if cleanup_stage:
                yield cleanup_stage

            self.result = ConversionResult(
                input_file=str(self._input_path),
                output_file=None if self.config.skip_step3 else self.docx_path,
                md_file=self.md_path,
                json_file=self.json_path,
                deleted_files=list(self._removed_files),
                kept_intermediate=self.config.keep_intermediate
            )
        except Exception:
            await asyncio.to_thread(self._cleanup_on_error)
            raise

    async def run_async(self) -> ConversionResult:
        """Асинхронно выполняет конвертацию без получения этапов."""
        async for _ in self.run_iter_async():
            pass
        if not self.result:
            raise RuntimeError("Конвертация не вернула результат")
        return self.result

    def _run_step1(self) -> ConversionStage:
        cfg = self.config
        # В прямом файловом режиме шаг 1 (PDF/DOCX -> MD) не нужен вообще
        if getattr(cfg, "use_direct_file_mode", False):
            # Не трогаем md_path, не создаём промежуточные файлы
            return ConversionStage(
                name="step1",
                status="skipped",
                path=str(self._input_path),
                message="Шаг 1 пропущен: используется прямой режим обработки файла через Gemini"
            )

        if cfg.skip_step1:
            if not self.md_path or not os.path.exists(self.md_path):
                raise FileNotFoundError(
                    f"Файл '{self.md_path}' не найден (--skip-step1 указан, но файл отсутствует)."
                )
            return ConversionStage(
                name="step1",
                status="skipped",
                path=self.md_path,
                message="Используется существующий Markdown файл"
            )

        if cfg.input_kind == "docx":
            self.md_path = step1_docx_to_md(cfg.input_file, self.md_path, verbose=self.verbose)
        else:
            self.md_path = step1_pdf_to_md(cfg.input_file, self.md_path, verbose=self.verbose)
        self._created_files['md'] = True
        return ConversionStage(
            name="step1",
            status="completed",
            path=self.md_path,
            message="Markdown файл создан"
        )

    def _run_step2(self) -> ConversionStage:
        cfg = self.config
        if cfg.skip_step2:
            if not self.json_path or not os.path.exists(self.json_path):
                raise FileNotFoundError(
                    f"Файл '{self.json_path}' не найден (--skip-step2 указан, но файл отсутствует)."
                )
            return ConversionStage(
                name="step2",
                status="skipped",
                path=self.json_path,
                message="Используется существующий JSON файл"
            )
        
        # Новый режим: прямое использование файла без промежуточного Markdown
        if cfg.use_direct_file_mode:
            self.json_path = step2_file_to_json(
                input_file=str(self._input_path),
                input_kind=cfg.input_kind,
                json_path=self.json_path,
                json_template=cfg.json_template,
                api_key=cfg.api_key,
                model=cfg.model,
                verbose=self.verbose,
                user_hint=cfg.user_hint,
            )
        else:
            # Старый режим: через промежуточный MD-файл
            self.json_path = step2_md_to_json(
                self.md_path,
                self.json_path,
                cfg.json_template,
                cfg.api_key,
                cfg.model,
                verbose=self.verbose,
                user_hint=cfg.user_hint,
            )
        self._created_files['json'] = True
        return ConversionStage(
            name="step2",
            status="completed",
            path=self.json_path,
            message="JSON файл создан"
        )

    def _run_step3(self) -> ConversionStage:
        cfg = self.config
        if cfg.skip_step3:
            return ConversionStage(
                name="step3",
                status="skipped",
                message="Шаг 3 пропущен, Word файл не создается"
            )

        self.docx_path = step3_json_to_docx(
            self.json_path,
            self.docx_path,
            cfg.docx_template,
            verbose=self.verbose
        )
        return ConversionStage(
            name="step3",
            status="completed",
            path=self.docx_path,
            message="DOCX файл создан"
        )

    def _cleanup(self) -> Optional[ConversionStage]:
        removed = self._remove_intermediate_files()
        self._removed_files = removed
        if removed:
            return ConversionStage(
                name="cleanup",
                status="completed",
                message="Удалены промежуточные файлы: " + ", ".join(removed)
            )
        return None

    def _cleanup_on_error(self) -> None:
        if self.config.keep_intermediate:
            return
        self._removed_files = self._remove_intermediate_files()

    def _remove_intermediate_files(self) -> List[str]:
        if self.config.keep_intermediate:
            return []
        removed = []
        if self._created_files.get('md') and self.md_path and os.path.exists(self.md_path):
            os.remove(self.md_path)
            removed.append(self.md_path)
        if self._created_files.get('json') and self.json_path and os.path.exists(self.json_path):
            os.remove(self.json_path)
            removed.append(self.json_path)
        return removed


def convert_resume(config: ConversionConfig, verbose: bool = True) -> ConversionResult:
    """Запускает полную конвертацию и возвращает результат."""

    converter = ResumeConverter(config, verbose=verbose)
    return converter.run()

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
        create_extraction_prompt,
        create_extraction_prompt_for_file,
        merge_with_template,
        save_json,
        get_api_key,
        DEFAULT_GEMINI_MODEL,
    )
except ImportError:
    try:
        from md_to_json import (
            read_file as read_md_file,
            load_json_template,
            process_with_gemini,
            create_extraction_prompt,
            create_extraction_prompt_for_file,
            merge_with_template,
            save_json,
            get_api_key,
            DEFAULT_GEMINI_MODEL,
        )
    except ImportError:
        print("Ошибка: не удалось импортировать функции из md_to_json")
        sys.exit(1)

try:
    from .ai_provider import (
        AIProviderError,
        process_file_with_gemini,
        process_with_fallback,
        get_api_keys,
    )
except ImportError:
    try:
        from ai_provider import (
            AIProviderError,
            process_file_with_gemini,
            process_with_fallback,
            get_api_keys,
        )
    except ImportError:
        print("Ошибка: не удалось импортировать функции из ai_provider")
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
                     api_key=None, model=None, verbose=True, user_hint=None):
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
        model,
        user_hint=user_hint,
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


def step2_file_to_json(
    input_file,
    input_kind="pdf",
    json_path=None,
    json_template="parser/template/example.json",
    api_key=None,
    model=None,
    verbose=True,
    user_hint=None,
):
    """
    Альтернативный шаг 2: прямое преобразование файла (PDF/DOCX) в JSON через Gemini.
    При ошибке или отсутствии Gemini — fallback на текстовый режим (Gemini/OpenRouter).
    """
    if verbose:
        print("\n" + "=" * 60)
        print("ШАГ 2 (direct): Преобразование файла -> JSON (Gemini)")
        print("=" * 60)
    
    # Получение правильного пути к шаблону
    json_template = get_template_path(json_template)
    
    # Проверка шаблона
    if not os.path.exists(json_template):
        msg = f"Ошибка: шаблон '{json_template}' не найден."
        print(msg)
        raise FileNotFoundError(msg)
    
    # Определение пути к выходному файлу
    if not json_path:
        in_file = Path(input_file)
        json_path = in_file.with_suffix('.json')
    
    if verbose:
        print(f"Входной файл: {input_file} ({input_kind})")
        print(f"Шаблон: {json_template}")
        print(f"Выходной файл: {json_path}")
    
    # Загрузка шаблона
    if verbose:
        print(f"Загрузка шаблона: {json_template}")
    json_template_data = load_json_template(json_template)
    
    # Получаем ключи из окружения / .env
    env_keys = get_api_keys()
    gemini_key = api_key or env_keys.get("gemini")
    openrouter_key = env_keys.get("openrouter")
    
    final_data = None
    
    # 1. Прямая попытка: Gemini + файл
    if gemini_key:
        try:
            if verbose:
                print("Попытка прямой обработки файла через Gemini (без MD)...")
            final_data = process_file_with_gemini(
                file_path=input_file,
                json_template=json_template_data,
                prompt_creator_func=create_extraction_prompt_for_file,
                gemini_api_key=gemini_key,
                gemini_model=model,
                verbose=verbose,
                user_hint=user_hint,
            )
        except AIProviderError as e:
            if verbose:
                print(f"⚠️  Ошибка прямой обработки файла через Gemini: {e}")
                print("    Переход к текстовому режиму (fallback)...")
    
    # 2. Fallback: извлекаем текст и используем общий провайдер (Gemini/OpenRouter)
    if final_data is None:
        if verbose:
            print("Извлечение текста из файла для текстового режима...")
        if input_kind == "docx":
            text_content = extract_text_from_docx(input_file)
        else:
            text_content = extract_text_from_pdf(input_file)
        
        if not text_content.strip():
            print("⚠️  Предупреждение: не удалось извлечь текст из файла для fallback-режима.")
        
        if verbose:
            print("Обработка через AI-провайдер (Gemini/OpenRouter) в текстовом режиме...")
        
        if not gemini_key and not openrouter_key:
            raise AIProviderError(
                "Не найден ни один API ключ для текстового режима. "
                "Установите GEMINI_API_KEY или OPENROUTER_API_KEY."
            )
        
        final_data = process_with_fallback(
            markdown_content=text_content,
            json_template=json_template_data,
            prompt_creator_func=create_extraction_prompt,
            gemini_api_key=gemini_key,
            openrouter_api_key=openrouter_key,
            gemini_model=model,
            verbose=verbose,
            user_hint=user_hint,
        )
    
    # Сохранение результата
    save_json(final_data, json_path)
    
    if verbose:
        print(f"✅ Шаг 2 (direct) завершен: {json_path}")
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
    
    config = ConversionConfig(
        input_file=args.pdf_file,
        input_kind="pdf",
        output_file=docx_path,
        md_path=md_path,
        json_path=json_path,
        json_template=args.json_template,
        docx_template=args.docx_template,
        api_key=args.api_key,
        model=args.model,
        keep_intermediate=args.keep_intermediate,
        skip_step1=args.skip_step1,
        skip_step2=args.skip_step2,
        skip_step3=args.skip_step3,
    )

    converter = ResumeConverter(config, verbose=True)

    try:
        for stage in converter.run_iter():
            if stage.name == "cleanup" and stage.message:
                print(f"\n🗑️  {stage.message}")
            elif stage.status == "skipped":
                if stage.name == "step1" and stage.path:
                    print(f"\n⏭️  Пропущен шаг 1, используется существующий файл: {stage.path}")
                elif stage.name == "step2" and stage.path:
                    print(f"\n⏭️  Пропущен шаг 2, используется существующий файл: {stage.path}")
                elif stage.name == "step3":
                    print("\n⏭️  Пропущен шаг 3")

        result = converter.result
        if not result:
            raise RuntimeError("Не удалось получить результат конвертации")

        print("\n" + "="*60)
        if result.output_file:
            print("✅ ПРЕОБРАЗОВАНИЕ ЗАВЕРШЕНО УСПЕШНО!")
            print("="*60)
            print(f"📄 Результат сохранен в: {result.output_file}")
        else:
            print("ℹ️  Конвертация завершена без создания Word файла (шаг 3 пропущен)")
            print("="*60)

        if args.keep_intermediate:
            print("📝 Промежуточные файлы сохранены:")
            if not args.skip_step1 and result.md_file:
                print(f"   - {result.md_file}")
            if not args.skip_step2 and result.json_file:
                print(f"   - {result.json_file}")
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
