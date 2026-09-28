"""
ZoMa Brain — Claude API client for uplink sessions
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

The single place that talks to the Claude API, used only while an uplink
session ("start uplink" / "end uplink") is active.
"""

import time
import anthropic

import config
import vision_engine


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    """
    Lazy singleton, so a missing ANTHROPIC_API_KEY doesn't break module
    import. Credentials are resolved by the `anthropic` SDK itself from
    the environment (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN).
    """
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


async def ask_claude_stream(
    user_text: str,
    system_context: str,
    client_type: str = "voice",
    metrics: dict | None = None,
    frame=None,
    web_search: bool = False,
    speaker_name: str | None = None,
):
    """
    Async generator: yields text chunks as they arrive from Claude.

    frame, if given (a BGR numpy array from VisionStream.get_latest_frame()),
    is JPEG-encoded and attached as an image content block on the same
    call, so Claude answers with the image already in hand -- no separate
    describe-then-personality pass.

    web_search: attaches Anthropic's server-side web_search tool to this
    call only when the caller explicitly asked for it (see
    smart_tools.is_web_search_request()) and config.CLAUDE_WEB_SEARCH_
    ENABLED is on. Not attached by default: search results become part of
    the request context and can noticeably add to latency and cost, so
    it's opt-in per turn rather than automatic.

    speaker_name: the speaker of this specific turn (per speaker ID), used
    to build an explicit "[SPEAKER: name] message" prefix rather than a
    bare "Name: message" one. A bare label can otherwise be read by the
    model as part of the request itself rather than as an attribution,
    particularly when the configured name could plausibly be a search
    subject. Falls back to config.PRIMARY_USER_NAME when no real
    speaker_name is available.

    metrics, if given, is populated in place (best-effort) with
    total_duration_s, input_tokens, output_tokens.
    """
    system_prompt = ""
    if client_type == "voice":
        system_prompt = (
            "This reply is being SPOKEN aloud, not read on a screen. Keep it "
            "to 1-3 short sentences by default. Only go longer if the person "
            "explicitly asks for more detail, a full explanation, or to "
            "elaborate."
        )

    user_content = ""
    if system_context:
        user_content += f"{system_context}\n\n"
    user_content += f"[SPEAKER: {speaker_name or config.PRIMARY_USER_NAME}] {user_text}"

    content_blocks = []
    if frame is not None:
        try:
            image_b64 = vision_engine.encode_frame_b64(frame)
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
            })
        except Exception as e:
            print(f" [UPLINK] Frame encode failed, continuing text-only: {e}")
    content_blocks.append({"type": "text", "text": user_content})

    # Server-side web search: Anthropic runs the search and hands Claude
    # real results inside this same call.
    tools = None
    if web_search and config.CLAUDE_WEB_SEARCH_ENABLED:
        tools = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": config.CLAUDE_WEB_SEARCH_MAX_USES,
        }]

    # Request/response logging, printed on every uplink call. served_by_model
    # in the response block below comes directly from the API response
    # object, so a misrouted call would fail loudly rather than print a
    # fabricated model name.
    print(f"\n===== [CLAUDE REQUEST] model={config.CLAUDE_MODEL}  "
          f"image_attached={'yes' if frame is not None else 'no'}  "
          f"web_search={'on (max_uses=' + str(config.CLAUDE_WEB_SEARCH_MAX_USES) + ')' if tools else 'off'} =====")
    print(f"--- system prompt ({len(system_prompt)} chars) ---\n{system_prompt}")
    print(f"--- user content ({len(user_content)} chars) ---\n{user_content}")
    print("=====")

    client = _get_client()
    t0 = time.time()
    full_reply = ""
    final = None
    stream_kwargs = dict(
        model=config.CLAUDE_MODEL,
        max_tokens=config.CLAUDE_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": content_blocks}],
    )
    if tools:
        stream_kwargs["tools"] = tools

    try:
        async with client.messages.stream(**stream_kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    full_reply += text
                    yield text
            try:
                final = await stream.get_final_message()
            except Exception:
                pass  # best-effort only -- the reply text already streamed fine either way

    except anthropic.AuthenticationError:
        print("===== [CLAUDE RESPONSE] REQUEST FAILED: invalid or missing API key. =====")
        yield "[SYSTEM ERROR] Uplink to Claude failed: invalid or missing API key."
        return
    except anthropic.RateLimitError:
        print("===== [CLAUDE RESPONSE] REQUEST FAILED: rate-limited. =====")
        yield "[SYSTEM ERROR] Uplink to Claude is rate-limited right now."
        return
    except anthropic.APIStatusError as e:
        print(f"===== [CLAUDE RESPONSE] REQUEST FAILED: {e.status_code} {e.message} =====")
        yield f"[SYSTEM ERROR] Uplink to Claude failed ({e.status_code}): {e.message}"
        return
    except anthropic.APIConnectionError as e:
        print(f"===== [CLAUDE RESPONSE] REQUEST FAILED: connection error ({e}) =====")
        yield f"[SYSTEM ERROR] Uplink to Claude failed: connection error ({e})"
        return

    served_by = getattr(final, "model", None) or "(model field unavailable -- get_final_message failed)"

    # web_search_tool_result.content is a list on success, an error object
    # on failure (server-tool errors return HTTP 200 rather than raising).
    search_uses = []
    if final is not None:
        for block in getattr(final, "content", []) or []:
            if getattr(block, "type", None) == "server_tool_use" and getattr(block, "name", None) == "web_search":
                search_uses.append(getattr(block, "input", {}).get("query", "?"))
            elif getattr(block, "type", None) == "web_search_tool_result":
                content = getattr(block, "content", None)
                if not isinstance(content, list):
                    print(f" [UPLINK] web_search error: {content}")
    if search_uses:
        print(f" [UPLINK] web_search USED ({len(search_uses)}x): {search_uses}")
    elif tools:
        print(" [UPLINK] web_search was attached to this request but Claude did not use it.")
    else:
        print(" [UPLINK] web_search not attached to this request (no explicit search command detected).")

    print(f"===== [CLAUDE RESPONSE] served_by_model={served_by}  "
          f"({len(full_reply)} chars) =====\n{full_reply}\n=====")

    if metrics is not None:
        if final is not None:
            try:
                metrics["input_tokens"] = final.usage.input_tokens
                metrics["output_tokens"] = final.usage.output_tokens
            except Exception:
                pass
        metrics["total_duration_s"] = time.time() - t0
