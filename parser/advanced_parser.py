import re
import time
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
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
    is_market: bool = False


class UniversalSignalParser:
    def __init__(self):
        self.patterns = {
            "direction": {
                "long": ["long", "лонг", "buy", "купить", "вверх", "рост"],
                "short": ["short", "шорт", "sell", "продать", "вниз", "падение"]
            },
            "entry": [
                "вход", "entry", "твх", "точка входа", "входим", "вход:",
                "entry:", "входная", "вход по", "цена входа", "take entry"
            ],
            "take_profit": [
                "тейк", "профит", "цель", "target", "tp", "цели:",
                "take profit", "тейк-профит", "по целям", "ориентировочные цели",
                "фиксация", "фиксируем", "цели", "targets", "цели :", "тейки:",
                "тейк-профит -", "точки фиксации", "фиксации"
            ],
            "stop_loss": [
                "стоп", "стоп-лосс", "stop", "sl", "stop loss", "лосс",
                "стоп лосс", "стоп:", "stop:", "стоп :", "стоп-лосс:", "стоп :", "стоп-лосс -"
            ],
            "market": ["рынок", "market", "по рынку", "маркет", "market entry", "MARKET"],
            "limit": ["лимит", "limit", "лимитка", "лимитный", "лимитный ордер", "лимитный ордер на"],
            "leverage": ["плечо", "leverage", "x", "кратность", "leverage:", "плечо:", "ливеридж"],
            "margin": ["маржа", "margin", "депозит", "депо", "риск", "объем", "% от", "на %"],
            "average": ["усреднение", "добор", "average", "добавить", "add"],
            "separators": {
                "range": ["-", "—", "до", "по", "или", "и"],
                "list": [",", ";", "|", "/", "и", "или", ":", "—", "-"],
                "decimal": [".", ","]
            }
        }

        self.stop_words = {
            'LONG', 'SHORT', 'USDT', 'BTC', 'ETH', 'TP', 'SL',
            'ENTRY', 'STOP', 'LOSS', 'TAKE', 'PROFIT', 'TARGET',
            'X', 'ВХОД', 'ВЫХОД', 'СТОП', 'ЦЕЛЬ', 'ДОБОР',
            'NESTEROV', 'FAMILY', 'TWO', 'FINGERS', 'PRIVATE',
            'CLUB', 'CRYPTO', 'FUTURES', 'COINFY', 'CRYPTOGRAD',
            'SHEF', 'FINANSIST', 'ЗАКРЫТОЕ', 'СООБЩЕСТВО', 'ШАФИНАНСИСТ'
        }

    def normalize_text(self, text: str) -> str:
        """Нормализует текст для обработки"""
        if not text:
            return ""

        # Удаляем форматирование Markdown
        patterns = [
            (r'\*\*(.*?)\*\*', r'\1'),  # **text**
            (r'\*(.*?)\*', r'\1'),  # *text*
            (r'__(.*?)__', r'\1'),  # __text__
            (r'_(.*?)_', r'\1'),  # _text_
            (r'`(.*?)`', r'\1'),  # `code`
            (r'~~(.*?)~~', r'\1'),  # ~~text~~
        ]

        normalized = text
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized)

        # Заменяем запятые на точки в десятичных числах
        def replace_comma(match):
            num = match.group(0)
            if ',' in num:
                # Проверяем, что это число с десятичной запятой
                parts = num.split(',')
                if len(parts) == 2 and parts[1].replace(' ', '').isdigit():
                    # Проверяем, что это не часть диапазона
                    if '-' not in num and '—' not in num:
                        return parts[0] + '.' + parts[1]
            return num

        normalized = re.sub(r'\d+,\d+', replace_comma, normalized)

        # Удаляем специальные символы, которые могут мешать парсингу
        special_chars = '~$€₽•→➜▶▼▲●○◆◇■□▢▣▤▥▦▧▨▩▪▫▬▭▮▯☐☑☒✅✓✔✕✖✗✘❌❎'
        for char in special_chars:
            normalized = normalized.replace(char, ' ')

        # Удаляем множественные пробелы
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    def detect_source(self, text: str, channel_name: str) -> str:
        """Определяет источник сигнала по ключевым словам и первой строке"""
        if not text:
            return channel_name.upper()

        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]

        if not lines:
            return channel_name.upper()

        text_lower = text.lower()

        # Проверяем по известным источникам в тексте
        sources = {
            "NESTEROV": ["nesterov", "family", "нестеров"],
            "CRYPTOGRAD": ["cryptograd", "криптоград"],
            "PRIVATE_CLUB": ["private", "club", "прайват", "клуб", "прайват клаб"],
            "CRYPTOFUTURES": ["cryptofutures", "криптофьючерс"],
            "COINFY": ["coinfy", "коинфи"],
            "TWO_FINGERS": ["two fingers", "ту фингерс"],
            "SHEF_FINANSIST": ["шеф финансист", "shef finansist"]
        }

        for source_name, keywords in sources.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return source_name

        # Проверяем характерные признаки CryptoGrad
        has_cryptograd_format = (
                re.search(r'точка входа:.*?лимитный ордер', text_lower) or
                re.search(r'ориентировочные цели:', text_lower) or
                re.search(r'маржа: кросс', text_lower)
        )

        if has_cryptograd_format:
            return "CRYPTOGRAD"

        # Ищем источник в первых строках
        for i, line in enumerate(lines[:3]):
            line_lower = line.lower()
            line_upper = line.upper()

            # Пропускаем строки, которые являются символом
            is_symbol_line = (
                    line.startswith('#') or
                    line.startswith('$') or
                    line.startswith('🎤') or
                    re.search(r'/USDT', line_upper) or
                    re.search(r'\b(?:LONG|SHORT)\b', line_upper) or
                    len(line.split()) <= 2
            )

            if not is_symbol_line:
                # Очищаем строку от эмодзи и спецсимволов
                clean_line = re.sub(r'[^\w\s]', '', line).strip()
                if clean_line and len(clean_line) > 2:
                    if not re.search(r'\d', clean_line) and not re.search(r'[^\w\s]', clean_line):
                        first_word = clean_line.split()[0]
                        if len(first_word) > 2:
                            return first_word.upper()

        return channel_name.upper()

    def extract_symbol(self, text: str) -> str:
        """Извлекает символ из текста - универсальный метод"""
        if not text:
            return "UNKNOWN"

        lines = text.split('\n')

        for line in lines:
            line_upper = line.upper().strip()

            # Удаляем эмодзи и специальные символы
            clean_line = re.sub(r'[^\w\s/#$]', '', line_upper).strip()

            # 1. #SYMBOL или #SYMBOLUSDT
            match = re.search(r'#([A-Z0-9]{2,10})(?:USDT)?\b', clean_line)
            if match:
                symbol = match.group(1)
                if symbol not in self.stop_words:
                    return self.normalize_symbol(symbol)

            # 2. $SYMBOL (особенно для Two Fingers: ✅$ Zec)
            match = re.search(r'\$([A-Z0-9]{2,10})\b', clean_line)
            if match:
                symbol = match.group(1)
                if symbol not in self.stop_words:
                    return self.normalize_symbol(symbol)

            # 3. SYMBOL/USDT (особенно для Шеф Финансист: 🎤BCH/USDT)
            match = re.search(r'\b([A-Z0-9]{2,10})/USDT\b', clean_line)
            if match:
                return self.normalize_symbol(match.group(1))

            # 4. SYMBOL USDT
            match = re.search(r'\b([A-Z0-9]{2,10})\s+USDT\b', clean_line)
            if match:
                return self.normalize_symbol(match.group(1))

            # 5. SYMBOL LONG/SHORT
            match = re.search(r'\b([A-Z0-9]{2,10})\s+(?:LONG|SHORT)\b', clean_line)
            if match:
                symbol = match.group(1)
                if (symbol not in self.stop_words and
                        not re.match(r'\d+[A-Z]+', symbol)):
                    return self.normalize_symbol(symbol)

            # 6. LONG/SHORT SYMBOL
            match = re.search(r'\b(?:LONG|SHORT)\s+([A-Z0-9]{2,10})\b', clean_line)
            if match:
                symbol = match.group(1)
                if symbol not in self.stop_words:
                    return self.normalize_symbol(symbol)

            # 7. Исключение для 1000PEPE - теперь преобразуем в PEPE
            if re.search(r'1000PEPE', clean_line):
                return "PEPEUSDT"

        # Если не нашли явно, ищем любую аббревиатуру
        for line in lines:
            clean_line = re.sub(r'[^\w\s]', '', line.upper())
            words = re.findall(r'\b[A-Z0-9]{2,8}\b', clean_line)
            for word in words:
                if (word not in self.stop_words and
                        not word.isdigit() and
                        len(word) >= 2 and
                        not re.fullmatch(r'\d+[XХ]', word)):
                    if re.match(r'\d+[A-Z]+', word):
                        match_letters = re.search(r'[A-Z]+', word)
                        if match_letters:
                            return self.normalize_symbol(match_letters.group(0))
                        continue
                    return self.normalize_symbol(word)

        return "UNKNOWN"

    def normalize_symbol(self, symbol: str) -> str:
        """Приводит символ к стандартному формату"""
        if not symbol:
            return "UNKNOWN"

        symbol = symbol.replace('/', '').replace('#', '').replace('$', '').upper()

        # Удаляем возможный существующий USDT
        if symbol.endswith('USDT'):
            symbol = symbol[:-4]

        # Добавляем USDT если его нет
        if not symbol.endswith('USDT'):
            symbol = symbol + 'USDT'

        # Проверяем на двойной USDT (на всякий случай)
        if symbol.endswith('USDTUSDT'):
            symbol = symbol[:-4]

        return symbol

    def extract_direction(self, text: str) -> str:
        """Определяет направление сделки"""
        if not text:
            return "UNKNOWN"

        text_upper = text.upper()
        text_lower = text.lower()

        # Сначала проверяем точные совпадения
        if re.search(r'\bLONG\b', text_upper):
            return "LONG"
        if re.search(r'\bSHORT\b', text_upper):
            return "SHORT"

        # Затем ключевые слова
        for keyword in self.patterns["direction"]["long"]:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                return "LONG"

        for keyword in self.patterns["direction"]["short"]:
            if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
                return "SHORT"

        return "UNKNOWN"

    def extract_leverage(self, text: str) -> Optional[int]:
        """Извлекает плечо"""
        if not text:
            return 1

        text_upper = text.upper()

        # Ищем паттерны типа 50X, 20x
        patterns = [
            r'(\d+)[XХ]\b',
            r'\b(\d+)\s*[XХ]\b',
            r'ПЛЕЧО[^\d]*(\d+)',
            r'LEVERAGE[^\d]*(\d+)',
            r'\b(\d+)X\s*LEVERAGE',
        ]

        for pattern in patterns:
            match = re.search(pattern, text_upper)
            if match:
                try:
                    leverage = int(match.group(1))
                    if 1 <= leverage <= 100:
                        return leverage
                except (ValueError, IndexError):
                    continue

        # Для диапазона (например, 10-50x) -> берем среднее
        range_match = re.search(r'(\d+)\s*[-—]\s*(\d+)\s*[XХ]', text_upper)
        if range_match:
            try:
                leverage1 = int(range_match.group(1))
                leverage2 = int(range_match.group(2))
                avg_leverage = (leverage1 + leverage2) // 2
                if 1 <= avg_leverage <= 100:
                    return avg_leverage
            except (ValueError, IndexError):
                pass

        return 1

    def extract_margin(self, text: str) -> Optional[float]:
        """Извлекает маржу (% от депозита)"""
        if not text:
            return None

        text_lower = text.lower()

        patterns = [
            r'(\d+(?:[.,]\d+)?)%\s*от\s*(?:торгового\s*)?депозита',
            r'на\s*(\d+(?:[.,]\d+)?)%\s*от\s*депо',
            r'маржа\s*(\d+(?:[.,]\d+)?)%',
            r'риск\s*(\d+(?:[.,]\d+)?)%',
            r'(\d+(?:[.,]\d+)?)%\s*депо',
            r'(\d+(?:[.,]\d+)?)%\s*объем',
            r'(\d+(?:[.,]\d+)?)%\s*в\s*сделку',
            r'заходим\s*максимум\s*на\s*(\d+(?:[.,]\d+)?)%',
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    margin = float(match.group(1).replace(',', '.'))
                    if 0.1 <= margin <= 100:
                        return margin
                except (ValueError, IndexError):
                    continue

        return None

    def find_prices_by_context(self, text: str, context_keywords: List[str]) -> List[float]:
        """Находит цены в контексте ключевых слов"""
        if not text:
            return []

        prices = []
        lines = text.split('\n')

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Проверяем наличие ключевых слов в строке
            normalized_line = re.sub(r'[^\w\s:]', '', line_lower)

            has_context = any(keyword in normalized_line for keyword in context_keywords)

            if has_context:
                # Извлекаем цены из этой строки
                line_prices = self.extract_prices_from_line(line, filter_percents=True)
                prices.extend(line_prices)

                # Проверяем следующие строки (для вертикальных списков)
                j = i + 1
                while j < len(lines) and j < i + 10:
                    next_line = lines[j].strip()
                    if not next_line:
                        j += 1
                        continue

                    # Если строка начинается с цифры или содержит только цены
                    if (re.match(r'^\d+[.,]\d+', next_line) or
                            len(self.extract_prices_from_line(next_line, filter_percents=True)) > 0 and
                            len(re.findall(r'[а-яА-Яa-zA-Z]', next_line)) < 3):
                        next_prices = self.extract_prices_from_line(next_line, filter_percents=True)
                        prices.extend(next_prices)
                        j += 1
                    else:
                        break

        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_prices = []
        for price in prices:
            if price not in seen:
                seen.add(price)
                unique_prices.append(price)

        return unique_prices

    def extract_prices_from_line(self, line: str, filter_percents: bool = False) -> List[float]:
        """Извлекает все цены из строки"""
        if not line:
            return []

        prices = []

        # Нормализуем запятые в точках
        normalized_line = line.replace(',', '.')

        # Удаляем знаки валют и другие мешающие символы
        normalized_line = re.sub(r'[$€₽:~]', '', normalized_line)

        # Проверяем, содержит ли строка знак процента (для фильтрации)
        has_percent_sign = '%' in line

        # Ищем числа с плавающей точкой и целые числа
        matches = re.findall(r'\b\d+\.\d+\b|\b\d+\b', normalized_line)

        for match in matches:
            try:
                price = float(match)

                # Базовые проверки на реалистичность цены
                if not (0.000001 <= price <= 1000000):
                    continue

                # Фильтрация процентов если требуется
                if filter_percents and has_percent_sign:
                    # Ищем процентные значения в исходной строке
                    percent_pattern = rf'{re.escape(match)}\s*%'
                    if re.search(percent_pattern, line):
                        continue

                prices.append(price)
            except ValueError:
                continue

        return prices

    def extract_entry_info(self, text: str, source: str) -> Tuple[List[float], List[float], bool]:
        """Извлекает информацию о входе (цены, тип)"""
        if not text:
            return [], [], False

        text_lower = text.lower()

        entry_prices = []
        limit_prices = []
        is_market = False

        # 1. Проверяем явные указания на рыночный вход
        market_keywords = self.patterns["market"] + ["по рынку", "market", "MARKET"]
        for keyword in market_keywords:
            if keyword in text_lower:
                is_market = True
                logger.info(f"🔍 Found market keyword: {keyword}")
                break

        # 2. Обрабатываем диапазоны входа (например, 5.370-5.360)
        direction = self.extract_direction(text)

        for line in text.split('\n'):
            range_match = re.search(r'(\d+[.,]\d+)\s*[-—]\s*(\d+[.,]\d+)', line)
            if range_match:
                try:
                    price1 = float(range_match.group(1).replace(',', '.'))
                    price2 = float(range_match.group(2).replace(',', '.'))

                    line_lower = line.lower()
                    if any(keyword in line_lower for keyword in self.patterns["entry"]):
                        # Это диапазон входа
                        # Для SHORT сортируем по убыванию, для LONG по возрастанию
                        if direction == "SHORT":
                            entry_prices = sorted([price1, price2], reverse=True)
                        else:
                            entry_prices = sorted([price1, price2])
                except (ValueError, IndexError):
                    continue

        # 3. Если НЕ рыночный и не нашли диапазон - ищем одиночные цены
        if not is_market and not entry_prices:
            entry_price_candidates = self.find_prices_by_context(text, self.patterns["entry"])

            if entry_price_candidates:
                entry_prices = entry_price_candidates

        logger.info(f"🔍 Entry detection - is_market: {is_market}, entry_prices: {entry_prices}")
        return entry_prices, limit_prices, is_market

    def extract_take_profits(self, text: str, direction: str, entry_price: Optional[float]) -> List[float]:
        """Извлекает тейк-профиты"""
        if not text:
            return []

        # Сначала ищем по контексту
        tp_candidates = self.find_prices_by_context(text, self.patterns["take_profit"])

        # Если не нашли, ищем любые цены после ключевых слов
        if not tp_candidates:
            lines = text.split('\n')
            in_tp_section = False

            for line in lines:
                line_lower = line.lower()

                # Входим в секцию тейк-профитов
                if any(keyword in line_lower for keyword in self.patterns["take_profit"]):
                    in_tp_section = True

                # Если в секции тейк-профитов
                if in_tp_section:
                    prices = self.extract_prices_from_line(line, filter_percents=True)
                    if prices:
                        tp_candidates.extend(prices)

                    # Выходим из секции, если нашли другую ключевую секцию
                    if any(keyword in line_lower for keyword in self.patterns["stop_loss"] + self.patterns["entry"]):
                        in_tp_section = False

        # Фильтруем по направлению если есть цена входа
        filtered_tps = []
        if direction == "LONG" and entry_price is not None:
            filtered_tps = [tp for tp in tp_candidates if tp > entry_price]
        elif direction == "SHORT" and entry_price is not None:
            filtered_tps = [tp for tp in tp_candidates if tp < entry_price]
        else:
            filtered_tps = tp_candidates

        # Убираем дубликаты
        seen = set()
        unique_tps = []
        for tp in filtered_tps:
            if tp not in seen:
                seen.add(tp)
                unique_tps.append(tp)

        # Сортируем в зависимости от направления
        if direction == "SHORT":
            unique_tps.sort(reverse=True)
        elif direction == "LONG":
            unique_tps.sort()

        return unique_tps

    def extract_stop_loss(self, text: str) -> Optional[float]:
        """Извлекает стоп-лосс"""
        if not text:
            return None

        # Ищем по контексту
        sl_candidates = self.find_prices_by_context(text, self.patterns["stop_loss"])

        if sl_candidates:
            # Фильтруем проценты
            for candidate in sl_candidates:
                # Проверяем, не является ли это процентом
                percent_pattern = rf'{re.escape(str(candidate))}\s*%'
                if not re.search(percent_pattern, text):
                    return candidate

        # Дополнительный поиск
        for line in text.split('\n'):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in self.patterns["stop_loss"]):
                prices = self.extract_prices_from_line(line, filter_percents=True)
                if prices:
                    return prices[0]

        return None

    def parse_signal(self, text: str, source: str) -> TradeSignal:
        """Основной метод парсинга"""
        if not text or not isinstance(text, str):
            raise ValueError("Текст сигнала не может быть пустым")

        if len(text) > 10000:
            logger.warning("Текст сигнала слишком длинный, обрезаем до 10000 символов")
            text = text[:10000]

        logger.info(f"🔍 Parsing signal from: {source}")

        try:
            # Нормализуем текст
            normalized_text = self.normalize_text(text)

            # Определяем источник
            detected_source = self.detect_source(normalized_text, source)
            logger.info(f"🔍 Detected source: {detected_source}")

            # Извлекаем данные
            symbol = self.extract_symbol(normalized_text)
            direction = self.extract_direction(normalized_text)
            leverage = self.extract_leverage(normalized_text)
            margin = self.extract_margin(normalized_text)

            logger.info(f"🔍 Symbol: {symbol}")
            logger.info(f"🔍 Direction: {direction}")
            logger.info(f"🔍 Leverage: {leverage}")
            if margin:
                logger.info(f"🔍 Margin: {margin}%")

            # Извлекаем информацию о входе
            entry_prices, limit_prices, is_market = self.extract_entry_info(normalized_text, detected_source)

            if is_market:
                logger.info("🔍 Market order detected")

            # Определяем базовую цену для фильтрации
            base_price = None
            if entry_prices:
                base_price = entry_prices[0]
            elif limit_prices:
                base_price = limit_prices[0]

            # Извлекаем тейк-профиты
            take_profits = self.extract_take_profits(normalized_text, direction, base_price)

            # Извлекаем стоп-лосс
            stop_loss = self.extract_stop_loss(normalized_text)

            logger.info(f"🔍 Entry prices: {entry_prices}")
            logger.info(f"🔍 Limit prices: {limit_prices}")
            logger.info(f"🔍 Take profits: {take_profits}")
            logger.info(f"🔍 Stop loss: {stop_loss}")

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
                timestamp=time.time(),
                is_market=is_market
            )
        except Exception as e:
            logger.error(f"❌ Error parsing signal: {e}")
            # Возвращаем минимальный сигнал с ошибкой
            return TradeSignal(
                symbol="ERROR",
                direction="UNKNOWN",
                entry_prices=[],
                limit_prices=[],
                take_profits=[],
                stop_loss=None,
                leverage=1,
                margin=None,
                source=source,
                timestamp=time.time(),
                is_market=False
            )

    def is_preliminary_announcement(self, text: str) -> bool:
        """Определяет, является ли сообщение предварительным объявлением"""
        if not text:
            return False

        text_lower = text.lower()

        preliminary_keywords = [
            'готовься', 'приготовь', 'скоро', 'будет', 'следи',
            'внимание', 'объявляю', 'анонс', 'предупреждение',
            'жду', 'ожидай', 'следующ', 'готовьтесь', 'вскоре',
            'на подходе', 'готовьте', 'следите', 'скоро выложу',
            'ожидайте', 'внимание!', 'вскоре будет'
        ]

        has_preliminary = any(keyword in text_lower for keyword in preliminary_keywords)

        if has_preliminary:
            # Считаем количество конкретных торговых данных
            trading_data_count = 0

            if re.search(r'\d+[.,]\d+', text_lower):
                trading_data_count += 1

            if any(keyword in text_lower for keyword in self.patterns["entry"]):
                trading_data_count += 1

            if any(keyword in text_lower for keyword in self.patterns["take_profit"]):
                trading_data_count += 1

            if any(keyword in text_lower for keyword in self.patterns["stop_loss"]):
                trading_data_count += 1

            if trading_data_count < 2:
                return True

        return False


# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
universal_parser = UniversalSignalParser()

# Для совместимости с существующим кодом
advanced_parser = universal_parser
