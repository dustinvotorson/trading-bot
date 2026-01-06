import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class BingXPublicAPI:
    def __init__(self):
        self.base_url = "https://open-api.bingx.com/openApi"
        self.session = None
        self.valid_symbols_cache = set()

    async def get_session(self) -> aiohttp.ClientSession:
        """Создает или возвращает существующую сессию"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def is_symbol_valid(self, symbol: str) -> bool:
        """Проверяет, существует ли символ на BingX"""
        try:
            normalized_symbol = self.normalize_symbol(symbol)

            if normalized_symbol in self.valid_symbols_cache:
                return True

            session = await self.get_session()
            url = f"{self.base_url}/swap/v2/quote/price"
            params = {"symbol": normalized_symbol}

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0 and data.get('data'):
                        self.valid_symbols_cache.add(normalized_symbol)
                        logger.info(f"✅ BingX: Символ {normalized_symbol} валиден")
                        return True
                    else:
                        logger.warning(
                            f"🚫 BingX: Символ {normalized_symbol} невалиден - {data.get('msg', 'Unknown error')}")
                        return False
                else:
                    logger.warning(f"🚫 BingX: Ошибка HTTP {response.status} для {normalized_symbol}")
                    return False

        except Exception as e:
            logger.error(f"❌ BingX: Ошибка проверки символа {symbol}: {e}")
            return False

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Получает текущую цену символа через BingX API"""
        try:
            normalized_symbol = self.normalize_symbol(symbol)

            session = await self.get_session()
            url = f"{self.base_url}/swap/v2/quote/price"
            params = {"symbol": normalized_symbol}

            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0 and data.get('data'):
                        price_data = data['data']
                        if isinstance(price_data, list) and len(price_data) > 0:
                            price = float(price_data[0].get('price', 0))
                        else:
                            price = float(price_data.get('price', 0))

                        logger.debug(f"💰 BingX: Цена {normalized_symbol}: {price}")
                        return price
                    else:
                        logger.error(
                            f"❌ BingX: Ошибка получения цены для {normalized_symbol}: {data.get('msg', 'Unknown error')}")
                        return None
                else:
                    logger.error(f"❌ BingX: Ошибка HTTP {response.status} для {normalized_symbol}")
                    return None

        except Exception as e:
            logger.error(f"❌ BingX: Неизвестная ошибка для {symbol}: {e}")
            return None

    def normalize_symbol(self, symbol: str) -> str:
        """Приводит символ к формату BingX"""
        symbol = symbol.upper().replace('/', '')

        # BingX использует формат SYMBOL-USDT (с дефисом)
        quote_assets = ['USDT', 'BUSD', 'BTC', 'ETH', 'USD']

        for quote in quote_assets:
            if symbol.endswith(quote):
                base = symbol[:-len(quote)]
                return f"{base}-{quote}"

        # Если не нашли котируемый актив, добавляем USDT
        return f"{symbol}-USDT"

    async def get_swap_symbols(self) -> list:
        """Получает список всех доступных символов на BingX"""
        try:
            session = await self.get_session()
            url = f"{self.base_url}/swap/v2/quote/contracts"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0:
                        symbols = [item['symbol'] for item in data.get('data', [])]
                        return symbols
                return []
        except Exception as e:
            logger.error(f"❌ BingX: Ошибка получения списка символов: {e}")
            return []

    async def close(self):
        """Закрывает сессию"""
        if self.session and not self.session.closed:
            await self.session.close()


# Глобальный экземпляр
bingx_public = BingXPublicAPI()
