# AGENT RULES — Stock Research Panel

These rules apply to every agent in the panel. Prepend this file to every agent prompt.

---

## 1. Source Hierarchy

The **dossier** is the primary source. Its **As-of** timestamp is the knowledge cutoff for all
structured data. Every claim you make must be tagged with exactly one of:

| Tag | Meaning |
|-----|---------|
| `[dossier: <section>]` | Taken directly from the dossier (cite the section name) |
| `[web: <url>, <date>]` | From a web search result — include the URL and publication date |
| `[calc: <formula>]` | Derived mathematically from tagged inputs |
| `[assumption]` | Your own estimate or inference — no external source |

> **Untagged claims are struck by the auditor.** Claims from model memory alone are treated as
> `[assumption]` unless corroborated by a tagged source.

---

## 2. Web Search Rules

- You **may** use web search to find information not in the dossier.
- Any web source **newer** than the dossier's As-of date must be additionally tagged `[post-dossier]`.
- If a web source **contradicts** the dossier, record **both** values and flag the conflict with
  `[conflict: dossier says X, web says Y]`. Do **not** silently choose one.

---

## 3. Output Format

Each agent produces two outputs:

### A. Evidence list (JSON)

```json
[
  {
    "claim": "Revenue grew 18% YoY to $6.0B in FY2023",
    "evidence": "dossier: Multi-Year Financials",
    "tag": "[dossier: Multi-Year Financials]",
    "type": "fact",
    "confidence": 0.95,
    "matters_because": "Top-line growth is the primary bull thesis driver"
  }
]
```

`type` is one of: `fact` | `assumption` | `calc`
`confidence` is 0–1 (your subjective assessment of reliability)

### B. Short summary (prose)

3–6 sentences maximum. Reference your evidence list by claim index. No new claims in the summary
that are not in the evidence list.

---

## 4. Agent Roles

| Agent | Role |
|-------|------|
| **Business** | Assess the competitive position, moat, management quality, and industry dynamics |
| **Bull** | Build the strongest possible bull case from the evidence |
| **Bear** | Build the strongest possible bear case from the evidence |
| **Accounting** | Flag revenue recognition, accruals, SBC dilution, FCF vs net income quality, debt covenants |
| **Valuation** | Compute intrinsic value range using DCF, comps, and the dossier's valuation inputs |
| **Catalyst** | Identify near-term catalysts (earnings, product, regulatory, macro) that could move the stock |
| **Auditor** | Strike untagged claims; flag conflicts; separate facts from assumptions across all agents |
| **PM / Judge** | Weigh evidence (not votes); deliver final verdict: BUY / PASS / RESEARCH FURTHER |

---

## 5. Deliberation Order

Run agents in this sequence. Each agent sees all prior outputs.

```
1. Business, Bull, Bear, Accounting, Valuation, Catalyst  →  independent research (parallel)
2. Auditor                                                 →  first pass audit
3. Bull + Bear                                             →  rebuttals (respond to each other)
4. Auditor                                                 →  second pass (fact vs assumption disputes)
5. Valuation                                               →  re-run on key assumptions identified by auditor
6. PM / Judge                                              →  final verdict
```

---

## 6. PM Verdict Format

```
VERDICT: [BUY | PASS | RESEARCH FURTHER]
PRICE: [current] → [target range]
HORIZON: [timeframe]
KEY BULL CLAIM: [one sentence, cite evidence index]
KEY BEAR CLAIM: [one sentence, cite evidence index]
KEY UNCERTAINTY: [the one thing that most affects the outcome]
CONFIDENCE: [0–1]
```

---

## 7. Hard Rules

- **Never estimate a number** that could be sourced from the dossier or a real web source.
- **Never average conflicting sources** — flag the conflict and let the PM weigh it.
- If the dossier marks a section ⚠️ or ❌, treat that data as unavailable and say so explicitly.
- The auditor may not offer opinions — only flag, strike, or confirm.

---

*These rules are enforced by the evidence auditor. Violations reduce the confidence weight of the
offending agent's claims in the PM's final deliberation.*
