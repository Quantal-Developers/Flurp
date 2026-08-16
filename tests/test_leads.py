from helpers import add_lead, make_pdf, upload


def test_lead_creation_requires_known_document(client) -> None:
    response = add_lead(client, "does-not-exist")
    assert response.status_code == 404


def test_lead_evidence_page_must_be_within_document(client) -> None:
    doc = upload(client).json()
    response = add_lead(client, doc["id"], evidence_page=99)
    assert response.status_code == 422
    assert "outside the source document" in response.json()["detail"]


def test_lead_evidence_page_equal_to_page_count_is_accepted(client) -> None:
    doc = upload(client).json()  # single-page PDF, so page_count == 1
    response = add_lead(client, doc["id"], evidence_page=doc["page_count"])
    assert response.status_code == 201


def test_lead_evidence_quote_must_appear_in_extracted_text(client) -> None:
    doc = upload(client).json()
    response = add_lead(client, doc["id"], evidence_quote="This sentence is nowhere in the filing.")
    assert response.status_code == 422
    assert "not found" in response.json()["detail"]


def test_lead_evidence_quote_match_tolerates_whitespace_and_case(client) -> None:
    """normalized_text() collapses whitespace/case so PDF line-wraps and case
    differences don't cause a false negative on an otherwise-genuine quote."""
    doc = upload(client).json()
    response = add_lead(
        client,
        doc["id"],
        evidence_quote="jane doe,   chief financial   officer, HOLDS 50000 shares.",
    )
    assert response.status_code == 201


def test_lead_creation_returns_score_breakdown(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    assert lead["score"] == sum(lead["score_breakdown"].values())
    assert lead["score_breakdown"]["role"] == 25  # Chief Financial Officer
    assert lead["score_breakdown"]["freshness"] == 15  # filed today
    assert lead["score_breakdown"]["rhp"] == 0  # DRHP, not RHP
    assert lead["stale"] is False
    assert lead["automatic_outreach_eligible"] is False


def test_lead_name_below_minimum_length_is_rejected(client) -> None:
    doc = upload(client).json()
    response = add_lead(client, doc["id"], name="J")
    assert response.status_code == 422


def test_lead_list_is_sorted_by_score_descending(client) -> None:
    doc = upload(
        client,
        content=make_pdf(
            "Jane Doe, Chief Financial Officer, holds 50000 shares. "
            "John Smith, Office Manager, holds no shares."
        ),
    ).json()
    low = add_lead(
        client,
        doc["id"],
        name="John Smith",
        role="Office Manager",
        evidence_quote="John Smith, Office Manager, holds no shares.",
    ).json()
    high = add_lead(client, doc["id"], disclosed_shares=1_000_000).json()  # Jane Doe, CFO, +55 share points

    ordered_ids = [item["id"] for item in client.get("/api/leads").json()]
    assert ordered_ids == [high["id"], low["id"]]


def test_lead_list_includes_source_document_fields(client) -> None:
    doc = upload(client).json()
    add_lead(client, doc["id"])
    leads = client.get("/api/leads").json()
    assert leads[0]["issuer"] == "Acme Ltd"
    assert leads[0]["document_type"] == "DRHP"


def test_enrichment_review_updates_lead(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()

    response = client.patch(
        f"/api/leads/{lead['id']}/enrichment",
        json={
            "email": "jane.doe@example.com",
            "linkedin_url": "https://www.linkedin.com/in/janedoe",
            "match_confidence": 0.87,
            "evidence": "LinkedIn profile lists Jane Doe as CFO of Acme Ltd.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "jane.doe@example.com"
    assert body["match_confidence"] == 0.87


def test_enrichment_review_requires_confidence_within_bounds(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()

    response = client.patch(
        f"/api/leads/{lead['id']}/enrichment",
        json={"match_confidence": 1.5, "evidence": "Confidence above the allowed range."},
    )
    assert response.status_code == 422


def test_enrichment_review_requires_existing_lead(client) -> None:
    response = client.patch(
        "/api/leads/does-not-exist/enrichment",
        json={"match_confidence": 0.5, "evidence": "Some evidence text goes here."},
    )
    assert response.status_code == 404


def test_outreach_creation_requires_existing_lead(client) -> None:
    response = client.post(
        "/api/leads/does-not-exist/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    )
    assert response.status_code == 404


def test_outreach_message_below_minimum_length_is_rejected(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    response = client.post(f"/api/leads/{lead['id']}/outreach", json={"message": "too short"})
    assert response.status_code == 422


def test_outreach_state_change_requires_existing_record(client) -> None:
    response = client.patch("/api/outreach/does-not-exist/state", json={"state": "approved"})
    assert response.status_code == 404


def test_outreach_state_change_rejects_unknown_state(client) -> None:
    doc = upload(client).json()
    lead = add_lead(client, doc["id"]).json()
    outreach = client.post(
        f"/api/leads/{lead['id']}/outreach",
        json={"message": "Hello, congratulations on the upcoming listing!"},
    ).json()
    response = client.patch(f"/api/outreach/{outreach['id']}/state", json={"state": "not_a_real_state"})
    assert response.status_code == 422
