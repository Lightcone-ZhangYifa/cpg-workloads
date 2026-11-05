#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(babel, work):
    """Check locale number/currency/date rules and malformed locale data."""
    from datetime import date
    from decimal import Decimal
    numbers = installed_module('babel.numbers'); dates = installed_module('babel.dates')
    require(numbers.format_decimal(12345.67,locale='en_US') == '12,345.67', 'English decimal formatting failed')
    require(numbers.format_decimal(12345.67,locale='de_DE') == '12.345,67', 'German decimal formatting failed')
    require(numbers.parse_decimal('12.345,67',locale='de_DE') == Decimal('12345.67'), 'Locale decimal parse failed')
    require(numbers.format_currency(12.5,'USD',locale='en_US') == '$12.50', 'Currency formatting failed')
    require(dates.format_date(date(2024,2,29),format='yyyy-MM-dd',locale='en_US') == '2024-02-29', 'Explicit date pattern failed')
    locale = babel.Locale.parse('ru')
    require([locale.plural_form(n) for n in [1,2,5]] == ['one','few','many'], 'Plural categories wrong')
    raises(numbers.NumberFormatError, lambda: numbers.parse_decimal('not a number',locale='de_DE'), 'Invalid localized number accepted')
    raises(babel.UnknownLocaleError, lambda: babel.Locale.parse('zz_ZZ'), 'Unknown locale accepted')
    return {'checks':['english-and-german-numbers','localized-decimal-parse','currency','explicit-date-pattern','plural-categories','invalid-number','unknown-locale'], 'scope':'selected bundled locale rules; not every CLDR locale or timezone'}

if __name__ == "__main__":
    raise SystemExit(main('babel', 'babel', functional))
