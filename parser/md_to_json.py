#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для преобразования Markdown резюме в JSON формат.
Использует структуру из example.json как шаблон.
"""

import sys
import os
import json
import argparse
from pathlib import Path

try:
    from google import genai
except ImportError:
    print("Ошибка: библиотека google-genai не установлена.")
    print("Установите её командой: pip install google-genai")
    sys.exit(1)


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def read_file(file_path):
    """
    Читает содержимое файла.
    
    Args:
        file_path (str): Путь к файлу
        
    Returns:
        str: Содержимое файла
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Ошибка при чтении файла {file_path}: {e}")
        sys.exit(1)


def load_json_template(template_path):
    """
    Загружает JSON шаблон.
    
    Args:
        template_path (str): Путь к JSON шаблону
        
    Returns:
        dict: Структура JSON
    """
    try:
        content = read_file(template_path)
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Ошибка при парсинге JSON шаблона: {e}")
        sys.exit(1)


def create_extraction_prompt(markdown_content, json_template):
    """
    Создает промпт для извлечения данных из MD в JSON структуру.
    
    Args:
        markdown_content (str): Содержимое MD файла
        json_template (dict): JSON шаблон
        
    Returns:
        str: Промпт для модели
    """
    template_str = json.dumps(json_template, ensure_ascii=False, indent=2)
    
    prompt = f"""
Ты — экспертный AI-ассистент, специализирующийся на парсинге резюме (CV) и извлечении структурированных данных. Твоя задача — заполнить JSON-структуру данными из текста резюме, следуя строгим правилам интерпретации понятий.

=== 1. КРИТИЧЕСКИЕ ПРАВИЛА (ZERO-SHOT CONSTRAINTS) ===
1. **Принцип Истины:** НЕ добавляй информацию, которой нет в тексте. НЕ придумывай названия проектов, компаний или цифры.
2. **Принцип Пустоты:** Если данные отсутствуют — оставляй поле пустым ("" или []).
3. **Принцип Точности:** Сохраняй оригинальные названия, даты и формулировки навыков.
4. **Запрет внешних знаний:** Используй только текст резюме.

=== 2. ОПРЕДЕЛЕНИЯ И АКЦЕНТЫ (ВНИМАТЕЛЬНО ИЗУЧИ) ===

### А. PROJECT BACKGROUND (Проектный бекграунд)
* **ЧТО ЭТО:** Это БИЗНЕС-ДОМЕН или ОТРАСЛЬ, в которой работал кандидат.
* **СТРОГО ИСКАТЬ:** Финтех, Ритейл, E-commerce, Банкинг, Нефтегаз, Телеком, EdTech, MedTech.
* **СТРОГИЙ ЗАПРЕТ:** НЕ пиши сюда технические роли или стек (Backend, Full-stack, Highload, Web-development — это НЕ бекграунд, это роль).
* **ИСТОЧНИК:** Описания проектов и компаний.

### Б. SOFT SKILLS (Мягкие навыки)
* **СТРАТЕГИЯ:**
    1. Ищи явные перечисления (раздел "Soft skills", "О себе").
    2. Если явных нет — допустим АККУРАТНЫЙ логический вывод из опыта (например, "управлял командой" -> "Лидерство").
    3. **ЗАПРЕТ:** Не добавляй "воду" (стрессоустойчивость, коммуникабельность), если в тексте нет подтверждения этим качествам.

### В. ОБРАЗОВАНИЕ (Education) vs КУРСЫ (Advanced Training)
* **EDUCATION:** Только фундаментальное образование (ВУЗы, колледжи). Степени: Бакалавр, Магистр, Специалист.
* **ADVANCED TRAINING:** Любые курсы повышения квалификации, тренинги, онлайн-школы (Яндекс Практикум, Udemy, Coursera, внутренние курсы компаний).
* **ВАЖНО:** Не путай эти два раздела.

=== 3. ИНСТРУКЦИИ ПО ПОЛЯМ ===

**ПОЛЕ "full_name":**
- ФИО кандидата. Если не найдено — пустая строка.

**ПОЛЕ "pitch" (Summary):**
- Краткая профессиональная выжимка (3-5 предложений).
- Пиши от первого лица ("Разрабатывал...", "Имею опыт..."), но опуская местоимение "Я".
- Используй факты, избегай общих фраз.

**ПОЛЕ "skills_and_tools" (Universal Smart Grouping):**
- Содержание: Только HARD SKILLS (инструменты, программы, оборудование, стандарты, нормативные акты).
- **ГЛАВНОЕ ПРАВИЛО (Адаптивность):**
  1. Сначала определи **Профессиональную Область** кандидата.
  2. Сгруппируй навыки, используя **профессиональную терминологию этой области**.
  3. Не используй IT-категории (Языки, Фреймворки) для не-IT специальностей.

- **Сценарии группировки:**

  **СЦЕНАРИЙ А: IT / Разработка / 1С**
  - Разделяй: "Языки", "Фреймворки", "БД".
  - Для 1С: Строго дели на "Конфигурации" (ERP, ЗУП), "Платформу" (8.3), "Отраслевые решения" и "Инструменты разработчика".
  - Форматы (JSON, XML) → в "Форматы данных" или "Интеграции", но НЕ в языки.

  **СЦЕНАРИЙ Б: Офис / Финансы / HR / Sales**
  - Используй категории: "Учетные системы" (1С, SAP), "BI и Аналитика", "CRM-системы", "Офисный пакет" (Excel сводные таблицы, макросы), "Законодательство/Стандарты" (ТК РФ, МСФО, ПБУ).

  **СЦЕНАРИЙ В: Производство / Инженерия / Дизайн**
  - Используй категории: "САПР/CAD" (AutoCAD, Revit), "Графические редакторы" (Photoshop, Figma), "Оборудование" (Станки ЧПУ, Теодолиты), "Нормативы" (ГОСТ, СНиП).

- **Правило чистоты:**
  - Не пиши "Уверенный пользователь ПК" или "Internet" — это мусор.
  - Не создавай категорию ради одного инструмента, если его можно логично объединить (например, "Jira" и "Confluence" → "Управление проектами").

- Формат строки: "Название категории: Инструмент1, Инструмент2"

**ПОЛЕ "education":**
- Формат: "Уровень\nГОД, ВУЗ, Город\nФакультет, Специальность (степень)"
- Пример: "Высшее \n2015, МГУ, Москва\nВМК, Прикладная математика"

**ПОЛЕ "advanced_training":**
- Формат: "ГОД г., Название курса — Организация"

**ПОЛЯ "technologies" (в Work Exp) и "technologies_and_tools" (в Project Exp):**
- Плоский список строк (Array of Strings).
- Каждая технология — отдельный элемент массива.
- Пример: ["Java", "Spring Boot", "PostgreSQL"] (НЕ ["Java, Spring, Postgres"]).

**ПОЛЯ "work_experience" и "project_experience":**
- **company:** Название компании или проекта.
- **period:**
    - Строго соблюдай формат: "МЕСЯЦ ГОД - МЕСЯЦ ГОД / X ЛЕТ Y МЕСЯЦЕВ" (или "... - настоящее время").
    - ВАЖНО: Ты должен сам вычислить длительность (X и Y) на основе дат. Считай внимательно.
- **role:** Роль кандидата.
- **achievements:** Список конкретных результатов (сделал X, улучшил Y на Z%).

=== 4. ВВОДНЫЕ ДАННЫЕ ===

Структура JSON (шаблон):
{template_str}

Текст резюме:
{markdown_content}

=== 5. ВЫВОД ===
Верни ТОЛЬКО валидный JSON. Никаких Markdown-тегов (```), никаких комментариев до или после JSON.
"""
    
    return prompt


