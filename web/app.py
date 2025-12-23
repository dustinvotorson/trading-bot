from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
from functools import lru_cache
import traceback

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# Конфигурация
class Config:
    MAX_HISTORY_DAYS = 30
    SIGNAL_MAX_AGE_SECONDS = 3600
    STATS_CACHE_TTL = 60  # секунд
    HISTORY_PER_PAGE = 50
    BACKUP_FILES_COUNT = 3


config = Config()


# Глобальное хранилище для данных с потокобезопасностью
class TradingData:
    def __init__(self):
        self._lock = threading.RLock()  # Reentrant Lock для потокобезопасности
        self.active_signals = {}
        self.price_updates = {}
        self.trade_history = []  # Новая: история всех сделок
        self.last_update = time.time()
        self.history_file = "trade_history.json"
        self._stats_cache = {}
        self._cache_timestamp = {}

        # Загружаем историю при запуске
        self.load_history()

    def _acquire_lock(self):
        """Контекстный менеджер для блокировки"""
        return self._lock

    def load_history(self):
        """Загружает историю сделок из файла с резервным копированием"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.trade_history = json.load(f)
                logger.info(f"Загружена история: {len(self.trade_history)} сделок")
            else:
                self.trade_history = []
                logger.info("Файл истории не найден, создан пустой список сделок")

            # Проверяем целостность данных
            self._validate_history()

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка формата JSON в файле истории: {e}")
            self._try_load_backup()
        except Exception as e:
            logger.error(f"Ошибка загрузки истории: {e}")
            logger.error(traceback.format_exc())
            self._try_load_backup()

    def _try_load_backup(self):
        """Пытается загрузить резервную копию"""
        backup_files = []
        for i in range(1, config.BACKUP_FILES_COUNT + 1):
            backup_file = f"trade_history_backup_{i}.json"
            if os.path.exists(backup_file):
                backup_files.append((backup_file, os.path.getmtime(backup_file)))

        if backup_files:
            # Берем самую свежую резервную копию
            backup_files.sort(key=lambda x: x[1], reverse=True)
            latest_backup = backup_files[0][0]
            try:
                with open(latest_backup, 'r', encoding='utf-8') as f:
                    self.trade_history = json.load(f)
                logger.info(f"Загружена резервная копия {latest_backup}: {len(self.trade_history)} сделок")
            except Exception as e:
                logger.error(f"Ошибка загрузки резервной копии: {e}")
                self.trade_history = []
        else:
            logger.warning("Резервные копии не найдены, создан пустой список сделок")
            self.trade_history = []

    def _validate_history(self):
        """Проверяет целостность истории"""
        valid_history = []
        corrupted_count = 0

        for i, trade in enumerate(self.trade_history):
            if not isinstance(trade, dict):
                corrupted_count += 1
                logger.warning(f"Сделка #{i} имеет неверный тип: {type(trade)}")
                continue

            # Проверяем обязательные поля
            required_fields = ['symbol', 'direction', 'timestamp']
            if all(field in trade for field in required_fields):
                valid_history.append(trade)
            else:
                corrupted_count += 1
                logger.warning(f"Сделка #{i} отсутствуют обязательные поля: {trade}")

        if corrupted_count > 0:
            logger.warning(f"Найдено {corrupted_count} некорректных записей в истории")
            self.trade_history = valid_history
            self.save_history()

    def save_history(self):
        """Сохраняет историю сделок в файл с созданием резервной копии"""
        with self._acquire_lock():
            try:
                # Создаем резервную копию текущего файла
                if os.path.exists(self.history_file):
                    # Ротация резервных копий
                    for i in range(config.BACKUP_FILES_COUNT - 1, 0, -1):
                        old_file = f"trade_history_backup_{i}.json"
                        new_file = f"trade_history_backup_{i + 1}.json"
                        if os.path.exists(old_file):
                            os.rename(old_file, new_file)

                    # Создаем свежую резервную копию
                    import shutil
                    shutil.copy2(self.history_file, "trade_history_backup_1.json")

                # Сохраняем новую историю
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(self.trade_history, f, ensure_ascii=False, indent=2)

                logger.debug("История сохранена успешно")
            except Exception as e:
                logger.error(f"Ошибка сохранения истории: {e}")
                logger.error(traceback.format_exc())

    def add_to_history(self, history_entry):
        """Добавляет сделку в историю"""
        with self._acquire_lock():
            # Валидация новой записи
            required_fields = ['symbol', 'direction', 'timestamp']
            if not all(field in history_entry for field in required_fields):
                logger.error(f"Попытка добавить некорректную запись в историю: {history_entry}")
                return

            self.trade_history.append(history_entry)
            self.last_update = time.time()

            # Инвалидируем кэш статистики
            self._invalidate_cache()

            # Авто-сохранение (отложенное)
            threading.Timer(1, self.save_history).start()

            # Авто-очистка старых данных
            threading.Timer(5, lambda: self.clean_old_history(config.MAX_HISTORY_DAYS)).start()

    def _invalidate_cache(self):
        """Инвалидирует кэш статистики"""
        self._stats_cache.clear()
        self._cache_timestamp.clear()

    def clean_old_history(self, max_days=30):
        """Очищает историю старше max_days дней"""
        with self._acquire_lock():
            current_time = time.time()
            cutoff_time = current_time - (max_days * 24 * 60 * 60)

            initial_count = len(self.trade_history)
            self.trade_history = [
                trade for trade in self.trade_history
                if trade.get('timestamp', current_time) >= cutoff_time
            ]

            if len(self.trade_history) < initial_count:
                removed_count = initial_count - len(self.trade_history)
                self.save_history()
                logger.info(f"Очищена история: {removed_count} старых сделок")
                self._invalidate_cache()

    def update_signal_data(self, signal_data: Dict[str, Any]):
        """Обновляет данные сигнала для веб-интерфейса"""
        with self._acquire_lock():
            signal_id = signal_data.get('signal_id')
            if signal_id:
                # Валидация timestamp
                if 'timestamp' not in signal_data:
                    signal_data['timestamp'] = time.time()

                self.active_signals[signal_id] = signal_data
                self.last_update = time.time()

                symbol = signal_data.get('symbol', 'Unknown')
                pnl = signal_data.get('pnl_percent', 0)
                logger.info(f"Обновлены данные сигнала {signal_id}: символ={symbol}, PnL={pnl}")

    def update_price_data(self, symbol: str, price_data: Dict[str, Any]):
        """Обновляет ценовые данные для веб-интерфейса"""
        with self._acquire_lock():
            if not symbol:
                logger.error("Попытка обновить цену без указания символа")
                return

            # Валидация данных
            if 'current_price' not in price_data:
                logger.warning(f"Ценовые данные для {symbol} не содержат current_price")

            self.price_updates[symbol] = price_data
            self.last_update = time.time()

            price = price_data.get('current_price', 'Unknown')
            logger.debug(f"Обновлены ценовые данные для {symbol}: цена={price}")

    def get_processed_data(self) -> Dict[str, Any]:
        """Возвращает обработанные данные с ПРАВИЛЬНЫМИ reached_tps"""
        with self._acquire_lock():
            processed_signals = {}

            for signal_id, signal in self.active_signals.items():
                try:
                    # Создаем минимальную копию необходимых полей
                    processed_signal = {
                        'signal_id': signal.get('signal_id'),
                        'symbol': signal.get('symbol'),
                        'direction': signal.get('direction'),
                        'take_profits': signal.get('take_profits', []),
                        'stop_loss': signal.get('stop_loss'),
                        'timestamp': signal.get('timestamp'),
                        'source': signal.get('source'),
                        'entry_prices': signal.get('entry_prices', []),
                        'reached_tps': [],  # Будет пересчитано
                        'current_price': None,
                        'pnl_percent': 0,
                        'exchange': 'Unknown'
                    }

                    symbol = signal.get('symbol')

                    # Если есть ценовые данные, ПЕРЕСЧИТЫВАЕМ reached_tps
                    if symbol and symbol in self.price_updates:
                        price_info = self.price_updates[symbol]
                        current_price = price_info.get('current_price')

                        if current_price is not None:
                            direction = signal.get('direction')
                            take_profits = signal.get('take_profits', [])

                            # Пересчитываем reached_tps на основе текущей цены
                            actual_reached_tps = []

                            for i, tp in enumerate(take_profits):
                                if direction == "LONG" and current_price >= tp:
                                    actual_reached_tps.append(i)
                                elif direction == "SHORT" and current_price <= tp:
                                    actual_reached_tps.append(i)

                            processed_signal['reached_tps'] = actual_reached_tps

                            # Обновляем остальные данные
                            processed_signal['current_price'] = current_price
                            processed_signal['pnl_percent'] = price_info.get('pnl_percent', 0)
                            processed_signal['exchange'] = price_info.get('exchange', 'Unknown')

                    processed_signals[signal_id] = processed_signal

                except Exception as e:
                    logger.error(f"Ошибка обработки сигнала {signal_id}: {e}")
                    logger.error(traceback.format_exc())
                    continue

            logger.debug(f"Обработано активных сигналов: {len(processed_signals)}")

            # Возвращаем копии данных для потокобезопасности
            return {
                'active_signals': processed_signals.copy(),
                'price_updates': self.price_updates.copy(),
                'last_update': self.last_update
            }

    def clear_old_signals(self, max_age_seconds: int = None):
        """Очищает старые сигналы"""
        if max_age_seconds is None:
            max_age_seconds = config.SIGNAL_MAX_AGE_SECONDS

        with self._acquire_lock():
            current_time = time.time()
            expired_signals = []

            for signal_id, signal_data in self.active_signals.items():
                # Используем timestamp из данных сигнала
                signal_time = signal_data.get('timestamp', 0)

                # Если timestamp невалиден или сигнал слишком старый
                if signal_time <= 0 or (current_time - signal_time > max_age_seconds):
                    expired_signals.append(signal_id)

            for signal_id in expired_signals:
                symbol = self.active_signals.get(signal_id, {}).get('symbol', 'Unknown')
                del self.active_signals[signal_id]
                logger.info(f"Удален старый сигнал {signal_id} для {symbol}")

            return len(expired_signals)

    def _get_cached_stats(self, cache_key, ttl, func, *args, **kwargs):
        """Получает статистику с кэшированием"""
        current_time = time.time()

        if (cache_key in self._stats_cache and
                cache_key in self._cache_timestamp and
                current_time - self._cache_timestamp[cache_key] < ttl):
            return self._stats_cache[cache_key]

        # Вычисляем и кэшируем
        result = func(*args, **kwargs)
        self._stats_cache[cache_key] = result
        self._cache_timestamp[cache_key] = current_time

        return result

    def get_weekly_stats(self):
        """Возвращает статистику по неделям с кэшированием"""
        with self._acquire_lock():
            return self._get_cached_stats(
                'weekly_stats',
                config.STATS_CACHE_TTL,
                self._calculate_weekly_stats
            )

    def _calculate_weekly_stats(self):
        """Вычисляет статистику по неделям"""
        weekly_stats = {}

        for trade in self.trade_history:
            try:
                # Определяем неделю
                trade_time = datetime.fromtimestamp(trade['timestamp'])
                year, week, _ = trade_time.isocalendar()
                week_key = f"{year}-W{week:02d}"

                if week_key not in weekly_stats:
                    weekly_stats[week_key] = {
                        'week_start': (trade_time - timedelta(days=trade_time.weekday())).timestamp(),
                        'total_trades': 0,
                        'profitable_trades': 0,
                        'total_pnl': 0,
                        'sources': defaultdict(int),
                        'closed_trades': 0,
                        'active_trades': 0
                    }

                week_data = weekly_stats[week_key]
                week_data['total_trades'] += 1

                # Считаем PnL если есть информация о закрытии
                if 'close_price' in trade and trade.get('entry_prices'):
                    entry_price = trade['entry_prices'][0]
                    close_price = trade['close_price']

                    if trade['direction'] == 'LONG':
                        pnl_percent = ((close_price - entry_price) / entry_price) * 100
                    else:
                        pnl_percent = ((entry_price - close_price) / entry_price) * 100

                    week_data['total_pnl'] += pnl_percent
                    if pnl_percent > 0:
                        week_data['profitable_trades'] += 1

                # Статистика по источникам
                source = trade.get('source', 'Unknown')
                week_data['sources'][source] += 1

                # Считаем закрытые сделки
                if 'close_reason' in trade:
                    week_data['closed_trades'] += 1
                else:
                    week_data['active_trades'] += 1

            except Exception as e:
                logger.warning(f"Ошибка обработки сделки для статистики: {e}")
                continue

        return weekly_stats

    def get_source_stats(self, days=7):
        """Статистика по источникам за последние N дней с кэшированием"""
        with self._acquire_lock():
            cache_key = f"source_stats_{days}"
            return self._get_cached_stats(
                cache_key,
                config.STATS_CACHE_TTL,
                self._calculate_source_stats,
                days
            )

    def _calculate_source_stats(self, days):
        """Вычисляет статистику по источникам"""
        cutoff_time = time.time() - (days * 24 * 60 * 60)

        source_stats = defaultdict(lambda: {
            'total_trades': 0,
            'profitable_trades': 0,
            'total_pnl': 0,
            'avg_leverage': 0,
            'leverage_sum': 0,
            'leverage_count': 0,
            'win_rate': 0
        })

        for trade in self.trade_history:
            if trade['timestamp'] < cutoff_time:
                continue

            try:
                source = trade.get('source', 'Unknown')
                stats = source_stats[source]
                stats['total_trades'] += 1

                # PnL расчет
                if 'close_price' in trade and trade.get('entry_prices'):
                    entry_price = trade['entry_prices'][0]
                    close_price = trade['close_price']

                    if trade['direction'] == 'LONG':
                        pnl_percent = ((close_price - entry_price) / entry_price) * 100
                    else:
                        pnl_percent = ((entry_price - close_price) / entry_price) * 100

                    stats['total_pnl'] += pnl_percent
                    if pnl_percent > 0:
                        stats['profitable_trades'] += 1

                # Плечо
                leverage = trade.get('leverage')
                if leverage:
                    stats['leverage_sum'] += leverage
                    stats['leverage_count'] += 1

            except Exception as e:
                logger.warning(f"Ошибка обработки сделки для source stats: {e}")
                continue

        # Вычисляем среднее плечо и win rate
        for source, stats in source_stats.items():
            if stats['leverage_count'] > 0:
                stats['avg_leverage'] = stats['leverage_sum'] / stats['leverage_count']

            if stats['total_trades'] > 0:
                stats['win_rate'] = (stats['profitable_trades'] / stats['total_trades']) * 100

        return dict(source_stats)

    def get_symbol_data(self, symbol: str) -> Dict[str, Any]:
        """Возвращает данные по символу"""
        with self._acquire_lock():
            return self.price_updates.get(symbol, {}).copy()

    def get_filtered_history(self, source_filter=None, status_filter=None):
        """Возвращает отфильтрованную историю без полного копирования"""
        with self._acquire_lock():
            filtered = []

            for trade in self.trade_history:
                # Фильтр по источнику
                if source_filter and trade.get('source') != source_filter:
                    continue

                # Фильтр по статусу
                if status_filter == 'active':
                    if 'close_reason' in trade:
                        continue
                elif status_filter == 'completed':
                    if trade.get('close_reason') != 'all_take_profits':
                        continue
                elif status_filter == 'stopped':
                    if trade.get('close_reason') != 'stop_loss':
                        continue
                # Для 'all' - не фильтруем

                filtered.append(trade)

                # Ограничиваем для производительности
                if len(filtered) >= 1000:  # Максимум 1000 записей за раз
                    break

            return filtered


# Глобальный экземпляр с потокобезопасностью
trading_data = TradingData()


# Простой rate limiting
class RateLimiter:
    def __init__(self, max_requests=100, window=60):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, ip):
        """Проверяет, не превышен ли лимит запросов"""
        with self._lock:
            current_time = time.time()

            # Удаляем старые запросы
            self.requests[ip] = [t for t in self.requests[ip]
                                 if current_time - t < self.window]

            # Проверяем лимит
            if len(self.requests[ip]) >= self.max_requests:
                return False

            # Добавляем новый запрос
            self.requests[ip].append(current_time)
            return True


# Создаем rate limiter для API endpoints
rate_limiter = RateLimiter(max_requests=60, window=60)  # 60 запросов в минуту


def check_rate_limit():
    """Декоратор для проверки rate limit"""

    def decorator(f):
        def wrapper(*args, **kwargs):
            ip = request.remote_addr
            if not rate_limiter.is_allowed(ip):
                logger.warning(f"Rate limit exceeded for IP: {ip}")
                return jsonify({
                    'error': 'Too many requests',
                    'message': 'Please try again later'
                }), 429
            return f(*args, **kwargs)

        wrapper.__name__ = f.__name__
        return wrapper

    return decorator


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stats')
def stats_page():
    return render_template('stats.html')


@app.route('/history')
def history_page():
    return render_template('stats.html')


@app.route('/api/data')
@check_rate_limit
def api_data():
    """API endpoint для получения данных в реальном времени"""
    try:
        # Очищаем старые сигналы (не чаще чем раз в 30 секунд)
        current_time = time.time()
        if current_time - trading_data.last_update > 30:
            cleared = trading_data.clear_old_signals()
            if cleared > 0:
                logger.info(f"Очищено {cleared} старых сигналов")

        # Возвращаем обработанные данные
        return jsonify(trading_data.get_processed_data())

    except Exception as e:
        logger.error(f"Ошибка в api_data: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/stats')
@check_rate_limit
def api_stats():
    """API для расширенной статистики"""
    try:
        weekly_stats = trading_data.get_weekly_stats()
        source_stats = trading_data.get_source_stats(days=7)

        return jsonify({
            'weekly_stats': weekly_stats,
            'source_stats': source_stats,
            'total_history_trades': len(trading_data.trade_history),
            'last_update': trading_data.last_update
        })

    except Exception as e:
        logger.error(f"Ошибка в api_stats: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/history')
@check_rate_limit
def api_history():
    """API для истории сделок"""
    try:
        page = request.args.get('page', 1, type=int)
        source_filter = request.args.get('source', '')
        status_filter = request.args.get('status', '')  # all, active, completed, stopped

        # Валидация параметров
        if page < 1:
            page = 1

        if status_filter not in ['', 'all', 'active', 'completed', 'stopped']:
            status_filter = ''

        # Получаем отфильтрованную историю
        filtered_history = trading_data.get_filtered_history(
            source_filter if source_filter else None,
            status_filter if status_filter and status_filter != 'all' else None
        )

        # Сортируем по времени (новые сверху)
        filtered_history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

        # Пагинация
        start_idx = (page - 1) * config.HISTORY_PER_PAGE
        end_idx = start_idx + config.HISTORY_PER_PAGE

        return jsonify({
            'history': filtered_history[start_idx:end_idx],
            'total_count': len(filtered_history),
            'page': page,
            'per_page': config.HISTORY_PER_PAGE,
            'total_pages': (len(filtered_history) + config.HISTORY_PER_PAGE - 1) // config.HISTORY_PER_PAGE
        })

    except Exception as e:
        logger.error(f"Ошибка в api_history: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/health')
def api_health():
    """Health check endpoint"""
    try:
        with trading_data._acquire_lock():
            return jsonify({
                'status': 'healthy',
                'active_signals': len(trading_data.active_signals),
                'trade_history': len(trading_data.trade_history),
                'last_update': trading_data.last_update,
                'timestamp': time.time()
            })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500


def get_trading_data():
    """Возвращает глобальный экземпляр trading_data"""
    return trading_data


def run_web_server():
    """Запускает веб-сервер"""
    logger.info("Web dashboard available at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)


# Запуск веб-сервера в отдельном потоке
def start_web_interface():
    web_thread = threading.Thread(target=run_web_server, daemon=True, name="WebServerThread")
    web_thread.start()
    logger.info("Веб-интерфейс запущен в отдельном потоке")
    return web_thread


# Добавляем middleware для логирования запросов
@app.before_request
def log_request_info():
    """Логирует входящие запросы"""
    if request.path.startswith('/api/'):
        logger.debug(f"API Request: {request.method} {request.path} from {request.remote_addr}")


@app.after_request
def log_response_info(response):
    """Логирует исходящие ответы"""
    if request.path.startswith('/api/'):
        logger.debug(f"API Response: {request.method} {request.path} - {response.status_code}")
    return response


# Точка входа при прямом запуске
if __name__ == '__main__':
    logger.info("Запуск приложения...")
    start_web_interface()

    # Держим основной поток активным
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем")
