from telegram.ext import Application, MessageHandler, filters
from parser.advanced_parser import advanced_parser
from exchanges.binance_public import binance_public
from config import TELEGRAM_BOT_TOKEN
import logging
import asyncio


async def list_chats(self):
    """Выводит список чатов, где находится бот"""
    async with self.app:
        chats = await self.app.bot.get_updates()
        print("🤖 Бот находится в следующих чатах:")
        for update in chats:
            if update.effective_chat:
                chat = update.effective_chat
                print(f"   - {chat.title or 'Unknown'} (@{chat.username or 'no_username'})")
# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("❌ Токен бота не найден! Проверь файл .env")

        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.active_signals = {}  # Словарь активных сигналов
        logger.info("✅ Бот инициализирован")

    async def handle_channel_message(self, update, context):
        """Обрабатывает сообщения из каналов"""
        # Проверяем, что сообщение не от самого бота
        if update.message.from_user and update.message.from_user.is_bot:
            return

        message_text = update.message.text
        chat_title = update.effective_chat.title or "Unknown Chat"
        chat_username = update.effective_chat.username or "unknown"

        # Пропускаем сообщения без текста
        if not message_text or message_text.strip() == '':
            return

        logger.info(f"📨 Сообщение из '{chat_title}' (@{chat_username}): {message_text[:100]}...")

        try:
            # Парсим сигнал
            signal = advanced_parser.parse_signal(message_text, chat_title)

            # Если символ не распознан, пропускаем
            if signal.symbol == "UNKNOWN":
                logger.warning(f"⚠️  Символ не распознан, пропускаем сообщение")
                return

            # Для рыночных входов (как Serebrov) получаем текущую цену
            if not signal.entry_prices:
                current_price = await binance_public.get_current_price(signal.symbol)
                if current_price:
                    signal.entry_prices = [current_price]
                    logger.info(f"💰 Рыночный вход - текущая цена {signal.symbol}: {current_price}")
                else:
                    logger.warning(f"⚠️  Не удалось получить цену для {signal.symbol}")

            # Сохраняем сигнал в активные
            signal_id = f"{signal.symbol}_{signal.timestamp}"
            self.active_signals[signal_id] = signal

            # Логируем успешный парсинг
            logger.info(f"✅ СИГНАЛ РАСПОЗНАН:")
            logger.info(f"   Символ: {signal.symbol}")
            logger.info(f"   Направление: {signal.direction}")
            logger.info(f"   Входы: {signal.entry_prices}")
            logger.info(f"   Тейки: {signal.take_profits}")
            logger.info(f"   Стоп: {signal.stop_loss}")
            logger.info(f"   Плечо: {signal.leverage}")
            logger.info(f"   Маржа: {signal.margin}")
            logger.info(f"   Источник: {signal.source}")
            logger.info("-" * 60)

            # Запускаем мониторинг цены для этого сигнала
            asyncio.create_task(self.monitor_signal(signal_id))

        except Exception as e:
            logger.error(f"❌ Ошибка парсинга: {e}")

            from exchanges.multi_exchange import multi_exchange  # ЗАМЕНИ ЭТУ СТРОКУ

            # Удали эту строку:
            # from exchanges.binance_public import binance_public

            # В методе handle_channel_message замени:
            async def handle_channel_message(self, event):
                """Обрабатывает сообщения из каналов"""
                try:
                    message_text = event.message.text
                    chat_id = event.chat_id
                    channel_name = MONITORED_CHANNELS.get(chat_id, f"Channel_{chat_id}")

                    if not message_text:
                        return

                    logger.info(f"📨 Сообщение из '{channel_name}': {message_text[:100]}...")

                    # Парсим сигнал
                    signal = advanced_parser.parse_signal(message_text, channel_name)

                    # Если символ не распознан, пропускаем
                    if signal.symbol == "UNKNOWN":
                        logger.warning(f"⚠️  Символ не распознан, пропускаем сообщение")
                        return

                    # ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ СИМВОЛА НА ЛЮБОЙ ИЗ БИРЖ
                    is_valid_symbol = await multi_exchange.is_symbol_valid(signal.symbol)

                    if not is_valid_symbol:
                        logger.warning(
                            f"🚫 Символ {signal.symbol} не найден ни на одной бирже. Пропускаем сигнал от {signal.source}.")
                        return

                    # Узнаем на какой бирже нашли символ
                    exchange_name = await multi_exchange.find_symbol_exchange(signal.symbol)
                    logger.info(f"✅ Символ {signal.symbol} найден на {exchange_name}")

                    # Для рыночных входов получаем текущую цену
                    if not signal.entry_prices:
                        current_price = await multi_exchange.get_current_price(signal.symbol)
                        if current_price:
                            signal.entry_prices = [current_price]
                            logger.info(
                                f"💰 Рыночный вход - текущая цена {signal.symbol} на {exchange_name}: {current_price}")
                        else:
                            logger.warning(f"⚠️  Не удалось получить цену для {signal.symbol}")

                    # Сохраняем сигнал в активные
                    signal_id = f"{signal.symbol}_{signal.timestamp}"
                    self.active_signals[signal_id] = signal

                    # Логируем успешный парсинг
                    logger.info(f"✅ СИГНАЛ РАСПОЗНАН И ДОБАВЛЕН:")
                    logger.info(f"   Символ: {signal.symbol}")
                    logger.info(f"   Биржа: {exchange_name}")
                    logger.info(f"   Направление: {signal.direction}")
                    logger.info(f"   Входы: {signal.entry_prices}")
                    logger.info(f"   Тейки: {signal.take_profits}")
                    logger.info(f"   Стоп: {signal.stop_loss}")
                    logger.info(f"   Плечо: {signal.leverage}")
                    logger.info(f"   Маржа: {signal.margin}")
                    logger.info(f"   Источник: {signal.source}")
                    logger.info("-" * 60)

                    # Запускаем мониторинг цены для этого сигнала
                    asyncio.create_task(self.monitor_signal(signal_id))

                except Exception as e:
                    logger.error(f"❌ Ошибка обработки сообщения: {e}")

            async def monitor_signal(self, signal_id: str):
                """Мониторит цену для сигнала в реальном времени"""
                if signal_id not in self.active_signals:
                    return

                signal = self.active_signals[signal_id]
                reached_tps = set()

                logger.info(f"🔍 Начинаем мониторинг {signal.symbol} {signal.direction}")

                try:
                    while signal_id in self.active_signals:
                        current_price = await multi_exchange.get_current_price(
                            signal.symbol)  # ИСПОЛЬЗУЕМ MULTI_EXCHANGE

                        # Остальной код метода monitor_signal остается без изменений...
                        # Просто замени все вызовы binance_public.get_current_price на multi_exchange.get_current_price

                if current_price and signal.entry_prices:
                    entry_price = signal.entry_prices[0]

                    # Рассчитываем PnL
                    if signal.direction == "LONG":
                        pnl_percent = ((current_price - entry_price) / entry_price) * 100
                        # Проверяем тейк-профиты
                        for i, tp in enumerate(signal.take_profits):
                            if current_price >= tp:
                                logger.info(f"🎯 ДОСТИГНУТ ТЕЙК-ПРОФИТ #{i + 1} для {signal.symbol}: {tp}")
                                # Можно добавить логику удаления сигнала при достижении тейка
                    else:  # SHORT
                        pnl_percent = ((entry_price - current_price) / entry_price) * 100
                        # Проверяем тейк-профиты для шорта
                        for i, tp in enumerate(signal.take_profits):
                            if current_price <= tp:
                                logger.info(f"🎯 ДОСТИГНУТ ТЕЙК-ПРОФИТ #{i + 1} для {signal.symbol}: {tp}")

                    # Проверяем стоп-лосс
                    if signal.stop_loss:
                        if (signal.direction == "LONG" and current_price <= signal.stop_loss) or \
                                (signal.direction == "SHORT" and current_price >= signal.stop_loss):
                            logger.info(f"🛑 ДОСТИГНУТ СТОП-ЛОСС для {signal.symbol}: {signal.stop_loss}")
                            # Удаляем сигнал при достижении стопа
                            del self.active_signals[signal_id]
                            break

                    # Логируем значительные изменения
                    if abs(pnl_percent) >= 1:  # Логируем только изменения >1%
                        status = "🟢" if pnl_percent > 0 else "🔴"
                        logger.info(f"{status} {signal.symbol}: {pnl_percent:+.2f}% | Цена: {current_price}")

                # Ждем 5 секунд перед следующим обновлением
                await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"❌ Ошибка мониторинга {signal.symbol}: {e}")

    async def cleanup(self):
        """Очистка ресурсов при завершении"""
        await binance_public.close()

    def run(self):
        """Запускает бота"""
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_channel_message))
        logger.info("🤖 Бот запущен... Ожидаем сообщения из каналов")
        logger.info("💡 Добавь бота в каналы как администратора (только чтение)")

        try:
            self.app.run_polling()
        finally:
            # Очистка при завершении
            asyncio.run(self.cleanup())


def run_bot():
    bot = TradingBot()
    bot.run()