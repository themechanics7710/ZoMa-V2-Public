"""
ZoMa Brain — heuristic router and live external data tools
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Fast keyword-based routing (no LLM round-trip) that decides whether a
turn needs a live-data tool call (finance/weather/news/vision), plus the
deterministic command detectors (uplink, volume, photo) checked ahead of
normal dispatch.
"""

import re
import requests
import yfinance as yf
from ddgs import DDGS

import ticker_manager


# --- 1. Heuristic router -----------------------------------------------------

def route_query_heuristic(user_text: str):
    """Lightning-fast keyword router. Returns (route, query)."""
    text = user_text.lower().strip()

    # --- MANUAL ROUTE OVERRIDES ---
    if text.startswith("v:") or text.startswith("vision:"):
        return "vision", user_text[2:].strip()
    if text.startswith("c:") or text.startswith("chat:"):
        return "chat", user_text[2:].strip()
    if text.startswith("w:") or text.startswith("weather:"):
        return "weather", user_text[2:].strip()
    if text.startswith("f:") or text.startswith("finance:"):
        return "finance", user_text[2:].strip()
    if text.startswith("n:") or text.startswith("news:"):
        return "news", user_text[2:].strip()
    # -----------------------------

    if any(kw in text for kw in ["stock", "price", "market", "shares", "ticker", "nasdaq"]):
        return "finance", user_text
    if any(kw in text for kw in ["weather", "forecast", "temperature"]):
        return "weather", user_text
    if any(kw in text for kw in ["news", "latest headlines"]):
        return "news", user_text
    if is_vision_request(text):
        return "vision", user_text

    # Bare conversational filler: routing these through the LLM classifier
    # always resolves to CHAT anyway, at the cost of a full round trip, so
    # they're matched directly here instead. Exact match only (not
    # substring), so "tell me about Napoleon" still falls through to
    # "auto" for proper routing -- only the bare phrase with nothing else
    # attached is safe to assume is pure continuation.
    stripped = text.strip(" ?!.,")
    if stripped in {
        "tell me", "continue", "continuo", "go on", "keep going", "more",
        "elaborate", "what are you thinking", "say more", "and then",
        "what else", "anything else", "carry on", "go ahead",
    }:
        return "chat", user_text

    # Defaults to "chat", not "auto": "auto" exists so
    # classify_context_with_llm can route to WEB/WIKI, but neither has an
    # actual external-lookup tool implemented here, so the only real
    # effect of WEB/WIKI today would be skipping the FAISS memory search
    # -- not worth the extra router round trip. classify_context_with_llm
    # and the "auto" handling stay in place and are trivial to re-enable
    # (change this one line) once real web/wiki tools exist.
    return "chat", user_text


# --- 1b. Vision-phrase detection, shared by the router and uplink sessions ----
#
# Pulled out of route_query_heuristic so process_uplink_query() (which
# skips route_query_heuristic entirely -- uplink sessions bypass tool
# routing) can still recognise a snapshot/vision request the same way.

_VISION_KEYWORDS = [
    "what do you see", "do you see", "look at", "look,", "look around",
    "camera", "are you looking", "can you see", "what's out there",
    "snapshot",
]
# "take a picture"/"take a photo" route through detect_photo_command()
# instead (flash + shutter click + save a real JPEG) -- kept out of this
# list so the two features can't both claim the same phrase.
# The robot's own name is deliberately not in this list: any sentence
# merely addressing the robot by name would otherwise route to VISION
# regardless of actual content, since people say the robot's name in
# nearly every sentence directed at it.


def is_vision_request(user_text: str) -> bool:
    text = user_text.lower().strip()
    if text.startswith("v:") or text.startswith("vision:"):
        return True
    return any(kw in text for kw in _VISION_KEYWORDS)


# --- 1d. Web search request, uplink-only (explicit command required) ----------
#
# Claude's server-side web search adds real latency and input-token cost
# (search-result content becomes part of the request context), so it's
# not attached to every uplink turn by default. Only
# process_uplink_query() consults this; Qwen's routing is untouched.

_WEB_SEARCH_KEYWORDS = [
    "search the web", "search online", "search the internet",
    "look it up online", "look that up online", "look online",
    "check online", "check the internet", "browse the web", "google it",
]


def is_web_search_request(user_text: str) -> bool:
    text = user_text.lower().strip()
    if text.startswith("web:") or text.startswith("search:"):
        return True
    return any(kw in text for kw in _WEB_SEARCH_KEYWORDS)


