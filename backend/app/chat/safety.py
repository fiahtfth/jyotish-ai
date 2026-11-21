"""Handle sensitive requests before chart calculation and provider routing."""
import re

_DISTRESS = re.compile(
    r"\b(?:suicid(?:e|al)|kill myself|end(?:ing)? my life|want to die|don.t want to live|hurt myself|"
    r"self.harm|khudkushi|marna chaht[ai]|jeena nahi|jina nahi|marna hai|mar jaunga|mar jaungi|"
    r"mar jana chaht[ai]|marne ka mann|suicide kar\w*|khud ko (?:khatam|maar)\w*|zindagi (?:khatam|se thak)\w*|"
    r"jindagi khatam|jeene ka mann nahi|jeene ki ichha nahi|life khatam|atmahatya|"
    # Tamil / Telugu romanized
    r"tha[tr]kolai|saa?ga (?:poren|porein|venum|vendum)|chanipovalani|chachipovalani)\b"
    r"|आत्महत्या|खुदकुशी|जीना नहीं|मरना चाहता|मरना चाहती|मरना है|मर जाऊँगा|मर जाऊंगा|मर जाऊँगी|मर जाऊंगी"
    r"|ज़िंदगी खत्म|जिंदगी खत्म|ज़िन्दगी खत्म|जिन्दगी खत्म|खुद को खत्म|खुद को मार|जीने का मन नहीं|सुसाइड|आत्मघात",
    re.I)
_MINOR_ROMANCE = re.compile(
    r"\b(?:marriage|marry|married|shaadi|shadi|vivah|wedding|spouse|husband|wife|girlfriend|boyfriend|"
    r"love life|love affair|affair|dating|date someone|romance|romantic|crush|relationship|partner|"
    r"sex\w*|kiss\w*|intimate|intimacy|pyaar|prem vivah|love marriage|breakup|break up)\b"
    r"|शादी|विवाह|प्रेम|प्यार|गर्लफ्रेंड|बॉयफ्रेंड|संबंध", re.I)
_MINOR_HEALTH = re.compile(
    r"\b(?:health|healthy|illness|ill|disease|sick|sickness|surgery|operation|cancer|diabet\w*|"
    r"mental|depress\w*|anxiety|accident|injur\w*|bimari|swasth\w*|tabiyat|longevity|lifespan|"
    r"life span|how long (?:will|do|can) i live|death|die|aayu)\b|स्वास्थ्य|बीमारी|मृत्यु|आयु", re.I)
_GAMBLING = re.compile(
    r"\b(?:gambl\w*|satta|matka|lottery|lotto|jackpot|betting|bets?|bet on|teen patti|rummy|casino|poker|"
    r"dream11|ipl bet|crypto|bitcoin|options trading|intraday|day trad\w*|stock tips?)\b"
    r"|सट्टा|लॉटरी|जुआ|मटका", re.I)
_GAMBLING_ASK = re.compile(
    r"\b(?:which|what|lucky|winning|number|numbers|when|best time|should i|will i win|win|tip|tips|"
    r"buy|sell|invest|kab|konsa|kaun sa)\b|कब|कौन सा|नंबर", re.I)
_LEGAL = re.compile(
    r"\b(?:court|case|lawsuit|litigation|verdict|judg(?:e)?ment|bail|custody|divorce case|"
    r"legal (?:matter|dispute|battle)|property dispute|fir|tribunal|appeal|sue|suing|cbi|police case)\b"
    r"|मुकदमा|केस|अदालत|कोर्ट|फैसला", re.I)
_DIAGNOSE = re.compile(
    r"\b(?:do i have|does (?:he|she|my \w+) have|am i (?:suffering|diagnosed)|diagnos\w+|"
    r"what (?:disease|illness|condition|sickness) (?:do|does|is|will)|which disease|"
    r"is (?:this|it|my \w+) (?:cancer|tumou?r|diabetes|tb|a tumou?r|serious)|what(?:'s| is) wrong with my)\b"
    r"|क्या मुझे .{0,20}(?:कैंसर|बीमारी|रोग)|कौन सी बीमारी", re.I)
_PREGNANCY = re.compile(
    r"\b(?:pregnan\w*|concep(?:tion|tive)|conceive|miscarri\w*|stillbirth|fertility treatment|IVF|garbh)\b"
    r"|गर्भ|गर्भपात|गर्भधारण", re.I)
