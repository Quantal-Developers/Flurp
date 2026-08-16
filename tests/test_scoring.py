from datetime import date, timedelta

from app import freshness_points, role_points, share_points


def test_share_score_is_visible_and_bounded() -> None:
    assert share_points(None) == 0
    assert share_points(1) == 10
    assert share_points(100_000) == 40
    assert share_points(1_000_000) == 55


def test_role_score_prioritises_seniority() -> None:
    assert role_points("Chief Financial Officer") == 25
    assert role_points("Vice President, Finance") == 18
    assert role_points("Finance Manager") == 10


def test_role_score_does_not_match_titles_as_substrings() -> None:
    assert role_points("Product Coordinator") == 5  # "coo" is a substring, not a word
    assert role_points("Doctoral Candidate") == 5  # "cto" is a substring, not a word


def test_old_filings_are_stale() -> None:
    score, stale = freshness_points("2020-01-01")
    assert score == 0
    assert stale is True


def test_today_is_fresh() -> None:
    score, stale = freshness_points(date.today().isoformat())
    assert score == 15
    assert stale is False


def test_72_hour_boundary_is_still_fresh() -> None:
    score, stale = freshness_points((date.today() - timedelta(days=3)).isoformat())
    assert score == 10
    assert stale is False


def test_past_72_hours_is_stale() -> None:
    score, stale = freshness_points((date.today() - timedelta(days=4)).isoformat())
    assert score == 0
    assert stale is True
