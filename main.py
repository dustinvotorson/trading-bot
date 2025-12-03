import asyncio
import logging
import signal
import sys
import time
from bot.telethon_bot import run_telethon_bot
from web.app import start_web_interface
from exchanges.multi_exchange import multi_exchange

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def shutdown():
    """Корректное завершение работы"""
    print("🔄 Завершаем работу...")
    await multi_exchange.close()
    sys.exit(0)


def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    asyncio.create_task(shutdown())


def main():
    print("🚀 Запускаем Trading Bot + Web Dashboard...")
    print("🔧 Мульти-биржа: Binance + BingX")

    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Запускаем веб-интерфейс
        start_web_interface()

        # Запускаем бота с БЕСКОНЕЧНЫМ ПЕРЕЗАПУСКОМ
        restart_count = 0
        max_restarts = 100  # Максимальное количество перезапусков

        while restart_count < max_restarts:
            try:
                asyncio.run(run_telethon_bot())
            except KeyboardInterrupt:
                asyncio.run(shutdown())
                break
            except Exception as e:
                restart_count += 1
                print(f"⚠️  Бот упал с ошибкой: {e}")
                print(f"🔄 Перезапуск #{restart_count} через 10 секунд...")
                time.sleep(10)  # Ждем 10 секунд перед перезапуском

                # Если много падений, ждем дольше
                if restart_count > 5:
                    time.sleep(60)
                if restart_count > 10:
                    time.sleep(300)  # 5 минут
    except KeyboardInterrupt:
        asyncio.run(shutdown())


if __name__ == "__main__":
    main()
