"""
Асинхронная работа с SQLite через aiosqlite.
Все временные метки — UTC, unix time (time.time()).

Этап 3: анти-спам (rate limit) и кэш анализа по (user, hash, exchange) до вызова ИИ.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

import config
from image_utils import calculate_image_hash

logger = logging.getLogger(__name__)


def _utc_now_int() -> int:
    return int(time.time())


def _ensure_db_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


async def _migrate_image_cache_schema(db: aiosqlite.Connection) -> None:
    """
    Этап 1–2: PK был только image_hash. Для этапа 3 нужны telegram_id и составной ключ.
    Старые строки переносим с telegram_id = -1 (служебный «до обновления»).
    """
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='image_cache';"
    )
    if await cur.fetchone() is None:
        return
    cur = await db.execute("PRAGMA table_info(image_cache);")
    rows = await cur.fetchall()
    col_names = {r[1] for r in rows}
    if "telegram_id" in col_names:
        return
    logger.info("Миграция image_cache: добавление telegram_id и составного PK")
    await db.execute("ALTER TABLE image_cache RENAME TO image_cache_legacy;")
    await db.executescript(
        """
        CREATE TABLE image_cache (
            telegram_id INTEGER NOT NULL,
            image_hash TEXT NOT NULL,
            exchange_name TEXT NOT NULL,
            analysis_result TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (telegram_id, image_hash, exchange_name)
        );
        CREATE INDEX IF NOT EXISTS idx_image_cache_created ON image_cache(created_at);
        """
    )
    await db.execute(
        """
        INSERT INTO image_cache (telegram_id, image_hash, exchange_name, analysis_result, created_at)
        SELECT -1, image_hash, COALESCE(exchange_name, ''), analysis_result, created_at
        FROM image_cache_legacy;
        """
    )
    await db.execute("DROP TABLE image_cache_legacy;")


async def _ensure_cache_metrics_table(db: aiosqlite.Connection) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS cache_metrics (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            hits INTEGER NOT NULL DEFAULT 0,
            misses INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO cache_metrics (id, hits, misses) VALUES (1, 0, 0);
        """
    )