def extract_json_from_response(response_text):
    """
    Извлекает JSON из ответа модели.
    
    Args:
        response_text (str): Текст ответа модели
        
    Returns:
        dict: Распарсенный JSON
    """
    # Пытаемся найти JSON в ответе (модель может добавить пояснения)
    response_text = response_text.strip()
    
    # Ищем начало JSON (первая {)
    start_idx = response_text.find('{')
    if start_idx == -1:
        raise ValueError("Не найдено начало JSON в ответе")
    
    # Ищем конец JSON (последняя })
    end_idx = response_text.rfind('}')
    if end_idx == -1 or end_idx < start_idx:
        raise ValueError("Не найден конец JSON в ответе")
    
    json_str = response_text[start_idx:end_idx + 1]
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Ошибка при парсинге JSON из ответа: {e}")
        print(f"Извлеченный текст: {json_str[:500]}...")
        raise


def process_with_gemini(markdown_content, json_template, api_key, model_name=None):
    """
    Обрабатывает текст через AI API (Gemini или OpenRouter) для извлечения данных в JSON.
    Автоматически переключается на OpenRouter при ошибках Gemini (503, 500, 429).
    
    Args:
        markdown_content (str): Содержимое MD файла
        json_template (dict): JSON шаблон
        api_key (str): API ключ Gemini (опционально, используется для обратной совместимости)
        model_name (str): Имя модели Gemini (по умолчанию: gemini-2.5-flash)
        
    Returns:
        dict: Заполненная JSON структура
    """
    try:
        from parser.ai_provider import process_with_fallback, get_api_keys
    except ImportError:
        # Fallback на старую реализацию, если новый модуль недоступен
        print("⚠️  Модуль ai_provider не найден, используется старая реализация Gemini")
        return _process_with_gemini_legacy(markdown_content, json_template, api_key, model_name)
    
    # Получаем API ключи
    env_keys = get_api_keys()
    gemini_key = api_key or env_keys['gemini']
    openrouter_key = env_keys['openrouter']
    
    # Используем новый провайдер с автоматическим fallback
    try:
        return process_with_fallback(
            markdown_content,
            json_template,
            create_extraction_prompt,
            gemini_api_key=gemini_key,
            openrouter_api_key=openrouter_key,
            gemini_model=model_name,
            verbose=True
        )
    except Exception as e:
        # Если новый провайдер не работает, пробуем старую реализацию
        if gemini_key:
            print(f"⚠️  Ошибка нового провайдера, пробуем старую реализацию: {e}")
            return _process_with_gemini_legacy(markdown_content, json_template, gemini_key, model_name)
        raise


