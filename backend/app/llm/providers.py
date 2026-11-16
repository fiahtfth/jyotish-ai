"""LLM providers.

Priority: configured provider (gemini | ollama | lmstudio) -> offline
deterministic responder. The offline responder never claims to be an LLM —
it composes answers directly from the locked chart facts and the
four-pillar result, so the app is fully usable with zero API keys.
"""
import json
import os
import re
import time

import httpx

from ..config import settings

SYSTEM_PERSONA = """You are Jyotish AI — a warm, perceptive, experienced Vedic astrologer.
Style rules (non-negotiable):
- Conversational, concise, human. No bullet-point reports unless asked.
- Ask at most ONE follow-up question per reply.
- Never invent planetary positions, dashas, dates, or probabilities — every
  astro fact you mention must come from the CHART FACTS and ANALYSIS blocks.
- Never claim to be a human. You may be an AI astrologer with a human voice.
- Admit ambiguity; do not force optimism or fear.
- No vague Barnum statements. Tie statements to the actual chart.
- Do not reveal raw degrees, JSON, tables or 'pillars' unless the user asks
  for the reasoning.
- Reply in the user's language (English / Hindi / natural Hinglish).
"""


def _gemini(system: str, messages: list[dict]) -> str:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    if not settings.LLM_EXTERNAL_CONSENT:
        # consent gate: external provider requires explicit opt-in
        raise RuntimeError("external LLM consent not granted (set JYOTISH_LLM_EXTERNAL_CONSENT=true)")
    contents = [{"role": "user" if m["role"] == "user" else "model",
                 "parts": [{"text": m["content"]}]} for m in messages]
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}")
    r = httpx.post(url, json=body, timeout=45)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _ollama(system: str, messages: list[dict]) -> str:
    prompt = system + "\n\n" + "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Astrologer'}: {m['content']}" for m in messages
    ) + "\n\nAstrologer:"
    r = httpx.post(f"{settings.OLLAMA_URL}/api/generate",
                   json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                   timeout=120)
    r.raise_for_status()
    return r.json()["response"].strip()


def _lmstudio(system: str, messages: list[dict]) -> str:
    r = httpx.post(f"{settings.LMSTUDIO_URL}/chat/completions",
                   json={"model": settings.LMSTUDIO_MODEL,
                         "messages": [{"role": "system", "content": system}] + messages,
                         "temperature": 0.7, "max_tokens": 600},
                   timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


PROVIDERS = {"gemini": _gemini, "ollama": _ollama, "lmstudio": _lmstudio}


def generate(messages: list[dict], facts: dict | None = None,
             analysis: dict | None = None, context_note: str = "") -> tuple[str, str]:
    """Return (reply, provider_used). Falls back to 'offline' on any failure."""
    system = SYSTEM_PERSONA
    if facts is not None:
        system += "\n\nCHART FACTS (authoritative — never contradict):\n" + _facts_brief(facts)
    if analysis is not None:
        system += "\n\nANALYSIS (four-pillar result for the current question):\n" + json.dumps(analysis, indent=1)[:4000]
    if context_note:
        system += "\n\nCONTEXT: " + context_note

    provider = settings.LLM_PROVIDER
    if provider in PROVIDERS:
        for attempt in range(3):
            try:
                text = PROVIDERS[provider](system, messages)
                if text:
                    return text, provider
            except Exception:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
    return offline_response(messages, facts, analysis, context_note), "offline"


def _facts_brief(facts: dict) -> str:
    p = facts["planets"]
    lag = facts["lagna"]
    lines = [f"Lagna: {lag['sign_name']} ({lag['degree']:.1f}°), lord {lag['lord']}"]
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

    conv = analysis.get("convergence", "")
    dom = analysis.get("domain", "that area")
    evidence = analysis.get("calculation_evidence_ids", [])
    lead = {
        "strong traditional convergence":
            f"Looking at your chart, the traditional indicators for {dom} line up quite well for that period.",
        "substantial traditional convergence":
            f"The traditional indicators for {dom} are mostly supportive, though not unanimous.",
        "mixed or conditional convergence":
            f"The signals for {dom} are genuinely mixed — I'd describe the period as possible rather than promised.",
    }.get(conv.split(" (")[0],
          f"The indications for {dom} are weak in that window — I wouldn't lean on it heavily.")
    bridge = ""
    if evidence:
        short = [e for e in evidence if "rules" not in e.lower()][:2]
        if short:
            bridge = " " + short[0].split(": ", 1)[-1].rstrip(".") + "."
    tail = " Is there a specific part of this you'd like me to go deeper into?"
    return lead + bridge + tail


def _offline_smalltalk(user_msg: str, facts: dict | None) -> str:
    if re.search(r"\b(hi|hello|hey|namaste)\b", user_msg):
        return "Namaste. I'm listening — what's on your mind?"
    if "thank" in user_msg:
        return "Of course. What else would you like to look at?"
    if facts is not None and ("lagna" in user_msg or "ascendant" in user_msg
                              or "rising" in user_msg):
        lag = facts["lagna"]
        return (f"Your lagna is {lag['sign_name']} ({lag['degree']:.1f}°), ruled by "
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
    return ("Tell me a little more about what you're asking — I read the chart, "
            "not a script, so the more specific you are the better I can help.")
