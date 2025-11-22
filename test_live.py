import asyncio
import logging
from bot.telegram_bot import TradingBot
from exchanges.binance_public import binance_public

# Настройка логирования для теста
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


async def test_binance():
    """Тестируем подключение к Binance"""
    print("🔍 Тестируем Binance API...")
    price = await binance_public.get_current_price("BTCUSDT")
    print(f"✅ Текущая цена BTCUSDT: {price}")

    price = await binance_public.get_current_price("ETHUSDT")
    print(f"✅ Текущая цена ETHUSDT: {price}")


async def test_parser():
    """Тестируем парсер на реальном сигнале"""
    from parser.advanced_parser import advanced_parser

    test_signal = """
    BTCUSDT LONG

    Вход: 65000
    Тейки: 67000, 69000, 72000
    Стоп: 63000
    """

    signal = advanced_parser.parse_signal(test_signal, "Test Channel")
    print(f"✅ Тестовый сигнал распознан:")
    print(f"   Символ: {signal.symbol}")
    print(f"   Вход: {signal.entry_prices}")
    print(f"   Тейки: {signal.take_profits}")
    print(f"   Стоп: {signal.stop_loss}")


if __name__ == "__main__":
    print("🧪 ТЕСТИРУЕМ СИСТЕМУ В РЕАЛЬНОМ ВРЕМЕНИ")
    asyncio.run(test_binance())
    asyncio.run(test_parser())
    print("\n🎉 Система готова к работе!")