"""
Inline-клавиатуры: ручной выбор биржи и ссылки на партнёров.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_exchange_selection_keyboard() -> InlineKeyboardMarkup:
    """
    Ручной выбор биржи при UNKNOWN / сбое детекции.
    callback_data: ``exchange:<ключ>``.
    """
    builder = InlineKeyboardBuilder()
    mapping = [
        ("Binance", "binance"),
        ("Bybit", "bybit"),
        ("OKX", "okx"),
        ("BingX", "bingx"),
        ("MEXC", "mexc"),
    ]
    for label, key in mapping:
        builder.button(text=label, callback_data=f"exchange:{key}")
    builder.button(text="❌ Другое", callback_data="exchange:other")
    builder.adjust(2)
    return builder.as_markup()


def get_partner_links_keyboard(links: dict[str, str]) -> InlineKeyboardMarkup:
    """
    Кнопки-URL по активным партнёрам из БД.
    ``links``: ``exchange_name`` (lower) → ``referral_link``.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for name, url in sorted(links.items()):
        rows.append([InlineKeyboardButton(text=name.upper(), url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_link_keyboard(url: str, title: str = "Стать партнёром") -> InlineKeyboardMarkup:
    """Одна кнопка — реферальная ссылка на конкретную биржу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=title, url=url)]]
    )
