"""
ZoMa Brain — local LLM client (Qwen via Ollama)
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

The single place that talks to the local Qwen model over Ollama: one
router, one streaming chat call, used for every non-uplink text/voice
reply.
"""

import datetime
import re
import json
import aiohttp

import config

# --- Heuristic complexity classifier (used only to decide "thinking" mode) ----

def classify_request_complexity(user_text: str) -> str:
    text = user_text.lower()
    word_count = len(user_text.split())

    has_code_markers = any(
        tok in text for tok in [
            "def ", "class ", "import ", "function ", "public ", "private ",
            "for(", "while(", "if(", "```", ";", "{", "}", "=>",
        ]
    )
    has_reasoning_markers = any(
        phrase in text for phrase in [
            "step by step", "reason about", "explain why", "walk me through",
            "analyze", "analysis", "prove that", "debug", "optimize",
            "design", "architecture", "trade-off", "tradeoff",
        ]
    )
    many_sentences = (text.count(".") + text.count("?") + text.count("!")) >= 3

    if has_code_markers or has_reasoning_markers or many_sentences or word_count > 40:
        return "complex"
    return "simple"


# --- Streaming chat call --------------------------------------------------------

async def ask_qwen_stream(
    user_text: str,
    system_context: str,
    client_type: str = "text",
    metrics: dict | None = None,
):
    """
    Async generator: yields text chunks as they arrive from the model.

    metrics, if given, is populated in place once Ollama's final "done"
    line arrives, with these keys (all durations in seconds):
        load_duration_s        -- time spent loading the model into VRAM.
                                   ~0 if the model was already resident;
                                   several seconds on a cold/evicted load.
        prompt_eval_duration_s -- time spent processing the input prompt.
        prompt_eval_count      -- input token count.
        eval_duration_s        -- time spent generating the reply itself.
        eval_count              -- output token count.
        total_duration_s       -- Ollama's own end-to-end figure.

    Left empty ({}) if the stream is cancelled/pre-empted before the
    "done" line arrives, or if the caller passes metrics=None (default).
    """
    with open(config.PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    current_time = datetime.datetime.now().strftime("%A, %B %d, %Y")
    final_system_prompt = f"{prompt_template}\n\n[SYSTEM CLOCK: {current_time}]\n\n"

    if client_type == "text":
        final_system_prompt += (
            "[NUMBERS OVERRIDE - TEXT CLIENT]\n"
            "- Represent numeric quantities using digits.\n\n"
        )
    elif client_type == "voice":
        final_system_prompt += (
            "[BREVITY OVERRIDE - VOICE CLIENT]\n"
            "- This reply is being SPOKEN aloud, not read on a screen. Keep it "
            "to 1-3 short sentences by default. Only go longer if the person "
            "explicitly asks for more detail, a full explanation, or to "
            "elaborate -- a direct question deserves a direct answer, not a "
            "monologue.\n\n"
        )

    enriched_user_text = ""
    if system_context:
        enriched_user_text += f"{system_context}\n\n"
    enriched_user_text += f"{config.PRIMARY_USER_NAME}: {user_text}"

    stop_tokens = [
        f"\n{config.PRIMARY_USER_NAME}:", f"\n[{config.PRIMARY_USER_NAME}]",
        "UNKNOWN:", "\n[UNKNOWN]", "<|im_end|>", "<|endoftext|>",
    ]

    payload = {
        "model": config.QWEN_TEXT_MODEL,
        "think": False,
        "messages": [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": enriched_user_text},
        ],
        "stream": True,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.7,
            "num_predict": 2048,
            "stop": stop_tokens,
            "num_ctx": config.QWEN_NUM_CTX,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(config.OLLAMA_API_URL, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                if not line:
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done") and metrics is not None:
                    metrics["load_duration_s"] = data.get("load_duration", 0) / 1e9
                    metrics["prompt_eval_duration_s"] = data.get("prompt_eval_duration", 0) / 1e9
                    metrics["prompt_eval_count"] = data.get("prompt_eval_count", 0)
                    metrics["eval_duration_s"] = data.get("eval_duration", 0) / 1e9
                    metrics["eval_count"] = data.get("eval_count", 0)
                    metrics["total_duration_s"] = data.get("total_duration", 0) / 1e9


# --- Dynamic LLM router (used only when the fast heuristic route returns "auto") --

async def classify_context_with_llm(user_text: str, recent_context: str) -> tuple[str, str]:
    """
    Falls back to an LLM call to decide the route when smart_tools'
    heuristic router can't confidently classify the message (route == "auto").
    Returns (route, optimized_query).
    """
    system_prompt = (
        "You are an intelligent classification AI. Read the user's message and determine "
        "the required data source.\n"
        "Output exactly ONE line in this strict format: ROUTE=WORD | QUERY=SEARCH_STRING\n\n"
        "Routing Rules:\n"
        "- WEB: check a website, read news, search the internet, live info (weather, stock, recipes).\n"
        "- WIKI: encyclopedic knowledge, historical facts, biographies.\n"
        "- LOCAL: personal uploaded documents, system configuration, past conversations.\n"
        "- VISION: anything about what the camera/ZoMa currently sees.\n"
        "- CHAT: greetings, casual conversation. NEVER select CHAT if the user asks to look up "
        "information, read a website, or search.\n\n"
        "Query Extraction Rules:\n"
        "1. If ROUTE is WEB or WIKI, extract the core search subject. Strip conversational filler. "
        "No quotation marks.\n"
        "2. Otherwise QUERY must strictly be the word NONE."
    )

    payload = {
        "model": config.QWEN_TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Recent Context:\n{recent_context}\n\nUser Message: {user_text}"},
        ],
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.0, "num_predict": 60},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(config.OLLAMA_API_URL, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                clean_resp = data.get("message", {}).get("content", "").replace("\n", " ").strip()
    except Exception as e:
        print(f" [ROUTER ERROR]: {e}")
        clean_resp = ""

    if not clean_resp:
        clean_resp = "ROUTE=CHAT | QUERY=NONE"

    print(f" [DEBUG-ROUTER] Raw LLM output: {clean_resp}")

    upper_resp = clean_resp.upper()
    route_map = {
        "ROUTE=WEB": "web", "ROUTE=WIKI": "wiki", "ROUTE=LOCAL": "local",
        "ROUTE=VISION": "vision", "ROUTE=CHAT": "chat",
    }
    route = next((v for k, v in route_map.items() if k in upper_resp), "chat")

    optimized_query = user_text
    match = re.search(r"QUERY\s*[:=]\s*(.*?)(?:$|\|)", clean_resp, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip().replace('"', "").replace("'", "")
        if extracted.upper() not in ["NONE", "[NONE]", ""]:
            optimized_query = extracted

    return route, optimized_query
