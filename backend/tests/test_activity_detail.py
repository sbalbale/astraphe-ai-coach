from app.dependencies import get_user_db


def test_activity_detail_missing_streams_short_cache_ttl(coach_client, fake_db, test_athlete_id):
    """
    When streams are missing (None), we should still return the combined payload and
    cache it only briefly so hydration doesn't get masked for 24h.
    """
    workout_id = "workout-123"

    # Seed only the minimal rows needed by the /detail endpoint.
    fake_db._table_seeds["activity_streams"] = []  # no row -> streams_payload=None
    fake_db._table_seeds["activity_laps"] = []
    fake_db._table_seeds["athletes"] = [
        {
            "id": test_athlete_id,
            "lthr": None,
            "threshold_hr": 170,
            "max_hr": 190,
            "resting_hr": 50,
            "hr_zone_method": "lthr",
        }
    ]
    fake_db._table_seeds["workouts"] = [
        {
            "id": workout_id,
            "athlete_id": test_athlete_id,
            "sport": "run",
            "intervals": [],
            "intervals_source": None,
            "splits_metric": [],
            "duration_seconds": 3600,
            "hr_zone_1_pct": 20,
            "hr_zone_2_pct": 50,
            "hr_zone_3_pct": 20,
            "hr_zone_4_pct": 10,
            "hr_zone_5_pct": 0,
        }
    ]

    # Capture the TTL used for the detail cache key.
    captured = {"ttl": None}

    class _FakeRedis:
        async def get(self, _key):  # type: ignore[override]
            return None

        async def setex(self, _key, ttl, _value):
            captured["ttl"] = ttl
            return True

        async def delete(self, _key):
            return 1

    # Patch redis getter inside the activity_detail module.
    import app.routers.activity_detail as activity_detail

    activity_detail.get_redis = lambda: _FakeRedis()

    # Ensure the route uses our seeded fake DB.
    from app.main import app

    app.dependency_overrides[get_user_db] = lambda: fake_db

    res = coach_client.get(f"/v1/activities/{workout_id}/detail")
    assert res.status_code == 200
    body = res.json()
    assert "streams" in body
    assert body["streams"] is None
    assert "zones" in body

    assert captured["ttl"] == 300