def _process_with_gemini_legacy(markdown_content, json_template, api_key, model_name=None):
    """
    Старая реализация обработки через Gemini API (для обратной совместимости).
    
    Args:
        markdown_content (str): Содержимое MD файла
        json_template (dict): JSON шаблон
        api_key (str): API ключ Gemini
        model_name (str): Имя модели (по умолчанию: gemini-2.5-flash)
        
    Returns:
        dict: Заполненная JSON структура
    """
    model_name = model_name or DEFAULT_GEMINI_MODEL
    
    prompt = create_extraction_prompt(markdown_content, json_template)
    
    print("Отправка запроса в Gemini API...")
    print(f"Используемая модель: {model_name}")
    
    try:
        client = genai.Client(api_key=api_key)
    except Exception as config_error:
        print(f"Ошибка конфигурации Gemini API: {config_error}")
        raise
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
    except Exception as api_error:
        print(f"Ошибка при обращении к Gemini API: {api_error}")
        raise
    
    response_text = getattr(response, "text", None)
    if not response_text:
        # Пытаемся извлечь текст из частей ответа
        try:
            candidates = getattr(response, "candidates", [])
            for candidate in candidates:
                for part in candidate.content.parts:
                    if getattr(part, "text", None):
                        response_text = part.text
                        break
                if response_text:
                    break
        except Exception:
            response_text = None
    
    if not response_text:
        print("Ошибка: пустой ответ от Gemini API.")
        raise RuntimeError("Пустой ответ от Gemini API")
    
    try:
        extracted_json = extract_json_from_response(response_text)
        return extracted_json
    except (ValueError, json.JSONDecodeError) as parse_error:
        print(f"Ошибка при обработке ответа Gemini: {parse_error}")
        print("Ответ модели:")
        print(response_text)
        raise


def merge_with_template(extracted_data, template):
    """
    Объединяет извлеченные данные с шаблоном, сохраняя структуру шаблона.
    
    Args:
        extracted_data (dict): Данные, извлеченные моделью
        template (dict): Исходный шаблон
        
    Returns:
        dict: Объединенная структура
    """
    def deep_merge(source, target):
        """Рекурсивно объединяет два словаря."""
        if isinstance(source, dict) and isinstance(target, dict):
            result = target.copy()
            for key, value in source.items():
                if key in result:
                    if isinstance(value, dict) and isinstance(result[key], dict):
                        result[key] = deep_merge(value, result[key])
                    elif isinstance(value, list) and isinstance(result[key], list):
                        # Для списков всегда берем данные из source (даже если пустые), чтобы не оставлять заглушки из шаблона
                        result[key] = value
                    else:
                        # Для примитивных значений берем из source (даже если пустые), чтобы не оставлять заглушки из шаблона
                        result[key] = value
                else:
                    result[key] = value
            return result
        return source if source else target
    
    return deep_merge(extracted_data, template)


