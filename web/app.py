from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

app = Flask(__name__)


# Глобальное хранилище для данных
class TradingData:
    def __init__(self):
        self.active_signals = {}
        self.price_updates = {}
        self.trade_history = []  # Новая: история всех сделок
        self.last_update = time.time()
        self.history_file = "trade_history.json"

        # Загружаем историю при запуске
        self.load_history()

    def load_history(self):
        """Загружает историю сделок из файла"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.trade_history = json.load(f)
                print(f"📖 Загружена история: {len(self.trade_history)} сделок")
        except Exception as e:
            print(f"❌ Ошибка загрузки истории: {e}")
            self.trade_history = []

    def save_history(self):
        """Сохраняет историю сделок в файл"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Ошибка сохранения истории: {e}")

    def add_to_history(self, history_entry):
        """Добавляет сделку в историю"""
        self.trade_history.append(history_entry)
        self.last_update = time.time()

        # Авто-сохранение
        self.save_history()

        # Авто-очистка старых данных (старше 30 дней)
        self.clean_old_history()

    def clean_old_history(self, max_days=30):
        """Очищает историю старше max_days дней"""
        current_time = time.time()
        cutoff_time = current_time - (max_days * 24 * 60 * 60)

        initial_count = len(self.trade_history)
        self.trade_history = [
            trade for trade in self.trade_history
            if trade.get('timestamp', current_time) >= cutoff_time
        ]

        if len(self.trade_history) < initial_count:
            self.save_history()
            print(f"🧹 Очищена история: {initial_count - len(self.trade_history)} старых сделок")

    def update_signal_data(self, signal_data: Dict[str, Any]):
        """Обновляет данные сигнала для веб-интерфейса"""
        signal_id = signal_data.get('signal_id')
        if signal_id:
            self.active_signals[signal_id] = signal_data
            self.last_update = time.time()
            print(
                f"📡 Обновлены данные сигнала {signal_id}: символ={signal_data.get('symbol')}, PnL={signal_data.get('pnl_percent')}")

    def update_price_data(self, symbol: str, price_data: Dict[str, Any]):
        """Обновляет ценовые данные для веб-интерфейса"""
        self.price_updates[symbol] = price_data
        self.last_update = time.time()
        print(f"💰 Обновлены ценовые данные для {symbol}: цена={price_data.get('current_price')}")

    def get_processed_data(self) -> Dict[str, Any]:
        """Возвращает обработанные данные с ПРАВИЛЬНЫМИ reached_tps"""
        processed_signals = {}

        # ВАЖНО: Используем self.active_signals.items() а не trading_data.active_signals
        for signal_id, signal in self.active_signals.items():
            # Создаем глубокую копию сигнала
            processed_signal = signal.copy()
            symbol = signal.get('symbol')

            print(f"🔍 Обрабатываем сигнал: {symbol}")

            # Если есть ценовые данные, ПЕРЕСЧИТЫВАЕМ reached_tps
            if symbol and symbol in self.price_updates:
                price_info = self.price_updates[symbol]
                current_price = price_info.get('current_price')

                if current_price is not None:
                    direction = signal.get('direction')
                    take_profits = signal.get('take_profits', [])

                    # ВАЖНО: СБРАСЫВАЕМ И ПЕРЕСЧИТЫВАЕМ reached_tps на основе текущей цены
                    actual_reached_tps = []

                    for i, tp in enumerate(take_profits):
                        if direction == "LONG" and current_price >= tp:
                            actual_reached_tps.append(i)
                        elif direction == "SHORT" and current_price <= tp:
                            actual_reached_tps.append(i)

                    # ЗАМЕНЯЕМ старые reached_tps на актуальные
                    processed_signal['reached_tps'] = actual_reached_tps

                    # Обновляем остальные данные
                    processed_signal['current_price'] = current_price
                    processed_signal['pnl_percent'] = price_info.get('pnl_percent', 0)
                    processed_signal['exchange'] = price_info.get('exchange', 'Unknown')

            processed_signals[signal_id] = processed_signal

        print(f"📊 Всего активных сигналов: {len(processed_signals)}")

        # ВОЗВРАЩАЕМ ВСЕ сигналы, без ограничений
        return {
            'active_signals': processed_signals,
            'price_updates': self.price_updates,
            'last_update': self.last_update
        }

    def clear_old_signals(self, max_age_seconds: int = 3600):
        """Очищает старые сигналы"""
        current_time = time.time()
        expired_signals = []

        for signal_id, signal_data in self.active_signals.items():
            # Используем timestamp из данных сигнала или время последнего обновления
            signal_time = signal_data.get('timestamp', self.last_update)
            if current_time - signal_time > max_age_seconds:
                expired_signals.append(signal_id)

        for signal_id in expired_signals:
            del self.active_signals[signal_id]

    def get_weekly_stats(self):
        """Возвращает статистику по неделям"""
        weekly_stats = {}

        for trade in self.trade_history:
            # Определяем неделю
            trade_time = datetime.fromtimestamp(trade['timestamp'])
            year, week, _ = trade_time.isocalendar()
            week_key = f"{year}-W{week:02d}"

            if week_key not in weekly_stats:
                weekly_stats[week_key] = {
                    'week_start': trade_time - timedelta(days=trade_time.weekday()),
                    'total_trades': 0,
                    'profitable_trades': 0,
                    'total_pnl': 0,
                    'sources': {},
                    'closed_trades': 0,
                    'active_trades': 0
                }

            week_data = weekly_stats[week_key]
            week_data['total_trades'] += 1

            # Считаем PnL если есть информация о закрытии
            if 'close_price' in trade and trade['entry_prices']:
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
            if source not in week_data['sources']:
                week_data['sources'][source] = 0
            week_data['sources'][source] += 1

            # Считаем закрытые сделки
            if 'close_reason' in trade:
                week_data['closed_trades'] += 1
            else:
                week_data['active_trades'] += 1

        return weekly_stats

    def get_source_stats(self, days=7):
        """Статистика по источникам за последние N дней"""
        cutoff_time = time.time() - (days * 24 * 60 * 60)

        source_stats = {}
        for trade in self.trade_history:
            if trade['timestamp'] >= cutoff_time:
                source = trade.get('source', 'Unknown')
                if source not in source_stats:
                    source_stats[source] = {
                        'total_trades': 0,
                        'profitable_trades': 0,
                        'total_pnl': 0,
                        'avg_leverage': 0,
                        'leverage_sum': 0,
                        'leverage_count': 0
                    }

                stats = source_stats[source]
                stats['total_trades'] += 1

                # PnL расчет
                if 'close_price' in trade and trade['entry_prices']:
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
                if trade.get('leverage'):
                    stats['leverage_sum'] += trade['leverage']
                    stats['leverage_count'] += 1

        # Вычисляем среднее плечо
        for source in source_stats.values():
            if source['leverage_count'] > 0:
                source['avg_leverage'] = source['leverage_sum'] / source['leverage_count']

        return source_stats

    def get_symbol_data(self, symbol: str) -> Dict[str, Any]:
        """Возвращает данные по символу"""
        return self.price_updates.get(symbol, {})


