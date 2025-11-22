from flask import Flask, jsonify
import threading
from bot.telethon_bot import bot_instance  # Нужно будет немного изменить архитектуру

app = Flask(__name__)

# Временное хранилище для веб-интерфейса
active_signals_store = {}

@app.route('/')
def dashboard():
    return """
    <html>
        <head>
            <title>📊 Trading Signals Live</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background: #0d1117; color: white; }
                .signal { background: #161b22; padding: 15px; margin: 10px 0; border-radius: 8px; }
                .profit { color: #00d4aa; }
                .loss { color: #ff4d4d; }
                .header { display: flex; justify-content: space-between; align-items: center; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 Live Trading Signals</h1>
                <div id="status">🟢 Connected</div>
            </div>
            <div id="signals"></div>
            <script>
                function updateSignals() {
                    fetch('/api/signals')
                        .then(r => r.json())
                        .then(signals => {
                            const container = document.getElementById('signals');
                            container.innerHTML = signals.map(signal => `
                                <div class="signal">
                                    <h3>${signal.symbol} ${signal.direction} | ${signal.source}</h3>
                                    <p>Entry: ${signal.entry_prices.join(', ')}</p>
                                    <p>Take Profits: ${signal.take_profits.join(', ')}</p>
                                    <p>Stop: ${signal.stop_loss || 'N/A'}</p>
                                    <p class="${signal.pnl_percent >= 0 ? 'profit' : 'loss'}">
                                        P&L: ${signal.pnl_percent.toFixed(2)}%
                                    </p>
                                    <p>Current Price: ${signal.current_price}</p>
                                </div>
                            `).join('');
                        });
                }
                setInterval(updateSignals, 5000);
                updateSignals();
            </script>
        </body>
    </html>
    """

@app.route('/api/signals')
def api_signals():
    signals = []
    # Здесь будем получать данные из бота
    return jsonify(signals)

def run_web_server():
    app.run(host='0.0.0.0', port=5000, debug=False)

# Запуск веб-сервера в отдельном потоке
def start_web_interface():
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print("🌐 Web dashboard available at http://localhost:5000")