# --- 1c. Uplink session control (explicit start/end phrases) ------------------
#
# Whisper reliably transcribes "uplink" as two words ("start up link") or
# merges it into the preceding verb ("startup link"), so _UPLINK_PATTERN
# matches "up" or "startup" at a word boundary, an optional space/hyphen,
# then "link" -- covering "uplink", "up link", "up-link", and "startup
# link" alike. Verbs are matched by substring, so "startup" still counts
# as containing "start". The pattern is required (not just a bare verb)
# so a plain "stop" (the global barge-in/silence command) is never
# mistaken for ending a session.
#
# Word-boundaried on purpose (not a bare "up[\s-]*link" substring search):
# an unrelated sentence like "the pickup link is broken, please close it"
# would otherwise match ("pickup" ends in "up", "close" is an end verb)
# and silently end a live session. \b before "up"/"startup" excludes
# "pickup", "backup", "warmup", etc. while still matching every real
# transcript variant.

_UPLINK_PATTERN = re.compile(r"\b(?:start)?up[\s-]*link\b")

UPLINK_START_VERBS = {"start", "go", "begin", "initiate", "open"}
UPLINK_END_VERBS = {"end", "stop", "terminate", "close", "finish"}


def detect_uplink_command(user_text: str) -> str | None:
    """Returns "start", "end", or None."""
    text = user_text.lower().strip(" ,.:;-!?")
    if not _UPLINK_PATTERN.search(text):
        return None
    if any(verb in text for verb in UPLINK_END_VERBS):
        return "end"
    if any(verb in text for verb in UPLINK_START_VERBS):
        return "start"
    return None


# --- 1b. Volume command -------------------------------------------------------
#
# Deterministic keyword matching, same as the router above -- NOT an LLM
# classifier. This flips a physical setting; a wrong guess here is a
# worse failure than a wrong guess on a chat topic, so it stays a cheap,
# fast, 100%-reproducible check.
#
# Word-based, not fixed-phrase-based: a fixed phrase like "increase the
# volume" is brittle against real speech, where an inserted word (e.g.
# "increase MORE the volume") breaks a substring match. Requiring the
# standalone topic word (volume) plus any direction word anywhere in the
# sentence catches word-order/insertion variance a fixed-phrase list
# would miss. Both English and Italian verb sets are included, since this
# system's STT is bilingual; "volume" is spelled identically in both
# languages, so only the verb sets need Italian entries.
_VOLUME_TOPIC = re.compile(r"\bvolume\b")

VOLUME_UP_WORDS = {
    "increase", "raise", "up", "louder", "more", "higher", "boost",  # EN
    "aumenta", "aumentare", "aumentato", "alza", "alzare",           # IT
}
VOLUME_DOWN_WORDS = {
    "decrease", "lower", "down", "quieter", "softer", "less", "reduce",  # EN
    "abbassa", "abbassare", "abbassato", "diminuisci", "diminuire", "diminuito", "meno",  # IT
}

# These work even without the word "volume" present at all -- unambiguous
# enough on their own ("turn it up" / "turn it down").
VOLUME_UP_STANDALONE = ("turn it up", "louder")
VOLUME_DOWN_STANDALONE = ("turn it down", "quieter", "softer")


def detect_photo_command(user_text: str) -> bool:
    """
    "take a picture" triggers a physical action (LED flash, shutter
    click, a real JPEG saved to disk), so it stays a deterministic
    keyword check, checked before dispatch_query -- same reasoning as
    detect_uplink_command/detect_volume_command above.

    Topic + verb word sets, not a fixed phrase, for the same
    insertion-robustness reason as detect_volume_command's design.
    """
    text = user_text.lower().strip(" ,.:;-!?")
    words = set(re.findall(r"[a-zà-ÿ']+", text))
    topic = {"picture", "photo", "photograph", "snapshot", "foto", "fotografia"}
    verbs = {"take", "snap", "capture", "grab", "shoot", "scatta", "scattare"}
    return bool(words & topic and words & verbs)


def detect_volume_command(user_text: str) -> str | None:
    """Returns "up", "down", or None. Checked BEFORE dispatch_query, same
    short-circuit shape as detect_uplink_command -- no LLM round-trip for
    something with a fixed, canned confirmation."""
    text = user_text.lower().strip(" ,.:;-!?")
    words = set(re.findall(r"[a-zà-ÿ']+", text))

    if _VOLUME_TOPIC.search(text):
        if words & VOLUME_DOWN_WORDS:
            return "down"
        if words & VOLUME_UP_WORDS:
            return "up"

    if any(p in text for p in VOLUME_DOWN_STANDALONE):
        return "down"
    if any(p in text for p in VOLUME_UP_STANDALONE):
        return "up"
    return None


# --- 2. Live finance tool -----------------------------------------------------