_CHILD_TIMING = re.compile(
    r"\bwhen\b.{0,30}\b(?:have|get|conceive|expect|welcome|blessed with)\b.{0,15}"
    r"\b(?:a |an |our |another |my )?(?:child|baby|kid|son|daughter|first child)\b"
    r"|\bwhen will (?:my|our|the) (?:child|baby) be born\b|\bsantan(?:\s+\w+)? kab\b|संतान .{0,15}कब", re.I)
_DEATH = re.compile(
    r"\b(?:lifespan|life span|longevity|life expectancy|age (?:of|at) death|time of death|date of death|"
    r"aayu|ayu yog|mrityu|maut kab|kab (?:marunga|marungi|marega|maregi|mar jayega|mar jaunga))\b"
    r"|\bwhen (?:will|would|shall|can|could) .{0,40}?\b(?:die(?!\s+(?:down|out))|death|pass away|passing away)\b"
    r"|\bwhen (?:am i|is \w+(?: \w+)?|are we) (?:going to|gonna) (?:die|pass away)\b"
    r"|\bwill (?:i|he|she|we|they|my \w+) (?:die|pass away)\b"
    r"|\bhow long (?:will|do|does|am|is|can|could) (?:i|he|she|we|they|my \w+) (?:live|survive)\b"
    r"|मृत्यु कब|आयु कितनी|कब मर|मौत कब", re.I)
_REMEDY = re.compile(
    r"\b(?:gem ?stones?|ratna|pukhraj|neelam|moonga|manik|panna|moti|which (?:stone|ring)|"
    r"what (?:stone|ring)|should i wear (?:a |an |any )?(?:stone|ring|gem)\w*|remed(?:y|ies)|upay|totka)\b", re.I)
_PREDICT = re.compile(
    r"\b(?:will|when|how soon|predict|prediction|chances?|guarantee|likely|risk|cause|can (?:i|my chart)|kab|yog)\b"
    r"|कब|योग|संभावना|भविष्यवाणी|होग[ाीे]", re.I)
_OTHER_MIND = re.compile(
    r"\b(?:does (?:he|she|my (?:ex|partner|spouse|wife|husband)) (?:love|miss|want) me|"
    r"what (?:does|is) (?:he|she|my (?:ex|partner|spouse|wife|husband)) (?:think|feel|thinking|feeling))\b", re.I)
_HINDI = re.compile(r"[\u0900-\u097f]")


CRISIS_RESOURCES = ("In India you can call Tele-MANAS at 14416 (free, 24x7) or the national emergency "
                    "number 112.")


