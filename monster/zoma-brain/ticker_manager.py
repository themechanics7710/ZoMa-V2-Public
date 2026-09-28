"""
ZoMa Brain — stock ticker resolver
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Resolves company names/tickers for smart_tools' live finance tool, and
learns new ones into a small local JSON map so repeated lookups skip the
search step.
"""

import json
import os
import re
import requests

import config

MAP_FILE = config.TICKER_MAP_FILE


def load_tickers():
    if os.path.exists(MAP_FILE):
        try:
            with open(MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_ticker(company_name, ticker_symbol):
    """Saves a new ticker to the JSON file permanently."""
    if not company_name or not ticker_symbol:
        return

    os.makedirs(os.path.dirname(MAP_FILE) or ".", exist_ok=True)
    tickers = load_tickers()
    clean_key = re.sub(r"[^a-z0-9\s]", "", company_name.lower()).strip()

    if clean_key and len(clean_key) > 2 and clean_key not in tickers:
        tickers[clean_key] = ticker_symbol.upper().strip()
        with open(MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(tickers, f, indent=4)
        print(f" [TICKER-MANAGER] Learned and saved: '{clean_key}' -> {ticker_symbol.upper()}")


def resolve_ticker(query):
    """Returns a tuple: (ticker_symbol, new_company_name_to_save)"""
    tickers = load_tickers()
    query_lower = query.lower()
    words = re.findall(r"\b\w+\b", query_lower)

    # 1. Reverse lookup: did the user type a known ticker symbol?
    known_symbols = {v.lower(): v for v in tickers.values()}
    for word in words:
        if word in known_symbols:
            return known_symbols[word], None

    # 2. Key lookup: did the user type a known company name?
    for name, tick in tickers.items():
        if len(name) > 2 and name in query_lower:
            return tick, None

    # 3. Regex fallback: explicit ALL CAPS word (2-5 letters).
    match = re.search(r"\b([A-Z]{2,5})\b", query)
    if match:
        return match.group(1), None

    # 4. Dynamic discovery via Yahoo Finance search.
    stop_words = r"\b(check|what|is|the|stock|price|of|give|me|for|market|shares|value|nasdaq|nyse|show|tell|how|created|in|a|company|mean)\b"
    clean_query = re.sub(stop_words, "", query_lower).strip()

    if clean_query and len(clean_query) > 2:
        try:
            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(clean_query)}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=3)
            data = res.json()
            quotes = data.get("quotes", [])
            for q in quotes:
                if q.get("quoteType") == "EQUITY":
                    return q.get("symbol"), clean_query
        except Exception as e:
            print(f" [TICKER-MANAGER] Dynamic search failed: {e}")

    return None, None