def get_live_stock(query: str) -> str:
    """Pulls live stock data and actively learns new tickers."""
    ticker, new_company_name = ticker_manager.resolve_ticker(query)

    if not ticker:
        return "[SYSTEM ERROR] No ticker identified. Please specify the company name or symbol."

    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")

        if data.empty:
            return f"[SYSTEM ERROR] Ticker {ticker} returned no data. It might be invalid."

        if new_company_name:
            ticker_manager.save_ticker(new_company_name, ticker)

        current_price = data["Close"].iloc[-1]
        return f"[SYSTEM: LIVE FINANCE DATA] The real-time price for {ticker} is ${current_price:.2f}."

    except Exception as e:
        return f"[SYSTEM ERROR] Finance fetch failed: {e}"


# --- 3. Live weather tool (Open-Meteo) -----------------------------------------

def get_live_weather(query: str) -> str:
    """Fetches live weather + forecast for a dynamic location, defaulting to Dubai."""
    text = query.lower().replace("what's", "what is").replace("how's", "how is")

    stop_words = r"\b(weather|forecast|temperature|raining|sunny|hot|cold|in|for|what|is|the|like|tomorrow|today|check|tell|me|how)\b"
    location_hint = re.sub(stop_words, "", text)
    location_hint = re.sub(r"[^\w\s]", "", location_hint).strip()

    lat, lon, city = 25.2048, 55.2708, "Dubai"  # default

    if len(location_hint) > 1 and location_hint != "dubai":
        try:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(location_hint)}&count=1"
            geo_res = requests.get(geo_url, timeout=5).json()

            if "results" in geo_res and len(geo_res["results"]) > 0:
                result = geo_res["results"][0]
                lat, lon, city = result["latitude"], result["longitude"], result["name"]
            else:
                return f"[SYSTEM ERROR] Could not find coordinates for location: {location_hint.title()}"
        except Exception as e:
            return f"[SYSTEM ERROR] Geocoding failed for {location_hint.title()}: {e}"

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current_weather=true&daily=temperature_2m_max,temperature_2m_min&timezone=auto"
        )
        data = requests.get(url, timeout=5).json()

        current = data.get("current_weather", {})
        temp = current.get("temperature", "Unknown")
        wind = current.get("windspeed", "Unknown")

        daily = data.get("daily", {})
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])

        if len(max_temps) >= 2:
            return (
                f"[SYSTEM: LIVE WEATHER DATA FOR {city.upper()}]\n"
                f"- Current: {temp}°C, Wind: {wind} km/h.\n"
                f"- Today's Forecast: High {max_temps[0]}°C, Low {min_temps[0]}°C.\n"
                f"- Tomorrow's Forecast: High {max_temps[1]}°C, Low {min_temps[1]}°C."
            )
        return f"[SYSTEM: LIVE WEATHER] Current conditions in {city}: {temp}°C."

    except Exception as e:
        return f"[SYSTEM ERROR] Weather fetch failed: {e}"


# --- 4. Live news tool (DDGS) --------------------------------------------------

def get_live_news(query: str) -> str:
    """Fetches the latest headlines, filtered by recency."""
    text = query.lower()
    stop_words = r"\b(news|latest|headlines|tell|me|about|do|you|have|any|from|what|are|the|check)\b"
    search_term = re.sub(stop_words, "", text)
    search_term = re.sub(r"[^\w\s]", "", search_term).strip()

    if len(search_term) < 2:
        search_term = "world news"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(search_term, timelimit="d", max_results=3))
            if not results:
                results = list(ddgs.news(search_term, timelimit="w", max_results=3))

            if not results:
                return f"[SYSTEM ERROR] No recent news headlines found for '{search_term}'."

            news_block = f"[SYSTEM: LIVE NEWS HEADLINES FOR '{search_term.upper()}']\n"
            for r in results:
                news_block += (
                    f"- {r['title']} (Source: {r.get('source', 'Unknown')}, "
                    f"Published: {r.get('date', 'Unknown')})\n  URL: {r.get('url', 'Unknown')}\n"
                )
            return news_block
    except Exception as e:
        return f"[SYSTEM ERROR] News fetch failed: {e}"


# --- 5. Vision tool stub (Tier 2 hook, not yet implemented) --------------------

def get_vision_context(vision_stream) -> str:
    """
    Placeholder for a future Tier 2 (Qwen-VL) call. For now it just
    reports whether a live frame is available, so the LLM can answer
    honestly ("I have a live feed but haven't been asked to analyze it
    yet") instead of hallucinating what it sees.
    """
    if vision_stream is None:
        return "[SYSTEM: VISION] No camera stream is currently configured."
    if not vision_stream.is_alive():
        return "[SYSTEM: VISION] Camera stream is configured but currently offline/unreachable."
    return "[SYSTEM: VISION] Live frame available from ZoMa's camera, but visual analysis (Qwen-VL) is not yet wired in."
