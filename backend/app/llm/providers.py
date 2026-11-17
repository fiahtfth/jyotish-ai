"""LLM providers.

Priority: configured provider (gemini | groq | openrouter | ollama | lmstudio)
-> groq/openrouter fallbacks when configured -> offline deterministic responder.
The offline responder never claims to be an LLM — it composes answers directly
from the locked chart facts and the four-pillar result, so the app is fully
usable with zero API keys.
"""
import json
import logging
import os
import re
import threading
import time

import httpx

from ..config import settings

log = logging.getLogger(__name__)

SYSTEM_PERSONA = """You are Jyotish AI — a warm, perceptive, experienced Vedic astrologer.
Style rules (non-negotiable):
- Conversational, concise, human. No bullet-point reports unless asked.
- Ask at most ONE follow-up question per reply.
- Read the latest user reply in the conversation context. Answer their chosen
  focus directly; never repeat a clarification question they already answered.
- Avoid repeating the same opening planetary placement in successive replies.
- Never invent planetary positions, dashas, dates, or probabilities — every
  astro fact you mention must come from the CHART FACTS and ANALYSIS blocks.
- Never claim to be a human. You may be an AI astrologer with a human voice.
- Admit ambiguity; do not force optimism or fear.
- Rule agreement is not predictive accuracy. Never describe an event as confirmed.
- Respect decision.disposition, abstention reasons, missing layers and birth-time sensitivity.
  When decision.disposition is abstain, give a useful natal-chart reading and discuss
  relevant placements, themes and current periods without promising an event or date.
  A broad question is valid: answer it, then ask at most one helpful follow-up.
  Scorability, rule counts, agreement labels, abstentions and record criteria are internal;
  do not mention them or prepend a refusal to an ordinary reading.
  Do not add dates outside the computed windows or invent event details or success criteria.
- No vague Barnum statements. Tie statements to the actual chart.
- Do not reveal raw degrees, JSON, tables or 'pillars' unless the user asks
  for the reasoning.
- Answer natal questions from the D1 CHART FACTS only — never answer about
  divisional charts or invent a different lagna unless the user explicitly
  names a varga.
- Plain text only: no markdown, no asterisks, no headings.
- Reply in the user's language (English / Hindi / natural Hinglish).
"""


