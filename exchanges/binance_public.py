import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class BinancePublicAPI:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        self.session = None
        self.valid_symbols_cache = set()  # Кеш для валидных символов

    async def get_session(self) -> aiohttp.ClientSession:
        """Создает или возвращает существующую сессию"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def is_symbol_valid(self, symbol: str) -> bool:
        """Проверяет, существует ли символ на Binance с улучшенной диагностикой"""
        try:
            normalized_symbol = self.normalize_symbol(symbol)

            # Если уже проверяли этот символ, используем кеш
            if normalized_symbol in self.valid_symbols_cache:
                return True

            session = await self.get_session()
            url = f"{self.base_url}/ticker/price?symbol={normalized_symbol}"

            async with session.get(url) as response:
                if response.status == 200:
                    self.valid_symbols_cache.add(normalized_symbol)
                    logger.info(f"✅ Символ {normalized_symbol} валиден")
                    return True
                else:
                    # Пробуем найти альтернативные котируемые активы
                    alternative_symbols = await self.find_alternative_symbols(symbol)
                    if alternative_symbols:
                        logger.info(f"🔍 Найдены альтернативы для {symbol}: {alternative_symbols}")
                        # Используем первую найденную альтернативу
                        best_alternative = alternative_symbols[0]
                        self.valid_symbols_cache.add(best_alternative)
                        logger.info(f"🎯 Используем альтернативу: {best_alternative}")
                        return True
                    else:
                        logger.warning(f"🚫 Символ {normalized_symbol} невалиден: HTTP {response.status}")
                        return False

        except Exception as e:
            logger.error(f"❌ Ошибка проверки символа {symbol}: {e}")
            return False

    async def find_alternative_symbols(self, base_symbol: str) -> list:
        """Ищет альтернативные торговые пары для базового символа"""
        try:
            base_symbol = base_symbol.upper()
            session = await self.get_session()
            url = "https://api.binance.com/api/v3/exchangeInfo"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    symbols = data['symbols']

                    # Ищем все пары где базовый актив совпадает
                    alternatives = []
                    for symbol_info in symbols:
                        if symbol_info['baseAsset'] == base_symbol and symbol_info['status'] == 'TRADING':
                            alternatives.append(symbol_info['symbol'])

                    # Сортируем по приоритету котируемых активов
                    quote_priority = ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB', 'USD', 'EUR']
                    alternatives.sort(key=lambda x: (
                        [quote in x for quote in quote_priority].index(True)
                        if any(quote in x for quote in quote_priority)
                        else len(quote_priority)
                    ))

                    return alternatives
                else:
                    return []

        except Exception as e:
            logger.error(f"❌ Ошибка поиска альтернатив для {base_symbol}: {e}")
            return []

    async def is_symbol_valid(self, symbol: str) -> bool:
        """Проверяет, существует ли символ на Binance с улучшенной диагностикой"""
        try:
            normalized_symbol = self.normalize_symbol(symbol)

            # Если уже проверяли этот символ, используем кеш
            if normalized_symbol in self.valid_symbols_cache:
                return True

            session = await self.get_session()
            url = f"{self.base_url}/ticker/price?symbol={normalized_symbol}"

            async with session.get(url) as response:
                if response.status == 200:
                    self.valid_symbols_cache.add(normalized_symbol)
                    logger.info(f"✅ Символ {normalized_symbol} валиден")
                    return True
                else:
                    # Пробуем найти альтернативные котируемые активы
                    alternative_symbols = await self.find_alternative_symbols(symbol)
                    if alternative_symbols:
                        logger.info(f"🔍 Найдены альтернативы для {symbol}: {alternative_symbols}")
                        # Используем первую найденную альтернативу
                        best_alternative = alternative_symbols[0]
                        self.valid_symbols_cache.add(best_alternative)
                        logger.info(f"🎯 Используем альтернативу: {best_alternative}")
                        return True
                    else:
                        logger.warning(f"🚫 Символ {normalized_symbol} невалиден: HTTP {response.status}")
                        return False

        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                logger.critical(f"❌ Binance: КРИТИЧЕСКАЯ ОШИБКА Event loop при проверке символа {symbol}")
                raise  # Пробрасываем выше для обработки в multi_exchange
            else:
                logger.error(f"❌ Binance: RuntimeError проверки символа {symbol}: {e}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка проверки символа {symbol}: {e}")
            return False

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Получает текущую цену символа через публичный API с поддержкой альтернатив"""
        try:
            # Сначала проверяем валидность символа (это также найдет альтернативы)
            if not await self.is_symbol_valid(symbol):
                return None

            # Получаем нормализованный символ (возможно альтернативный)
            normalized_symbol = self.normalize_symbol(symbol)

            # Если символ не в кеше, значит он невалиден и у нас нет альтернатив
            if normalized_symbol not in self.valid_symbols_cache:
                # Пробуем найти альтернативы вручную
                alternatives = await self.find_alternative_symbols(symbol)
                if alternatives:
                    normalized_symbol = alternatives[0]
                    self.valid_symbols_cache.add(normalized_symbol)
                else:
                    return None

            session = await self.get_session()
            url = f"{self.base_url}/ticker/price?symbol={normalized_symbol}"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['price'])
                    logger.debug(f"💰 Цена {normalized_symbol}: {price}")
                    return price
                else:
                    logger.error(f"❌ Ошибка получения цены для {normalized_symbol}: HTTP {response.status}")
                    return None

        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                logger.critical(f"❌ Binance: КРИТИЧЕСКАЯ ОШИБКА Event loop при получении цены {symbol}")
                raise
            else:
                logger.error(f"❌ Binance: RuntimeError получения цены {symbol}: {e}")
                return None
        except aiohttp.ClientError as e:
            logger.error(f"❌ Сетевая ошибка для {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка для {symbol}: {e}")
            return None

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Получает информацию о символе через публичный API"""
        try:
            symbol = self.normalize_symbol(symbol)
            session = await self.get_session()
            url = f"{self.base_url}/exchangeInfo?symbol={symbol}"

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"❌ Ошибка получения информации о {symbol}: HTTP {response.status}")
                    return {}

        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о {symbol}: {e}")
            return {}

    def normalize_symbol(self, symbol: str) -> str:
        """Приводит символ к формату Binance с поддержкой разных котируемых активов"""
        symbol = symbol.upper().replace('/', '')

        # Популярные котируемые активы на Binance
        quote_assets = ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB', 'USD', 'EUR']

        # Если символ уже заканчивается на известный котируемый актив, оставляем как есть
        for quote in quote_assets:
            if symbol.endswith(quote):
                return symbol

        # Пробуем добавить USDT (самый популярный)
        return symbol + 'USDT'

    async def close(self):
        """Закрывает сессию"""
        if self.session and not self.session.closed:
            await self.session.close()


# Глобальный экземпляр
binance_public = BinancePublicAPI()
