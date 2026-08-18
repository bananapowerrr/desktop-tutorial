import base64
import logging
import aiohttp
import async_timeout
from typing import Optional
from config import OLLAMA_VISION_MODEL, OLLAMA_URL, OLLAMA_ANALYZE_TIMEOUT_SECONDS, CHART_ANALYSIS_PROMPT
from texts import DISCLAIMER

logger = logging.getLogger(__name__)


async def detect_exchange_from_image(image_bytes: bytes) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with async_timeout.timeout(30):
                payload = {
                    "model": OLLAMA_VISION_MODEL,
                    "prompt": (
                        "Определи название криптовалютной биржи на этом скриншоте. "
                        "Ответь ТОЛЬКО одним словом: binance, bybit, okx, bingx, mexc или unknown. "
                        "Без пояснений."
                    ),
                    "images": [base64.b64encode(image_bytes).decode("utf-8")],
                }
                async with session.post(f"{OLLAMA_URL}/api/generate", json=payload) as resp:
                    if resp.status != 200:
                        logger.error("Ollama detect status %s", resp.status)
                        return "unknown"
                    data = await resp.json()
                    answer = data.get("response", "").strip().lower()
                    for name in ("binance", "bybit", "okx", "bingx", "mexc"):
                        if name in answer:
                            return name
                    return "unknown"
    except Exception as e:
        logger.error("detect_exchange_from_image: %s", e)
        return "unknown"


async def analyze_chart_image(
    image_bytes: bytes,
    exchange_name: str,
) -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with async_timeout.timeout(OLLAMA_ANALYZE_TIMEOUT_SECONDS):
                prompt = (
                    f"{CHART_ANALYSIS_PROMPT}\n\n"
                    f"Биржа: {exchange_name}"
                )
                payload = {
                    "model": OLLAMA_VISION_MODEL,
                    "prompt": prompt,
                    "images": [base64.b64encode(image_bytes).decode("utf-8")],
                }
                async with session.post(f"{OLLAMA_URL}/api/generate", json=payload) as resp:
                    if resp.status != 200:
                        raise Exception(f"Ollama error: {resp.status}")
                    data = await resp.json()
                    result = data.get("response")
                    if not result:
                        raise Exception("Empty response from Ollama")
                    return f"{result}\n\n{DISCLAIMER}"
    except Exception as e:
        logger.error("analyze_chart_image: %s", e)
        return None
