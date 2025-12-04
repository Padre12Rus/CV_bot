#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для работы с различными AI провайдерами с автоматическим fallback.
Поддерживает Gemini и OpenRouter с автоматическим переключением при ошибках.
"""

import os
import json
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from google import genai
except ImportError:
    genai = None

try:
    import requests
except ImportError:
    requests = None


# Константы для моделей
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
# По умолчанию используется openai/gpt-4o-mini (быстрая и недорогая модель)
# Можно изменить через переменную окружения OPENROUTER_MODEL в .env файле
# Популярные модели OpenRouter:
# - openai/gpt-4o-mini (быстрая, дешевая, по умолчанию)
# - openai/gpt-4o (более мощная)
# - openai/gpt-4-turbo (очень мощная)
# - anthropic/claude-3.5-sonnet (отличное качество)
# - anthropic/claude-3-haiku (быстрая)
# - google/gemini-pro-1.5 (альтернатива Gemini)
# - meta-llama/llama-3.1-70b-instruct (открытая модель)
# - mistralai/mistral-large (качественная модель)
# Полный список: https://openrouter.ai/models
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"

# Глобальная переменная для хранения информации о последней использованной модели
_last_used_provider_info = {
    'provider': None,
    'model': None,
    'timestamp': None
}


class AIProviderError(Exception):
    """Базовое исключение для ошибок AI провайдеров"""
    pass


class GeminiProvider:
    """Провайдер для работы с Google Gemini API"""
    
    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL):
        """
        Инициализация провайдера Gemini.
        
        Args:
            api_key: API ключ Gemini
            model: Имя модели (по умолчанию: gemini-2.5-flash)
        """
        if genai is None:
            raise AIProviderError(
                "Библиотека google-genai не установлена. "
                "Установите её командой: pip install google-genai"
            )
        
        self.api_key = api_key
        self.model = model
        self.client = None
        
    def _get_client(self):
        """Получает или создает клиент Gemini"""
        if self.client is None:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                raise AIProviderError(f"Ошибка конфигурации Gemini API: {e}")
        return self.client
    
    def generate_with_file(self, file_path: str, prompt: str) -> str:
        """
        Генерирует ответ через Gemini API, передавая исходный файл напрямую.
        
        Args:
            file_path: Путь к файлу (PDF/DOCX/другой поддерживаемый формат)
            prompt: Текстовая инструкция для модели
        """
        client = self._get_client()
        
        try:
            uploaded_file = client.files.upload(file=file_path)
        except Exception as upload_error:
            raise AIProviderError(f"Ошибка загрузки файла в Gemini: {upload_error}")
        
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    {
                        "role": "user",
                        "parts": [
                            {
                                "file_data": {
                                    "file_uri": uploaded_file.uri
                                }
                            },
                            {
                                "text": prompt
                            },
                        ],
                    }
                ],
            )
        except Exception as api_error:
            error_str = str(api_error).lower()
            if any(code in error_str for code in ['503', '500', '429', 'service unavailable', 'unavailable']):
                raise AIProviderError(f"Gemini API недоступен (503/500/429) при работе с файлом: {api_error}")
            raise AIProviderError(f"Ошибка при обращении к Gemini API (file-mode): {api_error}")
        
        # Извлечение текста из ответа
        response_text = getattr(response, "text", None)
        if not response_text:
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
            raise AIProviderError("Пустой ответ от Gemini API (file-mode)")
        
        return response_text
    
    def generate(self, prompt: str) -> str:
        """
        Генерирует ответ через Gemini API.
        
        Args:
            prompt: Промпт для модели
            
        Returns:
            str: Текст ответа модели
            
        Raises:
            AIProviderError: При ошибках API (включая 503)
        """
        client = self._get_client()
        
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
        except Exception as api_error:
            error_str = str(api_error).lower()
            # Проверяем на ошибки 503, 500, 429 и другие серверные ошибки
            if any(code in error_str for code in ['503', '500', '429', 'service unavailable', 'unavailable']):
                raise AIProviderError(f"Gemini API недоступен (503/500/429): {api_error}")
            raise AIProviderError(f"Ошибка при обращении к Gemini API: {api_error}")
        
        # Извлечение текста из ответа
        response_text = getattr(response, "text", None)
        if not response_text:
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
            raise AIProviderError("Пустой ответ от Gemini API")
        
        return response_text


class OpenRouterProvider:
    """Провайдер для работы с OpenRouter API"""
    
    def __init__(self, api_key: str, model: str = DEFAULT_OPENROUTER_MODEL):
        """
        Инициализация провайдера OpenRouter.
        
        Args:
            api_key: API ключ OpenRouter
            model: Имя модели (по умолчанию: openai/gpt-4o-mini)
        """
        if requests is None:
            raise AIProviderError(
                "Библиотека requests не установлена. "
                "Установите её командой: pip install requests"
            )
        
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
    
    def generate(self, prompt: str) -> str:
        """
        Генерирует ответ через OpenRouter API.
        
        Args:
            prompt: Промпт для модели
            
        Returns:
            str: Текст ответа модели
            
        Raises:
            AIProviderError: При ошибках API
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",  # Опционально, для отслеживания
            "X-Title": "EC_CV_project"  # Опционально, для идентификации
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,  # Низкая температура для более точных ответов
        }
        
        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=120  # 2 минуты таймаут
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Извлечение текста из ответа
            if "choices" in data and len(data["choices"]) > 0:
                message = data["choices"][0].get("message", {})
                content = message.get("content", "")
                if content:
                    return content
                else:
                    raise AIProviderError("Пустой ответ от OpenRouter API")
            else:
                raise AIProviderError(f"Неожиданный формат ответа от OpenRouter: {data}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 503:
                raise AIProviderError(f"OpenRouter API недоступен (503): {e}")
            elif e.response.status_code == 429:
                raise AIProviderError(f"OpenRouter API: превышен лимит запросов (429): {e}")
            raise AIProviderError(f"Ошибка HTTP при обращении к OpenRouter API: {e}")
        except requests.exceptions.RequestException as e:
            raise AIProviderError(f"Ошибка при обращении к OpenRouter API: {e}")


def get_api_keys() -> Dict[str, Optional[str]]:
    """
    Получает API ключи из переменных окружения или файла .env.
    
    Returns:
        dict: Словарь с ключами 'gemini' и 'openrouter'
    """
    keys = {
        'gemini': None,
        'openrouter': None
    }
    
    # Проверяем переменные окружения
    keys['gemini'] = os.getenv("GEMINI_API_KEY")
    keys['openrouter'] = os.getenv("OPENROUTER_API_KEY")
    
    # Если не найдено в переменных окружения, проверяем .env файл
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        keys['gemini'] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("OPENROUTER_API_KEY="):
                        keys['openrouter'] = line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    
    return keys


def get_openrouter_model() -> str:
    """
    Получает модель OpenRouter из переменной окружения или использует значение по умолчанию.
    
    Returns:
        str: Имя модели OpenRouter
    """
    # Сначала проверяем переменную окружения
    model = os.getenv("OPENROUTER_MODEL")
    if model:
        return model
    
    # Проверяем .env файл
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENROUTER_MODEL="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    
    # Возвращаем значение по умолчанию
    return "openai/gpt-4o-mini"


def get_models_info(
    gemini_model: Optional[str] = None,
    openrouter_model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Получает информацию о доступных моделях и их настройках.
    
    Args:
        gemini_model: Имя модели Gemini (опционально)
        openrouter_model: Имя модели OpenRouter (опционально)
        
    Returns:
        dict: Информация о моделях и провайдерах
    """
    keys = get_api_keys()
    gemini_model = gemini_model or DEFAULT_GEMINI_MODEL
    openrouter_model = openrouter_model or get_openrouter_model()
    
    info = {
        'gemini': {
            'available': keys['gemini'] is not None,
            'model': gemini_model,
            'api_key_set': bool(keys['gemini'])
        },
        'openrouter': {
            'available': keys['openrouter'] is not None,
            'model': openrouter_model,
            'api_key_set': bool(keys['openrouter'])
        },
        'primary_provider': 'gemini' if keys['gemini'] else ('openrouter' if keys['openrouter'] else None),
        'fallback_enabled': keys['gemini'] is not None and keys['openrouter'] is not None
    }
    
    return info


def get_last_used_provider() -> Dict[str, Any]:
    """
    Получает информацию о последней использованной модели.
    
    Returns:
        dict: Информация о последней использованной модели или None
    """
    global _last_used_provider_info
    if _last_used_provider_info['provider'] is None:
        return None
    return _last_used_provider_info.copy()


def process_file_with_gemini(
    file_path: str,
    json_template: Dict[str, Any],
    prompt_creator_func,
    gemini_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    verbose: bool = True,
    user_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Обрабатывает файл напрямую через Gemini API, без промежуточного Markdown.
    
    Args:
        file_path: Путь к исходному файлу (PDF/DOCX/др.)
        json_template: JSON шаблон
        prompt_creator_func: Функция для создания промпта (принимает json_template)
        gemini_api_key: API ключ Gemini (опционально, берётся из окружения)
        gemini_model: Имя модели Gemini (по умолчанию: DEFAULT_GEMINI_MODEL)
        verbose: Выводить ли логи
    """
    # Локальный импорт, чтобы избежать жёсткой циклической зависимости
    from parser.md_to_json import extract_json_from_response  # type: ignore
    
    keys = get_api_keys()
    gemini_key = gemini_api_key or keys.get("gemini")
    
    if not gemini_key:
        raise AIProviderError(
            "Не найден GEMINI_API_KEY для прямой обработки файла. "
            "Установите ключ в окружении или .env."
        )
    
    gemini_model = gemini_model or DEFAULT_GEMINI_MODEL
    try:
        prompt = prompt_creator_func(json_template, user_hint=user_hint)
    except TypeError:
        prompt = prompt_creator_func(json_template)
    
    if verbose:
        print("🔄 Обработка файла напрямую через Gemini API...")
        print(f"   Модель: {gemini_model}")
        print(f"   Файл: {file_path}")
    
    provider = GeminiProvider(gemini_key, gemini_model)
    response_text = provider.generate_with_file(file_path, prompt)
    
    global _last_used_provider_info
    _last_used_provider_info = {
        "provider": "gemini",
        "model": gemini_model,
        "timestamp": time.time(),
    }
    
    return extract_json_from_response(response_text)


def process_with_fallback(
    markdown_content: str,
    json_template: Dict[str, Any],
    prompt_creator_func,
    gemini_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    openrouter_model: Optional[str] = None,
    verbose: bool = True,
    return_provider_info: bool = False,
    user_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Обрабатывает текст через AI с автоматическим fallback между провайдерами.
    Сначала пытается использовать Gemini, при ошибках (503, 500, 429) переключается на OpenRouter.
    
    Args:
        markdown_content: Содержимое MD файла
        json_template: JSON шаблон
        prompt_creator_func: Функция для создания промпта (принимает markdown_content и json_template)
        gemini_api_key: API ключ Gemini (опционально, берется из окружения)
        openrouter_api_key: API ключ OpenRouter (опционально, берется из окружения)
        gemini_model: Имя модели Gemini (по умолчанию: gemini-2.5-flash)
        openrouter_model: Имя модели OpenRouter (по умолчанию: openai/gpt-4o-mini)
        verbose: Выводить ли информацию о процессе
        
    Returns:
        dict: Заполненная JSON структура
        
    Raises:
        AIProviderError: Если все провайдеры недоступны
    """
    global _last_used_provider_info
    
    # Получаем API ключи
    env_keys = get_api_keys()
    gemini_key = gemini_api_key or env_keys['gemini']
    openrouter_key = openrouter_api_key or env_keys['openrouter']
    
    # Проверяем наличие хотя бы одного ключа
    if not gemini_key and not openrouter_key:
        raise AIProviderError(
            "Не найден ни один API ключ. "
            "Установите GEMINI_API_KEY или OPENROUTER_API_KEY в переменных окружения или .env файле."
        )
    
    # Создаем промпт
    try:
        prompt = prompt_creator_func(markdown_content, json_template, user_hint=user_hint)
    except TypeError:
        prompt = prompt_creator_func(markdown_content, json_template)
    
    gemini_model = gemini_model or DEFAULT_GEMINI_MODEL
    openrouter_model = openrouter_model or get_openrouter_model()
    
    # Пытаемся использовать Gemini
    if gemini_key:
        try:
            if verbose:
                print("🔄 Попытка использования Gemini API...")
                print(f"   Модель: {gemini_model}")
            
            provider = GeminiProvider(gemini_key, gemini_model)
            response_text = provider.generate(prompt)
            
            # Сохраняем информацию о использованной модели
            _last_used_provider_info = {
                'provider': 'gemini',
                'model': gemini_model,
                'timestamp': time.time()
            }
            
            if verbose:
                print("✅ Успешно использован Gemini API")
            
            # Парсим JSON из ответа
            try:
                from parser.md_to_json import extract_json_from_response
            except ImportError:
                # Если не удалось импортировать, используем локальную реализацию
                def extract_json_from_response(response_text):
                    import json
                    response_text = response_text.strip()
                    start_idx = response_text.find('{')
                    if start_idx == -1:
                        raise ValueError("Не найдено начало JSON в ответе")
                    end_idx = response_text.rfind('}')
                    if end_idx == -1 or end_idx < start_idx:
                        raise ValueError("Не найден конец JSON в ответе")
                    json_str = response_text[start_idx:end_idx + 1]
                    return json.loads(json_str)
            
            return extract_json_from_response(response_text)
            
        except AIProviderError as e:
            error_msg = str(e).lower()
            # Проверяем, это ли ошибка доступности (503, 500, 429)
            if any(code in error_msg for code in ['503', '500', '429', 'unavailable']):
                if verbose:
                    print(f"⚠️  Gemini недоступен: {e}")
                    print("🔄 Переключение на OpenRouter...")
            else:
                # Другие ошибки - пробрасываем дальше
                if verbose:
                    print(f"❌ Ошибка Gemini: {e}")
                if not openrouter_key:
                    raise  # Если нет резервного провайдера, пробрасываем ошибку
                if verbose:
                    print("🔄 Переключение на OpenRouter...")
        except Exception as e:
            if verbose:
                print(f"❌ Неожиданная ошибка Gemini: {e}")
            if not openrouter_key:
                raise AIProviderError(f"Ошибка Gemini: {e}")
            if verbose:
                print("🔄 Переключение на OpenRouter...")
    
    # Пытаемся использовать OpenRouter как fallback
    if openrouter_key:
        try:
            if verbose:
                print("🔄 Использование OpenRouter API...")
                print(f"   Модель: {openrouter_model}")
            
            provider = OpenRouterProvider(openrouter_key, openrouter_model)
            response_text = provider.generate(prompt)
            
            # Сохраняем информацию о использованной модели
            _last_used_provider_info = {
                'provider': 'openrouter',
                'model': openrouter_model,
                'timestamp': time.time()
            }
            
            if verbose:
                print("✅ Успешно использован OpenRouter API")
            
            # Парсим JSON из ответа
            try:
                from parser.md_to_json import extract_json_from_response
            except ImportError:
                # Если не удалось импортировать, используем локальную реализацию
                def extract_json_from_response(response_text):
                    import json
                    response_text = response_text.strip()
                    start_idx = response_text.find('{')
                    if start_idx == -1:
                        raise ValueError("Не найдено начало JSON в ответе")
                    end_idx = response_text.rfind('}')
                    if end_idx == -1 or end_idx < start_idx:
                        raise ValueError("Не найден конец JSON в ответе")
                    json_str = response_text[start_idx:end_idx + 1]
                    return json.loads(json_str)
            
            return extract_json_from_response(response_text)
            
        except AIProviderError as e:
            if verbose:
                print(f"❌ Ошибка OpenRouter: {e}")
            raise
        except Exception as e:
            if verbose:
                print(f"❌ Неожиданная ошибка OpenRouter: {e}")
            raise AIProviderError(f"Ошибка OpenRouter: {e}")
    
    # Если дошли сюда, значит нет доступных провайдеров
    raise AIProviderError("Нет доступных AI провайдеров для обработки запроса")
