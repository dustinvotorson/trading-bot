from flask import Flask, render_template, jsonify
import threading
import asyncio
import json
import time
from typing import Dict, Any

app = Flask(__name__)

# Глобальное хранилище для данных (временное решение)
trading_data = {
    'active_signals': {},
    'price_updates': {},
    'last_update': time.time()
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def api_data():
    """API endpoint для получения данных в реальном времени"""
    return jsonify({
        'active_signals': trading_data['active_signals'],
        'price_updates': trading_data['price_updates'],
        'last_update': trading_data['last_update']
    })

def update_signal_data(signal_data: Dict[str, Any]):
    """Обновляет данные сигнала для веб-интерфейса"""
    signal_id = signal_data.get('signal_id')
    if signal_id:
        trading_data['active_signals'][signal_id] = signal_data
        trading_data['last_update'] = time.time()

def update_price_data(symbol: str, price_data: Dict[str, Any]):
    """Обновляет ценовые данные для веб-интерфейса"""
    trading_data['price_updates'][symbol] = price_data
    trading_data['last_update'] = time.time()

def run_web_server():
    """Запускает веб-сервер"""
    print("🌐 Web dashboard available at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# Запуск веб-сервера в отдельном потоке
def start_web_interface():
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()