def private_reply(text: str, *, minor: bool = False) -> str | None:
    hindi = bool(_HINDI.search(text))
    if _DISTRESS.search(text):
        if hindi:
            return ("मुझे दुख है कि आप इतना कठिन समय झेल रहे हैं। अगर अभी खुद को नुकसान पहुँचाने का खतरा है, "
                    "तो स्थानीय आपातकालीन सेवा को कॉल करें या नज़दीकी अस्पताल जाएँ। किसी भरोसेमंद व्यक्ति को अभी "
                    "बताएँ और उनसे साथ रहने के लिए कहें। भारत में Tele-MANAS की हेल्पलाइन 14416 है। "
                    "क्या आप अभी सुरक्षित हैं?")
        return ("I’m sorry things feel so hard right now. If you might hurt yourself soon, call your local emergency "
                "number or go to the nearest emergency department. If you can, tell someone you trust and ask them to "
                "stay with you. In India, you can call Tele-MANAS at 14416 (free, 24x7) or the emergency number 112. "
                "Are you safe right now?")
    if minor and (_MINOR_ROMANCE.search(text) or _MINOR_HEALTH.search(text)):
        if hindi:
            return ("आप अभी कम उम्र के हैं, इसलिए मैं शादी, प्रेम-संबंध, सेहत या आयु जैसे विषयों पर कुंडली से बात नहीं करूँगा। "
                    "इन बातों के लिए अपने माता-पिता, शिक्षक या डॉक्टर जैसे भरोसेमंद बड़ों से बात करना सबसे अच्छा है। "
                    "चाहें तो हम पढ़ाई, रुचियों और अपनी ताकतों पर बात कर सकते हैं।")
        return ("Since this chart is for someone under 18, I keep away from marriage, romance, health and "
                "lifespan topics. A parent, teacher or doctor you trust is the right person for those. "
                "I'm happy to talk about studies, interests and strengths, which the chart can speak to "
                "as natural aptitudes.")
    if _DEATH.search(text):
        if hindi:
            return ("मैं किसी की मृत्यु या आयु का अनुमान नहीं लगाता, और कुंडली से यह जाना भी नहीं जा सकता। "
                    "अगर आप अपनी या किसी अपने की सेहत को लेकर चिंतित हैं, तो योग्य चिकित्सक से बात करें और "
                    "उनके साथ समय बिताएँ। चाहें तो हम स्वास्थ्य और देखभाल के पहलुओं पर बात कर सकते हैं।")
        return ("I don’t predict death or how long anyone will live, and a chart can’t tell that. If you’re worried "
                "about someone’s health, or your own, a doctor is the right person to ask, and spending time with "
                "them matters more than any date. I’m glad to talk through care and wellbeing themes in the chart "
                "if that would help.")
    if (_PREGNANCY.search(text) and _PREDICT.search(text)) or _CHILD_TIMING.search(text):
        if hindi:
            return ("कुंडली से गर्भधारण, गर्भावस्था, गर्भपात या संतान के समय का अनुमान नहीं लगाया जा सकता; "
                    "परिवार और संतान के विषय केवल प्रतीकात्मक रूप से देखे जा सकते हैं। "
                    "अगर यह आपके स्वास्थ्य से जुड़ा सवाल है, तो योग्य चिकित्सक से बात करें।")
        return ("A birth chart can’t predict conception, pregnancy, miscarriage, or a medical outcome, so I won’t "
                "give dates for these. It can only speak symbolically about family and children themes. If this is "
                "a health concern or you’re planning, a qualified clinician can help you understand your situation.")
    if _GAMBLING.search(text) and _GAMBLING_ASK.search(text):
        return ("I don't predict lottery, satta, betting, crypto or trading numbers or timings, and no chart can "
                "tell which bet will win. Money put on chance is best kept to what you could comfortably lose, "
                "and if gambling is becoming hard to stop, India's Tele-MANAS (14416) can listen. I'm glad to "
                "talk about your steadier earning and saving patterns in the chart instead.")
    if _DIAGNOSE.search(text):
        return ("A chart can't diagnose an illness or say what condition someone has, so I won't try. If a "
                "symptom or test result worries you, please see a doctor soon; that matters more than any "
                "planetary reading. I'm happy to talk about rest, routine and wellbeing themes once you've "
                "had that checked.")
    if _OTHER_MIND.search(text):
        return ("A chart can’t tell me what someone else feels. We can talk through what you’ve actually observed "
                "and what you’d like to ask them.")
    return None


REMEDY_NOTE = ("The user asked for remedies: give optional, low-cost remedies first, graded: conduct and service "
               "(seva), then mantra or charity, then simple fasting. Mention a gemstone only because they asked, "
               "and only for a strong functional benefic or the Lagna lord after checking the running dasha, as a "
               "trial period with a plain way to stop (never as a requirement); never suggest a Rahu, Ketu or "
               "Saturn stone, and do not recommend paid pujas or rituals.")
LEGAL_NOTE = ("The user asks about a legal matter. Do not predict a verdict, win or loss. You may describe "
              "general timing themes (periods of effort, delay or settlement) in plain words and must say "
              "they should consult a qualified lawyer.")
MINOR_NOTE = ("The native is under 18. Treat career and education only as natural aptitude and interests, "
              "never as predicted outcomes (no exam results, admissions, jobs or income). No marriage, romance, "
              "health or longevity content.")


def context_note(text: str, *, minor: bool = False) -> str:
    """Extra instruction for the model on turns that need a safety posture
    rather than an intercept. Empty when none applies."""
    notes = []
    if _REMEDY.search(text or ""):
        notes.append(REMEDY_NOTE)
    if _LEGAL.search(text or ""):
        notes.append(LEGAL_NOTE)
    if minor:
        notes.append(MINOR_NOTE)
    return " ".join(notes)
