from telethon import TelegramClient, events, Button
import random
from parser.advanced_parser import advanced_parser
from exchanges.multi_exchange import multi_exchange
from config_telethon import API_ID, API_HASH, MONITORED_CHANNELS, BOT_TOKEN, WEB_APP_URL
from config_telethon import is_admin, is_whitelisted, add_user, remove_user, ADMINS, WHITELIST
from web.app import get_trading_data
import logging
import asyncio
import time
import os
import re
from config_telethon import get_channel_source
import sys
from telethon.errors import TypeNotFoundError
from typing import Dict, Optional, Set, Any
from dataclasses import dataclass, field
from functools import wraps

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем глобальный экземпляр trading_data
trading_data = get_trading_data()

# Проверяем доступность InputWebAppInfo
try:
    from telethon.tl.types import InputWebAppInfo

    HAS_WEB_APP_SUPPORT = True
    logger.info("✅ Поддержка Web App доступна")
except ImportError:
    HAS_WEB_APP_SUPPORT = False
    logger.warning("⚠️  InputWebAppInfo не доступен, используем fallback")


    class InputWebAppInfo:
        def __init__(self, url):
            self.url = url


@dataclass
class UserState:
    """Класс для хранения состояния пользователя"""
    waiting_for_signal: bool = False
    signal_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceCacheEntry:
    """Запись в кэше цен"""
    price: float
    timestamp: float
    exchange: str


class PriceCache:
    """Кэш цен для оптимизации запросов к биржам"""

    def __init__(self, ttl: int = 5):
        self.cache: Dict[str, PriceCacheEntry] = {}
        self.ttl = ttl  # время жизни кэша в секундах

    async def get_price(self, symbol: str) -> tuple[Optional[float], Optional[str]]:
        """Получает цену из кэша или от биржи"""
        current_time = time.time()

        # Проверяем кэш
        if symbol in self.cache:
            entry = self.cache[symbol]
            if current_time - entry.timestamp < self.ttl:
                return entry.price, entry.exchange

        # Получаем свежую цену
        try:
            price, exchange = await multi_exchange.get_current_price(symbol)
            if price:
                self.cache[symbol] = PriceCacheEntry(
                    price=price,
                    timestamp=current_time,
                    exchange=exchange
                )
            return price, exchange
        except Exception as e:
            logger.error(f"❌ Ошибка получения цены для {symbol}: {e}")
            return None, None

    def clear_old_entries(self):
        """Очищает старые записи в кэше"""
        current_time = time.time()
        to_delete = []

        for symbol, entry in self.cache.items():
            if current_time - entry.timestamp > self.ttl * 2:
                to_delete.append(symbol)

        for symbol in to_delete:
            del self.cache[symbol]


def admin_only(func):
    """Декоратор для проверки прав администратора"""

    @wraps(func)
    async def wrapper(self, event, *args, **kwargs):
        # Проверяем, что это личное сообщение
        if not event.is_private:
            await event.answer("❌ Эта команда доступна только в личных сообщениях")
            return

        # Проверяем права администратора
        if not is_admin(event.sender_id):
            await event.reply("❌ Эта команда только для администраторов")
            return

        # Проверяем доступ к боту
        if not is_whitelisted(event.sender_id):
            await event.reply("❌ Доступ запрещен")
            return

        return await func(self, event, *args, **kwargs)

    return wrapper


def private_only(func):
    """Декоратор для ограничения команд только личными сообщениями"""

    @wraps(func)
    async def wrapper(self, event, *args, **kwargs):
        if not event.is_private:
            return
        return await func(self, event, *args, **kwargs)

    return wrapper


