import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
import time
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Класс для хранения торгового сигнала"""
    symbol: str = "UNKNOWN"
    direction: str = "UNKNOWN"  # LONG или SHORT
    entry_prices: List[float] = field(default_factory=list)
    limit_prices: List[float] = field(default_factory=list)
    take_profits: List[float] = field(default_factory=list)
    stop_loss: Optional[float] = None
    leverage: Optional[int] = None
    margin: Optional[float] = None
    source: str = "Unknown"
    timestamp: float = field(default_factory=time.time)
    is_market: bool = False
    entry_executed: bool = False
    original_text: str = ""
    risk_level: Optional[str] = None
    confidence: Optional[int] = None


class AdvancedParser:
    """Парсер торговых сигналов из разных источников"""

    # Ключевые слова для поиска блоков с тейк-профитами
    TAKE_PROFIT_KEYWORDS = [
        'тейк', 'take profit', 'тейки', 'take profits', 'тейк-профит',
        'цель', 'цели', 'target', 'targets', 'tp', 'тп',
        'goals', 'take', 'профит', 'profit', '🎯', '👑', '✅'
    ]

    # Ключевые слова для окончания блока тейк-профитов
    BLOCK_END_KEYWORDS = [
        'стоп', 'stop', 'стоп-лосс', 'stop loss', 'stoploss',
        'вход', 'entry', 'маржа', 'margin', 'леверидж', 'leverage',
        'риск', 'risk', '📊', '🚫', '❌'
    ]

    @staticmethod
    def filter_take_profits_by_entry(direction: str, entry_price: float, take_profits: List[float]) -> List[float]:
        """
        Фильтрует тейк-профиты в зависимости от направления и цены входа
        """
        if not take_profits or not entry_price:
            return take_profits

        logger.info(f"Фильтруем тейк-профиты: direction={direction}, entry={entry_price}, tps={take_profits}")

        if direction == "LONG":
            filtered = [tp for tp in take_profits if tp > entry_price]
            filtered.sort()  # Для LONG сортируем по возрастанию
            return filtered
        elif direction == "SHORT":
            filtered = [tp for tp in take_profits if tp < entry_price]
            filtered.sort(reverse=True)  # Для SHORT сортируем по убыванию
            return filtered
        else:
            return take_profits

    @staticmethod
    def extract_take_profits_block(text: str) -> Optional[str]:
        """
        Извлекает блок текста, содержащий тейк-профиты/цели
        """
        text_lower = text.lower()

        # Ищем начало блока с тейк-профитами
        start_pos = -1
        start_keyword = None

        # Специальная обработка для Nesterov Family формата "По целям:"
        if 'по целям:' in text_lower:
            pattern = re.compile(r'По целям:', re.IGNORECASE)
            match = pattern.search(text)
            if match:
                start_pos = match.start()
                start_keyword = 'По целям:'
                logger.debug(f"Найден специальный паттерн Nesterov Family: '{start_keyword}' на позиции {start_pos}")

        if start_pos == -1:
            # Обычный поиск по ключевым словам
            for keyword in AdvancedParser.TAKE_PROFIT_KEYWORDS:
                # Используем регулярное выражение для поиска слова с границами
                pattern = re.compile(rf'\b{re.escape(keyword)}[\s:—-]*', re.IGNORECASE)
                match = pattern.search(text)
                if match:
                    start_pos = match.start()
                    start_keyword = keyword
                    break

        if start_pos == -1:
            logger.debug("Не найден блок тейк-профитов в тексте")
            return None

        logger.debug(f"Найден стартовый ключ '{start_keyword}' на позиции {start_pos}")

        # Ищем конец блока тейк-профитов
        end_pos = len(text)

        # Для Nesterov Family ищем конец после запятой (или до следующего раздела)
        if 'По целям:' in text_lower:
            # Ищем следующие ключевые слова после "По целям:"
            for keyword in ['стоп', 'stop', 'сл', 'stoploss']:
                pos = text_lower.find(keyword, start_pos + len('По целям:'))
                if pos != -1 and pos < end_pos:
                    end_pos = pos
                    logger.debug(f"Найден конечный ключ для Nesterov: '{keyword}' на позиции {pos}")
                    break
        else:
            # Обычный поиск конца блока
            for keyword in AdvancedParser.BLOCK_END_KEYWORDS:
                # Ищем после начала блока
                pos = text_lower.find(keyword, start_pos + len(start_keyword))
                if pos != -1 and pos < end_pos:
                    end_pos = pos
                    logger.debug(f"Найден конечный ключ '{keyword}' на позиции {pos}")

        # Также ищем конец строки как альтернативный конец блока
        # Ищем перенос строки или знак конца сообщения
        for end_marker in ['\n', '•', '📈', '📊', 'ℹ️', '➡️']:
            pos = text.find(end_marker, start_pos)
            if pos != -1 and pos < end_pos:
                end_pos = pos
                logger.debug(f"Используем '{end_marker}' как конец блока на позиции {pos}")

        # Извлекаем блок
        block = text[start_pos:end_pos].strip()

        # Убираем стартовое ключевое слово и следующие за ним знаки препинания
        if start_keyword:
            # Создаем паттерн для удаления ключевого слова и следующих знаков препинания
            pattern = re.compile(f'{re.escape(start_keyword)}[\\s\\:\\-—]*', re.IGNORECASE)
            block = pattern.sub('', block, 1)

        # Убираем знаки препинания в начале блока
        block = re.sub(r'^[:\-—\s]+', '', block)

        logger.debug(f"Извлеченный блок тейк-профитов: '{block}'")
        return block

    @staticmethod
    def parse_take_profits_from_block(block: str) -> List[float]:
        """
        Парсит тейк-профиты из блока текста
        """
        if not block:
            return []

        logger.debug(f"Парсим тейк-профиты из блока: '{block}'")

        # Заменяем запятые на точки в десятичных числах (0,1202 → 0.1202)
        block = re.sub(r'(\d),(\d)', r'\1.\2', block)

        # Для Nesterov Family формата "5.307, 5.255, 5.200, 5.143" - парсим разделенные запятыми
        if ', ' in block or ' ,' in block or block.count(',') >= 2:
            # Разделяем по запятым
            parts = [p.strip() for p in block.split(',')]
            take_profits = []
            for part in parts:
                if not part:
                    continue
                # Очищаем часть от мусора
                clean_part = re.sub(r'[^\d.]', '', part)
                if clean_part:
                    try:
                        price = float(clean_part)
                        take_profits.append(price)
                        logger.debug(f"Найден тейк-профит (через запятую): {price}")
                    except ValueError:
                        logger.debug(f"Не удалось преобразовать '{clean_part}' в число")
            if take_profits:
                logger.info(f"Найдено тейк-профитов (через запятую): {len(take_profits)}")
                return take_profits

        # Обычная обработка для других форматов
        # Очищаем блок: оставляем только цифры, точки, дефисы, пробелы и символы разделителей
        cleaned_block = re.sub(r'[^\d\s.\-/|—,]', ' ', block)
        cleaned_block = re.sub(r'\s+', ' ', cleaned_block).strip()

        logger.debug(f"Очищенный блок: '{cleaned_block}'")

        # Разделяем на токены
        tokens = re.split(r'[\s—\-/,|]+', cleaned_block)
        take_profits = []

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            # Пробуем извлечь число
            number_match = re.match(r'^(\d+\.?\d*)$', token)
            if number_match:
                num_str = number_match.group(1)
                try:
                    price = float(num_str)
                    take_profits.append(price)
                    logger.debug(f"Найден тейк-профит: {price}")
                except ValueError:
                    logger.debug(f"Не удалось преобразовать '{num_str}' в число")
                    continue

        logger.info(f"Найдено тейк-профитов: {len(take_profits)}")
        return take_profits
    @staticmethod
    def parse_take_profits(text: str) -> List[float]:
        """
        Основная функция для парсинга тейк-профитов
        """
        # 1. Извлекаем блок с тейк-профитами
        block = AdvancedParser.extract_take_profits_block(text)

        # 2. Если блок найден, парсим из него числа
        if block:
            return AdvancedParser.parse_take_profits_from_block(block)

        return []

    @staticmethod
    def extract_symbol(text: str) -> str:
        """
        Извлекает торговый символ из текста с улучшенным fallback-детектором
        """
        FORBIDDEN = {
            "PUMP", "LONG", "SHORT", "SIGNAL", "ENTRY", "TARGET", "TARGETS",
            "TP", "SL", "STOP", "BUY", "SELL",
            "ТОЧКА", "ВХОД", "ТЕЙК", "ТЕЙКИ", "ЦЕЛИ", "ФИКСАЦИИ", "ДОБОР",
            "МАРЖА", "ПЛЕЧО", "УВЕДОМЛЮ", "КЛАБ", "ПРАЙВАТ", "TG", "ТГ",
            "ЗАКРЫТОЕ", "СООБЩЕСТВО", "PRIVATE", "CLUB", "УВЕДОМЛЮ", "ДОБОР",
            "ВХОДА", "ТОЧКА", "ТЕЙКИ", "TEЙKИ"
        }

        def normalize_symbol(sym: str) -> str:
            """Нормализует символ: убирает все не-буквы/цифры, приводит к верхнему регистру"""
            return re.sub(r'[^A-Z0-9]', '', sym.upper())

        text_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        upper_text = text.upper()

        # 1. Основные паттерны из оригинальной функции
        patterns = [
            # Сначала пробуем найти "Avax Short" или "PEPE SHORT" (слово перед SHORT/LONG)
            r'\b([A-Za-z0-9]{2,15})\s+(?:SHORT|LONG)\b',  # Avax Short или PEPE SHORT
            r'\b([A-Z]{2,10}/[A-Z]{3,5})\b',  # BTC/USDT
            r'\b([A-Z]{2,10}-[A-Z]{3,5})\b',  # BTC-USDT
            r'\$([A-Z]{2,10})\b',  # $BTC
            r'#([A-Z]{2,10})\b',  # #BTCUSDT
            r'\b([A-Z]{2,10}USDT)\b',  # BTCUSDT
            r'(\d+[A-Z]{2,10})\s+(?:SHORT|LONG)',  # 1000PEPE SHORT
            r'🎤([A-Z]+/[A-Z]+)',  # 🎤DAM/USDT
            r'\$\s*([A-Z]{2,10})\b',  # $ Zec
            r'\b([A-Z]{2,10})\s*$',  # AVAX в конце строки
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                symbol = match.group(1).upper()
                symbol = symbol.replace('/', '').replace('-', '')

                # Обработка для паттерна с цифрами (1000PEPE -> PEPE)
                if re.match(r'^\d+[A-Z]+$', symbol):
                    # Удаляем начальные цифры
                    symbol = re.sub(r'^\d+', '', symbol)

                if not symbol.endswith('USDT') and len(symbol) <= 10:
                    symbol += 'USDT'

                # Проверяем, не является ли запрещенным словом
                if normalize_symbol(symbol) in FORBIDDEN:
                    logger.debug(f"Символ {symbol} в списке запрещенных, пропускаем")
                    continue

                logger.info(f"Извлечен символ (основной паттерн): {symbol}")
                return symbol

        # 2. Fallback: строка вида "Avax Short" / "AVAX LONG" - ищем в первых 6 строках
        for i, line in enumerate(text_lines[:6]):
            line_up = line.upper()

            # Проверяем, есть ли в строке LONG/SHORT (как отдельное слово)
            words_in_line = re.split(r'\s+', line_up)
            for idx, word in enumerate(words_in_line):
                if word == "LONG" or word == "SHORT":
                    if idx > 0:
                        candidate = normalize_symbol(words_in_line[idx - 1])
                        # Удаляем начальные цифры если есть
                        candidate = re.sub(r'^\d+', '', candidate)

                        if (2 <= len(candidate) <= 15 and
                                candidate not in FORBIDDEN and
                                not any(forbidden in candidate for forbidden in FORBIDDEN)):
                            symbol = f"{candidate}USDT"
                            logger.info(f"Извлечен символ (fallback LONG/SHORT): {symbol} из строки: '{line}'")
                            return symbol

        # 3. Fallback: ищем любое слово из 2-10 символов в начале первых строк
        for line in text_lines[:3]:
            # Разбиваем на слова
            words = re.findall(r'\b[A-Za-z0-9]{2,15}\b', line)
            for word in words:
                candidate = normalize_symbol(word)
                # Удаляем начальные цифры
                candidate = re.sub(r'^\d+', '', candidate)

                if (2 <= len(candidate) <= 10 and
                        candidate not in FORBIDDEN and
                        not candidate.isdigit() and  # не чисто цифры
                        not any(forbidden in candidate for forbidden in FORBIDDEN)):

                    # Проверяем контекст - есть ли рядом торговые термины
                    line_up = line.upper()
                    has_trading_context = any(
                        term in line_up for term in [
                            'ENTRY', 'TP', 'SL', 'STOP', 'TAKE', 'PROFIT',
                            'ТОЧКА', 'ТЕЙК', 'СТОП', 'ЦЕЛЬ', 'ВХОД'
                        ]
                    )

                    if has_trading_context:
                        symbol = f"{candidate}USDT"
                        logger.info(f"Извлечен символ (fallback контекст): {symbol} из строки: '{line}'")
                        return symbol

        # 4. Fallback: хэштег без USDT типа "#AVAX"
        m = re.search(r'[#\$]([A-Z0-9]{2,15})\b', upper_text)
        if m:
            candidate = normalize_symbol(m.group(1))
            if candidate and candidate not in FORBIDDEN:
                if not candidate.endswith('USDT'):
                    candidate += 'USDT'
                logger.info(f"Извлечен символ (хэштег): {candidate}")
                return candidate

        # 5. Fallback: ищем слово перед "Short" или "Long" (регистронезависимо)
        pattern_fallback = re.compile(r'\b([A-Za-z0-9]{2,15})\s+(?:Short|Long)\b', re.IGNORECASE)
        match = pattern_fallback.search(text)
        if match:
            candidate = normalize_symbol(match.group(1))
            # Удаляем начальные цифры
            candidate = re.sub(r'^\d+', '', candidate)

            if candidate and candidate not in FORBIDDEN:
                symbol = f"{candidate}USDT"
                logger.info(f"Извлечен символ (regex fallback): {symbol}")
                return symbol

        # 6. Fallback: ищем первое слово в тексте, которое похоже на тикер
        for line in text_lines[:2]:
            # Ищем все слова, состоящие только из букв (2-10 символов)
            words = re.findall(r'\b[A-Z]{2,10}\b', line.upper())
            for word in words:
                if word not in FORBIDDEN and 2 <= len(word) <= 10:
                    # Проверяем, что это не просто английское слово
                    common_words = {'THE', 'AND', 'FOR', 'ARE', 'NOT', 'ALL', 'BUT', 'FROM', 'WITH'}
                    if word not in common_words:
                        # Проверяем, не является ли это аббревиатурой
                        if not word.isalpha():
                            continue
                        symbol = f"{word}USDT"
                        logger.info(f"Извлечен символ (первое слово): {symbol}")
                        return symbol

        logger.warning(f"Символ не распознан в тексте: {text[:200]}...")
        return "UNKNOWN"

    @staticmethod
    def extract_direction(text: str) -> str:
        """
        Извлекает направление торговли
        """
        text_upper = text.upper()

        # Сначала проверяем SHORT (чтобы приоритет был у SHORT если есть оба)
        if ('SHORT' in text_upper or '🔽' in text or '📉' in text or
                'ШОРТ' in text_upper or 'SHORT' in text):
            return "SHORT"
        elif ('LONG' in text_upper or '🔼' in text or '📈' in text or
              'ЛОНГ' in text_upper or 'Лонг' in text or 'лонг' in text):
            return "LONG"
        elif re.search(r'\bКУПИТЬ\b|\bBUY\b', text, re.IGNORECASE):
            return "LONG"
        elif re.search(r'\bПРОДАТЬ\b|\bSELL\b', text, re.IGNORECASE):
            return "SHORT"

        return "UNKNOWN"

    @staticmethod
    def extract_entry_prices(text: str) -> List[float]:
        """
        Извлекает цены входа (ОСНОВНЫЕ ЦЕНЫ ВХОДА)
        """
        entry_prices = []

        patterns = [
            r'твх[:\s-]+([\d.,-~]+)',  # Твх: 5.370-5.360 или ~0,1218$
            r'вход[:\s-]+([\d.,-~]+)',  # Вход: 100.50
            r'entry[:\s-]+([\d.,-~]+)',  # Entry: 100.50
            r'цена входа[:\s-]+([\d.,-~]+)',  # Цена входа: 100.50
            r'точка входа[:\s-]+([\d.,-~]+)',  # Точка входа: ~0,1218$
            r'вх[:\s-]+([\d.,-~]+)',  # Вх: 100.50
            r'лимитка[:\s-]+([\d.,-~]+)',  # лимитка - 290.60
            r'входим на[:\s-]+(\d+(?:[.,]\d+)?)(?![%])',  # Входим на 1 (но не 1%)
            r'~([\d.,]+)\$',  # ~0,1218$
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                price_str = match.group(1)
                if price_str:
                    try:
                        # Удаляем тильду и знаки валюты
                        clean_price = price_str.replace('~', '').replace('$', '').strip()

                        # Обработка диапазонов (100-101)
                        if '-' in clean_price and not clean_price.startswith('-'):
                            range_parts = clean_price.split('-')
                            for part in range_parts:
                                part_clean = part.replace(',', '.').strip()
                                if part_clean:
                                    price_val = float(part_clean)
                                    if price_val > 0.001:  # Фильтр для процентов
                                        entry_prices.append(price_val)
                        else:
                            # Заменяем запятую на точку перед конвертацией
                            clean_price = clean_price.replace(',', '.')
                            price_val = float(clean_price)
                            if price_val > 0.001:  # Фильтр для процентов
                                entry_prices.append(price_val)
                    except ValueError:
                        continue

        # Удаляем дубликаты но сохраняем порядок (для диапазонов важен порядок)
        seen = set()
        unique_prices = []
        for price in entry_prices:
            if price not in seen:
                seen.add(price)
                unique_prices.append(price)

        return unique_prices

    @staticmethod
    def extract_limit_prices(text: str) -> List[float]:
        """
        Извлекает лимитные цены входа (дополнительные входы)
        """
        limit_prices = []

        patterns = [
            r'лимит(?:ка|ный ордер)?[:\s-]+([\d.,-~]+)',
            r'limit[:\s-]+([\d.,-~]+)',
            r'лимитный ордер на[:\s-]+([\d.,-~]+)',
            r'при стоимости монеты в[:\s-]+([\d.,-~]+)',
            r'лимитка[:\s-]+([\d.,-~]+)',
            r'усреднение[:\s-]+([\d.,-~]+)',  # Усреднение : 464.3
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                price_str = match.group(1)
                if price_str:
                    try:
                        clean_price = price_str.replace(',', '.').replace('~', '').strip()
                        limit_prices.append(float(clean_price))
                    except ValueError:
                        continue

        limit_prices = sorted(list(set(limit_prices)))
        return limit_prices

    @staticmethod
    def extract_stop_loss(text: str) -> Optional[float]:
        """
        Извлекает стоп-лосс
        """
        patterns = [
            r'стоп[-\s]?лосс?[:\s-]+([\d.,~]+)',
            r'stop[-\s]?loss?[:\s-]+([\d.,~]+)',
            r'🚫[:\s-]+([\d.,~]+)',
            r'❌[:\s-]+([\d.,~]+)',
            r'стоп[:\s-]+([\d.,~]+)',
            r'Стоп:\s*([\d.,~]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    stop_str = match.group(1).replace(',', '.').replace('~', '')
                    return float(stop_str)
                except ValueError:
                    continue

        return None

    @staticmethod
    def extract_leverage(text: str) -> Optional[int]:
        """
        Извлекает значение плеча
        """
        patterns = [
            r'(\d+)\s*[XxХх]\b',  # 50X
            r'плечо[:\s-]*(\d+)',  # Плечо: 10
            r'leverage[:\s-]*(\d+)',  # Leverage: 10
            r'плечо\s*:\s*(\d+)-(\d+)x',  # Плечо: 10-50x
            r'плечо\s*:\s*(\d+)[\s-]*(\d+)\s*x',  # Плечо : 10-50x
            r'leverage\s*:\s*(\d+)[\s-]*(\d+)\s*x',  # Leverage : 10-50x
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    if match.lastindex == 2:
                        min_leverage = int(match.group(1))
                        max_leverage = int(match.group(2))
                        return (min_leverage + max_leverage) // 2
                    else:
                        return int(match.group(1))
                except (ValueError, IndexError):
                    continue

        return None

    @staticmethod
    def extract_margin(text: str) -> Optional[float]:
        """
        Извлекает значение маржи (% от депозита)
        """
        patterns = [
            r'(\d+)\s*%\s*от депозита',
            r'на\s*(\d+)\s*%',
            r'маржа[:\s-]*(\d+)\s*%',
            r'margin[:\s-]*(\d+)\s*%',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue

        return None

    @staticmethod
    def detect_source_specific_pattern(text: str, source: str) -> Dict[str, Any]:
        """
        Определяет специфические паттерны для разных источников
        """
        result = {}

        if "Nesterov" in source or "Family" in source:
            # Специфичный парсинг для Nesterov Family
            entry_match = re.search(r'Твх:\s*([\d.,-]+)', text)
            if entry_match:
                entry_str = entry_match.group(1)
                if '-' in entry_str:
                    # Сохраняем порядок как в тексте
                    prices = []
                    for p in entry_str.split('-'):
                        p_clean = p.strip().replace(',', '.')
                        if p_clean:
                            try:
                                prices.append(float(p_clean))
                            except ValueError:
                                pass
                    result['entry_prices'] = prices

            # УЛУЧШЕННЫЙ парсинг тейк-профитов для Nesterov Family
            # Ищем блок от "По целям:" до конца строки или до "Стоп:"
            take_profit_pattern = re.compile(r'По целям:\s*(.+?)(?=\s*Стоп:|\s*$)', re.DOTALL)
            take_profit_match = take_profit_pattern.search(text)

            if take_profit_match:
                tp_str = take_profit_match.group(1).strip()
                logger.info(f"Найден блок тейк-профитов для Nesterov: '{tp_str}'")

                # Извлекаем все числа (формат: 5.307, 5.255, 5.200, 5.143)
                take_profits = []

                # Сначала пробуем извлечь числа, разделенные запятыми
                numbers = re.findall(r'\d+\.\d+', tp_str.replace(',', '.'))

                for num_str in numbers:
                    try:
                        take_profits.append(float(num_str))
                    except ValueError:
                        pass

                # Если не нашли, пробуем другой паттерн
                if not take_profits:
                    # Ищем любые числа в блоке
                    for num_match in re.finditer(r'[\d]+\.?[\d]*', tp_str):
                        try:
                            num = float(num_match.group(0).replace(',', '.'))
                            take_profits.append(num)
                        except ValueError:
                            pass

                if take_profits:
                    result['take_profits'] = take_profits
                    logger.info(f"Найдены тейк-профиты для Nesterov: {take_profits}")

            stop_match = re.search(r'Стоп:\s*([\d.,]+)', text)
            if stop_match:
                try:
                    result['stop_loss'] = float(stop_match.group(1).replace(',', '.'))
                except ValueError:
                    pass

        elif "прайват клаб" in source.lower() or "прайват" in source.lower():
            # Для Прайват клаб - специальный парсинг для столбика
            lines = text.split('\n')

            # Ищем точку входа
            for line in lines:
                entry_match = re.search(r'Точка входа:\s*([\d.,]+)', line, re.IGNORECASE)
                if entry_match:
                    try:
                        result['entry_prices'] = [float(entry_match.group(1).replace(',', '.'))]
                        break
                    except ValueError:
                        pass

            # Ищем цели в столбике
            tps = []
            in_tps_section = False

            for line in lines:
                line_lower = line.lower()

                if 'цели' in line_lower:
                    in_tps_section = True
                    continue

                if in_tps_section:
                    # Проверяем, не начался ли новый раздел
                    if any(keyword in line_lower for keyword in ['закрытое', 'стоп', 'вход', 'плечо', 'маржа']):
                        break

                    # Ищем число в строке
                    match = re.search(r'([\d.,]+)', line)
                    if match:
                        try:
                            tps.append(float(match.group(1).replace(',', '.')))
                        except ValueError:
                            pass

            if tps:
                result['take_profits'] = tps

        elif "Финансист" in source or "Шеф" in source:
            # Для Шеф Финансист
            tp_match = re.search(r'✅Тейки:\s*([\d.,\s—]+)', text)
            if tp_match:
                tp_str = tp_match.group(1)
                take_profits = []
                for p in re.findall(r'[\d.,]+', tp_str):
                    p_clean = p.strip().replace(',', '.')
                    if p_clean:
                        try:
                            take_profits.append(float(p_clean))
                        except ValueError:
                            pass
                if take_profits:
                    result['take_profits'] = take_profits

        elif "CryptoFutures" in source:
            # Для CryptoFutures
            entry_match = re.search(r'Вход: Рынок и лимитка - ([\d.,]+)', text)
            if entry_match:
                try:
                    result['entry_prices'] = [float(entry_match.group(1).replace(',', '.'))]
                    result['limit_prices'] = [float(entry_match.group(1).replace(',', '.'))]
                except ValueError:
                    pass

        elif "MAGIC/USDT" in source or "MAGIC" in source:
            # Для MAGIC/USDT - специальная обработка
            entry_match = re.search(r'Точка входа: ~([\d.,]+)\$', text)
            if entry_match:
                try:
                    result['entry_prices'] = [float(entry_match.group(1).replace(',', '.'))]
                except ValueError:
                    pass

            limit_match = re.search(r'лимитный ордер.*?([\d.,]+)\$', text)
            if limit_match:
                try:
                    result['limit_prices'] = [float(limit_match.group(1).replace(',', '.'))]
                except ValueError:
                    pass

        return result

    @staticmethod
    def parse_signal(text: str, source: str = "Unknown") -> TradeSignal:
        """
        Парсит торговый сигнал из текста сообщения
        """
        # Логируем входящий текст для отладки
        logger.info(f"Парсим сигнал из источника '{source}': {text[:200]}...")

        signal = TradeSignal()
        signal.source = source
        signal.timestamp = time.time()
        signal.original_text = text

        # Определяем символ с улучшенным детектором
        signal.symbol = AdvancedParser.extract_symbol(text)

        # Логируем результат извлечения символа
        logger.info(f"Результат извлечения символа: {signal.symbol}")

        # Если символ UNKNOWN, пробуем дополнительные методы
        if signal.symbol == "UNKNOWN":
            # Для private club ищем слово перед SHORT/LONG в первых строках
            if "прайват клаб" in source.lower() or "private club" in source.lower():
                lines = text.split('\n')
                for line in lines[:3]:
                    line_upper = line.upper()
                    if "SHORT" in line_upper or "LONG" in line_upper:
                        # Разбиваем на слова
                        words = re.findall(r'\b[A-Za-z0-9]+\b', line_upper)
                        for i, word in enumerate(words):
                            if word == "SHORT" or word == "LONG":
                                if i > 0:
                                    candidate = words[i - 1]
                                    # Проверяем, что это не число (1000PEPE обрабатывается отдельно)
                                    if not candidate.isdigit() and len(candidate) >= 2:
                                        # Очищаем от цифр в начале (1000PEPE -> PEPE)
                                        clean_candidate = re.sub(r'^\d+', '', candidate)
                                        if 2 <= len(clean_candidate) <= 10:
                                            signal.symbol = f"{clean_candidate}USDT"
                                            logger.info(f"Извлечен символ из контекста Private Club: {signal.symbol}")
                                            break
                        if signal.symbol != "UNKNOWN":
                            break

        # Определяем направление
        signal.direction = AdvancedParser.extract_direction(text)

        # Определяем цены входа (главный вход)
        signal.entry_prices = AdvancedParser.extract_entry_prices(text)

        # Определяем лимитные цены (дополнительные входы)
        signal.limit_prices = AdvancedParser.extract_limit_prices(text)

        # Определяем тейк-профиты
        signal.take_profits = AdvancedParser.parse_take_profits(text)

        # Определяем стоп-лосс
        signal.stop_loss = AdvancedParser.extract_stop_loss(text)

        # Определяем плечо
        signal.leverage = AdvancedParser.extract_leverage(text)

        # Определяем маржу
        signal.margin = AdvancedParser.extract_margin(text)

        # Определяем рыночный вход
        market_keywords = ['по рынку', 'market', 'маркет', 'рынок', 'market(']
        if any(keyword in text.lower() for keyword in market_keywords):
            signal.is_market = True

        # Определяем тейк-профиты (повторно для логирования)
        logger.info(f"После parse_take_profits: {signal.take_profits}")

        # Проверяем специфичные паттерны для источника
        source_specific_data = AdvancedParser.detect_source_specific_pattern(text, source)
        logger.info(f"source_specific_data для {source}: {source_specific_data}")

        for key, value in source_specific_data.items():
            if hasattr(signal, key):
                # Для entry_prices добавляем, если нет
                if key == 'entry_prices' and value and not signal.entry_prices:
                    signal.entry_prices = value
                # Для take_profits заменяем полностью
                elif key == 'take_profits' and value:
                    logger.info(f"ПЕРЕЗАПИСЫВАЕМ take_profits: {value}")
                    signal.take_profits = value
                elif key == 'stop_loss' and value:
                    signal.stop_loss = value
                elif key == 'limit_prices' and value:
                    signal.limit_prices = value

        logger.info(f"После source_specific_data: {signal.take_profits}")

        # 🔥 ВАЖНОЕ ИЗМЕНЕНИЕ: ФИЛЬТРАЦИЯ ТЕЙК-ПРОФИТОВ ПО ЦЕНЕ ВХОДА
        # Но только если тейк-профитов больше 0
        if signal.entry_prices and signal.take_profits and len(signal.take_profits) > 0:
            entry_price = signal.entry_prices[0]
            original_count = len(signal.take_profits)

            # Для SHORT: оставляем все тейки НИЖЕ входа (не только самый дальний!)
            if signal.direction == "SHORT":
                # Фильтруем, но сохраняем ВСЕ тейки ниже входа
                filtered_tps = [tp for tp in signal.take_profits if tp < entry_price]
                # Сортируем по убыванию (ближайший тейк первый)
                filtered_tps.sort(reverse=True)
                signal.take_profits = filtered_tps
            elif signal.direction == "LONG":
                # Для LONG: оставляем все тейки ВЫШЕ входа
                filtered_tps = [tp for tp in signal.take_profits if tp > entry_price]
                # Сортируем по возрастанию (ближайший тейк первый)
                filtered_tps.sort()
                signal.take_profits = filtered_tps

            if len(signal.take_profits) != original_count:
                logger.info(f"Отфильтрованы тейк-профиты: было {original_count}, стало {len(signal.take_profits)}")

        # Для CryptoFutures: если есть limit_prices и нет entry_prices, копируем
        if "CryptoFutures" in source and signal.limit_prices and not signal.entry_prices:
            signal.entry_prices = signal.limit_prices.copy()

        # Для Two Fingers: улучшаем извлечение плеча
        if "Two Fingers" in source and signal.leverage == 50:
            # Ищем диапазон "10-50x" более точно
            range_match = re.search(r'(\d+)[\s-]*(\d+)\s*x', text, re.IGNORECASE)
            if range_match:
                try:
                    min_l = int(range_match.group(1))
                    max_l = int(range_match.group(2))
                    signal.leverage = (min_l + max_l) // 2
                except (ValueError, IndexError):
                    pass

        # 🔥 ДОПОЛНИТЕЛЬНАЯ ФИЛЬТРАЦИЯ: убираем тейк-профиты, которые слишком близко к входу
        if signal.entry_prices and signal.take_profits:
            entry_price = signal.entry_prices[0]
            filtered_tps = []

            for tp in signal.take_profits:
                # Рассчитываем разницу в процентах
                diff_percent = abs(tp - entry_price) / entry_price * 100

                # Для SHORT: тейк должен быть МЕНЬШЕ входа минимум на 0.5%
                if signal.direction == "SHORT" and tp < entry_price and diff_percent >= 0.5:
                    filtered_tps.append(tp)
                # Для LONG: тейк должен быть БОЛЬШЕ входа минимум на 0.5%
                elif signal.direction == "LONG" and tp > entry_price and diff_percent >= 0.5:
                    filtered_tps.append(tp)

            if filtered_tps:
                # Сохраняем сортировку
                if signal.direction == "SHORT":
                    filtered_tps.sort(reverse=True)
                else:
                    filtered_tps.sort()

                if len(filtered_tps) != len(signal.take_profits):
                    logger.info(
                        f"Убраны тейк-профиты слишком близкие к входу: было {len(signal.take_profits)}, стало {len(filtered_tps)}")
                    signal.take_profits = filtered_tps

        # Логируем финальный результат
        logger.info(f"✅ ФИНАЛЬНЫЙ СИГНАЛ:")
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
        logger.info(f"   Время: {datetime.fromtimestamp(signal.timestamp).strftime('%H:%M:%S')}")
        logger.info("-" * 60)

        return signal

    @staticmethod
    def validate_signal(signal: TradeSignal) -> bool:
        """
        Проверяет валидность сигнала
        """
        if signal.symbol == "UNKNOWN":
            return False

        if signal.direction == "UNKNOWN":
            return False

        if not signal.entry_prices and not signal.limit_prices and not signal.is_market:
            return False

        if not signal.take_profits:
            return False

        return True


# Глобальный экземпляр парсера
advanced_parser = AdvancedParser()


# Функции для обратной совместимости
def parse_signal(text: str, source: str = "Unknown") -> TradeSignal:
    return advanced_parser.parse_signal(text, source)


def parse_khrustalev(text: str, source: str) -> TradeSignal:
    return advanced_parser.parse_signal(text, source)  # Используем общий парсер


# Экспорт класса TradeSignal
TradeSignal = TradeSignal
