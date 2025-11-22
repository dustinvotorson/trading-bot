import asyncio
import aiohttp
import logging

logging.basicConfig(level=logging.DEBUG)


async def check_hype_detailed():
    """Подробная проверка HYPE на Binance"""
    print("🔍 Детальная проверка HYPE на Binance...")

    async with aiohttp.ClientSession() as session:
        # Проверяем разные варианты символа
        symbols_to_check = ['HYPE', 'HYPEUSDT', 'HYPE/USDT']

        for symbol in symbols_to_check:
            try:
                # Нормализуем символ
                normalized = symbol.upper().replace('/', '')
                if not normalized.endswith('USDT'):
                    normalized += 'USDT'

                print(f"\n🔍 Проверяем символ: {symbol} -> {normalized}")

                url = f"https://api.binance.com/api/v3/ticker/price?symbol={normalized}"
                print(f"📡 URL: {url}")

                async with session.get(url) as response:
                    print(f"📊 HTTP статус: {response.status}")

                    if response.status == 200:
                        data = await response.json()
                        print(f"✅ Символ валиден! Цена: {data['price']}")
                    else:
                        error_text = await response.text()
                        print(f"❌ Ошибка: {error_text}")

            except Exception as e:
                print(f"💥 Исключение: {e}")


asyncio.run(check_hype_detailed())