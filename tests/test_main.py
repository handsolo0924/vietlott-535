import main


def test_validate_draw():
    assert main.validate_draw([1, 2, 3, 4, 35], 12)
    assert not main.validate_draw([1, 2, 3, 4, 4], 12)
    assert not main.validate_draw([0, 2, 3, 4, 5], 1)
    assert not main.validate_draw([1, 2, 3, 4, 5], 13)


def sample_draws(n=45):
    return [
        {"draw_id": i + 1, "draw_date": f"2026-01-{(i % 28) + 1:02d}",
         "main_numbers": sorted({((i * 3 + j * 7) % 35) + 1 for j in range(5)}),
         "special_number": (i % 12) + 1}
        for i in range(n)
    ]


def test_analytics_shape_and_counts():
    data = main.analytics_summary(sample_draws(20))
    assert data["draw_count"] == 20
    assert len(data["main_frequency"]) == 35
    assert len(data["special_frequency"]) == 12
    assert data["top_pairs"]
    assert len(data["gap_distribution"]) == 35


def test_feature_vector_and_target_dimensions():
    draws = sample_draws(25)
    assert len(main._feature_vector(draws)) == 35 * 3 + 1 + 12
    target = main._target_vector(draws[-1])
    assert len(target) == 35
    assert sum(target) == 5


def test_health_and_draws_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.sqlite"))
    main.save_draws([{
        "draw_id": 1, "draw_date": "2026-01-01",
        "main_numbers": [1, 2, 3, 4, 5], "special_number": 6,
        "source_url": "test"
    }])
    with TestClient(main.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["stored_draws"] == 1
        result = client.get("/api/draws?limit=10")
        assert result.status_code == 200
        assert result.json()["draws"][0]["main_numbers"] == [1, 2, 3, 4, 5]


def test_fetch_parser_skips_malformed(monkeypatch):
    class Response:
        text = '\n'.join([
            '{"id":1,"date":"2026-01-01","result":[1,2,3,4,5,6]}',
            '{"id":"bad","date":"oops","result":[1,2,3,4,5,6]}',
            'not-json'
        ])
        def raise_for_status(self): pass
    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: Response())
    rows = main.fetch_remote_draws(limit=10)
    assert len(rows) == 1
    assert rows[0]["draw_id"] == 1
