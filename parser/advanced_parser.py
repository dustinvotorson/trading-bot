import re
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    symbol: str
    direction: str
    entry_prices: List[float]
    limit_prices: List[float]
    take_profits: List[float]
    stop_loss: Optional[float]
    leverage: Optional[int]
    margin: Optional[float]
    source: str
    timestamp: float


class AdvancedSignalParser:
    def __init__(self):
        self.sources_keywords = {
            'CRYPTOGRAD': ['cryptograd', 'криптоград'],
            'SEREBROV': ['serebrov', 'silver', 'серебров'],
            'CRYPTOFUTURES': ['cryptofutures', 'криптофьючерс'],
            'LIGHT': ['#light', 'лайт'],
            'NESTOEROV': ['nesterov', 'family', 'нестеров'],
            'PRIVATE': ['private', 'club', 'прайват', 'клуб', 'прайват клаб', 'торговый букварь'],
            'VT': ['vt'],
            'WOLF_TRADING': ['wolf trading'],
            'ARTEMA': ['артема'],
            'KHRUSTALEV': ['хрусталев', 'khrustalev']
        }

    def extract_all_numbers(self, text: str) -> List[float]:
        """Извлекает все числа из текста"""
        numbers = []
        normalized_text = text.replace(',', '.')

        # Ищем числа с плавающей точкой
        float_matches = re.findall(r'\d+\.\d+', normalized_text)
        numbers = [float(match) for match in float_matches]

        return list(dict.fromkeys(numbers))

    def normalize_symbol(self, symbol: str) -> str:
        """Приводит символ к стандартному формату"""
        symbol = symbol.replace('/', '').replace('#', '').upper()
        if not symbol.endswith('USDT'):
            symbol += 'USDT'
        return symbol

    def parse_cryptograd(self, text: str) -> Tuple[List[float], List[float], Optional[float]]:
        """Парсинг CryptoGrad - УЛУЧШЕННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing CryptoGrad format")

        entry_prices = []
        take_profits = []
        stop_loss = None

        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Поиск входа - разные форматы
            if any(keyword in line_clean.lower() for keyword in ['точка входа', 'entry']):
                prices = re.findall(r'(\d+[.,]\d+)', line_clean.replace(',', '.'))
                if prices:
                    entry_prices = [float(prices[0])]
                    logger.info(f"🔧 Found CryptoGrad entry: {entry_prices}")

            # Поиск тейк-профитов
            elif any(keyword in line_clean.lower() for keyword in ['цели', 'тейк', 'take profit', 'tp']):
                prices = re.findall(r'(\d+[.,]\d+)', line_clean.replace(',', '.'))
                if prices:
                    take_profits.extend([float(p) for p in prices])
                    logger.info(f"🔧 Found CryptoGrad TPs: {take_profits}")

            # Поиск стоп-лосса
            elif any(keyword in line_clean.lower() for keyword in ['стоп', 'stop loss', 'sl']):
                prices = re.findall(r'(\d+[.,]\d+)', line_clean.replace(',', '.'))
                if prices:
                    stop_loss = float(prices[0])
                    logger.info(f"🔧 Found CryptoGrad SL: {stop_loss}")

        return entry_prices, take_profits, stop_loss

    def parse_nesterov(self, text: str) -> Tuple[List[float], List[float], Optional[float]]:
        """Парсинг Nesterov Family - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing Nesterov format")

        entry_prices = []
        take_profits = []
        stop_loss = None

        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Диапазон входов: "Твх: 656-658" или "Твх: 1.0930-1.0980"
            if any(keyword in line_clean.lower() for keyword in ['твх:', 'вход:', 'entry:']):
                # Ищем диапазон типа 656-658 или 1.0930-1.0980
                range_match = re.search(r'(\d+\.?\d*)[^\d]*-[^\d]*(\d+\.?\d*)', line_clean)
                if range_match:
                    try:
                        price1 = float(range_match.group(1))
                        price2 = float(range_match.group(2))
                        entry_prices = [price1, price2]
                        logger.info(f"🔧 Found Nesterov entry range: {entry_prices}")
                    except:
                        pass
                else:
                    # Ищем одиночные цены
                    prices = re.findall(r'\d+\.?\d*', line_clean)
                    if prices:
                        try:
                            entry_prices = [float(prices[0])]
                            logger.info(f"🔧 Found Nesterov entry: {entry_prices}")
                        except:
                            pass

            # Тейк-профиты: "По целям: 651.72, 645.14, 638.56, 631.97"
            elif any(keyword in line_clean.lower() for keyword in ['по целям', 'цели', 'targets']):
                prices = re.findall(r'\d+\.\d+', line_clean)
                if prices:
                    try:
                        take_profits = [float(p) for p in prices]
                        logger.info(f"🔧 Found Nesterov TPs: {take_profits}")
                    except:
                        pass

            # Стоп-лосс
            elif any(keyword in line_clean.lower() for keyword in ['стоп', 'stop']):
                prices = re.findall(r'\d+\.\d+', line_clean)
                if prices:
                    try:
                        stop_loss = float(prices[0])
                        logger.info(f"🔧 Found Nesterov SL: {stop_loss}")
                    except:
                        pass

        return entry_prices, take_profits, stop_loss
    def parse_private_club(self, text: str) -> Tuple[List[float], List[float], Optional[float]]:
        """Парсинг Private Club - УЛУЧШЕННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing Private Club format")

        entry_prices = []
        take_profits = []
        stop_loss = None

        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Вход: "Точка входа: 0.003422"
            if any(keyword in line_clean.lower() for keyword in ['точка входа', 'entry']):
                prices = re.findall(r'\d+\.\d+', line_clean)
                if prices:
                    entry_prices = [float(prices[0])]
                    logger.info(f"🔧 Found Private Club entry: {entry_prices}")

            # Точки фиксации: "Точки фиксации: 0.003466, 0.003490, ..."
            elif any(keyword in line_clean.lower() for keyword in ['точки фиксации', 'take profit', 'tp']):
                prices = re.findall(r'\d+\.\d+', line_clean)
                if prices:
                    take_profits = [float(p) for p in prices]
                    logger.info(f"🔧 Found Private Club TPs: {take_profits}")

        return entry_prices, take_profits, stop_loss

    def parse_wolf_trading(self, text: str) -> Tuple[List[float], List[float], List[float], Optional[float]]:
        """Парсинг Wolf Trading - УЛУЧШЕННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing Wolf Trading format")

        entry_prices = []
        limit_prices = []
        take_profits = []
        stop_loss = None
        leverage = 1

        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Определяем направление и символ
            if line_clean.startswith('LONG') or line_clean.startswith('SHORT'):
                # Ищем плечо (50X)
                leverage_match = re.search(r'(\d+)X', line_clean)
                if leverage_match:
                    leverage = int(leverage_match.group(1))

            # Цена входа (рыночный вход)
            elif line_clean.startswith('TAKE ENTRY'):
                try:
                    entry_price = float(line_clean.split()[-1])
                    entry_prices = [entry_price]
                    logger.info(f"🔧 Found Wolf Trading entry: {entry_prices}")
                except:
                    pass

            # Тейк-профиты
            elif line_clean.startswith('SET TP'):
                try:
                    tp_price = float(line_clean.split()[-1])
                    take_profits.append(tp_price)
                    logger.info(f"🔧 Found Wolf Trading TP: {tp_price}")
                except:
                    pass

            # Стоп-лосс
            elif line_clean.startswith('SET SL'):
                try:
                    stop_loss = float(line_clean.split()[-1])
                    logger.info(f"🔧 Found Wolf Trading SL: {stop_loss}")
                except:
                    pass

        # Сортируем тейк-профиты
        take_profits.sort()

        return entry_prices, limit_prices, take_profits, stop_loss

    def parse_artema(self, text: str) -> Tuple[List[float], List[float], List[float], Optional[float]]:
        """Парсинг сигналов от Артема - ПОЛНОСТЬЮ ПЕРЕРАБОТАННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing Artema format")

        entry_prices = []
        limit_prices = []
        take_profits = []
        stop_loss = None

        # Очищаем текст от лишних символов
        clean_text = text.replace('**', '').replace('*', '').replace('•', '')
        lines = [line.strip() for line in clean_text.split('\n') if line.strip()]

        # 1. Парсим цены входа и лимитные ордера - ТОЧНЫЙ ПОИСК
        for i, line in enumerate(lines):
            line_clean = line.lower()

            # Точный поиск цен входа
            if 'значение для входа:' in line_clean:
                # Ищем число после "Значение для входа:"
                matches = re.findall(r'значение для входа:\s*(\d+[.,]\d+)', line_clean)
                for match in matches:
                    try:
                        price = float(match.replace(',', '.'))
                        if 0.1 <= price <= 100:  # ETHFI диапазон
                            limit_prices.append(price)
                            logger.info(f"🔧 Found Artema entry price: {price}")
                    except:
                        pass

            # Поиск доборов
            elif 'добор' in line_clean and not any(x in line_clean for x in ['%', 'фикс']):
                # Ищем числа в строке с добором, исключая проценты
                matches = re.findall(r'(\d+[.,]\d+)', line_clean)
                for match in matches:
                    try:
                        price = float(match.replace(',', '.'))
                        # Фильтруем: должны быть цены, а не проценты
                        if 0.1 <= price <= 100 and price not in limit_prices:
                            limit_prices.append(price)
                            logger.info(f"🔧 Found Artema add entry: {price}")
                    except:
                        pass

        # 2. Парсим тейк-профиты - ОСНОВНОЙ ФОКУС
        # Ищем секцию с TP
        in_tp_section = False
        tp_lines = []

        for line in lines:
            line_clean = line.lower()

            # Начало секции TP
            if any(keyword in line_clean for keyword in ['tp1:', 'тейк']):
                in_tp_section = True

            # Конец секции TP
            if any(keyword in line_clean for keyword in ['стоп', 'sl', 'stop']):
                in_tp_section = False

            if in_tp_section and any(keyword in line_clean for keyword in ['tp', 'тейк']):
                tp_lines.append(line)

        # Парсим TP из найденных строк
        for line in tp_lines:
            # Убираем текст в скобках (проценты объема)
            line_without_brackets = re.sub(r'\([^)]*\)', '', line)

            # Ищем TP в разных форматах
            tp_patterns = [
                r'TP\s*\d*\s*:?\s*(\d+[.,]?\d*)\s*\$?',  # TP1: 3$ или TP1: 3.0
                r'(\d+[.,]?\d*)\s*\$',  # 3$ или 3.0$
                r'TP\s*\d*\s*:?\s*(\d+[.,]\d+)',  # TP1: 0.48
                r'(\d+[.,]\d+)(?:\s|$)',  # 0.48 (в конце строки)
            ]

            for pattern in tp_patterns:
                matches = re.findall(pattern, line_without_brackets, re.IGNORECASE)
                for match in matches:
                    try:
                        price = float(match.replace(',', '.'))
                        # Строгая фильтрация тейк-профитов
                        if (0.1 <= price <= 1000 and
                                price not in take_profits and
                                not (0 < price < 1 and price in [0.3, 0.2]) and  # Исключаем проценты маржи
                                not (price > 10 and price % 1 == 0 and price in [20, 30,
                                                                                 50])):  # Исключаем проценты объема
                            take_profits.append(price)
                            logger.info(f"🔧 Found Artema TP: {price} from: {line.strip()}")
                    except:
                        pass

        # 3. Парсим стоп-лосс отдельно
        for line in lines:
            line_clean = line.lower()
            if any(keyword in line_clean for keyword in ['стоп', 'sl', 'stop']):
                # Ищем число после ключевых слов стоп-лосса
                sl_matches = re.findall(r'стоп[^\d]*(\d+[.,]\d+)', line_clean)
                if not sl_matches:
                    sl_matches = re.findall(r'(\d+[.,]\d+)', line_clean)

                if sl_matches:
                    try:
                        stop_loss = float(sl_matches[0].replace(',', '.'))
                        # Проверяем, что стоп-лосс реалистичный
                        if 0.01 <= stop_loss <= 100:
                            logger.info(f"🔧 Found Artema SL: {stop_loss}")
                            break
                    except:
                        pass

        # 4. Обработка и фильтрация результатов
        # Убираем дубликаты и сортируем
        limit_prices = sorted(list(set(limit_prices)))
        take_profits = sorted(list(set(take_profits)))

        # Фильтруем тейк-профиты: для LONG должны быть больше цены входа
        if limit_prices and take_profits:
            main_entry = limit_prices[0]  # Основная цена входа
            filtered_tps = []
            for tp in take_profits:
                if tp > main_entry:  # Для LONG тейк-профиты должны быть выше цены входа
                    filtered_tps.append(tp)
                else:
                    logger.info(f"🔧 Filtered out TP {tp} (not greater than entry {main_entry})")
            take_profits = filtered_tps

        # Устанавливаем основную цену входа
        if limit_prices and not entry_prices:
            entry_prices = [limit_prices[0]]  # Первая цена как основной вход

        # Если нет тейк-профитов, но есть текст с TP, пробуем альтернативный метод
        if not take_profits and any('tp' in line.lower() for line in lines):
            logger.info("🔧 Alternative TP parsing...")
            # Пробуем найти любые числа после TP в тексте
            for line in lines:
                if 'tp' in line.lower():
                    # Ищем все числа в строке с TP
                    numbers = re.findall(r'(\d+[.,]\d+)', line)
                    for num in numbers:
                        try:
                            price = float(num.replace(',', '.'))
                            if 0.1 <= price <= 100 and price not in take_profits:
                                take_profits.append(price)
                        except:
                            pass
            take_profits = sorted(list(set(take_profits)))

        logger.info(
            f"🔧 Final Artema - Entries: {entry_prices}, Limits: {limit_prices}, TPs: {take_profits}, SL: {stop_loss}")

        return entry_prices, limit_prices, take_profits, stop_loss

    def parse_cryptofutures(self, text: str) -> Tuple[List[float], List[float], Optional[float]]:
        """Парсинг CryptoFutures - специальный парсер"""
        logger.info("🔧 Parsing CryptoFutures format")

        entry_prices = []
        take_profits = []
        stop_loss = None

        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Вход: "Вход: Рынок и лимитка - 6.680"
            if any(keyword in line_clean.lower() for keyword in ['вход:', 'entry:']):
                # Ищем число после дефиса или двоеточия
                prices = re.findall(r'[\s:-](\d+\.\d+)', line_clean)
                if prices:
                    try:
                        entry_prices = [float(prices[0])]
                        logger.info(f"🔧 Found CryptoFutures entry: {entry_prices}")
                    except:
                        pass

            # Цели: "Цели: 7.055 7.260 7.810"
            elif any(keyword in line_clean.lower() for keyword in ['цели:', 'targets:']):
                prices = re.findall(r'(\d+\.\d+)', line_clean)
                if prices:
                    try:
                        take_profits = [float(p) for p in prices]
                        logger.info(f"🔧 Found CryptoFutures TPs: {take_profits}")
                    except:
                        pass

            # Стоп-лосс: "Стоп: 6.455"
            elif any(keyword in line_clean.lower() for keyword in ['стоп:', 'stop:']):
                prices = re.findall(r'(\d+\.\d+)', line_clean)
                if prices:
                    try:
                        stop_loss = float(prices[0])
                        logger.info(f"🔧 Found CryptoFutures SL: {stop_loss}")
                    except:
                        pass

        return entry_prices, take_profits, stop_loss
    def parse_khrustalev(self, text: str, source: str) -> TradeSignal:
        """Парсинг сигналов Хрусталева - УЛУЧШЕННАЯ ВЕРСИЯ"""
        logger.info("🔧 Parsing Khrustalev format")

        symbol = "UNKNOWN"
        direction = "UNKNOWN"
        entry_prices = []
        take_profits = []
        stop_loss = None

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        logger.info(f"🔧 Khrustalev lines: {lines}")

        # Определяем тип сообщения
        has_symbol_direction = any(any(word in line.upper() for word in ['LONG', 'SHORT']) for line in lines)
        has_entry = any('твх:' in line.lower() for line in lines)
        has_targets = any('цели:' in line.lower() for line in lines)

        # 1. Парсим символ и направление (только если есть в сообщении)
        if has_symbol_direction:
            for line in lines:
                line_upper = line.upper()
                if any(word in line_upper for word in ['LONG', 'SHORT']):
                    # Используем улучшенный метод извлечения символа
                    symbol = self.extract_symbol_improved(line)
                    if symbol == "UNKNOWN":
                        # Пробуем извлечь символ из строки вручную
                        words = line_upper.split()
                        for i, word in enumerate(words):
                            if word in ['LONG', 'SHORT'] and i > 0:
                                symbol_candidate = words[i - 1]
                                symbol = self.normalize_symbol(symbol_candidate)
                                break

                    direction = "LONG" if "LONG" in line_upper else "SHORT"
                    logger.info(f"🔧 Found Khrustalev symbol: {symbol}, direction: {direction}")
                    break

        # 2. Парсим точку входа (твх)
        if has_entry:
            for line in lines:
                line_lower = line.lower()
                if 'твх:' in line_lower:
                    matches = re.findall(r'твх:\s*(\d+[.,]\d+)', line_lower)
                    for match in matches:
                        try:
                            price = float(match.replace(',', '.'))
                            entry_prices = [price]
                            logger.info(f"🔧 Found Khrustalev entry: {price}")
                        except:
                            pass

        # 3. Парсим цели - УЛУЧШЕННЫЙ ПАРСИНГ
        if has_targets:
            in_targets_section = False
            for line in lines:
                line_clean = line.strip()
                line_lower = line_clean.lower()

                if 'цели:' in line_lower:
                    in_targets_section = True
                    continue

                if in_targets_section:
                    # Если нашли "добор:", выходим из секции целей
                    if 'добор:' in line_lower:
                        in_targets_section = False
                    else:
                        # Ищем числа в строке (только если строка не пустая и не содержит других ключевых слов)
                        if line_clean and not any(keyword in line_lower for keyword in ['твх:', 'long', 'short']):
                            matches = re.findall(r'(\d+[.,]\d+)', line_clean)
                            for match in matches:
                                try:
                                    price = float(match.replace(',', '.'))
                                    if 0.001 < price < 1000 and price not in take_profits:
                                        take_profits.append(price)
                                        logger.info(f"🔧 Found Khrustalev TP: {price}")
                                except:
                                    pass

        # 4. Парсим добор (стоп-лосс)
        for line in lines:
            line_lower = line.lower()
            if 'добор:' in line_lower:
                matches = re.findall(r'добор:\s*(\d+[.,]\d+)', line_lower)
                if matches:
                    try:
                        stop_loss = float(matches[0].replace(',', '.'))
                        logger.info(f"🔧 Found Khrustalev SL: {stop_loss}")
                    except:
                        pass

        # Сортируем тейк-профиты
        take_profits.sort()

        logger.info(f"🔧 Khrustalev result - Symbol: {symbol}, Direction: {direction}, " +
                    f"Entries: {entry_prices}, TPs: {take_profits}, SL: {stop_loss}")

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_prices=entry_prices,
            limit_prices=[],
            take_profits=take_profits,
            stop_loss=stop_loss,
            leverage=1,
            margin=None,
            source=source,
            timestamp=time.time()
        )
    def extract_leverage(self, text: str) -> Optional[int]:
        """Извлекает плечо - УЛУЧШЕННАЯ ВЕРСИЯ"""
        patterns = [
            r'(\d+)[xх]\s',
            r'\s(\d+)[xх]',
            r'[Пп]лечо[^\d]*(\d+)',
            r'[Лл]иверидж[^\d]*(\d+)',
            r'(\d+)[xх]',
            r'LONG\s+(\d+)x',
            r'SHORT\s+(\d+)x',
            r'(\d+)[xх]',  # Дублируем для надежности
        ]

        for pattern in patterns:
            leverage_match = re.search(pattern, text, re.IGNORECASE)
            if leverage_match:
                try:
                    leverage = int(leverage_match.group(1))
                    logger.info(f"🔧 Found leverage {leverage}")
                    return leverage
                except:
                    continue
        return 1

    def extract_margin(self, text: str) -> Optional[float]:
        """Извлекает маржу - УЛУЧШЕННАЯ ВЕРСИЯ"""
        # Ищем проценты маржи в контексте депозита
        margin_patterns = [
            r'(\d+[.,]\d+)%\s*от\s*депозита',
            r'(\d+)%\s*от\s*депозита',
            r'маржа\s*(\d+[.,]?\d*)%',
            r'(\d+[.,]?\d*)%\s*объем',
            r'фикс\s*(\d+)[.,]?\d*\s*%',  # "фикс 20% объема"
            r'(\d+[.,]?\d*)%\s*от\s*торгового',
        ]

        for pattern in margin_patterns:
            margin_matches = re.findall(pattern, text.lower())
            for match in margin_matches:
                try:
                    margin = float(match.replace(',', '.'))
                    # Фильтруем реалистичные значения маржи (0.1% - 100%)
                    if 0.1 <= margin <= 100:
                        logger.info(f"🔧 Found margin: {margin}%")
                        return margin
                except:
                    pass

        return None

    def extract_direction(self, text: str) -> str:
        """Определяет направление сделки"""
        text_upper = text.upper()
        if any(word in text_upper for word in ['LONG', 'ЛОНГ']):
            return "LONG"
        elif any(word in text_upper for word in ['SHORT', 'ШОРТ']):
            return "SHORT"
        else:
            return "UNKNOWN"

    def extract_symbol_improved(self, text: str) -> str:
        """Улучшенное извлечение символа - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        lines = text.split('\n')

        for line in lines:
            line_clean = line.strip()

            # Паттерн 1: Символ с /, например ILV/USDT или OPEN/USDT
            symbol_match = re.search(r'([A-Za-z0-9]{2,10})/[A-Za-z]{2,10}', line_clean)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with /: {symbol}")
                return self.normalize_symbol(symbol)

            # Паттерн 2: #SYMBOL (самый частый)
            symbol_match = re.search(r'#([A-Za-z0-9]{2,10})(?![a-z])', line_clean)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with #: {symbol}")
                return self.normalize_symbol(symbol)

            # Паттерн 3: LONG/SHORT #SYMBOL
            symbol_match = re.search(r'(?:LONG|SHORT)\s+#([A-Za-z0-9]{2,10})', line_clean, re.IGNORECASE)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with LONG/SHORT #: {symbol}")
                return self.normalize_symbol(symbol)

            # Паттерн 4: SYMBOL LONG/SHORT
            symbol_match = re.search(r'([A-Za-z0-9]{2,10})\s+(?:LONG|SHORT)', line_clean, re.IGNORECASE)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with LONG/SHORT: {symbol}")
                return self.normalize_symbol(symbol)

            # Паттерн 5: SYMBOLUSDT
            symbol_match = re.search(r'([A-Za-z0-9]{2,10})USDT', line_clean, re.IGNORECASE)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with USDT: {symbol}")
                return self.normalize_symbol(symbol)

            # Паттерн 6: SYMBOL/USDT
            symbol_match = re.search(r'([A-Za-z0-9]{2,10})/USDT', line_clean, re.IGNORECASE)
            if symbol_match:
                symbol = symbol_match.group(1).upper()
                logger.info(f"🔍 Found symbol with /USDT: {symbol}")
                return self.normalize_symbol(symbol)

        # Если символ не найден, попробуем найти любую аббревиатуру из заглавных букв
        for line in lines:
            line_clean = line.strip()
            # Ищем слова из 2-6 заглавных букв/цифр
            possible_symbols = re.findall(r'\b[A-Z0-9]{2,6}\b', line_clean)
            for symbol in possible_symbols:
                # Исключаем стоп-слова
                stop_words = {'LONG', 'SHORT', 'USDT', 'BTC', 'ETH', 'TP', 'SL', 'ENTRY', 'STOP', 'LOSS', 'TAKE',
                              'PROFIT', 'TARGET'}
                if symbol not in stop_words and not symbol.isdigit():
                    logger.info(f"🔍 Found possible symbol: {symbol}")
                    return self.normalize_symbol(symbol)

        logger.warning("🔍 Symbol not found in text")
        return "UNKNOWN"

    def detect_source(self, text: str, channel_source: str) -> str:
        """Определяет источник сигнала"""
        text_lower = text.lower()

        # Сначала проверяем специальные форматы
        if 'TAKE ENTRY' in text and 'SET TP' in text and 'SET SL' in text:
            return "WOLF_TRADING"
        elif 'Сигналы от Артема' in text or (
                'Открываю' in text and any(keyword in text for keyword in ['#LONG', '#SHORT', 'LONG', 'SHORT'])):
            return "ARTEMA"
        elif 'Nesterov Family' in text or 'нестеров' in text_lower:
            return "NESTOEROV"
        elif 'прайват клаб' in text_lower or 'private club' in text_lower:
            return "PRIVATE"
        elif 'CryptoGrad' in text or 'криптоград' in text_lower:
            return "CRYPTOGRAD"
        # ДОБАВЛЕНО: для Хрусталева проверяем по channel_source
        elif channel_source == "Хрусталев":
            return "KHRUSTALEV"
        else:
            # Затем проверяем по ключевым словам
            for source_name, keywords in self.sources_keywords.items():
                for keyword in keywords:
                    if keyword in text_lower:
                        return source_name
            return channel_source

    def parse_signal(self, text: str, source: str) -> TradeSignal:
        """Основной метод парсинга - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        logger.info(f"🔍 Parsing signal from: {source}")

        # Определяем источник
        detected_source = self.detect_source(text, source)
        logger.info(f"🔍 Detected source: {detected_source}")

        # Извлекаем символ
        symbol = self.extract_symbol_improved(text)
        logger.info(f"🔍 Symbol: {symbol}")

        # Направление
        direction = self.extract_direction(text)
        logger.info(f"🔍 Direction: {direction}")

        # Плечо
        leverage = self.extract_leverage(text)
        logger.info(f"🔍 Leverage: {leverage}")

        # Маржа
        margin = self.extract_margin(text)

        # Парсим в зависимости от источника
        entry_prices = []
        limit_prices = []
        take_profits = []
        stop_loss = None

        if detected_source == "WOLF_TRADING":
            entry_prices, limit_prices, take_profits, stop_loss = self.parse_wolf_trading(text)
        elif detected_source == "ARTEMA":
            entry_prices, limit_prices, take_profits, stop_loss = self.parse_artema(text)
        elif detected_source == "NESTOEROV":
            entry_prices, take_profits, stop_loss = self.parse_nesterov(text)
        elif detected_source == "PRIVATE":
            entry_prices, take_profits, stop_loss = self.parse_private_club(text)
        elif detected_source == "CRYPTOGRAD":
            entry_prices, take_profits, stop_loss = self.parse_cryptograd(text)
        elif detected_source == "CRYPTOFUTURES":
            entry_prices, take_profits, stop_loss = self.parse_cryptofutures(text)
        else:
            # Универсальный парсер для неизвестных форматов
            all_prices = self.extract_all_numbers(text)
            if all_prices:
                if len(all_prices) >= 3:
                    entry_prices = [all_prices[0]]
                    take_profits = all_prices[1:-1]
                    stop_loss = all_prices[-1]
                elif len(all_prices) == 2:
                    entry_prices = [all_prices[0]]
                    take_profits = [all_prices[1]]
                elif len(all_prices) == 1:
                    entry_prices = [all_prices[0]]
                logger.info(f"🔍 Universal parser found: Entries: {entry_prices}, TPs: {take_profits}, SL: {stop_loss}")

        # Если не нашли цены, пробуем найти любые числа в тексте
        if not entry_prices and not take_profits:
            all_numbers = self.extract_all_numbers(text)
            if all_numbers:
                entry_prices = [all_numbers[0]]
                if len(all_numbers) > 1:
                    take_profits = all_numbers[1:]
                logger.info(f"🔍 Fallback parser found: Entries: {entry_prices}, TPs: {take_profits}")

        logger.info(f"🔍 Final result - Symbol: {symbol}, Direction: {direction}, " +
                    f"Entries: {entry_prices}, Limits: {limit_prices}, TPs: {take_profits}, SL: {stop_loss}")

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_prices=entry_prices,
            limit_prices=limit_prices,
            take_profits=take_profits,
            stop_loss=stop_loss,
            leverage=leverage,
            margin=margin,
            source=detected_source,
            timestamp=time.time()
        )


# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
advanced_parser = AdvancedSignalParser()