class TelethonTradingBot:
    def __init__(self):
        """Инициализация клиента Telethon"""
        self._setup_telethon_error_handler()

        # 1) Получаем имя сессии (файл сессии Telethon)
        try:
            from config_telethon import SESSION_NAME as CONFIG_SESSION_NAME
        except Exception:
            CONFIG_SESSION_NAME = None

        session_name = CONFIG_SESSION_NAME or os.getenv("SESSION_NAME") or "trading_session"
        session = session_name  # Telethon создаст файл session_name.session

        # 2) Берём прокси из proxy_settings (если есть). Превращаем в формат telethon.
        try:
            import proxy_settings
            raw_proxy = random.choice(proxy_settings.MT_PROXIES)
        except Exception:
            raw_proxy = None

        def build_proxy_arg(p):
            if p is None:
                return None
            if isinstance(p, (tuple, list)):
                return tuple(p)
            if isinstance(p, dict):
                p_type = p.get("type", "socks5")
                host = p.get("host")
                port = p.get("port")
                if not host or not port:
                    return None
                rdns = p.get("rdns", True)
                username = p.get("username")
                password = p.get("password")
                if username:
                    return (p_type, host, int(port), rdns, username, password)
                return (p_type, host, int(port))
            return None

        proxy_arg = build_proxy_arg(raw_proxy)

        # 3) Создаём клиента Telethon
        try:
            self.client = TelegramClient(session, API_ID, API_HASH, proxy=proxy_arg)
            logger.info("✅ Клиент Telethon создан успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка при создании клиента Telethon: {e}")
            self.client = None

        # 4) Обычные поля класса
        self.active_signals: Dict[str, Any] = {}
        self.partial_signals: Dict[str, Any] = {}  # Кеш для неполных сигналов
        self.partial_khrustalev_signals: Dict[str, Any] = {}  # Кеш для сигналов Хрусталева
        self.user_states: Dict[int, UserState] = {}  # Состояния пользователей
        self.price_cache = PriceCache(ttl=5)  # Кэш цен

        # Конфигурация
        self.partial_signals_ttl = 300  # 5 минут TTL для неполных сигналов
        self.khrustalev_timeout = 180  # 3 минуты для объединения сигналов Хрусталева
        self.max_active_signals = 50  # Максимальное количество активных сигналов

        # Флаг для отслеживания критических ошибок
        self.event_loop_closed = False
        self.restart_attempts = 0
        self.max_restart_attempts = 3

        # Запускаем фоновые задачи
        asyncio.create_task(self._cleanup_tasks())
    def _setup_telethon_error_handler(self):
        """Настраивает обработчик ошибок Telethon"""
        try:
            loop = asyncio.get_event_loop()

            def exception_handler(loop, context):
                exception = context.get('exception')
                if isinstance(exception, TypeNotFoundError):
                    logger.warning(f"⚠️  Telethon TypeNotFoundError: {exception}")
                    logger.info("🔄 Игнорируем ошибку и продолжаем работу...")
                    return

                # Для других ошибок - стандартная обработка
                if loop.default_exception_handler:
                    loop.default_exception_handler(context)

            loop.set_exception_handler(exception_handler)
        except Exception as e:
            logger.error(f"❌ Ошибка настройки обработчика ошибок: {e}")

    async def _cleanup_tasks(self):
        """Фоновая задача для очистки старых данных"""
        while True:
            try:
                # Очищаем старые кэшированные цены
                self.price_cache.clear_old_entries()

                # Очищаем устаревшие частичные сигналы Хрусталева
                await self.clean_old_khrustalev_signals()

                # Очищаем устаревшие состояния пользователей (старше 1 часа)
                current_time = time.time()
                users_to_remove = []
                for user_id, state in self.user_states.items():
                    if hasattr(state, 'last_activity') and current_time - state.last_activity > 3600:
                        users_to_remove.append(user_id)

                for user_id in users_to_remove:
                    del self.user_states[user_id]

                await asyncio.sleep(60)  # Запускаем каждую минуту
            except Exception as e:
                logger.error(f"❌ Ошибка в задаче очистки: {e}")
                await asyncio.sleep(60)

    async def handle_channel_message(self, event):
        """Обрабатывает сообщения из каналов с фильтрацией предварительных объявлений"""
        try:
            # Проверяем, нет ли критических ошибок
            if self.event_loop_closed:
                logger.critical("❌ ОБРАБОТКА СООБЩЕНИЙ ПРИОСТАНОВЛЕНА: Цикл событий закрыт. Требуется перезапуск бота.")
                return

            message_text = event.message.text
            chat_id = event.chat_id

            # Определяем источник по ID канала
            channel_name = get_channel_source(chat_id)

            if not message_text:
                return

            logger.info(f"📨 Сообщение из '{channel_name}': {message_text[:100]}...")

            # Для Хрусталева используем специальный обработчик
            if "khrustalev" in channel_name.lower():
                await self.handle_khrustalev_message(message_text, channel_name, event)
                return

            # Проверяем лимит активных сигналов
            if len(self.active_signals) >= self.max_active_signals:
                logger.warning(f"⚠️  Достигнут лимит активных сигналов ({self.max_active_signals})")
                return

            # Парсим сигнал
            signal = advanced_parser.parse_signal(message_text, channel_name)

            # Если символ не распознан, пропускаем
            if signal.symbol == "UNKNOWN":
                logger.warning(f"⚠️  Символ не распознан, пропускаем сообщение")
                return

            # 🔥 ФИЛЬТРАЦИЯ: Проверяем, что это полноценный торговый сигнал, а не предварительное объявление
            if not self.is_valid_trading_signal(signal, message_text):
                logger.info(f"🔕 Пропускаем предварительное объявление для {signal.symbol} - недостаточно данных")
                return

            # 🔥 УНИВЕРСАЛЬНОЕ ПРАВИЛО: ЕСЛИ НЕТ ЦЕНЫ ВХОДА → СЧИТАЕМ РЫНОЧНЫМ
            is_market_condition = (
                    signal.is_market or  # Парсер определил как рынок
                    (not signal.entry_prices and not signal.limit_prices)  # Нет цен входа
            )

            if is_market_condition and signal.take_profits:
                logger.info(f"🎯 Сигнал {signal.symbol} без цены входа → считаем рыночным")
                signal.is_market = True  # Устанавливаем флаг

                # Получаем текущую цену
                try:
                    current_price, exchange_used = await self.price_cache.get_price(signal.symbol)

                    # Проверяем, не является ли ошибка критической (event loop closed)
                    if exchange_used == "Event loop closed":
                        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Цикл событий закрыт. Требуется перезапуск бота.")
                        self.event_loop_closed = True

                        # Пытаемся перезапустить цикл событий
                        await self._handle_event_loop_error()
                        return

                    if current_price:
                        signal.entry_prices = [current_price]
                        logger.info(
                            f"💰 Рыночный вход - текущая цена {signal.symbol}: {current_price} (биржа: {exchange_used})")
                    else:
                        logger.warning(
                            f"⚠️  Не удалось получить цену для {signal.symbol}, пробуем альтернативный символ...")

                        # Пробуем альтернативный формат (например, BCH вместо BCHUSDT)
                        alt_symbol = signal.symbol.replace("USDT", "")
                        current_price, exchange_used = await self.price_cache.get_price(alt_symbol)

                        # Проверяем, не является ли ошибка критической (event loop closed)
                        if exchange_used == "Event loop closed":
                            logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Цикл событий закрыт. Требуется перезапуск бота.")
                            self.event_loop_closed = True
                            await self._handle_event_loop_error()
                            return

                        if current_price:
                            signal.entry_prices = [current_price]
                            logger.info(f"💰 Рыночный вход - альтернативная цена {alt_symbol}: {current_price}")
                        else:
                            logger.warning(f"⚠️  Не удалось получить цену для {signal.symbol}, пропускаем сигнал")
                            return

                except RuntimeError as e:
                    if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА RUNTIME: {e}")
                        self.event_loop_closed = True
                        await self._handle_event_loop_error()
                        return
                    else:
                        raise

            # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Если после всех манипуляций все еще нет цены входа → пропускаем
            elif not signal.entry_prices and not signal.limit_prices:
                logger.info(f"🔕 Пропускаем сигнал {signal.symbol} - не удалось определить цену входа")
                return

            # Сохраняем сигнал в активные
            signal_id = f"{signal.symbol}_{int(signal.timestamp)}"
            self.active_signals[signal_id] = signal

            # Сохраняем сигнал в trading_data для веб-интерфейса
            signal_data = {
                'signal_id': signal_id,
                'symbol': signal.symbol,
                'direction': signal.direction,
                'entry_prices': signal.entry_prices,
                'limit_prices': signal.limit_prices,
                'take_profits': signal.take_profits,
                'stop_loss': signal.stop_loss,
                'leverage': signal.leverage,
                'margin': signal.margin,
                'source': signal.source,
                'pnl_percent': 0,
                'reached_tps': [],
                'exchange': 'Unknown',
                'timestamp': signal.timestamp,
                'is_market': signal.is_market
            }
            trading_data.update_signal_data(signal_data)
            logger.info(f"💾 Сигнал сохранен в trading_data: {signal.symbol}")

            # Логируем успешный парсинг
            logger.info(f"✅ СИГНАЛ РАСПОЗНАН:")
            logger.info(f"   Символ: {signal.symbol}")
            logger.info(f"   Направление: {signal.direction}")
            logger.info(f"   Входы: {signal.entry_prices}")
            logger.info(f"   Лимитные входы: {signal.limit_prices}")
            logger.info(f"   Тейки: {signal.take_profits}")
            logger.info(f"   Стоп: {signal.stop_loss}")
            logger.info(f"   Плечо: {signal.leverage}")
            logger.info(f"   Маржа: {signal.margin}")
            logger.info(f"   Источник: {signal.source}")
            logger.info(f"   Рыночный вход: {signal.is_market}")
            logger.info("-" * 60)

            # Запускаем мониторинг цены для этого сигнала
            asyncio.create_task(self.monitor_signal(signal_id))

        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА В ОБРАБОТКЕ СООБЩЕНИЯ: {e}")
                self.event_loop_closed = True
                await self._handle_event_loop_error()
            else:
                logger.error(f"❌ RuntimeError обработки сообщения: {e}")
                import traceback
                logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _handle_event_loop_error(self):
        """Обрабатывает критическую ошибку event loop closed"""
        logger.critical("🔄 Попытка восстановления после критической ошибки event loop...")

        # Увеличиваем счетчик попыток перезапуска
        self.restart_attempts += 1

        if self.restart_attempts > self.max_restart_attempts:
            logger.critical("🚫 Превышено максимальное количество попыток перезапуска. Бот остановлен.")

            # Отправляем уведомление админу
            await self._notify_admin_critical_error()

            # Останавливаем бота
            await self.client.disconnect()
            raise SystemExit("Критическая ошибка: цикл событий закрыт")

        try:
            # Пытаемся восстановить цикл событий
            await self._restart_event_loop()
            self.event_loop_closed = False
            logger.info("✅ Цикл событий восстановлен")
        except Exception as e:
            logger.critical(f"❌ Не удалось восстановить цикл событий: {e}")
            await self._notify_admin_critical_error()
            raise

    async def _restart_event_loop(self):
        """Перезапускает цикл событий и критические компоненты"""
        logger.info("🔄 Перезапуск критических компонентов...")

        # 1. Закрываем все текущие сессии
        try:
            await multi_exchange.close()
        except:
            pass

        # 2. Создаем новый event loop если нужно
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                logger.info("🔄 Текущий цикл событий закрыт, создаем новый...")
                asyncio.set_event_loop(asyncio.new_event_loop())
        except:
            asyncio.set_event_loop(asyncio.new_event_loop())

        # 3. Пересоздаем кэш цен
        self.price_cache = PriceCache(ttl=5)

        # 4. Пауза перед продолжением
        await asyncio.sleep(2)

        logger.info("✅ Критические компоненты перезапущены")

    async def _notify_admin_critical_error(self):
        """Отправляет уведомление админу о критической ошибке"""
        try:
            for admin_id in ADMINS:
                try:
                    await self.client.send_message(
                        admin_id,
                        f"🚨 **КРИТИЧЕСКАЯ ОШИБКА БОТА**\n\n"
                        f"Обнаружена ошибка 'Event loop closed'.\n"
                        f"Попыток перезапуска: {self.restart_attempts}/{self.max_restart_attempts}\n"
                        f"Требуется ручное вмешательство!\n\n"
                        f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except:
                    pass
        except:
            pass

    def is_valid_trading_signal(self, signal, message_text: str) -> bool:
        """Проверяет, является ли сообщение полноценным торговым сигналом - УЛУЧШЕННАЯ ВЕРСИЯ"""

        # 1. Символ не должен быть UNKNOWN
        if signal.symbol == "UNKNOWN":
            logger.info(f"🔕 Пропускаем - символ не распознан")
            return False

        # 2. Направление должно быть определено (LONG/SHORT)
        if signal.direction == "UNKNOWN":
            logger.info(f"🔕 Пропускаем - направление не распознано")
            return False

        # 3. Должны быть указаны тейк-профиты (если нет тейков - это предварительное объявление)
        has_take_profits = bool(signal.take_profits)
        if not has_take_profits:
            logger.info(f"🔕 Пропускаем - нет тейк-профитов (вероятно предварительное объявление)")
            return False

        # 4. Проверяем конкретные данные в сообщении
        has_concrete_data = self.has_concrete_trading_data(message_text)
        if not has_concrete_data:
            logger.info(f"🔕 Пропускаем - нет конкретных торговых данных")
            return False

        logger.info(f"✅ Сигнал {signal.symbol} прошел все проверки")
        return True

    def has_concrete_trading_data(self, message_text: str) -> bool:
        """Проверяет, содержит ли сообщение конкретные торговые данные"""
        # Ищем конкретные числовые паттерны, указывающие на торговые инструкции
        concrete_patterns = [
            r'\d+[.,]\d+\s*\$',  # Цены с долларом: 0.48$, 3$
            r'[TТ][PП]\d*\s*:?\s*\d+[.,]\d+',  # TP1: 0.48, ТП2: 0.58
            r'тейк\s*профит',  # Упоминание тейк-профитов
            r'стоп\s*лосс',  # Упоминание стоп-лосса
            r'вход\s*:?\s*\d+[.,]\d+',  # Вход: 0.9
            r'добор\s*\d+[.,]\d+',  # Добор 0.78
            r'лимитный\s*ордер',  # Лимитный ордер
            r'маржа\s*\d+',  # Маржа 0.3%
            r'фикс\s*\d+%',  # Фикс 20% объема
        ]

        clean_text = message_text.lower().replace(' ', '')

        for pattern in concrete_patterns:
            if re.search(pattern, message_text, re.IGNORECASE):
                return True

        # Дополнительная проверка: должно быть достаточно чисел для торговли
        numbers = re.findall(r'\d+[.,]\d+', message_text)
        if len(numbers) >= 3:  # Если есть хотя бы 3 числа (вход + тейки/стоп)
            return True

        return False

    async def handle_khrustalev_message(self, text: str, source: str, event):
        """Обработка сообщений от Хрусталева с временным окном 3 минуты"""
        try:
            # Парсим сообщение
            signal = advanced_parser.parse_khrustalev(text, source)
            current_time = time.time()

            logger.info(f"🔧 Обработка Хрусталева: символ={signal.symbol}, тейков={len(signal.take_profits)}")

            # Очищаем устаревшие частичные сигналы
            await self.clean_old_khrustalev_signals()

            # Если это сообщение с символом и входом (первое сообщение)
            if signal.symbol != "UNKNOWN" and signal.entry_prices:
                signal_id = f"khrustalev_{signal.symbol}"
                self.partial_khrustalev_signals[signal_id] = {
                    'signal': signal,
                    'timestamp': current_time,
                    'first_message': text
                }
                logger.info(f"💾 Сохранено первое сообщение Хрусталева: {signal.symbol}")
                return

            # Если это сообщение с целями (второе сообщение)
            elif signal.take_profits and not signal.entry_prices:
                logger.info("🔍 Поиск частичного сигнала для целей Хрусталева...")

                # Ищем самый свежий частичный сигнал (последний добавленный)
                latest_signal_id = None
                latest_timestamp = 0

                for signal_id, data in self.partial_khrustalev_signals.items():
                    if data['timestamp'] > latest_timestamp:
                        latest_timestamp = data['timestamp']
                        latest_signal_id = signal_id

                if latest_signal_id and (current_time - latest_timestamp) <= self.khrustalev_timeout:
                    # Нашли свежий частичный сигнал в пределах 3 минут
                    partial_data = self.partial_khrustalev_signals[latest_signal_id]
                    first_signal = partial_data['signal']

                    logger.info(f"🔗 Объединяем с сигналом: {first_signal.symbol} " +
                                f"(возраст: {current_time - latest_timestamp:.1f} сек)")

                    # Объединяем сигналы
                    merged_signal = self.merge_khrustalev_signals(first_signal, signal)

                    # Проверяем лимит активных сигналов
                    if len(self.active_signals) >= self.max_active_signals:
                        logger.warning(f"⚠️  Достигнут лимит активных сигналов, пропускаем {merged_signal.symbol}")
                        return

                    # Создаем финальный сигнал
                    final_signal_id = f"{merged_signal.symbol}_{int(time.time())}"
                    self.active_signals[final_signal_id] = merged_signal

                    # Удаляем из частичных
                    del self.partial_khrustalev_signals[latest_signal_id]

                    # Сохраняем в trading_data
                    signal_data = {
                        'signal_id': final_signal_id,
                        'symbol': merged_signal.symbol,
                        'direction': merged_signal.direction,
                        'entry_prices': merged_signal.entry_prices,
                        'limit_prices': merged_signal.limit_prices,
                        'take_profits': merged_signal.take_profits,
                        'stop_loss': merged_signal.stop_loss,
                        'leverage': merged_signal.leverage,
                        'margin': merged_signal.margin,
                        'source': merged_signal.source,
                        'pnl_percent': 0,
                        'reached_tps': [],
                        'exchange': 'Unknown',
                        'timestamp': merged_signal.timestamp
                    }
                    trading_data.update_signal_data(signal_data)

                    logger.info(f"✅ ОБЪЕДИНЕННЫЙ СИГНАЛ ХРУСТАЛЕВА:")
                    logger.info(f"   Символ: {merged_signal.symbol}")
                    logger.info(f"   Направление: {merged_signal.direction}")
                    logger.info(f"   Вход: {merged_signal.entry_prices}")
                    logger.info(f"   Тейки: {merged_signal.take_profits}")
                    logger.info(f"   Стоп: {merged_signal.stop_loss}")
                    logger.info("-" * 60)

                    # Запускаем мониторинг
                    asyncio.create_task(self.monitor_signal(final_signal_id))

                else:
                    if latest_signal_id:
                        logger.warning(
                            f"⚠️  Сигнал устарел: {current_time - latest_timestamp:.1f} сек > {self.khrustalev_timeout} сек")
                    else:
                        logger.warning("⚠️  Не найдено частичных сигналов для объединения")

            else:
                logger.warning("⚠️  Непонятный формат сообщения Хрусталева")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения Хрусталева: {e}")

    async def clean_old_khrustalev_signals(self):
        """Очищает устаревшие частичные сигналы Хрусталева"""
        current_time = time.time()
        expired_signals = []

        for signal_id, data in self.partial_khrustalev_signals.items():
            if current_time - data['timestamp'] > self.khrustalev_timeout:
                expired_signals.append(signal_id)

        for signal_id in expired_signals:
            symbol = self.partial_khrustalev_signals[signal_id]['signal'].symbol
            del self.partial_khrustalev_signals[signal_id]
            logger.info(f"🧹 Удален устаревший частичный сигнал Хрусталева: {symbol}")

    def merge_khrustalev_signals(self, first_signal, second_signal):
        """Объединяет два сигнала Хрусталева"""
        merged = advanced_parser.TradeSignal()

        # Берем основные данные из первого сообщения
        merged.symbol = first_signal.symbol
        merged.direction = first_signal.direction
        merged.entry_prices = first_signal.entry_prices
        merged.source = first_signal.source
        merged.timestamp = first_signal.timestamp

        # Добавляем данные из второго сообщения
        merged.take_profits = second_signal.take_profits
        merged.stop_loss = second_signal.stop_loss

        # Прочие поля
        merged.leverage = first_signal.leverage or second_signal.leverage
        merged.margin = first_signal.margin or second_signal.margin

        return merged

    async def check_access(self, event) -> bool:
        """Проверяет доступ пользователя - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        # Проверяем, что это личное сообщение, а не из канала
        if not event.is_private:
            return False  # Игнорируем сообщения из каналов/групп

        user_id = event.sender_id
        if not is_whitelisted(user_id):
            await event.reply("❌ **Доступ запрещен**\n\nВы не в белом списке. Обратитесь к администратору.")
            return False
        return True

    async def start(self):
        """Запускает бота"""
        await self.client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Telethon бот запущен")

        # Регистрируем обработчики команд
        self.client.add_event_handler(self.handle_start_command, events.NewMessage(pattern='/start'))
        self.client.add_event_handler(self.handle_dashboard_command, events.NewMessage(pattern='/dashboard'))
        self.client.add_event_handler(self.handle_stats_command, events.NewMessage(pattern='/stats'))
        self.client.add_event_handler(self.handle_active_command, events.NewMessage(pattern='/active'))
        self.client.add_event_handler(self.handle_help_command, events.NewMessage(pattern='/help'))

        # Админские команды
        self.client.add_event_handler(self.handle_admin_command, events.NewMessage(pattern='/admin'))
        self.client.add_event_handler(self.handle_admin_help_command, events.NewMessage(pattern='/adminhelp'))
        self.client.add_event_handler(self.handle_add_user_command, events.NewMessage(pattern='/adduser'))
        self.client.add_event_handler(self.handle_remove_user_command, events.NewMessage(pattern='/removeuser'))
        self.client.add_event_handler(self.handle_list_users_command, events.NewMessage(pattern='/listusers'))
        self.client.add_event_handler(self.handle_edit_signal_command, events.NewMessage(pattern='/editsignal'))
        self.client.add_event_handler(self.handle_add_signal_command, events.NewMessage(pattern='/addsignal'))
        self.client.add_event_handler(self.handle_active_signals_command,
                                      events.NewMessage(pattern='/activesignals'))

        # Обработчик текстовых сообщений (кнопки)
        self.client.add_event_handler(self.handle_text_messages, events.NewMessage)

        # Обработчик inline кнопок
        self.client.add_event_handler(self.handle_callback_query, events.CallbackQuery)

        # Обработчик для всех сообщений из мониторируемых каналов
        self.client.add_event_handler(self.handle_channel_message, events.NewMessage(chats=MONITORED_CHANNELS))

        logger.info(f"🔍 Мониторим каналы: {MONITORED_CHANNELS}")
        await self.client.run_until_disconnected()

    def create_web_app_button(self, text, url):
        """Создает кнопку Web App с fallback"""
        if HAS_WEB_APP_SUPPORT:
            return Button.web_app(text, InputWebAppInfo(url))
        else:
            return Button.url(text, url)

    @private_only
    async def handle_start_command(self, event):
        """Обработчик команды /start - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            return

        user = await event.get_sender()

        # Создаем отдельные клавиатуры для разных типов кнопок
        if HAS_WEB_APP_SUPPORT:
            # Если есть поддержка Web App - используем inline кнопки
            buttons = [
                [self.create_web_app_button("📊 Trading Dashboard", WEB_APP_URL)],
                [Button.inline("📈 Статистика", b"stats"), Button.inline("🔄 Активные сделки", b"active")],
                [Button.inline("❓ Помощь", b"help")]
            ]

            # Добавляем админскую кнопку если пользователь админ
            if is_admin(event.sender_id):
                buttons.append([Button.inline("👑 Админ панель", b"admin")])
        else:
            # Fallback: используем обычные кнопки
            buttons = [
                [Button.text("📊 Dashboard", resize=True)],
                [Button.text("📈 Статистика", resize=True), Button.text("🔄 Активные сделки", resize=True)],
                [Button.text("❓ Помощь", resize=True)]
            ]

            # Добавляем админскую кнопку если пользователь админ
            if is_admin(event.sender_id):
                buttons.append([Button.text("👑 Админ панель", resize=True)])

        welcome_text = f"""
🤖 **Trading Bot Dashboard**

Привет, {user.first_name}! Я мониторю торговые сигналы в реальном времени.

**Основные команды:**
📊 /dashboard - Открыть веб-интерфейс
📈 /stats - Статистика сделок
🔄 /active - Активные сделки

**Что я умею:**
• Автоматически парсить сигналы из каналов
• Мониторить цены в реальном времени  
• Показывать PnL и прогресс по тейк-профитам
• Работать с Binance и BingX

Нажми кнопку ниже чтобы открыть dashboard 👇
        """

        await event.reply(welcome_text, buttons=buttons, link_preview=False)

    @private_only
    async def handle_callback_query(self, event):
        """Обработчик нажатий на inline кнопки - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            await event.answer("❌ Доступ запрещен")
            return

        data = event.data.decode('utf-8') if event.data else ''

        try:
            if data == "stats":
                await self._send_stats_response(event)
            elif data == "active":
                await self._send_active_response(event)
            elif data == "help":
                await self._send_help_response(event)
            elif data == "admin":
                if is_admin(event.sender_id):
                    await self._send_admin_response(event)
                else:
                    await event.answer("❌ Доступ запрещен", alert=True)
            else:
                await event.answer(f"❌ Неизвестная команда: {data}")

            # Подтверждаем нажатие кнопки
            await event.answer()

        except Exception as e:
            logger.error(f"❌ Ошибка обработки callback: {e}")
            await event.answer("❌ Произошла ошибка", alert=True)

    async def _send_stats_response(self, event):
        """Отправляет статистику в ответ на callback"""
        if not self.active_signals:
            await event.respond("📊 **Статистика**\n\nАктивных сделок нет")
            return

        stats_text = "📊 **Статистика сделок**\n\n"
        total_pnl = 0
        signals_with_pnl = 0

        for signal_id, signal in list(self.active_signals.items())[:5]:
            symbol_data = trading_data.get_symbol_data(signal.symbol)
            if symbol_data and 'pnl_percent' in symbol_data:
                pnl = symbol_data['pnl_percent']
                total_pnl += pnl
                signals_with_pnl += 1

                direction_emoji = "🟢" if signal.direction == "LONG" else "🔴"
                pnl_emoji = "📈" if pnl > 0 else "📉"

                stats_text += f"{direction_emoji} **{signal.symbol}** {signal.direction}\n"
                stats_text += f"   {pnl_emoji} PnL: {pnl:+.2f}%\n"
                stats_text += f"   🎯 Тейков: {len(signal.take_profits)}\n"
                stats_text += f"   📍 Источник: {signal.source}\n\n"

        if signals_with_pnl > 0:
            avg_pnl = total_pnl / signals_with_pnl
            stats_text += f"**Общая статистика:**\n"
            stats_text += f"• Активных сделок: {len(self.active_signals)}\n"
            stats_text += f"• Средний PnL: {avg_pnl:+.2f}%\n"

        await event.respond(stats_text)

    async def _send_active_response(self, event):
        """Отправляет активные сделки в ответ на callback"""
        if not self.active_signals:
            await event.respond("🔄 **Активные сделки**\n\nНет активных сделок")
            return

        active_text = "🔄 **Активные сделки**\n\n"

        for signal_id, signal in list(self.active_signals.items())[:5]:
            symbol_data = trading_data.get_symbol_data(signal.symbol)
            current_price = symbol_data.get('current_price', 'N/A') if symbol_data else 'N/A'
            pnl = symbol_data.get('pnl_percent', 0) if symbol_data else 0

            direction_emoji = "🟢" if signal.direction == "LONG" else "🔴"
            pnl_emoji = "📈" if pnl > 0 else "📉"

            active_text += f"{direction_emoji} **{signal.symbol}** {signal.direction}\n"
            active_text += f"   💰 Цена: {current_price}\n"
            active_text += f"   {pnl_emoji} PnL: {pnl:+.2f}%\n"
            active_text += f"   🎯 Тейков: {len(signal.take_profits)}\n\n"

        if len(self.active_signals) > 5:
            active_text += f"*... и еще {len(self.active_signals) - 5} сделок*"

        await event.respond(active_text)

    async def _send_help_response(self, event):
        """Отправляет справку в ответ на callback"""
        help_text = """
❓ **Помощь по Trading Bot**

**Основные команды:**
/start - Главное меню
/dashboard - Открыть веб-интерфейс  
/stats - Статистика сделок
/active - Активные сделки
        """

        # Добавляем админские команды если пользователь админ
        if is_admin(event.sender_id):
            help_text += "\n\n**👑 Админ команды:**\n"
            help_text += "/admin - Админ панель\n"
            help_text += "/adminhelp - Подробная справка по админ-командам\n"
            help_text += "/adduser <id> - Добавить пользователя\n"
            help_text += "/removeuser <id> - Удалить пользователя\n"
            help_text += "/listusers - Список пользователей\n"
            help_text += "/editsignal - Редактировать сделку\n"
            help_text += "/addsignal - Добавить сделку вручную\n"
            help_text += "/activesignals - Список сделок с ID\n"

        await event.respond(help_text)

    async def _send_admin_response(self, event):
        """Отправляет админ панель в ответ на callback"""
        admin_text = f"""
👑 **Админ панель**

**Статистика пользователей:**
• Админы: {len(ADMINS)}
• Белый список: {len(WHITELIST)}
• Активных сделок: {len(self.active_signals)}

**👥 Управление пользователями:**
`/adduser <user_id>` - Добавить пользователя
`/removeuser <user_id>` - Удалить пользователя  
`/listusers` - Список пользователей

**📊 Управление сделками:**
`/editsignal <signal_id> <param> <value>` - Редактировать сделку
`/addsignal` - Добавить сделку вручную
`/activesignals` - Список сделок с ID

**🛠 Другие команды:**
`/adminhelp` - Подробная справка по командам

**📝 Примеры:**
`/adduser 123456789`
`/editsignal BTCUSDT_123456 stop_loss 50000`
`/editsignal BTCUSDT_123456 take_profits [51000,52000,53000]`
`/addsignal` - и следуйте инструкциям
        """

        await event.respond(admin_text)

    @admin_only
    async def handle_admin_command(self, event):
        """Обработчик команды /admin"""
        admin_text = f"""
👑 **Админ панель**

**Статистика пользователей:**
• Админы: {len(ADMINS)}
• Белый список: {len(WHITELIST)}
• Активных сделок: {len(self.active_signals)}

**👥 Управление пользователями:**
`/adduser <user_id>` - Добавить пользователя
`/removeuser <user_id>` - Удалить пользователя  
`/listusers` - Список пользователей

**📊 Управление сделками:**
`/editsignal <signal_id> <param> <value>` - Редактировать сделку
`/addsignal` - Добавить сделку вручную
`/activesignals` - Список сделок с ID

**🛠 Другие команды:**
`/adminhelp` - Подробная справка по командам

**📝 Примеры:**
`/adduser 123456789`
`/editsignal BTCUSDT_123456 stop_loss 50000`
`/editsignal BTCUSDT_123456 take_profits [51000,52000,53000]`
`/addsignal` - и следуйте инструкциям
        """

        await event.reply(admin_text)

    @admin_only
    async def handle_add_user_command(self, event):
        """Добавление пользователя в белый список"""
        args = event.message.text.split()
        if len(args) != 2:
            await event.reply("❌ Использование: /adduser <user_id>")
            return

        try:
            user_id = int(args[1])
            add_user(user_id)
            await event.reply(f"✅ Пользователь {user_id} добавлен в белый список")
        except ValueError:
            await event.reply("❌ user_id должен быть числом")

    @admin_only
    async def handle_remove_user_command(self, event):
        """Удаление пользователя из белого списка"""
        args = event.message.text.split()
        if len(args) != 2:
            await event.reply("❌ Использование: /removeuser <user_id>")
            return

        try:
            user_id = int(args[1])
            remove_user(user_id)
            await event.reply(f"✅ Пользователь {user_id} удален из белого списка")
        except ValueError:
            await event.reply("❌ user_id должен быть числом")

    @admin_only
    async def handle_list_users_command(self, event):
        """Показать список пользователей"""
        users_text = "👥 **Список пользователей**\n\n"
        users_text += f"**Админы ({len(ADMINS)}):**\n"
        for admin_id in ADMINS:
            users_text += f"• `{admin_id}`\n"

        users_text += f"\n**Белый список ({len(WHITELIST)}):**\n"
        for user_id in WHITELIST:
            users_text += f"• `{user_id}`\n"

        await event.reply(users_text)

    @admin_only
    async def handle_edit_signal_command(self, event):
        """Редактирование параметров сделки"""
        args = event.message.text.split()
        if len(args) < 4:
            await event.reply(
                "❌ Использование: /editsignal <signal_id> <param> <value>\n\nПараметры: stop_loss, take_profits, entry_prices")
            return

        signal_id = args[1]
        param = args[2]
        value_str = ' '.join(args[3:])

        if signal_id not in self.active_signals:
            await event.reply("❌ Сделка не найдена")
            return

        signal = self.active_signals[signal_id]

        try:
            if param == "stop_loss":
                new_value = float(value_str)
                signal.stop_loss = new_value
                await event.reply(f"✅ Стоп-лосс для {signal.symbol} изменен на {new_value}")

            elif param == "take_profits":
                # Парсим список тейк-профитов [value1,value2,value3]
                if value_str.startswith('[') and value_str.endswith(']'):
                    values = value_str[1:-1].split(',')
                    new_value = [float(v.strip()) for v in values]
                    signal.take_profits = new_value
                    await event.reply(f"✅ Тейк-профиты для {signal.symbol} изменены на {new_value}")
                else:
                    await event.reply("❌ Формат: [value1,value2,value3]")

            elif param == "entry_prices":
                # Парсим список цен входа [value1,value2,value3]
                if value_str.startswith('[') and value_str.endswith(']'):
                    values = value_str[1:-1].split(',')
                    new_value = [float(v.strip()) for v in values]
                    signal.entry_prices = new_value
                    await event.reply(f"✅ Цены входа для {signal.symbol} изменены на {new_value}")
                else:
                    await event.reply("❌ Формат: [value1,value2,value3]")

            else:
                await event.reply("❌ Неизвестный параметр. Доступные: stop_loss, take_profits, entry_prices")

            # Обновляем данные в веб-интерфейсе
            await self.update_signal_in_web_interface(signal_id)

        except ValueError as e:
            await event.reply(f"❌ Ошибка формата числа: {e}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: {e}")

    @admin_only
    async def handle_admin_help_command(self, event):
        """Обработчик команды /adminhelp - расширенная помощь для админов"""
        help_text = """
👑 **АДМИН КОМАНДЫ - Полный список**

👥 **Управление пользователями:**
`/adduser <user_id>` - Добавить пользователя в белый список
`/removeuser <user_id>` - Удалить пользователя из белого списка  
`/listusers` - Показать всех пользователей

📊 **Управление сделками:**
`/editsignal <signal_id> <param> <value>` - Редактировать сделку
`/addsignal` - Вручную добавить новую сделку
`/activesignals` - Список активных сделок с ID

🛠 **Другие команды:**
`/admin` - Панель управления
`/adminhelp` - Эта справка

📝 **ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:**

**Добавление пользователя:**
`/adduser 123456789` - добавить пользователя с ID 123456789

**Редактирование сделки:**
`/editsignal BTCUSDT_1700000000 stop_loss 50000`
`/editsignal BTCUSDT_1700000000 take_profits [51000,52000,53000]`
`/editsignal BTCUSDT_1700000000 entry_prices [50000,49500]`

**Добавление сделки вручную:**
Отправьте `/addsignal` и следуйте инструкциям

🔍 **Где найти signal_id?**
- В веб-интерфейсе в столбце "ID сигнала"
- В команде `/activesignals`
- В логах бота при парсинге сигнала
        """

        await event.reply(help_text)

    @admin_only
    async def handle_add_signal_command(self, event):
        """Обработчик команды /addsignal - ручное добавление сделки"""
        # Устанавливаем состояние ожидания данных
        if event.sender_id not in self.user_states:
            self.user_states[event.sender_id] = UserState()

        self.user_states[event.sender_id].waiting_for_signal = True

        instruction_text = """
📝 **ДОБАВЛЕНИЕ СДЕЛКИ ВРУЧНУЮ**

Отправьте данные сделки в формате:

**СИМВОЛ НАПРАВЛЕНИЕ ЦЕНА_ВХОДА СТОП_ЛОСС ТЕЙК_ПРОФИТЫ [ПЛЕЧО] [МАРЖА] [ИСТОЧНИК]**

**Примеры:**
`BTCUSDT LONG 50000 49000 51000,52000,53000`
`ETHUSDT SHORT 3500 3600 3400,3300,3200 10 1000 Manual`
`SOLUSDT LONG 150 140 160,170,180 5 500 My_Analysis`

**Обязательные поля:**
- Символ (BTCUSDT, ETHUSDT и т.д.)
- Направление (LONG/SHORT) 
- Цена входа (число)
- Стоп-лосс (число)
- Тейк-профиты (через запятую)

**Опциональные:**
- Плечо (по умолчанию: 1)
- Маржа (по умолчанию: 0) 
- Источник (по умолчанию: "Manual")

Отправьте данные сейчас:
        """

        await event.reply(instruction_text)

    async def process_add_signal_steps(self, event):
        """Обрабатывает ввод данных для добавления сделки"""
        try:
            data = event.message.text.strip()
            parts = data.split()

            if len(parts) < 5:
                await event.reply("❌ Недостаточно данных. Нужно минимум 5 параметров.")
                return

            # Проверяем лимит активных сигналов
            if len(self.active_signals) >= self.max_active_signals:
                await event.reply(f"❌ Достигнут лимит активных сигналов ({self.max_active_signals})")
                return

            # Парсим обязательные параметры
            symbol = parts[0].upper()
            direction = parts[1].upper()

            # Проверяем направление
            if direction not in ["LONG", "SHORT"]:
                await event.reply("❌ Направление должно быть LONG или SHORT")
                return

            entry_price = float(parts[2])
            stop_loss = float(parts[3])
            take_profits = [float(tp.strip()) for tp in parts[4].split(',')]

            # Проверяем цены
            if entry_price <= 0 or stop_loss <= 0:
                await event.reply("❌ Цены должны быть положительными числами")
                return

            # Проверяем тейк-профиты
            if not take_profits:
                await event.reply("❌ Должен быть хотя бы один тейк-профит")
                return

            for tp in take_profits:
                if tp <= 0:
                    await event.reply("❌ Тейк-профиты должны быть положительными числами")
                    return

            # Парсим опциональные параметры
            leverage = 1
            margin = 0
            source = "Manual"

            if len(parts) > 5:
                leverage = float(parts[5])
                if leverage <= 0:
                    await event.reply("❌ Плечо должно быть положительным числом")
                    return

            if len(parts) > 6:
                margin = float(parts[6])
                if margin < 0:
                    await event.reply("❌ Маржа не может быть отрицательной")
                    return

            if len(parts) > 7:
                source = ' '.join(parts[7:])

            # Проверяем валидность символа (опционально, если есть функция проверки)
            # if hasattr(multi_exchange, 'validate_symbol'):
            #     if not await multi_exchange.validate_symbol(symbol):
            #         await event.reply(f"❌ Символ {symbol} не найден на поддерживаемых биржах")
            #         return

            # Создаем сигнал
            signal = advanced_parser.TradeSignal()
            signal.symbol = symbol
            signal.direction = direction
            signal.entry_prices = [entry_price]
            signal.stop_loss = stop_loss
            signal.take_profits = take_profits
            signal.leverage = leverage
            signal.margin = margin
            signal.source = source
            signal.timestamp = time.time()

            # Сохраняем в активные сделки
            signal_id = f"{signal.symbol}_{int(signal.timestamp)}"
            self.active_signals[signal_id] = signal

            # Логируем
            logger.info(f"✅ РУЧНАЯ СДЕЛКА ДОБАВЛЕНА:")
            logger.info(f"   ID: {signal_id}")
            logger.info(f"   Символ: {signal.symbol}")
            logger.info(f"   Направление: {signal.direction}")
            logger.info(f"   Вход: {signal.entry_prices}")
            logger.info(f"   Стоп: {signal.stop_loss}")
            logger.info(f"   Тейки: {signal.take_profits}")
            logger.info(f"   Плечо: {signal.leverage}")
            logger.info(f"   Маржа: {signal.margin}")
            logger.info(f"   Источник: {signal.source}")

            # Сохраняем в trading_data
            signal_data = {
                'signal_id': signal_id,
                'symbol': signal.symbol,
                'direction': signal.direction,
                'entry_prices': signal.entry_prices,
                'take_profits': signal.take_profits,
                'stop_loss': signal.stop_loss,
                'leverage': signal.leverage,
                'margin': signal.margin,
                'source': signal.source,
                'pnl_percent': 0,
                'reached_tps': [],
                'exchange': 'Unknown',
                'timestamp': signal.timestamp,
                'is_market': False
            }
            trading_data.update_signal_data(signal_data)

            # Запускаем мониторинг
            asyncio.create_task(self.monitor_signal(signal_id))

            # Отправляем подтверждение
            success_text = f"""
✅ **СДЕЛКА ДОБАВЛЕНА**

**ID сделки:** `{signal_id}`
**Символ:** {signal.symbol}
**Направление:** {signal.direction}
**Цена входа:** {entry_price}
**Стоп-лосс:** {stop_loss}
**Тейк-профиты:** {', '.join(map(str, take_profits))}
**Плечо:** {leverage}
**Маржа:** {margin}
**Источник:** {source}

Сделка теперь отслеживается в реальном времени!
            """

            await event.reply(success_text)

        except ValueError as e:
            await event.reply(f"❌ Ошибка формата чисел: {e}\nПроверьте, что все числовые значения введены правильно.")
        except Exception as e:
            await event.reply(f"❌ Ошибка при добавлении сделки: {e}")
        finally:
            # Сбрасываем состояние пользователя
            if event.sender_id in self.user_states:
                self.user_states[event.sender_id].waiting_for_signal = False

    @admin_only
    async def handle_active_signals_command(self, event):
        """Показывает активные сделки с их ID для редактирования"""
        if not self.active_signals:
            await event.reply("🔍 **Активные сделки**\n\nНет активных сделок")
            return

        active_text = "🔍 **АКТИВНЫЕ СДЕЛКИ (с ID)**\n\n"

        for signal_id, signal in list(self.active_signals.items())[:10]:  # Ограничиваем чтобы не было слишком длинно
            symbol_data = trading_data.get_symbol_data(signal.symbol)
            current_price = symbol_data.get('current_price', 'N/A') if symbol_data else 'N/A'
            pnl = symbol_data.get('pnl_percent', 0) if symbol_data else 0

            direction_emoji = "🟢" if signal.direction == "LONG" else "🔴"
            pnl_emoji = "📈" if pnl > 0 else "📉"

            active_text += f"{direction_emoji} **{signal.symbol}** {signal.direction}\n"
            active_text += f"   🆔 ID: `{signal_id}`\n"
            active_text += f"   💰 Текущая цена: {current_price}\n"
            active_text += f"   {pnl_emoji} PnL: {pnl:+.2f}%\n"
            active_text += f"   🎯 Тейков: {len(signal.take_profits)}\n"
            active_text += f"   📍 Источник: {signal.source}\n\n"

        if len(self.active_signals) > 10:
            active_text += f"*... и еще {len(self.active_signals) - 10} сделок*"

        active_text += "\n**Для редактирования используйте:**\n"
        active_text += "`/editsignal <ID> <параметр> <значение>`"

        await event.reply(active_text)

    async def update_signal_in_web_interface(self, signal_id):
        """Обновляет данные сигнала в веб-интерфейсе"""
        if signal_id not in self.active_signals:
            return

        signal = self.active_signals[signal_id]

        # Получаем текущую цену для расчета PnL
        current_price, exchange_used = await multi_exchange.get_current_price(signal.symbol)

        pnl_percent = None
        reached_tps = []

        if current_price is not None and signal.entry_prices:
            entry_price = signal.entry_prices[0]
            if signal.direction == "LONG":
                pnl_percent = ((current_price - entry_price) / entry_price) * 100
            else:
                pnl_percent = ((entry_price - current_price) / entry_price) * 100

            for i, tp in enumerate(signal.take_profits or []):
                if (signal.direction == "LONG" and current_price >= tp) or \
                        (signal.direction == "SHORT" and current_price <= tp):
                    reached_tps.append(i)

        signal_data = {
            'signal_id': signal_id,
            'symbol': signal.symbol,
            'direction': signal.direction,
            'entry_prices': signal.entry_prices or [],
            'limit_prices': getattr(signal, "limit_prices", []) or [],
            'take_profits': signal.take_profits or [],
            'stop_loss': signal.stop_loss,
            'leverage': signal.leverage,
            'margin': signal.margin,
            'source': signal.source,
            'pnl_percent': pnl_percent,
            'reached_tps': reached_tps,
            'exchange': exchange_used,
            'current_price': current_price,
            'entry_executed': getattr(signal, "entry_executed", False),
            'timestamp': signal.timestamp
        }
        trading_data.update_signal_data(signal_data)

    @private_only
    async def handle_dashboard_command(self, event):
        """Обработчик команды /dashboard - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            return

        button = self.create_web_app_button("🚀 Открыть Trading Dashboard", WEB_APP_URL)
        await event.reply(
            "📊 **Trading Dashboard**\n\n"
            "Нажми кнопку ниже чтобы открыть веб-интерфейс с мониторингом сделок:",
            buttons=button
        )

    @private_only
    async def handle_stats_command(self, event):
        """Обработчик команды /stats - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            return

        active_signals_count = len(self.active_signals)

        if active_signals_count == 0:
            await event.reply("📊 **Статистика**\n\nАктивных сделок нет")
            return

        # Собираем статистику по активным сделкам
        stats_text = "📊 **Статистика сделок**\n\n"
        total_pnl = 0
        signals_with_pnl = 0

        for signal_id, signal in list(self.active_signals.items())[:10]:
            symbol_data = trading_data.get_symbol_data(signal.symbol)
            if symbol_data and 'pnl_percent' in symbol_data:
                pnl = symbol_data['pnl_percent']
                total_pnl += pnl
                signals_with_pnl += 1

                direction_emoji = "🟢" if signal.direction == "LONG" else "🔴"
                pnl_emoji = "📈" if pnl > 0 else "📉"

                stats_text += f"{direction_emoji} **{signal.symbol}** {signal.direction}\n"
                stats_text += f"   {pnl_emoji} PnL: {pnl:+.2f}%\n"
                stats_text += f"   🎯 Тейков: {len(signal.take_profits)}\n"
                stats_text += f"   📍 Источник: {signal.source}\n\n"

        if signals_with_pnl > 0:
            avg_pnl = total_pnl / signals_with_pnl
            stats_text += f"**Общая статистика:**\n"
            stats_text += f"• Активных сделок: {active_signals_count}\n"
            stats_text += f"• Средний PnL: {avg_pnl:+.2f}%\n"

        button = self.create_web_app_button("📊 Детальная статистика", WEB_APP_URL)
        await event.reply(stats_text, buttons=button)

    @private_only
    async def handle_active_command(self, event):
        """Обработчик команды /active - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            return

        if not self.active_signals:
            await event.reply("🔄 **Активные сделки**\n\nНет активных сделок")
            return

        active_text = "🔄 **Активные сделки**\n\n"

        for signal_id, signal in list(self.active_signals.items())[:5]:
            symbol_data = trading_data.get_symbol_data(signal.symbol)
            current_price = symbol_data.get('current_price', 'N/A') if symbol_data else 'N/A'
            pnl = symbol_data.get('pnl_percent', 0) if symbol_data else 0

            direction_emoji = "🟢" if signal.direction == "LONG" else "🔴"
            pnl_emoji = "📈" if pnl > 0 else "📉"

            active_text += f"{direction_emoji} **{signal.symbol}** {signal.direction}\n"
            active_text += f"   💰 Цена: {current_price}\n"
            active_text += f"   {pnl_emoji} PnL: {pnl:+.2f}%\n"
            active_text += f"   🎯 Тейков: {len(signal.take_profits)}\n\n"

        if len(self.active_signals) > 5:
            active_text += f"*... и еще {len(self.active_signals) - 5} сделок*"

        button = self.create_web_app_button("📊 Все сделки в деталях", WEB_APP_URL)
        await event.reply(active_text, buttons=button)

    @private_only
    async def handle_text_messages(self, event):
        """Обработчик текстовых сообщений (кнопки)"""
        if not await self.check_access(event):
            return

        # Проверяем, находится ли пользователь в процессе добавления сделки
        if event.sender_id in self.user_states and self.user_states[event.sender_id].waiting_for_signal:
            await self.process_add_signal_steps(event)
            return

        text = event.raw_text
        if text == "📊 Dashboard":
            await self.handle_dashboard_command(event)
        elif text == "📈 Статистика":
            await self.handle_stats_command(event)
        elif text == "🔄 Активные сделки":
            await self.handle_active_command(event)
        elif text == "❓ Помощь":
            await self.handle_help_command(event)
        elif text == "👑 Админ панель" and is_admin(event.sender_id):
            await self.handle_admin_command(event)

    @private_only
    async def handle_help_command(self, event):
        """Обработчик команды помощи - ТОЛЬКО ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ"""
        if not await self.check_access(event):
            return

        help_text = """
❓ **Помощь по Trading Bot**

**Основные команды:**
/start - Главное меню
/dashboard - Открыть веб-интерфейс  
/stats - Статистика сделок
/active - Активные сделки
        """

        # Добавляем админские команды если пользователь админ
        if is_admin(event.sender_id):
            help_text += "\n\n**👑 Админ команды:**\n"
            help_text += "/admin - Админ панель\n"
            help_text += "/adminhelp - Подробная справка по админ-командам\n"
            help_text += "/adduser <id> - Добавить пользователя\n"
            help_text += "/removeuser <id> - Удалить пользователя\n"
            help_text += "/listusers - Список пользователей\n"
            help_text += "/editsignal - Редактировать сделку\n"
            help_text += "/addsignal - Добавить сделку вручную\n"
            help_text += "/activesignals - Список сделок с ID\n"

        await event.reply(help_text)

    async def monitor_signal(self, signal_id: str):
        """Мониторит цену для сигнала в реальном времени"""
        if signal_id not in self.active_signals:
            return

        signal = self.active_signals[signal_id]
        reached_tps: Set[int] = set()
        error_count = 0
        entry_executed = True  # Для рыночных входов сразу выполнено
        max_errors = 5  # Максимальное количество ошибок подряд

        logger.info(f"🔍 Начинаем мониторинг {signal.symbol} {signal.direction}")

        try:
            while signal_id in self.active_signals and error_count < max_errors:
                try:
                    # Проверяем, нет ли критических ошибок
                    if self.event_loop_closed:
                        logger.critical(f"❌ Мониторинг {signal.symbol} приостановлен: цикл событий закрыт")
                        await asyncio.sleep(10)
                        continue

                    current_price, exchange_used = await self.price_cache.get_price(signal.symbol)

                    # Проверяем, не является ли ошибка критической
                    if exchange_used == "Event loop closed":
                        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА при мониторинге {signal.symbol}: цикл событий закрыт")
                        self.event_loop_closed = True

                        # Сохраняем сигнал в историю с причиной ошибки
                        await self.save_to_history(signal_id, "event_loop_error", 0)

                        # Удаляем из активных
                        if signal_id in self.active_signals:
                            del self.active_signals[signal_id]

                        # Пытаемся восстановиться
                        await self._handle_event_loop_error()
                        break

                    # Если не удалось получить цену
                    if current_price is None:
                        error_count += 1
                        if error_count >= max_errors:
                            logger.error(f"❌ Прекращаем мониторинг {signal.symbol} - символ не найден на биржах")

                            # Сохраняем в историю с причиной ошибки
                            await self.save_to_history(signal_id, "symbol_not_found", 0)

                            # Удаляем из активных
                            if signal_id in self.active_signals:
                                del self.active_signals[signal_id]
                            break

                        await asyncio.sleep(10)
                        continue

                    # Сброс счетчика ошибок
                    error_count = 0

                    # Рассчитываем PnL
                    pnl_percent = 0
                    if signal.entry_prices:
                        entry_price = signal.entry_prices[0]
                        if signal.direction == "LONG":
                            pnl_percent = ((current_price - entry_price) / entry_price) * 100
                            # Проверяем тейк-профиты
                            for i, tp in enumerate(signal.take_profits):
                                if current_price >= tp and i not in reached_tps:
                                    logger.info(f"🎯 ДОСТИГНУТ ТЕЙК-ПРОФИТ #{i + 1} для {signal.symbol}: {tp}")
                                    reached_tps.add(i)
                        else:  # SHORT
                            pnl_percent = ((entry_price - current_price) / entry_price) * 100
                            for i, tp in enumerate(signal.take_profits):
                                if current_price <= tp and i not in reached_tps:
                                    logger.info(f"🎯 ДОСТИГНУТ ТЕЙК-ПРОФИТ #{i + 1} для {signal.symbol}: {tp}")
                                    reached_tps.add(i)

                    # 🔥 ОБНОВЛЯЕМ ДАННЫЕ В TRADING_DATA
                    signal_data = {
                        'signal_id': signal_id,
                        'symbol': signal.symbol,
                        'direction': signal.direction,
                        'entry_prices': signal.entry_prices,
                        'limit_prices': signal.limit_prices,
                        'take_profits': signal.take_profits,
                        'stop_loss': signal.stop_loss,
                        'leverage': signal.leverage,
                        'margin': signal.margin,
                        'source': signal.source,
                        'pnl_percent': pnl_percent,
                        'reached_tps': list(reached_tps),
                        'exchange': exchange_used,
                        'timestamp': signal.timestamp,
                        'entry_executed': entry_executed
                    }
                    trading_data.update_signal_data(signal_data)

                    # Обновляем ценовые данные
                    price_data = {
                        'current_price': current_price,
                        'entry_price': signal.entry_prices[0] if signal.entry_prices else current_price,
                        'pnl_percent': pnl_percent,
                        'timestamp': signal.timestamp,
                        'exchange': exchange_used,
                        'entry_executed': entry_executed
                    }
                    trading_data.update_price_data(signal.symbol, price_data)

                    # Логируем в консоль (раз в 30 секунд чтобы не засорять логи)
                    if int(time.time()) % 30 == 0:
                        status = "🟢" if pnl_percent > 0 else "🔴"
                        logger.info(f"{status} {signal.symbol}: {pnl_percent:+.2f}% | Цена: {current_price}")

                    # Проверяем завершение сделки
                    if len(reached_tps) == len(signal.take_profits) and signal.take_profits:
                        logger.info(f"✅ ВСЕ ТЕЙК-ПРОФИТЫ ДОСТИГНУТЫ для {signal.symbol}")
                        await self.save_to_history(signal_id, "all_take_profits", current_price)
                        if signal_id in self.active_signals:
                            del self.active_signals[signal_id]
                        break

                    if signal.stop_loss:
                        if (signal.direction == "LONG" and current_price <= signal.stop_loss) or \
                                (signal.direction == "SHORT" and current_price >= signal.stop_loss):
                            logger.info(f"🛑 ДОСТИГНУТ СТОП-ЛОСС для {signal.symbol}: {signal.stop_loss}")
                            await self.save_to_history(signal_id, "stop_loss", current_price)
                            if signal_id in self.active_signals:
                                del self.active_signals[signal_id]
                            break

                    await asyncio.sleep(5)

                except RuntimeError as e:
                    if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА RUNTIME в мониторинге {signal.symbol}: {e}")
                        self.event_loop_closed = True
                        await self._handle_event_loop_error()
                        break
                    else:
                        logger.error(f"⚠️  RuntimeError в цикле мониторинга {signal.symbol}: {e}")
                        error_count += 1
                        await asyncio.sleep(5)
                except asyncio.CancelledError:
                    logger.info(f"🔄 Мониторинг {signal_id} отменен")
                    break
                except Exception as e:
                    logger.error(f"⚠️  Ошибка в цикле мониторинга {signal.symbol}: {e}")
                    error_count += 1
                    await asyncio.sleep(5)

        except RuntimeError as e:
            if "Event loop is closed" in str(e) or "no running event loop" in str(e):
                logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА RUNTIME мониторинга {signal.symbol}: {e}")
                self.event_loop_closed = True
                await self._handle_event_loop_error()
            else:
                logger.error(f"❌ RuntimeError мониторинга {signal.symbol}: {e}")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка мониторинга {signal.symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Очищаем ресурсы если сигнал еще активен
            if signal_id in self.active_signals:
                logger.warning(f"⚠️  Мониторинг {signal_id} завершился неожиданно")

    async def save_to_history(self, signal_id: str, close_reason: str, close_price: float):
        """Сохраняет сделку в историю и удаляет из активных"""
        if signal_id not in self.active_signals:
            return

        signal = self.active_signals[signal_id]

        history_entry = {
            'signal_id': signal_id,
            'symbol': signal.symbol,
            'direction': signal.direction,
            'entry_prices': signal.entry_prices,
            'take_profits': signal.take_profits,
            'stop_loss': signal.stop_loss,
            'leverage': signal.leverage,
            'margin': signal.margin,
            'source': signal.source,
            'timestamp': signal.timestamp,
            'close_reason': close_reason,
            'close_price': close_price,
            'close_time': time.time(),
            'duration_minutes': (time.time() - signal.timestamp) / 60
        }

        # Сохраняем в глобальные данные
        trading_data.add_to_history(history_entry)

        logger.info(f"📝 Сделка {signal.symbol} добавлена в историю с причиной: {close_reason}")

        # Удаляем из активных
        if signal_id in self.active_signals:
            del self.active_signals[signal_id]


async def run_telethon_bot():
    """Запускает Telethon бота"""
    try:
        bot = TelethonTradingBot()
        await bot.start()
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска бота: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    # Запуск бота
    asyncio.run(run_telethon_bot())