# Глобальный экземпляр
trading_data = TradingData()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stats')
def stats_page():
    return render_template('stats.html')


@app.route('/history')
def history_page():
    return render_template('stats.html')  # Можно использовать тот же шаблон


@app.route('/api/data')
def api_data():
    """API endpoint для получения данных в реальном времени"""
    # Очищаем старые сигналы
    trading_data.clear_old_signals()

    # Возвращаем обработанные данные
    return jsonify(trading_data.get_processed_data())


@app.route('/api/stats')
def api_stats():
    """API для расширенной статистики"""
    weekly_stats = trading_data.get_weekly_stats()
    source_stats = trading_data.get_source_stats(days=7)

    return jsonify({
        'weekly_stats': weekly_stats,
        'source_stats': source_stats,
        'total_history_trades': len(trading_data.trade_history),
        'last_update': trading_data.last_update
    })


@app.route('/api/history')
def api_history():
    """API для истории сделок"""
    page = request.args.get('page', 1, type=int)
    source_filter = request.args.get('source', '')
    status_filter = request.args.get('status', '')  # all, active, completed, stopped

    # Фильтрация
    filtered_history = trading_data.trade_history.copy()

    if source_filter:
        filtered_history = [t for t in filtered_history if t.get('source') == source_filter]

    # ПРАВИЛЬНАЯ фильтрация по статусу
    if status_filter == 'active':
        # Активные сделки - те, у которых нет close_reason
        filtered_history = [t for t in filtered_history if 'close_reason' not in t]
    elif status_filter == 'completed':
        # Завершенные по тейк-профитам
        filtered_history = [t for t in filtered_history if t.get('close_reason') == 'all_take_profits']
    elif status_filter == 'stopped':
        # Остановленные по стоп-лоссу
        filtered_history = [t for t in filtered_history if t.get('close_reason') == 'stop_loss']
    # Для 'all' - не фильтруем

    # Сортируем по времени (новые сверху)
    filtered_history.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

    # Пагинация
    per_page = 50
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page

    return jsonify({
        'history': filtered_history[start_idx:end_idx],
        'total_count': len(filtered_history),
        'page': page,
        'per_page': per_page
    })


def get_trading_data():
    """Возвращает глобальный экземпляр trading_data"""
    return trading_data


def run_web_server():
    """Запускает веб-сервер"""
    print("🌐 Web dashboard available at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


# Запуск веб-сервера в отдельном потоке
def start_web_interface():
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
