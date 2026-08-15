# Flurp V1 — Pre-IPO executive signal prototype

## Product decision

Flurp V1 identifies senior leaders and material pre-IPO shareholders disclosed
in public DRHP/RHP documents, ranks their *research priority*, and lets an
operator review enrichment and outreach. It does **not** claim to know which
individuals received a fresh IPO allocation.

The operator remains responsible for confirming every identity and approving
every message. No external email, LinkedIn, or enrichment API is called in V1.

## In scope

1. Upload a DRHP or RHP PDF with issuer and filing-date metadata.
2. Keep the original document, extracted text, SHA-256, and extraction time.
3. Add a candidate manually with a source page and quoted evidence.
4. Rank candidates using disclosed pre-IPO shares, role seniority, document
   type, and freshness. Show the calculation instead of hiding it behind AI.
5. Record an externally enriched profile only after operator review.
6. Draft, approve, send-log, and reply-track outreach manually.

## Explicit exclusions

- Automated or bulk email sending.
- Automated Apollo calls or LinkedIn scraping.
- Inferring allocation, wealth, or investment intent from incomplete filings.
- Using a contact with unresolved or conflicting identity evidence.
- Any claim that ranking is financial advice or a suitability assessment.

## Source and field contract

| Field | Required | Origin | Rule |
| --- | --- | --- | --- |
| Issuer, filing date, document type | Yes | Operator + source PDF | DRHP/RHP only in V1. |
| Candidate name, role | Yes | Quoted PDF evidence | Store page number and verbatim quote. |
| Pre-IPO shares / option count | Optional | Quoted PDF evidence | `null` is valid; never invent or estimate it. |
| Exercise/allotment price | Optional | Quoted PDF evidence | Preserve the value and its label; do not treat options as liquid shares. |
| Work email / LinkedIn | Optional | Operator-reviewed enrichment | Must have match evidence; no auto-send. |
| Outreach / reply state | Yes after a draft exists | Operator | Audit every state change and timestamp. |

## V1 ranking

`score = share score (0–55) + role score (0–25) + freshness score (0–15) + RHP score (0–5)`.

The score is a work queue, not a measure of wealth or likelihood to buy. A
candidate without disclosed shares may still be retained but gets no share
score. The score and its inputs must be visible in every lead record.

## Acceptance criteria

- Process 30 recent documents manually or via upload.
- At least 20 candidate records have page-level documentary evidence.
- Identity matching is manually audited before use; no automated outreach
  occurs until the process demonstrates at least 95% precision on a labelled
  sample of 100 candidates.
- “Fresh” means the filing date is within 72 hours. Older records are visibly
  marked stale and excluded from automated sequencing in future versions.
