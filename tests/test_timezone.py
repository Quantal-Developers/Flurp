from datetime import date, datetime
from zoneinfo import ZoneInfo

import app as app_module


class FixedClock(datetime):
    """A datetime subclass whose now() always returns a fixed UTC instant,
    letting datetime.now(tz) below convert that instant into any zone."""

    fixed_utc_instant = datetime(2026, 8, 16, 20, 0, tzinfo=ZoneInfo("UTC"))

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_utc_instant.astimezone(tz) if tz else cls.fixed_utc_instant


def test_today_in_filing_timezone_follows_the_filing_zone_not_utc(monkeypatch) -> None:
    """20:00 UTC is 01:30 IST the following calendar day -- if the app fell
    back to a UTC (or other server-local) date instead of the configured
    filing timezone, a filing genuinely dated "today" in India would be
    rejected as future-dated for hours after IST midnight has already
    passed."""
    monkeypatch.setattr(app_module, "datetime", FixedClock)
    assert app_module.today_in_filing_timezone() == date(2026, 8, 17)
