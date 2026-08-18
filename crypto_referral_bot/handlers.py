import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from database import (
    create_user,
    get_user,
    check_rate_limit,
    update_last_request,
    get_cached_analysis,
    save_to_cache,
    decrement_trials,
    get_trials_and_status,
    user_has_registered_exchange,
    add_verified_exchange,
    maybe_upgrade_premium_if_eligible,
    get_all_active_referrals,
    get_referral_link,
)
from ai_service import detect_exchange_from_image, analyze_chart_image
from image_utils import calculate_image_hash
from keyboards import (
    get_exchange_selection_keyboard,
    get_partner_links_keyboard,
    referral_link_keyboard,
)
from texts import (
    MSG_WELCOME,
    MSG_SPAM_BLOCK,
    MSG_CACHED_RESPONSE,
    MSG_UNKNOWN_EXCHANGE,
    MSG_OTHER_EXCHANGE,
    MSG_NOT_PARTNER,
    MSG_TRIALS_EXHAUSTED,
    MSG_ANALYSIS_ERROR,
    MSG_ANALYSIS_SUCCESS,
    MSG_PREMIUM_UNLOCKED,
)
from config import SUPPORTED_EXCHANGES, PREMIUM_MIN_EXCHANGES

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await create_user(user.id, user.username)
    await message.answer(MSG_WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Отправьте скриншот графика криптовалюты, и ИИ проведёт анализ.\n\n"
        "Команды:\n"
        "/start — приветствие\n"
        "/status — ваш статус и лимиты\n"
        "/exchanges — список партнёрских бирж"
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    trials, status = await get_trials_and_status(message.from_user.id)
    text = (
        f"Статус: {status.upper()}\n"
        f"Бесплатные попытки: {trials}"
    )
    await message.answer(text)


@router.message(Command("exchanges"))
async def cmd_exchanges(message: Message):
    links = await get_all_active_referrals()
    if links:
        kb = get_partner_links_keyboard(links)
        await message.answer("Партнёрские биржи:", reply_markup=kb)
    else:
        await message.answer("Партнёрские биржи пока не настроены.")


@router.message(F.photo)
async def handle_photo(message: Message):
    user = message.from_user
    telegram_id = user.id

    await create_user(telegram_id, user.username)

    rate = await check_rate_limit(telegram_id)
    if not rate["allowed"]:
        wait_min = round(rate["wait_seconds"] / 60, 1)
        await message.answer(MSG_SPAM_BLOCK.format(minutes=wait_min))
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = (await message.bot.download_file(file.file_path)).read()

    if image_bytes is None:
        await message.answer(MSG_ANALYSIS_ERROR)
        return

    image_hash = calculate_image_hash(image_bytes)

    trials, status = await get_trials_and_status(telegram_id)

    exchange = await detect_exchange_from_image(image_bytes)

    if exchange == "unknown":
        await message.answer(
            MSG_UNKNOWN_EXCHANGE,
            reply_markup=get_exchange_selection_keyboard(),
        )
        return

    if exchange not in SUPPORTED_EXCHANGES:
        links = await get_all_active_referrals()
        await message.answer(
            MSG_OTHER_EXCHANGE,
            reply_markup=get_partner_links_keyboard(links) if links else None,
        )
        return

    is_partner = await user_has_registered_exchange(telegram_id, exchange)
    if not is_partner:
        ref_link = await get_referral_link(exchange)
        kb = referral_link_keyboard(ref_link) if ref_link else None
        await message.answer(
            MSG_NOT_PARTNER.format(exchange=exchange),
            reply_markup=kb,
        )
        return

    if status != "premium" and trials <= 0:
        links = await get_all_active_referrals()
        await message.answer(
            MSG_TRIALS_EXHAUSTED,
            reply_markup=get_partner_links_keyboard(links) if links else None,
        )
        return

    cached = await get_cached_analysis(telegram_id, image_hash, exchange)
    if cached:
        await message.answer(MSG_CACHED_RESPONSE.format(analysis=cached))
        return

    await update_last_request(telegram_id)

    result = await analyze_chart_image(image_bytes, exchange)
    if not result:
        await message.answer(MSG_ANALYSIS_ERROR)
        return

    await save_to_cache(telegram_id, image_hash, exchange, result)

    if status != "premium":
        await decrement_trials(telegram_id)

    await message.answer(MSG_ANALYSIS_SUCCESS.format(analysis=result))


@router.callback_query(F.data.startswith("exchange:"))
async def callback_exchange(callback: CallbackQuery):
    data = callback.data.split(":", 1)[1]
    telegram_id = callback.from_user.id

    if data == "other":
        links = await get_all_active_referrals()
        await callback.message.edit_text(
            MSG_OTHER_EXCHANGE,
            reply_markup=get_partner_links_keyboard(links) if links else None,
        )
        await callback.answer()
        return

    if data not in SUPPORTED_EXCHANGES:
        await callback.answer("Неизвестная биржа", show_alert=True)
        return

    is_partner = await user_has_registered_exchange(telegram_id, data)
    if not is_partner:
        ref_link = await get_referral_link(data)
        kb = referral_link_keyboard(ref_link) if ref_link else None
        await callback.message.edit_text(
            MSG_NOT_PARTNER.format(exchange=data),
            reply_markup=kb,
        )
        await callback.answer()
        return

    await add_verified_exchange(telegram_id, data)
    upgraded = await maybe_upgrade_premium_if_eligible(telegram_id)
    if upgraded:
        await callback.message.edit_text(MSG_PREMIUM_UNLOCKED)
    else:
        await callback.message.edit_text(
            f"Биржа {data.upper()} добавлена в ваш профиль.\n"
            "Отправьте скриншот графика для анализа."
        )
    await callback.answer()
