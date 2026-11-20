"""Handle sensitive requests before chart calculation and provider routing."""
import re

_DISTRESS = re.compile(
    r"\b(?:suicid(?:e|al)|kill myself|end(?:ing)? my life|want to die|don.t want to live|hurt myself|"
    r"self.harm|khudkushi|marna chaht[ai]|jeena nahi)\b|आत्महत्या|खुदकुशी|जीना नहीं|मरना चाहता|मरना चाहती", re.I)
_PREGNANCY = re.compile(
    r"\b(?:pregnan\w*|concep(?:tion|tive)|conceive|miscarri\w*|stillbirth|fertility treatment|IVF|garbh|"
    r"child\s?birth|santaa?n|have (?:a )?(?:baby|child(?:ren)?|kid|baccha)s?|"
    r"baccha\s+(?:hona|hoga|paida|chaahiye))\b"
    r"|गर्भ|गर्भपात|गर्भधारण|संतान|बच्चा\s+(?:होगा|होना|पैदा)", re.I)
_PREDICT = re.compile(
    r"\b(?:will|when|how soon|predict|prediction|chances?|guarantee|likely|risk|cause|"
    r"possible|is it (?:possible|going)|can (?:i|my chart)|kab|yog)\b"
    r"|कब|योग|संभावना|भविष्यवाणी|होग[ाीे]", re.I)
_OTHER_MIND = re.compile(
    r"\b(?:does (?:he|she|my (?:ex|partner|spouse|wife|husband)) (?:love|miss|want) me|"
    r"what (?:does|is) (?:he|she|my (?:ex|partner|spouse|wife|husband)) (?:think|feel|thinking|feeling))\b", re.I)
_HINDI = re.compile(r"[\u0900-\u097f]")


def private_reply(text: str) -> str | None:
    hindi = bool(_HINDI.search(text))
    if _DISTRESS.search(text):
        if hindi:
            return ("मुझे दुख है कि आप इतना कठिन समय झेल रहे हैं। अगर अभी खुद को नुकसान पहुँचाने का खतरा है, "
                    "तो स्थानीय आपातकालीन सेवा को कॉल करें या नज़दीकी अस्पताल जाएँ। किसी भरोसेमंद व्यक्ति को अभी "
                    "बताएँ और उनसे साथ रहने के लिए कहें। भारत में Tele-MANAS की हेल्पलाइन 14416 है। "
                    "क्या आप अभी सुरक्षित हैं?")
        return ("I’m sorry things feel so hard right now. If you might hurt yourself soon, call your local emergency "
                "number or go to the nearest emergency department. If you can, tell someone you trust and ask them to "
                "stay with you. In India, you can call Tele-MANAS at 14416. Are you safe right now?")
    # Pregnancy wording and a prediction cue must appear in the SAME clause —
    # "I have children. When will I get promoted?" is not a conception ask.
    # A conditional clause joins its question: "if I do IVF, what are my
    # chances?" is one ask.
    clauses = re.split(r"[.!?।;\n]+|,\s*", text)
    merged = []
    for clause in clauses:
        if merged and re.match(r"\s*(?:if|when)\b", merged[-1], re.I):
            merged[-1] += " " + clause
        else:
            merged.append(clause)
    if any(_PREGNANCY.search(clause) and _PREDICT.search(clause) for clause in merged):
        if hindi:
            return ("कुंडली से गर्भधारण, गर्भपात या किसी चिकित्सकीय परिणाम का अनुमान नहीं लगाया जा सकता। "
                    "अगर यह आपके स्वास्थ्य से जुड़ा सवाल है, तो योग्य चिकित्सक से बात करें।")
        return ("A birth chart can’t predict conception, miscarriage, or a medical outcome. If this is a health concern, "
                "a qualified clinician can help you understand your situation.")
    if _OTHER_MIND.search(text):
        return ("A chart can’t tell me what someone else feels. We can talk through what you’ve actually observed "
                "and what you’d like to ask them.")
    return None
