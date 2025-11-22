import logging
from typing import Optional, Tuple
from .binance_public import binance_public
from .bingx_public import bingx_public

logger = logging.getLogger(__name__)


class MultiExchangeAPI:
    def __init__(self):
        self.exchanges = [
            ("Binance", binance_public),
            ("BingX", bingx_public)
        ]

    async def get_current_price(self, symbol: str) -> Tuple[Optional[float], str]:
        """Получает цену с любой доступной биржи, возвращает цену и имя биржи"""
        for exchange_name, exchange_api in self.exchanges:
            try:
                # Сначала проверяем валидность символа
                if await exchange_api.is_symbol_valid(symbol):
                    price = await exchange_api.get_current_price(symbol)
                    if price and price > 0:
                        logger.info(f"✅ {exchange_name}: Цена для {symbol} = {price}")
                        return price, exchange_name
                    else:
                        logger.warning(f"⚠️ {exchange_name}: Не удалось получить цену для {symbol}")
            except Exception as e:
                logger.error(f"❌ {exchange_name}: Ошибка для {symbol}: {e}")
                continue

        logger.error(f"🚫 Все биржи: Не удалось получить цену для {symbol}")
        return None, "None"

    async def is_symbol_available(self, symbol: str) -> Tuple[bool, str]:
        """Проверяет доступность символа на любой бирже, возвращает статус и имя биржи"""
        for exchange_name, exchange_api in self.exchanges:
            try:
                if await exchange_api.is_symbol_valid(symbol):
                    logger.info(f"✅ {exchange_name}: Символ {symbol} доступен")
                    return True, exchange_name
            except Exception as e:
                logger.error(f"❌ {exchange_name}: Ошибка проверки {symbol}: {e}")
                continue

        logger.error(f"🚫 Все биржи: Символ {symbol} недоступен")
        return False, "None"

    async def close(self):
        """Закрывает все сессии"""
        for _, exchange_api in self.exchanges:
            await exchange_api.close()


# Глобальный экземпляр
multi_exchange = MultiExchangeAPI()