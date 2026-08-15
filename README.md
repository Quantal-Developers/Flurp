# Flurp — Pre-IPO executive signal prototype

Flurp is an evidence-first local prototype for researching executives and
material shareholders disclosed in public DRHP/RHP filings. It ranks research
priority and records human-reviewed enrichment and outreach state.

It is **not** an automatic prospecting sender, does not scrape LinkedIn, does
not call Apollo, and does not claim to know individual IPO allocations.

Read [the V1 scope and data contract](docs/v1-scope-and-data-contract.md)
before adding integrations or automation.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>. The prototype stores its SQLite database under
`data/` and PDFs under `uploads/`; both are ignored by Git.

## Workflow

1. Upload one DRHP/RHP PDF and record its filing date.
2. Add only candidates backed by a PDF page number and verbatim quote.
3. Review any enrichment evidence before adding contact details.
4. Create a draft, explicitly approve it, then log sent/replied/bounced/opted-out states.

The API never sends email. That integration needs a separately approved consent,
suppression, and mailbox-authentication design.

## Checks

```bash
pytest -q
python -m compileall -q app.py tests
```