def _gemini(system: str, messages: list[dict], timeout: float = 45) -> str:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    if not settings.LLM_EXTERNAL_CONSENT:
        # consent gate: external provider requires explicit opt-in
        raise RuntimeError("external LLM consent not granted (set JYOTISH_LLM_EXTERNAL_CONSENT=true)")
    contents = [{"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": m["content"]}]} for m in messages]
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1400,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{settings.GEMINI_MODEL}:generateContent")
    r = httpx.post(url, json=body, timeout=timeout,
                   headers={"x-goog-api-key": settings.GEMINI_API_KEY})
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _groq(system: str, messages: list[dict], timeout: float = 45) -> str:
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")
    if not settings.LLM_EXTERNAL_CONSENT:
        # consent gate: external provider requires explicit opt-in
        raise RuntimeError("external LLM consent not granted (set JYOTISH_LLM_EXTERNAL_CONSENT=true)")
    payload = {"model": settings.GROQ_MODEL,
               "messages": [{"role": "system", "content": system}] + messages,
               "temperature": 0.7, "max_tokens": 1400}
    if "gpt-oss" in settings.GROQ_MODEL:
        payload["reasoning_effort"] = "low"
        payload["reasoning_format"] = "hidden"
    r = httpx.post("https://api.groq.com/openai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                   json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _openrouter(system: str, messages: list[dict], timeout: float = 45) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    if not settings.LLM_EXTERNAL_CONSENT:
        # consent gate: external provider requires explicit opt-in
        raise RuntimeError("external LLM consent not granted (set JYOTISH_LLM_EXTERNAL_CONSENT=true)")
    model = settings.OPENROUTER_MODEL
    if model != "openrouter/free" and not model.endswith(":free"):
        raise RuntimeError("OpenRouter fallback is restricted to free models (:free or openrouter/free)")
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions",
                   headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                            "X-OpenRouter-Title": "Jyotish AI"},
                   json={"model": model,
                         "messages": [{"role": "system", "content": system}] + messages,
                         "temperature": 0.7, "max_tokens": 1400},
                   timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _ollama(system: str, messages: list[dict], timeout: float = 120) -> str:
    prompt = system + "\n\n" + "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Astrologer'}: {m['content']}" for m in messages
    ) + "\n\nAstrologer:"
    r = httpx.post(f"{settings.OLLAMA_URL}/api/generate",
                   json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                   timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


def _lmstudio(system: str, messages: list[dict], timeout: float = 120) -> str:
    r = httpx.post(f"{settings.LMSTUDIO_URL}/chat/completions",
                   json={"model": settings.LMSTUDIO_MODEL,
                         "messages": [{"role": "system", "content": system}] + messages,
                         "temperature": 0.7, "max_tokens": 600},
                   timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ------------------------------------------------------------ streaming
# Each stream function pushes text chunks to `on_delta` as they arrive and
# returns the full text. They share the config/consent gates of the blocking
# functions above and raise on any failure.

def _require_external(key: str, name: str):
    if not key:
        raise RuntimeError(f"{name} not set")
    if not settings.LLM_EXTERNAL_CONSENT:
        raise RuntimeError("external LLM consent not granted (set JYOTISH_LLM_EXTERNAL_CONSENT=true)")


def _sse_data_lines(r: httpx.Response, timeout: float):
    """Yield the payload of each `data:` line, enforcing a total time budget
    (httpx timeouts are per-read, not overall)."""
    end = time.monotonic() + timeout
    for line in r.iter_lines():
        if time.monotonic() > end:
            raise httpx.ReadTimeout("stream exceeded turn deadline")
        if line.startswith("data:"):
            yield line[5:].strip()


def _openai_stream(url: str, headers: dict, payload: dict, on_delta, timeout: float) -> str:
    payload = {**payload, "stream": True}
    parts: list[str] = []
    with httpx.stream("POST", url, headers=headers, json=payload, timeout=timeout) as r:
        r.raise_for_status()
        for data in _sse_data_lines(r, timeout):
            if data == "[DONE]":
                break
            choices = json.loads(data).get("choices") or []
            chunk = (choices[0].get("delta") or {}).get("content") if choices else None
            if chunk:
                parts.append(chunk)
                on_delta(chunk)
    return "".join(parts).strip()


def _gemini_stream(system: str, messages: list[dict], on_delta, timeout: float = 45) -> str:
    _require_external(settings.GEMINI_API_KEY, "GEMINI_API_KEY")
    contents = [{"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": m["content"]}]} for m in messages]
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1400,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{settings.GEMINI_MODEL}:streamGenerateContent?alt=sse")
    parts: list[str] = []
    with httpx.stream("POST", url, json=body, timeout=timeout,
                      headers={"x-goog-api-key": settings.GEMINI_API_KEY}) as r:
        r.raise_for_status()
        for data in _sse_data_lines(r, timeout):
            cands = json.loads(data).get("candidates") or []
            for part in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
                chunk = part.get("text")
                if chunk:
                    parts.append(chunk)
                    on_delta(chunk)
    return "".join(parts).strip()


