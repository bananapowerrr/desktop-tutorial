"""
Утилиты для изображений: хэш байтов (SHA-256) для кэша до вызова ИИ.
"""

from __future__ import annotations

import hashlib


def calculate_image_hash(file_bytes: bytes) -> str:
    """Возвращает hex SHA-256 от содержимого файла (не от пути)."""
    return hashlib.sha256(file_bytes).hexdigest()
