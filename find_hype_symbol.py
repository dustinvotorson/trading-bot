import asyncio
import logging
from exchanges.bingx_public import bingx_api
from exchanges.multi_exchange import multi_exchange

logging.basicConfig(level=logging.INFO)


async def check_hype_on_bingx():
    print("🔍 Проверяем HYPE на BingX...")

    # Проверяем напрямую через BingX API
    is_valid = await bingx_api.is_symbol_valid("HYPE")
    print(f"✅ HYPE валиден на BingX: {is_valid}")

    if is_valid:
        price = await bingx_api.get_current_price("HYPE")
        print(f"💰 Текущая цена HYPE на BingX: {price}")

    # Проверяем через multi_exchange
    print("\n🔍 Проверяем HYPE через MultiExchange...")
    is_valid_multi = await multi_exchange.is_symbol_valid("HYPE")
    print(f"✅ HYPE валиден через MultiExchange: {is_valid_multi}")

    if is_valid_multi:
        exchange = await multi_exchange.find_symbol_exchange("HYPE")
        price_multi = await multi_exchange.get_current_price("HYPE")
        print(f"💰 Цена HYPE на {exchange}: {price_multi}")


async def check_other_symbols():
    """Проверяем другие проблемные символы"""
    symbols_to_check = ['HYPE', 'ZK', 'GMT', 'PORT3']

    print(f"\n🔍 Проверяем символы на разных биржах:")
    for symbol in symbols_to_check:
        is_valid = await multi_exchange.is_symbol_valid(symbol)
        if is_valid:
            exchange = await multi_exchange.find_symbol_exchange(symbol)
            price = await multi_exchange.get_current_price(symbol)
            print(f"✅ {symbol}: найдено на {exchange} по цене {price}")
        else:
            print(f"❌ {symbol}: не найден ни на одной бирже")


if __name__ == "__main__":
    asyncio.run(check_hype_on_bingx())
    asyncio.run(check_other_symbols())