def _groq_stream(system: str, messages: list[dict], on_delta, timeout: float = 45) -> str:
    _require_external(settings.GROQ_API_KEY, "GROQ_API_KEY")
    payload = {"model": settings.GROQ_MODEL,
               "messages": [{"role": "system", "content": system}] + messages,
               "temperature": 0.7, "max_tokens": 1400}
    if "gpt-oss" in settings.GROQ_MODEL:
        payload["reasoning_effort"] = "low"
        payload["reasoning_format"] = "hidden"
    return _openai_stream("https://api.groq.com/openai/v1/chat/completions",
                          {"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                          payload, on_delta, timeout)


def _openrouter_stream(system: str, messages: list[dict], on_delta, timeout: float = 45) -> str:
    _require_external(settings.OPENROUTER_API_KEY, "OPENROUTER_API_KEY")
    model = settings.OPENROUTER_MODEL
    if model != "openrouter/free" and not model.endswith(":free"):
        raise RuntimeError("OpenRouter fallback is restricted to free models (:free or openrouter/free)")
    return _openai_stream("https://openrouter.ai/api/v1/chat/completions",
                          {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                           "X-OpenRouter-Title": "Jyotish AI"},
                          {"model": model,
                           "messages": [{"role": "system", "content": system}] + messages,
                           "temperature": 0.7, "max_tokens": 1400},
                          on_delta, timeout)


def _lmstudio_stream(system: str, messages: list[dict], on_delta, timeout: float = 120) -> str:
    return _openai_stream(f"{settings.LMSTUDIO_URL}/chat/completions", {},
                          {"model": settings.LMSTUDIO_MODEL,
                           "messages": [{"role": "system", "content": system}] + messages,
                           "temperature": 0.7, "max_tokens": 600},
                          on_delta, timeout)


def _ollama_stream(system: str, messages: list[dict], on_delta, timeout: float = 120) -> str:
    prompt = system + "\n\n" + "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Astrologer'}: {m['content']}" for m in messages
    ) + "\n\nAstrologer:"
    parts: list[str] = []
    end = time.monotonic() + timeout
    with httpx.stream("POST", f"{settings.OLLAMA_URL}/api/generate", timeout=timeout,
                      json={"model": settings.OLLAMA_MODEL, "prompt": prompt,
                            "stream": True}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if time.monotonic() > end:
                raise httpx.ReadTimeout("stream exceeded turn deadline")
            if not line.strip():
                continue
            chunk = json.loads(line).get("response")
            if chunk:
                parts.append(chunk)
                on_delta(chunk)
    return "".join(parts).strip()


STREAM_PROVIDERS = {"gemini": _gemini_stream, "groq": _groq_stream,
                    "openrouter": _openrouter_stream, "ollama": _ollama_stream,
                    "lmstudio": _lmstudio_stream}


_llm_slots = threading.BoundedSemaphore(max(1, settings.LLM_MAX_CONCURRENCY))
_MIN_CALL_SECONDS = 1.0

PROVIDERS = {"gemini": _gemini, "groq": _groq, "openrouter": _openrouter,
             "ollama": _ollama, "lmstudio": _lmstudio}


EXTERNAL_PROVIDERS = ("gemini", "groq", "openrouter")


def generate(messages: list[dict], facts: dict | None = None,
             analysis: dict | None = None, context_note: str = "",
             allow_external: bool = True, on_delta=None) -> tuple[str, str]:
    """Return (reply, provider_used). Falls back through Groq/OpenRouter to 'offline'.

    `on_delta(text)` (optional) enables streaming: chunks are pushed as they
    arrive. Once any chunk has been emitted a failure is NOT retried and no other
    provider is tried (that would splice two replies); the returned reply is
    then the offline text, which callers treat as authoritative.

    `allow_external=False` (the user hasn't opted in) restricts generation to
    local providers and the offline responder — nothing is sent off-server."""
    system = SYSTEM_PERSONA
    if facts is not None:
        system += "\n\nCHART FACTS (authoritative — never contradict):\n" + _facts_brief(facts)
    if analysis is not None:
        system += "\n\nANALYSIS (four-pillar result for the current question):\n" + json.dumps(analysis, separators=(",", ":"))
    if context_note:
        system += "\n\nCONTEXT: " + context_note

    provider = settings.LLM_PROVIDER
    providers_to_try = []
    if provider in PROVIDERS:
        providers_to_try = [provider] + [f for f in ("groq", "openrouter") if f != provider]
    # skip external providers that have no key or no consent — no point retrying them
    keys = {"gemini": settings.GEMINI_API_KEY, "groq": settings.GROQ_API_KEY,
            "openrouter": settings.OPENROUTER_API_KEY}
    providers_to_try = [p for p in providers_to_try
                        if p not in keys or (keys[p] and settings.LLM_EXTERNAL_CONSENT)]
    if not allow_external:
        providers_to_try = [p for p in providers_to_try if p not in EXTERNAL_PROVIDERS]
    emitted = 0

    def _emit(chunk: str):
        nonlocal emitted
        chunk = re.sub(r"[*_`]{1,2}", "", chunk)
        if chunk:
            emitted += 1
            on_delta(chunk)

    def _offline():
        text = offline_response(messages, facts, analysis, context_note)
        if provider != "offline":
            if not allow_external and provider in EXTERNAL_PROVIDERS:
                notice = ("Accept the updated service terms to use AI chat. "
                          "AI replies use your chart summary and recent messages with external providers.")
            elif not providers_to_try:
                notice = "AI chat is not configured or enabled on the server."
            else:
                notice = "The AI service is temporarily unavailable."
            text = notice + " I'm using the limited built-in chart responder for this reply.\n\n" + text
        if on_delta is not None and not emitted:
            _emit(text)          # the whole offline reply as a single delta
        return text, "offline"

    if not providers_to_try:
        return _offline()
    # global cap on in-flight LLM turns so slow upstreams can't hold every worker thread
    if not _llm_slots.acquire(blocking=False):
        return _offline()
    try:
        deadline = time.monotonic() + settings.LLM_TURN_DEADLINE_SECONDS
        for index, p in enumerate(providers_to_try):
            # Reserve time for each remaining provider. A primary read timeout
            # must not consume the entire turn and silently bypass healthy backups.
            now = time.monotonic()
            budget = (deadline - now) / (len(providers_to_try) - index)
            provider_deadline = min(deadline, now + max(_MIN_CALL_SECONDS, budget))
            for attempt in range(3):
                now = time.monotonic()
                if deadline - now < _MIN_CALL_SECONDS:
                    log.warning("LLM turn deadline reached; using offline responder")
                    return _offline()
                remaining = provider_deadline - now
                if remaining <= 0:
                    break
                try:
                    if on_delta is None:
                        text = PROVIDERS[p](system, messages, timeout=remaining)
                    else:
                        text = STREAM_PROVIDERS[p](system, messages, _emit, timeout=remaining)
                    if text:
                        # the persona demands plain text; strip stray markdown
                        return re.sub(r"[*_`]{1,2}", "", text), p
                    log.warning("LLM provider %s returned empty text", p)
                    retryable = False
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    log.warning("LLM provider %s failed: HTTP %s", p, code)
                    retryable = code == 429 or code >= 500
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    log.warning("LLM provider %s failed: %s", p, type(exc).__name__)
                    retryable = True
                except Exception as exc:  # RuntimeError config errors, bad payloads, ...
                    log.warning("LLM provider %s failed: %s", p, type(exc).__name__)
                    retryable = False
                if emitted:
                    # partial text already reached the client: no retry, no fallback
                    return _offline()
                if not retryable or attempt >= 2:
                    break
                delay = 2 * (attempt + 1)
                if time.monotonic() + delay + _MIN_CALL_SECONDS >= provider_deadline:
                    break
                time.sleep(delay)
    finally:
        _llm_slots.release()
    return _offline()


def _facts_brief(facts: dict) -> str:
    p = facts["planets"]
    lag = facts["lagna"]
    # degrees are withheld even from the model — it interprets, never states them
    lines = [f"Lagna: {lag['sign_name']}, lord {lag['lord']}"]
    for name, rec in p.items():
        extra = []
        if rec["retrograde"]:
            extra.append("retro")
        if rec["combust"]:
            extra.append("combust")
        if rec["dignity"]:
            extra.append("/".join(rec["dignity"]))
        lines.append(f"{name}: {rec['sign_name']} house {rec['house']}, "
                     f"nakshatra {rec['nakshatra']['name']} pada {rec['nakshatra']['pada']}"
                     + (f" [{', '.join(extra)}]" if extra else ""))
    func = facts["functional"]
    lines.append(f"Functional benefics: {', '.join(func['benefics'])}; "
                 f"malefics: {', '.join(func['malefics'])}; "
                 f"yogakaraka: {func['yogakaraka']}; maraka: {', '.join(func['maraka_lords'])}")
    jk = facts["jaimini"]["karakas"]
    lines.append("Chara karakas: " + ", ".join(f"{k}={v}" for k, v in jk.items()))
    return "\n".join(lines)


# ------------------------------------------------------------------ offline

def offline_response(messages: list[dict], facts: dict | None,
                     analysis: dict | None, context_note: str = "") -> str:
    """Deterministic responder built purely on computed facts + analysis."""
    user_msg = messages[-1]["content"].lower() if messages else ""
    if analysis is None:
        return _offline_smalltalk(user_msg, facts)
    if analysis.get("decision", {}).get("disposition") == "abstain":
        from ..astro.prediction import interpretation_reading
        return interpretation_reading(analysis, facts, messages)

    dom = analysis.get("domain", "that area")
    evidence = analysis.get("calculation_evidence_ids", [])
    support = analysis.get("support_count", 0)
    conflict = analysis.get("conflict_count", 0)
    if support >= 3:
        lead = f"Looking at your chart, the traditional indicators for {dom} line up quite well for that period."
    elif support == 2 and conflict == 0:
        lead = f"The traditional indicators for {dom} are mostly supportive, though not unanimous."
    elif support >= 1:
        lead = f"The signals for {dom} are genuinely mixed — I'd describe the period as possible rather than promised."
    else:
        lead = f"The indications for {dom} are weak in that window — I wouldn't lean on it heavily."
    bridge = ""
    if evidence:
        short = [e for e in evidence if "rules" not in e.lower()][:2]
        if short:
            bridge = " " + short[0].split(": ", 1)[-1].rstrip(".") + "."
    prec = analysis.get("precision") or {}
    extras = ""
    if prec.get("confirmation") in ("Both confirmation methods support", "Hidden friction"):
        extras += f" The secondary methods give this a '{prec['confirmation'].lower()}' reading."
    if prec.get("timing_windows"):
        w = prec["timing_windows"][0]
        extras += (" The weeks where the traditional indicators concentrate most are "
                   f"{w['start']} to {w['end']}.")
    if prec.get("magnitude"):
        extras += f" The strength picture suggests something {prec['magnitude']} in scale."
    tail = " Is there a specific part of this you'd like me to go deeper into?"
    return lead + bridge + extras + tail


def _offline_smalltalk(user_msg: str, facts: dict | None) -> str:
    if re.search(r"\b(hi|hello|hey|namaste)\b", user_msg):
        return "Namaste. I'm listening — what's on your mind?"
    if "thank" in user_msg:
        return "Of course. What else would you like to look at?"
    if facts is not None and ("lagna" in user_msg or "ascendant" in user_msg
                              or "rising" in user_msg):
        lag = facts["lagna"]
        return (f"Your lagna is {lag['sign_name']}, ruled by "
                f"{lag['lord']}. It's a {lag['nakshatra']['name']} rising nakshatra. "
                "What would you like to look at next?")
    if facts is not None and ("moon" in user_msg or "rashi" in user_msg):
        m = facts["planets"]["Moon"]
        return (f"Your Moon is in {m['sign_name']} — {m['nakshatra']['name']} nakshatra, "
                f"pada {m['nakshatra']['pada']}, in the {m['house']}th house.")
    if facts is not None and "dasha" in user_msg:
        return ("Dasha timing is the backbone of what I read — ask me about a specific "
                "area (career, marriage, studies) and I'll walk you through what the "
                "periods show.")
    if facts is not None and ("chart" in user_msg or "kundli" in user_msg):
        lag = facts["lagna"]
        return (f"Your chart is a {lag['sign_name']} lagna chart — the moon sits in "
                f"{facts['planets']['Moon']['sign_name']}. What would you like to explore?")
    return ("The built-in responder cannot interpret that question. It can show computed "
            "chart facts; try 'What is my lagna?', 'Where is my Moon?' or 'Show my birth chart'.")
