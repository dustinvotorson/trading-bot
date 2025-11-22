from .advanced_parser import advanced_parser, TradeSignal

# Для обратной совместимости
SignalParser = type('SignalParser', (), {
    'parse_signal': lambda self, text, source: advanced_parser.parse_signal(text, source)
})

signal_parser = SignalParser()