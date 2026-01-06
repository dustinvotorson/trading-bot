import asyncio
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
        self._event_loop_warning_logged = False

    def _check_event_loop(self) -> bool:
        """Проверяет состояние event loop. Возвращает True если есть проблемы."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                if not self._event_loop_warning_logged:
                    logger.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Event loop закрыт! Требуется перезапуск бота.")
                    self._event_loop_warning_logged = True
                return True
            return False
        except RuntimeError as e:
            if "no running event loop" in str(e) or "no current event loop" in str(e):
                if not self._event_loop_warning_logged:
                    logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Нет работающего event loop! {e}")
                    self._event_loop_warning_logged = True
                return True
            # Для других RuntimeError тоже считаем проблемой
            if not self._event_loop_warning_logged:
                logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА RuntimeError: {e}")
                self._event_loop_warning_logged = True
            return True
        except Exception as e:
            logger.error(f"⚠️  Неизвестная ошибка проверки event loop: {e}")
            return False

    async def get_current_price(self, symbol: str) -> Tuple[Optional[float], str]:
        """Получает цену с любой доступной биржи, возвращает цену и имя биржи"""
        # Сначала проверяем состояние event loop
        if self._check_event_loop():
            return None, "Event loop closed"

        for exchange_name, exchange_api in self.exchanges:
            try:
                # Сначала проверяем валидность символа
                if await exchange_api.is_symbol_valid(symbol):
                    price = await exchange_api.get_current_price(symbol)
                    if price and price > 0:
                        logger.info(f"✅ {exchange_name}: Цена для {symbol} = {price}")
                        # Сброс флага предупреждения если все работает
                        self._event_loop_warning_logged = False
                        return price, exchange_name
                    else:
                        logger.warning(f"⚠️ {exchange_name}: Не удалось получить цену для {symbol}")
            except RuntimeError as e:
                if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                    logger.critical(f"❌ {exchange_name}: КРИТИЧЕСКАЯ ОШИБКА - Event loop закрыт для {symbol}")
                    return None, "Event loop closed"
                else:
                    logger.error(f"❌ {exchange_name}: RuntimeError для {symbol}: {e}")
                    continue
            except Exception as e:
                logger.error(f"❌ {exchange_name}: Ошибка для {symbol}: {e}")
                continue

        logger.error(f"🚫 Все биржи: Не удалось получить цену для {symbol}")
        return None, "None"

    async def is_symbol_available(self, symbol: str) -> Tuple[bool, str]:
        """Проверяет доступность символа на любой бирже, возвращает статус и имя биржи"""
        # Сначала проверяем состояние event loop
        if self._check_event_loop():
            return False, "Event loop closed"

        for exchange_name, exchange_api in self.exchanges:
            try:
                if await exchange_api.is_symbol_valid(symbol):
                    logger.info(f"✅ {exchange_name}: Символ {symbol} доступен")
                    # Сброс флага предупреждения если все работает
                    self._event_loop_warning_logged = False
                    return True, exchange_name
            except RuntimeError as e:
                if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                    logger.critical(f"❌ {exchange_name}: КРИТИЧЕСКАЯ ОШИБКА - Event loop закрыт при проверке {symbol}")
                    return False, "Event loop closed"
                else:
                    logger.error(f"❌ {exchange_name}: RuntimeError проверки {symbol}: {e}")
                    continue
            except Exception as e:
                logger.error(f"❌ {exchange_name}: Ошибка проверки {symbol}: {e}")
                continue

        logger.error(f"🚫 Все биржи: Символ {symbol} недоступен")
        return False, "None"

    async def close(self):
        """Закрывает все сессии"""
        for _, exchange_api in self.exchanges:
            try:
                await exchange_api.close()
            except:
                pass


# Глобальный экземпляр
multi_exchange = MultiExchangeAPI()
