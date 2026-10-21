from datetime import timedelta

from grokbot_bridge.rate_limit import RateLimiter
from tests.support import T0


def test_limit_is_per_user_and_expires_at_the_window_edge() -> None:
    now = {"t": T0}
    limiter = RateLimiter(2, timedelta(minutes=10), clock=lambda: now["t"])
    assert limiter.allow("100")
    assert limiter.allow("100")
    assert not limiter.allow("100")
    assert limiter.allow("200")
    now["t"] = T0 + timedelta(minutes=10)
    assert limiter.allow("100")
    assert "2 emails per 10 minutes" in limiter.denial_message()