async def init_db() -> None:
    """
    Создаёт таблицы. При ошибке подключения логирует и пробрасывает исключение.
    """
    _ensure_db_parent_dir(config.DB_PATH)
    db_path = str(config.DB_PATH)
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    last_request_time INTEGER,
                    free_trials_left INTEGER NOT NULL DEFAULT 3,
                    registered_exchanges TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'free',
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exchange_config (
                    exchange_name TEXT PRIMARY KEY,
                    referral_link TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS image_cache (
                    telegram_id INTEGER NOT NULL,
                    image_hash TEXT NOT NULL,
                    exchange_name TEXT NOT NULL,
                    analysis_result TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (telegram_id, image_hash, exchange_name)
                );

                CREATE INDEX IF NOT EXISTS idx_image_cache_created
                ON image_cache(created_at);

                CREATE TABLE IF NOT EXISTS cache_metrics (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    hits INTEGER NOT NULL DEFAULT 0,
                    misses INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO cache_metrics (id, hits, misses) VALUES (1, 0, 0);
                """
            )
            await _migrate_image_cache_schema(db)
            await _ensure_cache_metrics_table(db)
            await db.commit()
        logger.info("БД инициализирована: %s", db_path)
    except aiosqlite.Error as exc:
        logger.exception("Ошибка SQLite при init_db (%s): %s", db_path, exc)
        raise RuntimeError(f"Не удалось инициализировать БД: {db_path}") from exc


async def get_user(telegram_id: int) -> dict[str, Any] | None:
    """Возвращает строку пользователя или None."""
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ?;",
                (telegram_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return dict(row)
    except aiosqlite.Error as exc:
        logger.exception("get_user: %s", exc)
        raise


async def create_user(telegram_id: int, username: str | None) -> None:
    """Создаёт пользователя, если его ещё нет."""
    now = _utc_now_int()
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO users (
                    telegram_id, username, last_request_time, free_trials_left,
                    registered_exchanges, status, created_at
                )
                VALUES (?, ?, NULL, 3, '[]', 'free', ?);
                """,
                (telegram_id, username, now),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("create_user: %s", exc)
        raise


async def update_last_request(telegram_id: int) -> None:
    """Обновляет last_request_time на текущий UTC timestamp."""
    now = _utc_now_int()
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            await db.execute(
                "UPDATE users SET last_request_time = ? WHERE telegram_id = ?;",
                (now, telegram_id),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("update_last_request: %s", exc)
        raise


async def decrement_trials(telegram_id: int) -> None:
    """Уменьшает free_trials_left на 1, не уходя ниже нуля."""
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            await db.execute(
                """
                UPDATE users
                SET free_trials_left = MAX(0, free_trials_left - 1)
                WHERE telegram_id = ?;
                """,
                (telegram_id,),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("decrement_trials: %s", exc)
        raise


async def bulk_update_exchange_config(exchanges_list: list[dict[str, Any]]) -> None:
    """
    Пакетная запись рефералок из Google Sheets в `exchange_config`.
    Каждый элемент: ``exchange_name``, ``referral_link``, ``is_active`` (bool).
    Пустой список — операция no-op (кэш в БД не очищается).
    """
    if not exchanges_list:
        return
    try:
        applied = 0
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            for item in exchanges_list:
                name = str(item.get("exchange_name", "")).strip().lower()
                link = str(item.get("referral_link", "")).strip()
                active = bool(item.get("is_active", True))
                if not name or not link:
                    continue
                await db.execute(
                    """
                    INSERT INTO exchange_config (exchange_name, referral_link, is_active)
                    VALUES (?, ?, ?)
                    ON CONFLICT(exchange_name) DO UPDATE SET
                        referral_link = excluded.referral_link,
                        is_active = excluded.is_active;
                    """,
                    (name, link, 1 if active else 0),
                )
                applied += 1
            await db.commit()
        logger.info("bulk_update_exchange_config: применено строк: %s", applied)
    except aiosqlite.Error as exc:
        logger.exception("bulk_update_exchange_config: %s", exc)
        raise


async def add_verified_exchange(telegram_id: int, exchange: str) -> None:
    """
    Добавляет биржу в JSON ``registered_exchanges`` пользователя (верификация партнёра).
    Создаёт пользователя при отсутствии записи.
    """
    key = exchange.strip().lower()
    if not key:
        return
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT registered_exchanges FROM users WHERE telegram_id = ?;",
                (telegram_id,),
            ) as cur:
                row = await cur.fetchone()
            now = _utc_now_int()
            if row is None:
                await db.execute(
                    """
                    INSERT INTO users (
                        telegram_id, username, last_request_time, free_trials_left,
                        registered_exchanges, status, created_at
                    )
                    VALUES (?, NULL, NULL, 3, ?, 'free', ?);
                    """,
                    (telegram_id, json.dumps([key], ensure_ascii=False), now),
                )
            else:
                raw = row["registered_exchanges"] or "[]"
                try:
                    arr = json.loads(raw)
                except json.JSONDecodeError:
                    arr = []
                if not isinstance(arr, list):
                    arr = []
                normalized = [str(x).lower().strip() for x in arr if str(x).strip()]
                if key not in normalized:
                    normalized.append(key)
                await db.execute(
                    "UPDATE users SET registered_exchanges = ? WHERE telegram_id = ?;",
                    (json.dumps(sorted(set(normalized)), ensure_ascii=False), telegram_id),
                )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("add_verified_exchange: %s", exc)
        raise


async def get_exchange_config(exchange_name: str) -> dict[str, Any] | None:
    """
    Активная конфигурация биржи: exchange_name, referral_link, is_active.
    Ключ сравнивается в нижнем регистре.
    """
    key = exchange_name.strip().lower()
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT exchange_name, referral_link, is_active
                FROM exchange_config
                WHERE lower(exchange_name) = ? AND is_active = 1;
                """,
                (key,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            return {
                "exchange_name": str(row["exchange_name"]),
                "referral_link": str(row["referral_link"]),
                "is_active": bool(row["is_active"]),
            }
    except aiosqlite.Error as exc:
        logger.exception("get_exchange_config: %s", exc)
        raise


async def get_referral_link(exchange_name: str) -> str | None:
    """URL рефералки для биржи или None."""
    row = await get_exchange_config(exchange_name)
    return str(row["referral_link"]) if row else None


async def get_all_active_referrals() -> dict[str, str]:
    """exchange_name (lower) -> referral_link для активных строк."""
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT exchange_name, referral_link FROM exchange_config WHERE is_active = 1;"
            ) as cur:
                rows = await cur.fetchall()
        return {str(r["exchange_name"]).lower(): str(r["referral_link"]) for r in rows}
    except aiosqlite.Error as exc:
        logger.exception("get_all_active_referrals: %s", exc)
        raise


async def user_has_registered_exchange(telegram_id: int, exchange_key: str) -> bool:
    """Есть ли биржа в JSON ``registered_exchanges``."""
    user = await get_user(telegram_id)
    if not user:
        return False
    ex = exchange_key.strip().lower()
    try:
        arr = json.loads(user["registered_exchanges"] or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(arr, list):
        return False
    return ex in {str(x).lower().strip() for x in arr if str(x).strip()}


async def maybe_upgrade_premium_if_eligible(telegram_id: int) -> bool:
    """≥ 2 бирж в профиле → ``premium``."""
    user = await get_user(telegram_id)
    if not user:
        return False
    try:
        arr = json.loads(user["registered_exchanges"] or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(arr, list):
        return False
    n = len({str(x).lower().strip() for x in arr if str(x).strip()})
    if n < 2:
        return False
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            await db.execute(
                "UPDATE users SET status = 'premium' WHERE telegram_id = ?;",
                (telegram_id,),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("maybe_upgrade_premium_if_eligible: %s", exc)
        raise
    return True


async def get_trials_and_status(telegram_id: int) -> tuple[int, str]:
    """Оставшиеся бесплатные попытки и статус (free/premium)."""
    user = await get_user(telegram_id)
    if not user:
        return 3, "free"
    return int(user["free_trials_left"]), str(user["status"])


async def _increment_cache_hit(db: aiosqlite.Connection) -> None:
    await db.execute("UPDATE cache_metrics SET hits = hits + 1 WHERE id = 1;")


async def _increment_cache_miss(db: aiosqlite.Connection) -> None:
    await db.execute("UPDATE cache_metrics SET misses = misses + 1 WHERE id = 1;")


async def check_rate_limit(telegram_id: int) -> dict[str, Any]:
    """
    Анти-спам: если с ``last_request_time`` прошло меньше ``SPAM_LIMIT_SECONDS`` — запрет.
    Новый пользователь или ``last_request_time IS NULL`` — разрешено.
    """
    now = _utc_now_int()
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT last_request_time FROM users WHERE telegram_id = ?;",
                (telegram_id,),
            ) as cur:
                row = await cur.fetchone()
    except aiosqlite.Error as exc:
        logger.exception("check_rate_limit: %s", exc)
        raise

    if row is None or row["last_request_time"] is None:
        return {"allowed": True, "wait_seconds": 0}

    last = int(row["last_request_time"])
    elapsed = now - last
    if elapsed < config.SPAM_LIMIT_SECONDS:
        wait = config.SPAM_LIMIT_SECONDS - elapsed
        logger.info("Спам-блок для user %s", telegram_id)
        return {"allowed": False, "wait_seconds": wait}
    return {"allowed": True, "wait_seconds": 0}


async def get_cached_analysis(
    telegram_id: int,
    image_hash: str,
    exchange_name: str,
    ttl_seconds: int | None = None,
) -> str | None:
    """
    Возвращает текст анализа из кэша, если запись есть и не старше TTL.
    При ошибке БД — ``None`` (fail-open: пропускаем кэш, продолжаем пайплайн).
    """
    ttl = ttl_seconds if ttl_seconds is not None else config.CACHE_TTL_SECONDS
    ex = exchange_name.strip().lower()
    now = _utc_now_int()
    cutoff = now - ttl

    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT analysis_result, created_at FROM image_cache
                WHERE telegram_id = ? AND image_hash = ? AND lower(exchange_name) = ?;
                """,
                (telegram_id, image_hash, ex),
            ) as cur:
                row = await cur.fetchone()

            if row is None:
                await _increment_cache_miss(db)
                await db.commit()
                logger.info("Кэш мисс, продолжаем анализ")
                return None

            created = int(row["created_at"])
            if created < cutoff:
                await _increment_cache_miss(db)
                await db.commit()
                logger.debug(
                    "Кэш мисс: устаревшая запись created_at=%s cutoff=%s hash=%s",
                    created,
                    cutoff,
                    image_hash[:16],
                )
                logger.info("Кэш мисс, продолжаем анализ")
                return None

            await _increment_cache_hit(db)
            await db.commit()
            logger.info("Кэш хит для хэша %s", image_hash)
            return str(row["analysis_result"])
    except aiosqlite.Error as exc:
        logger.warning(
            "get_cached_analysis: БД недоступна, кэш пропущен (fail-open): %s",
            exc,
        )
        return None


async def save_to_cache(
    telegram_id: int,
    image_hash: str,
    exchange_name: str,
    analysis_result: str,
) -> None:
    """Сохраняет или обновляет результат анализа в ``image_cache``."""
    now = _utc_now_int()
    ex = exchange_name.strip().lower()
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            await db.execute(
                """
                INSERT INTO image_cache (telegram_id, image_hash, exchange_name, analysis_result, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id, image_hash, exchange_name) DO UPDATE SET
                    analysis_result = excluded.analysis_result,
                    created_at = excluded.created_at;
                """,
                (telegram_id, image_hash, ex, analysis_result, now),
            )
            await db.commit()
    except aiosqlite.Error as exc:
        logger.exception("save_to_cache: %s", exc)
        raise


async def clear_user_cache(telegram_id: int) -> int:
    """Удаляет все записи кэша изображений для пользователя (отладка)."""
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            cur = await db.execute(
                "DELETE FROM image_cache WHERE telegram_id = ?;",
                (telegram_id,),
            )
            await db.commit()
            return cur.rowcount if cur.rowcount is not None else 0
    except aiosqlite.Error as exc:
        logger.exception("clear_user_cache: %s", exc)
        raise


async def get_cache_stats() -> dict[str, Any]:
    """
    Число строк в ``image_cache``, счётчики попаданий/промахов и доля хитов.
    """
    try:
        async with aiosqlite.connect(str(config.DB_PATH)) as db:
            async with db.execute("SELECT COUNT(*) FROM image_cache;") as cur:
                row_n = await cur.fetchone()
            n = int(row_n[0]) if row_n else 0
            async with db.execute("SELECT hits, misses FROM cache_metrics WHERE id = 1;") as cur:
                row_m = await cur.fetchone()
            hits = int(row_m[0]) if row_m else 0
            misses = int(row_m[1]) if row_m else 0
        total = hits + misses
        hit_rate = (hits / total) if total else None
        return {
            "cache_rows": n,
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
        }
    except aiosqlite.Error as exc:
        logger.exception("get_cache_stats: %s", exc)
        raise