def save_json(data, output_path):
    """
    Сохраняет данные в JSON файл.
    
    Args:
        data (dict): Данные для сохранения
        output_path (str): Путь к выходному файлу
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ JSON файл сохранен в: {output_path}")
    except Exception as e:
        print(f"Ошибка при сохранении файла: {e}")
        sys.exit(1)


def get_api_key():
    """
    Получает API ключ из переменной окружения или файла.
    
    Returns:
        str: API ключ
    """
    # Сначала проверяем переменную окружения
    api_key = os.getenv("GEMINI_API_KEY")
    
    if api_key:
        return api_key
    
    # Проверяем файл .env
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except:
            pass
    
    # Если не найдено, просим пользователя ввести
    print("\n⚠️  API ключ Gemini не найден.")
    print("Получите бесплатный ключ на https://aistudio.google.com/app/apikey")
    print("Вы можете:")
    print("  1. Установить переменную окружения: set GEMINI_API_KEY=your_key")
    print("  2. Создать файл .env с строкой: GEMINI_API_KEY=your_key")
    print("  3. Ввести ключ сейчас (он не будет сохранен)")
    
    api_key = input("\nВведите ваш Gemini API ключ: ").strip()
    
    if not api_key:
        print("Ошибка: API ключ обязателен для работы.")
        sys.exit(1)
    
    return api_key


def main():
    """Основная функция."""
    parser = argparse.ArgumentParser(
        description="Преобразование Markdown резюме в JSON формат с использованием Gemini",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python md_to_json.py document.md
  python md_to_json.py document.md --template example.json
  python md_to_json.py document.md --output result.json
  python md_to_json.py document.md --model gemini-2.5-flash
  python md_to_json.py document.md --template example.json --output result.json --model gemini-2.5-pro

Примечание: Если модель не указана, используется gemini-2.5-flash.
Для получения API ключа: https://aistudio.google.com/app/apikey
Примеры моделей: gemini-2.5-flash, gemini-2.5-pro, gemini-1.5-pro-exp
        """
    )
    
    parser.add_argument("input_file", help="Путь к входному Markdown файлу")
    parser.add_argument(
        "--template", "-t",
        default="parser/template/example.json",
        help="Путь к JSON шаблону (по умолчанию: parser/template/example.json)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Путь к выходному JSON файлу (по умолчанию: <имя_файла>.json)"
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_GEMINI_MODEL,
        help="Имя модели Gemini (например: gemini-1.5-flash). Если не указано, используется gemini-1.5-flash."
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API ключ (или используйте переменную GEMINI_API_KEY)"
    )
    
    args = parser.parse_args()
    
    # Проверка входного файла
    if not os.path.exists(args.input_file):
        print(f"Ошибка: файл '{args.input_file}' не найден.")
        sys.exit(1)
    
    # Проверка шаблона
    if not os.path.exists(args.template):
        print(f"Ошибка: шаблон '{args.template}' не найден.")
        sys.exit(1)
    
    # Определение выходного файла
    if args.output:
        output_path = args.output
    else:
        input_file = Path(args.input_file)
        output_path = input_file.stem + ".json"
    
    # Получение API ключа
    api_key = args.api_key or get_api_key()
    
    # Загрузка шаблона
    print(f"Загрузка шаблона: {args.template}")
    json_template = load_json_template(args.template)
    print(f"Структура шаблона загружена")
    
    # Чтение MD файла
    print(f"Чтение файла: {args.input_file}")
    markdown_content = read_file(args.input_file)
    print(f"Размер файла: {len(markdown_content)} символов")
    
    # Обработка через API
    extracted_data = process_with_gemini(
        markdown_content,
        json_template,
        api_key,
        args.model
    )
    
    # Объединение с шаблоном для сохранения структуры
    final_data = merge_with_template(extracted_data, json_template)
    
    # Сохранение результата
    save_json(final_data, output_path)
    
    # Показываем краткую статистику
    print(f"\n📊 Статистика извлеченных данных:")
    print(f"  - Опыт работы: {len(final_data.get('work_experience', []))} записей")
    print(f"  - Проекты: {len(final_data.get('project_experience', []))} записей")
    skills_count = len(final_data.get('general_info', {}).get('skills_and_tools', []))
    print(f"  - Навыки: {skills_count} записей")


if __name__ == "__main__":
    main()
