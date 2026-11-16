# Licensing notes — read before deploying

This app combines components with strong copyleft licenses. **Do not assume a closed-source commercial launch is permitted.**

| Component | License | Impact |
|---|---|---|
| PyJHora 5.0.0 (chart engine) | **AGPL-3.0** | Serving this app over a network makes PyJHora's terms apply to the combined work — you must offer the app's source (including your backend) to its users. |
| OpenJyotish (architecture reference only) | GPL-3.0 | We studied its pipeline design but copied no code — GPL obligations attach only if you reuse its code. |
| Swiss Ephemeris (via pyswisseph) | AGPL-3.0 **or** paid commercial license | AGPL requires source disclosure; a commercial Swiss Ephemeris license is the alternative for proprietary deployment. |
| This project's code | choose a compatible license | AGPL-3.0 is the path of least resistance. |

## Practical guidance

- **Internal / personal use or open-sourced AGPL-3.0 release**: current setup is fine as-is.
- **Proprietary commercial product**: you would need (a) a commercial Swiss Ephemeris license and (b) a chart engine without copyleft terms, or a separate unbundled AGPL service boundary — get real legal advice.
- The app's own text, prompts, and UI are yours; classical texts (BPHS etc.) are public-domain translations — keep citations accurate and do not fabricate them (the verifier rejects invented citations).
