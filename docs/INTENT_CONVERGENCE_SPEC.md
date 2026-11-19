# JYOTISH AI — CALCULATION & MULTI-METHOD CONVERGENCE SPEC FOR ALL 61 INTENTS

(Transcribed from the user's pasted spec. Implement each template ONCE; each intent is configuration, not new code.)

Convergence makes answers consistent, traceable and harder to over-claim. It does not prove predictive accuracy. Do not show percentages. Every rule is a traditional rule and must exist in the rule pack with rule_id, version, source (BPHS, K.N. Rao Chara Dasha, Tajika Neelakanthi, KP Reader…) and unit tests. Rules marked (VERIFY) must stay DISABLED until a source check is recorded. Real-world performance is measured later by the L5 backtest harness.

## PART 1 — SHARED CONVERGENCE ENGINE

### 1.1 Pillar result values
S supportive (activation met, no dominant adverse) | M mixed (activation + significant adverse) | W weak (partial activation) | A adverse (adverse dominates) | NE not evaluated (module not implemented, inputs missing e.g. Mode B without birth time, or rule disabled).
Each result carries Evidence[] (rule_id, fact_ids, direction, weight, depends_on_factors[]) and the time interval it applies to.

### 1.2 Factor de-duplication
Each evidence item lists underlying factors ("PLANET:VENUS","HOUSE:7","LORD:H7","MOON_NAKSHATRA","LAGNA_SIGN"). A pillar counts toward convergence ONLY IF at least one SUPPORTIVE evidence item uses a factor no higher-priority pillar already counted (priority P1>P2>P3>P4). Otherwise show "S (dependent — shares factors with P1)" and it does NOT add to n. Vimshottari and Yogini both depend on MOON_NAKSHATRA → one P1 signal.

### 1.3 Natal promise gate (Stage 0, every timing intent)
Score for event houses E:
- E-lord strength: +1 Shadbala ratio ≥1.0 or Vimshopaka ≥10; −1 ratio <0.8 and debilitated without Neecha Bhanga.
- E-lord dignity D1: +1 exalted/moolatrikona/own/friend sign; −1 debilitated/enemy/combust.
- E-house condition: +1 benefic occupation/aspect, SAV(E) ≥28; −1 only malefic influence, SAV(E) <25.
- Varga V confirmation: +1 D1 E-lord in kendra/trikona of V or vargottama; −1 in 6/8/12 of V.
- Karaka K: +1 strong & well placed in D1 and V; −1 debilitated/combust/6-8-12.
- Yogas: +1 relevant supportive yoga (classical conditions met); −1 relevant denial combination (rule pack).
Promise = STRONG (≥+3), MODERATE (0..+2), WEAK (<0). WEAK caps final output at "weak_indication". Score and evidence always stored.

### 1.4 TIMING TEMPLATE T(E,K,V,J,TAJ,TRIG,KP)
ADV (adverse houses) = 12th from each house in E (computed in code). A planet "links to house h" if: L1 lords h; L2 occupies h; L3 aspects h (graha drishti); L4 conjunct with / aspects lord of h; L5 its nakshatra lord lords or occupies h; L6 occupies sign owned by lord of h. Each link type is a separate evidence item. Count from Lagna (primary) and Moon (secondary, weight 0.5).

P1 Parashari (Vimshottari MD→AD→PD + varga + double transit), for every AD in range and its PDs:
1 Activation: AD lord links to E (required); MD lord or PD lord also links to E (≥1).
2 Varga: AD lord in V sits in kendra/trikona from V-Lagna OR links to corresponding E-house of V.
3 MD–AD relationship: 1/7,3/11,4/10,5/9,1/1 clean; 2/12 or 6/8 friction (→MIXED).
4 Double transit (K.N. Rao): in same window transiting Jupiter AND Saturn each occupy or aspect primary E-house OR sign of E-lord, from Lagna (Moon secondary).
5 Adverse: AD lord's links to ADV outweigh links to E (weighted).
6 Yogini cross-check (same factor, dependent): Yogini lord links to E — adds evidence weight only, never a pillar.
Result: S = items 1,2,4 and no adverse dominance; M = item 1 + friction/adverse; W = item 1 only; A = adverse dominates. Window = PD (or AD) interval ∩ double-transit interval.

P2 Jaimini (Chara Dasha per configured chara_dasha_school + karakas + arudhas + Rashi Drishti), for each Chara MD sign and AD signs:
1 Dasha sign as temporary Lagna: activation if the E-house counted from the dasha sign (7th marriage, 10th career) is OCCUPIED or RASHI-ASPECTED by any J point or the D1 E-lord.
2 Alt: dasha sign contains or rashi-aspects the primary Jaimini karaka in J.
3 Transit support: transiting Jupiter occupies or rashi-aspects dasha sign or relevant arudha in J.
4 Adverse: dasha sign is 6/8/12 from relevant arudha, or holds malefics without benefic rashi-aspect (VERIFY wording vs K.N. Rao).
S = (1 or 2)+3; M = (1 or 2)+adverse; W = (1 or 2) only; A = adverse only. Window = AD-sign interval.

P3 Tajika (annual chart) + Triple Sudarshana, each year:
1 Varsha Pravesha chart (exact sidereal solar return).
2 Annual E-house: annual E-lord strong (Pancha-vargiya bala) AND Ithasala with Varsha Lagna lord or Varsheshwara.
3 Muntha: supportive if in E or in 1,2,3,5,9,10,11 with strong lord; adverse if in 4,6,7,8,12 with weak lord (VERIFY vs Tajika Neelakanthi). Intent override: Muntha in E-house supportive.
4 Varsheshwara links to annual E-house.
5 Mudda Dasha: periods of planets linked to annual E-house give month-level windows.
6 Triple Sudarshana: for each of Lagna, Moon, Sun, year's progressed sign "active" if equal to E counted from that reference OR contains/aspected by D1 E-lord or karaka in K. Score 0–3.
S = item 2 AND (Muntha supportive OR Sudarshana ≥2); M = item 2 with adverse Muntha; W = only one of items 2–6; A = adverse Muntha + weak annual E-lord + Sudarshana 0. Window = solar-return year (Mudda inside).

P4 Micro-timing (Ashtakavarga + Kakshya + fast transits + nakshatra), inside windows from P1–P3:
1 Dates trigger planet p in TRIG transits primary E-house sign / D1 E-lord sign / karaka sign.
2 Ashtakavarga: p's own BAV in that sign ≥4 support, ≥5 strong; SAV(E-house) ≥28 raises weight; BAV ≤2 adverse.
3 Kakshya: narrow to weeks when p is in a 3°45′ Kakshya whose lord contributed a bindu in p's BAV for that sign.
4 Fast triggers: Mars or Sun transiting/aspecting E-house or E-lord gives month-level triggers.
5 Transit over natal nakshatra of E-lord or karaka — supportive Tarabala per rule pack.
S = 1+2(≥4)+3; W = 1+2 only; A = BAV ≤2 for every trigger planet. Window = weeks/months.

KP (separate frame, reported separately, NOT counted in n/4): if enabled and birth time known: (1) cusp sub-lord of primary E cusp signifies the favourable set KP; (2) Dasha–Bhukti–Antara lords signify KP and don't predominantly signify negating set (12th from each KP house); (3) ruling planets at query time OPTIONAL labelled "horary". Report "KP: supportive / not supportive / not evaluated". Never adds to n.

Convergence output per window: n = number of pillars P1–P4 that are S and NOT dependent. Badge "Traditional convergence: n/4". Show "k of 4 methods evaluated" whenever any pillar is NE. Result type: supportive_period = n≥3 AND promise not WEAK AND no pillar A; mixed_period = n≥2 with at least one A or M; weak_indication = n≤1 OR promise WEAK; insufficient_data = ≤1 pillar evaluated. Narrowing order P1(years/months)→P2(months)→P3(year/Mudda months)→P4(weeks); report intersection only if non-empty, else P1 window with other pillars' status. Always keep supportive AND conflicting evidence.

### 1.5 NATAL TEMPLATE N(E,K,V,J)
Badge "Natal agreement: n/4": M1 D1 (E-house occupants, E-lord placement/dignity, aspects, relevant yogas); M2 Varga V (E-lord and karaka condition in V; V-Lagna and corresponding E-house of V); M3 Jaimini (J karaka sign/house/rashi-aspects; relevant arudha and its 2nd/7th/12th); M4 Strength (Shadbala, Vimshopaka of E-lord and karaka; Bhava Bala of E; SAV of E). Optional KP reported separately. De-duplicate as §1.2. Optional overlay "Is this theme active now?" = P1 for current MD/AD/PD.

### 1.6 Specificity gate (required per TIMING intent before release)
Run each timing intent on ≥1000 random charts × random 12-month windows; record how often supportive_period and the average share of each year marked supportive. Release rule (configurable): supportive_period on ≤25% of random windows. If fails, tighten rules (PD-level activation, stricter double transit); if still fails present as a "theme" not "timing". Publish firing rates in the coverage report.

## PART 2 — LOOKUP TABLES
### 2.1 Domain → varga
Wealth D2 (coarse; also D1 2/11, optional D11); Siblings/courage D3; Property/residence D4; Marriage D9; Career D10; Children D7; Parents D12; Vehicles/comforts D16; Spirituality D20; Education D24; Disputes/health themes D6 (D30 optional); General karmic D60 (only when its stable window ≥ birth-time uncertainty).
### 2.2 Jaimini points
Self AK/AL; Career AmK/A10; Siblings BK/A3; Mother-home MK/A4; Children-education PK/A5; Relatives-disputes-health GK/A6; Spouse DK/UL(A12),A7; Wealth A2; Fortune-father A9; Gains A11; Expenses-foreign A12.
### 2.3 Natural karakas
Father Sun; Mind/mother Moon; Property/land/siblings/courage Mars; Intellect/commerce/education Mercury; Wealth/children/wisdom Jupiter; Spouse/vehicles/comforts Venus (Jupiter for women's marriage per configured tradition); Service/career endurance/foreign Saturn; Foreign/unconventional Rahu; Separation/spirituality Ketu; 10th house: Sun, Mercury, Jupiter, Saturn.
### 2.4 KP favourable house sets (enable ONLY rows VERIFIED against KP Reader)
Marriage 2,7,11; Love marriage 5,7,11; Service/job/promotion 2,6,10,11; Business 2,7,10,11; Foreign travel/residence 3,9,12; Education success 4,9,11; Competitive exam 6,11(+1); Property/house 4,11,12; Vehicle 4,11; Children 2,5,11; Litigation success 6,11(+1). All other matters: KP = NOT_EVALUATED.

## PART 3 — THE 61 INTENTS
Fields: [template] E houses | K karakas | V varga | J Jaimini | TAJ | TRIG | KP | SPECIAL | OUTPUT. ⭐ = Phase 1.

### A. CAREER
1 JOB_TIMING ⭐ [T] E:10,6,11(+2) K:Saturn,Sun,Mercury,AmK V:D10 J:AmK,A10 TAJ:annual 10th&6th; Muntha 10/11 TRIG:Jupiter,Saturn; Mars/Sun monthly KP:2,6,10,11. SPECIAL: first-job vs job-change clarification (first job ignores 12th/resignation logic); P1 requires AD lord link to 10 OR 6 plus D10 confirmation. OUT: candidate windows + supporting/conflicting evidence.
2 CAREER_PROMOTION ⭐ [T] E:10,11,2,6 K:Sun,Saturn,AmK V:D10 J:AmK,A10,AL TAJ:annual 10th lord strong + Ithasala with Varsha Lagna lord; Varsheshwara linked to 10 TRIG:Jupiter over 10/10th lord/A10, Saturn KP:2,6,10,11(+10th cusp sub-lord). SPECIAL: classify change: promotion (10+Sun), raise (2/11 dominant), internal role change (10 w/o 2/11), external switch (3/12 → route to #3). Year-limited: current/next solar-return year. OUT: type + window.
3 JOB_CHANGE ⭐ [T] E:10,3,12,6,11 K:Saturn,Rahu,AmK V:D10 J:AmK,A10 TAJ:annual 10th&12th; Muntha into 3/10/12 TRIG:Saturn,Jupiter,Rahu/Ketu sign changes KP:NE (VERIFY). SPECIAL: score "change"(3/12 links) vs "stability"(10/11 w/o 3/12) separately, present both; Dasha sandhi in window adds change evidence. OUT: balance + window.
4 GOVT_JOB [T+natal overlay] E:10,6,11 K:Sun,Saturn,Jupiter,AmK V:D10 J:AmK,A10 TAJ:annual 10th; Sun TRIG:Jupiter,Saturn,Sun KP:2,6,10,11+Sun (VERIFY). SPECIAL: natal gate adds government check: Sun strong (Shadbala ≥1) or linked to 10/10th lord in D1 AND D10; 6th = competitive exams. OUT: natal inclination + exam/selection window; no guarantee.
5 CAREER_SUITABILITY [N] E:10,1,5(+2/11) K:AmK,10th lord,strongest planet linked to 10 V:D10 J:AmK,A10,AK karakamsha. SPECIAL: rank planet signatures: 10th lord's navamsa dispositor (VERIFY Phaladeepika/Saravali); planets in/aspecting 10th in D1 and D10; AmK; planets in/aspecting karakamsha. Map top 2–3 planets to profession families via rule table. OUT: 2–3 domains with methods; never single "destined" job.
6 JOB_VS_BUSINESS ⭐ [N+optional T] E:6 vs 7, shared 10,11 K:Mercury,Saturn,AmK V:D10 J:A7,A10. SPECIAL: SERVICE score (6/10 links, Saturn) vs ENTERPRISE score (7/10/11 links, Mercury, strong 3rd) in each of M1–M4; optional P1 overlay. OUT: comparative balance; hybrid allowed.
7 CAREER_STAGNATION [N+current P1] E:10,11 K:Saturn,Sun,AmK V:D10 J:AmK,A10. SPECIAL: explain via weak/afflicted 10th lord; current MD/AD lords linking to ADV (9,10); malefic transits over 10/A10 (Saturn,Rahu); Sade Sati; show next supportive period from T. OUT: themes + next window.
8 JOB_DISRUPTION [T adverse] E(adverse):9,5,12,8 K:Saturn,Rahu,Mars V:D10 J:A10,AmK TRIG:Saturn,Rahu/Ketu over 10/A10, Mars KP:NE. SPECIAL: run T with E inverted; output only "periods of elevated change/pressure", phrased as preparation never certain job loss; require n≥3. OUT: pressure windows + protective factors.

### B. MARRIAGE & RELATIONSHIPS
9 MARRIAGE_TIMING ⭐ [T] E:7,2,11 K:Venus(Jupiter per tradition),DK V:D9 J:DK,UL,A7 TAJ:annual 7th lord + Ithasala with Varsha Lagna lord; Venus strong; Muntha in 7 SUPPORTIVE TRIG:Jupiter over 7/7th lord/UL/Venus, Saturn KP:2,7,11 (negate 1,6,10). SPECIAL: P1 AD lord links to 7 or 7th lord AND in D9 links to D9 7th or D9 Lagna; natural significators: planets in/with 7th lord, Venus, DK, UL lord. P2 (K.N. Rao): Chara AD sign or 7th from it holds/rashi-aspected by DK, UL or UL lord. Ignore windows before legal marriage age. Ask relationship-status clarification. OUT: 1–3 candidate windows with n/4; never exact date.
10 LOVE_VS_ARRANGED [N] E:5↔7; 9/2 K:Venus,Mars,Rahu,DK V:D9 J:DK,UL,A5,A7 KP:5,7,11 (VERIFY). SPECIAL: LOVE: 5th lord↔7th lord link (conj/exchange/mutual aspect) in D1 AND D9; Venus–Mars link; Rahu on 5/7; DK linked to 5th. ARRANGED: 7th lord linked to 2/9/4 with no 5–7 link. Compare across M1–M4. OUT: balance as traditional tendencies.
11 MARRIAGE_DELAY [N+T] E:7,2,11 K:Venus,Saturn,DK V:D9 J:DK,UL. SPECIAL: delay factors: Saturn linked to 7/7th lord/Venus/UL; 7th lord in 6/8/12 or debilitated (check Neecha Bhanga); Venus combust/debilitated; 7th lord weak in D9; current dasha lords not linked to 7. Then run #9 for next window. OUT: themes + next window; no fatalistic language.
12 COMPATIBILITY [special, CONSENT REQUIRED] badge "Compatibility methods agreeing: n/4": M1 Ashtakoota /36 with each koota and documented exceptions (Nadi/Bhakoot cancellations per rule pack); M2 Mangal Dosha both charts with cancellations and mutual cancellation; M3 cross-links: Moon–Moon and Lagna–Lagna not 6/8; each 7th lord/Venus to partner's Lagna/Moon; D9 Lagna relationship; DK of one on other's Lagna/UL; M4 Dasha alignment: neither in strongly 7-ADV-linked period during planned marriage window; overlapping supportive periods. OUT: per-method; never "doomed".
13 MARRIAGE_STABILITY [N+current P1] E:7,2,4,12,8 K:Venus,Moon,DK V:D9 J:UL, 2nd from UL, A7. SPECIAL: Jaimini sustenance (VERIFY Jaimini Sutras): benefics in/aspecting 2nd from UL support continuity; malefics without benefic influence = strain; combine with 7th lord & Venus in D1/D9; P1 overlay flags strain periods (AD lord linked to 12 or 6 from 7). OUT: strengths + watch periods; never predict divorce.
14 RECONCILIATION [T restricted] E:7,11,5,2 K:Venus,DK V:D9 J:DK,A7 KP:NE. SPECIAL: user's own chart only; never infer other person's feelings; require n≥3; always include agency language. OUT: periods favouring reconnection/communication.
15 SPOUSE_NATURE [N] E:7 K:Venus,DK V:D9 J:DK(sign,nakshatra,navamsa),UL(sign,lord). SPECIAL: traits from 7th sign & occupants, 7th lord sign/dignity, DK nature, UL sign/lord, D9 7th; report themes in ≥2 methods; no physical-appearance or caste/community claims. OUT: 3–5 traits with methods.
16 RELATIONSHIP_CHALLENGES [N] E(adverse):6,8,12 from Lagna AND from 7th K:Venus,Mars,Saturn,Rahu/Ketu,DK V:D9 J:UL, 2nd from UL, A7. SPECIAL: malefics in 7 w/o benefic aspect; 7th lord in 6/8/12 (D1,D9); afflicted UL/2nd from UL; Mangal Dosha after cancellations; theme only if ≥2 methods agree; pair with protective factors. OUT: themes + protective factors; never predetermined divorce.

### C. MONEY, BUSINESS, FINANCE
17 INCOME_IMPROVEMENT ⭐ [T] E:11,2,10 K:Jupiter,Venus,Mercury V:D2(coarse)+D10 J:A11,A2 TAJ:annual 11th&2nd; Muntha 2/11 TRIG:Jupiter over 2/11/11th lord/A11, Saturn KP:2,6,11 (VERIFY). SPECIAL: Dhana yoga lords in MD/AD raise weight. OUT: windows + likely source theme.
18 WEALTH_POTENTIAL ⭐ [N] E:2,11,5,9(+1) K:Jupiter,Venus V:D2(+D11 optional) J:A2,A11,AL (11th from AL gains; 12th from AL expenses). SPECIAL: Dhana yogas (links between lords of 1/2/5/9/11 with classical conditions); Lakshmi yoga (VERIFY); SAV of 2 and 11 vs 12; Jaimini benefics in 11th from AL vs 12th. OUT: wealth-building style (earning/saving/inheritance/enterprise) with methods.
19 BUSINESS_START [T+Muhurta] E:7,10,11(+3) K:Mercury,Jupiter V:D10 J:A7,A10,AmK TAJ:annual 7/10/11 TRIG:Jupiter,Saturn,Mercury (direct preferred) KP:2,7,10,11. SPECIAL: after window found optionally run #58. OUT: window + optional Muhurta.
20 BUSINESS_PARTNERSHIP [N+T; partner chart with CONSENT] E:7,11,10,8 K:Mercury,Venus V:D10(+D9) J:A7 KP:7,11(+2)(VERIFY). SPECIAL: own-chart 7th check; with consent cross-chart links (each 7th lord to other's Lagna/11th) and Dasha alignment (#12 M4). OUT: indications + timing; not business/financial advice.
21 DEBT_RELIEF [T] E:6 adverse; relief = 5,11,2 K:Jupiter,Saturn V:D2(+D6) J:A6,A11 TRIG:Jupiter over 11/2; Saturn leaving 6/12/2 KP:NE. SPECIAL: compare accumulation (2/11) vs expenditure (12) per AD. OUT: easing + pressure windows.
22 FINANCIAL_COMMITMENT [T] E:2,11,5,8 K:Jupiter,Mercury V:D2 J:A2,A11 TAJ:annual 2/11 TRIG:Jupiter,Saturn KP:NE. SPECIAL: flag strong 8/12 activation as "caution"; mandatory not-financial-advice line. OUT: supportive/caution windows.
23 FINANCIAL_DISRUPTION [T adverse] E(adverse):12,8,10,1 K:Saturn,Rahu,Mars V:D2 J:12th from AL,A12 TRIG:Saturn/Rahu over 2/11 or lords. SPECIAL: n≥3 for "elevated"; pair with protective factors. OUT: caution windows.
24 LEGAL_DISPUTE [T] E:6,11,1; adverse 7,12,8 K:Mars,Saturn,Jupiter V:D6 J:A6,GK KP:6,11(+1)(VERIFY). SPECIAL: compare self/6th/11th strength vs 7th (opponent); AD lords linked to 6/11 favourable; 7/12 dominance unfavourable. OUT: favourable/unfavourable windows; no verdict; not legal advice.

### D. EDUCATION
25 STUDY_FIELD ⭐ [N] E:4,5,9(+10) K:Mercury,Jupiter V:D24 J:PK,A5,karakamsha. SPECIAL: rank planet signatures linked to 4/5/9 in D1,D24 and karakamsha; map to subject families; fields found in ≥2 methods; cross-reference #5. OUT: 2–3 fields.
26 COLLEGE_ADMISSION [T] E:4,9,11,5 K:Mercury,Jupiter V:D24 J:A5,PK TAJ:annual 4/9 TRIG:Jupiter over 4/9/5 or lords KP:4,9,11. SPECIAL: limit to admission cycle given. OUT: window + reminder admission depends on criteria/effort.
27 COMPETITIVE_EXAMS ⭐ [T] E:6,11,5,9,4 K:Mercury,Jupiter,Mars V:D24 J:A6,A5,PK TAJ:annual 6/11 TRIG:Jupiter,Saturn; Mercury direct/retro noted KP:6,11(+1)(VERIFY). SPECIAL: month-level via P1 PD + P4; never predict scores. OUT: supportive months, preparation framing.
28 STUDY_ABROAD [N+T] E:9+12+4 K:Rahu,Jupiter,Saturn V:D24(+D4) J:A12,A9 KP:(3,9,12)∩(4,9,11)(VERIFY). SPECIAL: natal "foreign" signature (9th/12th lords linked; Rahu on 9/12; 12th lord in 9) AND education promise; then T. OUT: indication + window.
29 HIGHER_STUDIES [N] E:9,5,8,12 K:Jupiter,Mercury,Ketu,Saturn V:D24 J:A5,A9,karakamsha. SPECIAL: research signature (8th links + Ketu/Saturn) reported separately from general higher-learning. OUT: themes.
30 RESUME_EDUCATION [T] E:4,5,9 K:Mercury,Jupiter V:D24 J:A5 TRIG:Jupiter over 4/5/9 or lords KP:4,9,11. OUT: windows.

### E. FOREIGN / RELOCATION (travel, temporary residence, overseas job, permanent settlement are SEPARATE outcomes)
31 FOREIGN_TRAVEL ⭐ [T] E:12,9,3 K:Rahu,Saturn,Moon V:D4(D9 optional) J:A12,A9 TAJ:annual 9/12; Muntha 9/12 TRIG:Rahu/Ketu axis on 9/12/3, Jupiter, Saturn KP:3,9,12. OUT: short-term travel windows.
32 FOREIGN_SETTLEMENT ⭐ [N+T] E:12,4(adverse),9,7(VERIFY) K:Rahu,Saturn V:D4 J:A4,A12,12th from AL KP:3,9,12 with 4 not dominant (VERIFY). SPECIAL: natal settlement signature: 4th lord in 12 or linked to 12; 12th lord in 4; Rahu/Saturn on 4; afflicted 4th with strong 12th; in D4 4th lord in 12 or 12th-lord link. Require signature in BOTH D1 and D4 before reporting "settlement"; timing via T with E=12,4(adverse),9. OUT: settlement vs temporary-stay + windows.
33 FOREIGN_CAREER [N+T] E:10∩12,6,9 K:Saturn,Rahu,AmK V:D10(+D4) J:AmK,A10,A12 KP:(2,6,10,11)∩(3,9,12)(VERIFY). SPECIAL: requires career activation (#1/#3) AND foreign activation (#31) in SAME window. OUT: overseas-career windows.
34 CITY_RELOCATION [T] E:3,4,12 K:Moon,Mars,Saturn V:D4 J:A4,MK TRIG:Saturn/Rahu over 4 or lord; Jupiter KP:NE (VERIFY). OUT: windows.
35 RETURN_HOME [N+T] E:4 (12 receding),9 K:Moon,Mars V:D4 J:A4. SPECIAL: activation of 4 and lord must outweigh 12 in P1; Rahu/Ketu axis moving off 12/4 supportive. OUT: windows + balance.
36 VISA_TIMING [T] E:9,12,11 K:Rahu,Jupiter,Sun V:D4(+D9) J:A12,A9 TRIG:Jupiter over 9/11/12; Rahu axis KP:3,9,12+11 (VERIFY). SPECIAL: month-level only; outcome rests with authorities. OUT: supportive filing windows.

### F. PROPERTY / VEHICLES
37 PROPERTY_PURCHASE ⭐ [T] E:4,11,2,12(supportive for purchase) K:Mars,Venus,Moon,Saturn V:D4 J:A4,MK TAJ:annual 4/11; Muntha 4/11 TRIG:Jupiter over 4/4th lord/A4; Saturn; Mars monthly KP:4,11,12. SPECIAL: natal gate includes D4 4th lord strength and Mars condition. OUT: windows.
38 PROPERTY_SALE [T] E:3,11,7,12 K:Mars,Venus,Mercury V:D4 J:A4,A11 KP:NE (VERIFY). OUT: windows.
39 INHERITANCE [N] E:8,2,4,9 K:Jupiter,Saturn,Sun V:D4(+D12) J:A8,A4,A9. SPECIAL: 8th lord linked to 2/11; benefics in 8; 4th/9th lords linked to 8; report only if ≥2 methods agree. OUT: themes only; never legal entitlement.
40 HOUSE_CONSTRUCTION [T+Muhurta] E:4,12,11 K:Mars,Saturn,Venus V:D4 J:A4 TRIG:Mars,Jupiter,Saturn KP:4,11,12 (VERIFY). SPECIAL: optional #58 construction Muhurta (bhoomi pujan rules in rule pack). OUT: windows + Muhurta.
41 VEHICLE_PURCHASE [T+Muhurta] E:4,11,2 K:Venus V:D16 J:A4 TRIG:Venus,Jupiter KP:4,11. SPECIAL: short-horizon → P1 PD + P4; optional #58. OUT: windows + Muhurta.

### G. CHILDREN & FAMILY (no conception/pregnancy/miscarriage/medical predictions; themes only)
42 PARENTHOOD [N + optional T] E:5,9,11,2 K:Jupiter,PK V:D7 J:PK,A5 KP:2,5,11 (timing only if user asks). SPECIAL: classical progeny rules (VERIFY BPHS); Jupiter condition and D7 Lagna/5th; never state infertility or number of children. OUT: themes + optional supportive periods + medical-information disclaimer.
43 FAMILY_TENSION [N+current P1] E:2,4,7,11 K:Moon,Mars,Saturn,Rahu V:D12,D4 J:A2,A4,GK. SPECIAL: AD lord links to 6/8/12 from 2 and 4; malefic transits over 2/4/Moon; Sade Sati. OUT: themes + when period changes.
44 PARENTS_RESPONSIBILITY [N] E:4 (mother),9 (father; 10 per lineage configurable VERIFY) K:Moon,Sun,MK V:D12 J:MK,A4,A9. OUT: themes with configured father-house convention shown.
45 SIBLINGS [N] E:3,11 K:Mars,BK V:D3 J:BK,A3,A11. OUT: themes.
46 CHILD_SUPPORT [N; child's chart with guardian CONSENT] E(parent):5; E(child optional):4,5,9 K:Jupiter,Mercury V:D7(parent),D24(child) J:PK,A5. SPECIAL: encouragement themes; no deterministic claims. OUT: supportive suggestions.

### H. WELL-BEING (no diagnosis; route distress to support + crisis resources)
47 STRESS_PHASE [current-period context only]: Moon condition; Lagna lord; 4th, 6th/12th activation by current MD/AD; Saturn/Rahu transits over Moon/Lagna/4th; Sade Sati (#48). No convergence badge. Context + practical coping suggestions. No medical/psychological cause claims. If distress, switch to supportive mode with crisis resources (India: Tele-MANAS 14416).
48 SADE_SATI ⭐ [deterministic astronomy, no convergence]: transiting Saturn sidereal ingress/egress dates for 12th from natal Moon sign (phase 1), Moon sign (phase 2), 2nd from it (phase 3); include retrograde re-entries; also Dhaiya/Ashtama Shani (4th/8th from Moon) if requested. Verify dates vs reference ephemeris (±1 day). Optional: Saturn BAV in each phase sign (≥4 milder). OUT: exact phases and dates; no fear-based language.
49 SELF_CARE_PERIODS [T restricted] E(adverse):6,8,12 with 1 K:Sun,Moon,Saturn V:D6(D30 optional) J:A6,GK TRIG:Saturn/Rahu over Lagna/Moon/Sun KP:NE. SPECIAL: optional Shoola Dasha only if implemented & verified; require n≥3 for "heightened self-care period"; mandatory disclaimer traditional indicators not medical advice. OUT: gentle self-care windows.
50 EMOTIONAL_SUPPORT [conversation-first]: supportive conversation + practical coping; if asked #47-style period context and when current AD/PD changes; crisis routing as #47.

### I. PERSONALITY, SPIRITUALITY, DOSHAS, REMEDIES
51 CHART_STRENGTHS [N] E:1 with Lagna lord, Moon, Sun K:AK V:D9,D1 J:AK,karakamsha,AL. SPECIAL: strongest 2–3 planets (Shadbala), confirmed yogas (classical conditions met), weakest areas (lowest SAV houses, afflicted lords); each item cites ≥2 methods. OUT: balanced strengths + challenges.
52 RECURRING_PATTERNS [N+current P1]: Lagna, Moon, 5th/7th, Rahu–Ketu axis, AK, current MD lord themes. OUT: possible themes as reflection questions, not hidden psychological facts.
53 SPIRITUAL_PATH [N] E:9,12,5,8 K:Jupiter,Ketu V:D20 J:AK, karakamsha and 12th from it (ishta-devata, VERIFY Jaimini Sutras/Rath), Ketu. SPECIAL: respect user's tradition; offer options, never prescribe. OUT: practice themes.
54 REMEDIES_GEMSTONES [N strict]: gemstones only for FUNCTIONAL BENEFICS (Lagna lord, trikona lords, yogakaraka) that are weak; NEVER for functional malefics or lords of 6/8/12 (VERIFY). Prefer low-cost practices: mantra, charity, conduct. Convergence: functional role + Shadbala strength + current dasha relevance + no contraindication — ALL FOUR must agree before mentioning a gemstone. OUT: options, no guaranteed effects, no expensive prescriptions.
55 YOGA_DOSHA_EXPLAINED [N]: for named yoga/dosha show exact rule and classical conditions; each condition met/not met; cancellations (Neecha Bhanga, Mangal Dosha); strength of planets; varga confirmation; whether the yoga's planets run a dasha in lifetime range. OUT: "basic" vs "classical conditions met" + traditional meaning + traditional activation dashas.

### J. GENERAL, TIMING & VERIFICATION
56 ANNUAL_THEMES ⭐ [multi-domain T light]: run T across all domains for next solar-return year: P1 houses current MD/AD/PD lords link to; P2 Chara AD sign's activated houses; P3 Varsha chart strongest houses, Muntha house, Varsheshwara houses, Mudda sequence; P4 major transits (Jupiter/Saturn/Rahu sign changes, Sade Sati) with BAV. Rank domains by n (de-duplicated). OUT: top 3 themes + 1 caution theme, month markers.
57 LIFE_TRANSITION [T structural]: markers: Vimshottari MD change within 24 months; Chara MD sign change; Saturn return; Jupiter return; Rahu/Ketu return or half-return; start/end Sade Sati; Sudarshana year reaching 1/4/7/10 from all three references. Convergence = count of independent markers in same 12-month span. OUT: marker count (not probability) + dates.
58 MUHURTA [Panchanga convergence] inputs: event type, location, date range. Per slot: (1) Panchanga shuddhi (Tithi, Vara, Nakshatra, Yoga, Karana per event type, rule pack, Muhurta Chintamani VERIFY); (2) Tarabala & Chandrabala from natal Moon; (3) Lagna shuddhi (muhurta Lagna & its 8th free of malefics; benefics in kendras); (4) avoid Rahu Kaal, Yamaganda, Gulika Kaal, Bhadra (Vishti), event exclusions. Badge "Muhurta factors satisfied: k/4". Top 3 slots with reasons/exclusions.
59 PAST_EVENT_CHECK ⭐ [retrospective T]: per user-entered event (date+type): map type to intent E/K/V/J; run P1–P4 for event date (historical dasha, Chara AD sign, Varsha chart of that year, transits on date) and KP separately. Rules FROZEN before user feedback shown; store results immutably. OUT: per event methods active as n/4; "consistent with", never proof.
60 BIRTH_TIME_CHECK ⭐ [rectification]: 1 stable windows per varga across ±15 min (or user range); 2 candidates = one representative time per distinct (D1,D9,D10,Moon pada) combo; 3 run #59 on user's ≥3 events; score = total n; 4 rank, report margin between top two, require clear lead (configurable, e.g. ≥2 events better explained) else "cannot distinguish"; 5 report dasha-balance difference. OUT: "consistent with window X" or "cannot distinguish"; never "verified".
61 CURRENT_DASHA ⭐ [N+P1/P2]: current Vimshottari MD/AD/PD with exact dates; per lord: houses ruled/occupied, dignity/strength, D9/D10 placement, nakshatra lord; cross-reference Yogini (same factor, cross-check) and Chara MD/AD signs with activated houses. OUT: plain-language themes, next change date, most-activated domains.

## PART 4 — IMPLEMENTATION CHECKLIST
1 Implement T, N and convergence/de-duplication ONCE; each intent = JSON config + optional SPECIAL hooks.
2 Every rule in the rule pack: rule_id, version, source citation, conditions, exceptions, tests. (VERIFY) items disabled until a source check is recorded.
3 Pillars return NE when module/input missing. Never fabricate a pillar.
4 KP computed separately, never adds to n.
5 Run specificity gate (§1.6) for every TIMING intent; publish firing rates.
6 Every user-facing number traces to engine fact IDs (verifier).
7 Tests per intent: hand-derived fixture charts; de-dup test (same planet P1 and P2 → P2 dependent); promise-gate cap test; NE-pillar test; safety-language tests for domains B, G, H.
8 Build order: Phase 1 (⭐) intents first; then T-based intents of same domains; then N-based; then Muhurta/compatibility/rectification extensions.
