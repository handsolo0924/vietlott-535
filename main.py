"""
Vietlott Lotto 5/35 Statistics API
Nguồn dữ liệu: open dataset https://github.com/vietvudanh/vietlott-data
(cập nhật hàng ngày, MIT license) — thay thế scraper trực tiếp vì Cloudflare.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import logging
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = os.getenv("DB_PATH", "vietlott.db")
DATA_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data/power535.jsonl"
HEADERS = {
    "User-Agent": "VietlottStats/2.0 (personal statistics dashboard; +https://github.com/vietvudanh/vietlott-data)"
}

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("vietlott535")

app = FastAPI(title="Vietlott 5/35 Statistics API", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draws (
            draw_id     INTEGER PRIMARY KEY,
            draw_date   TEXT NOT NULL,
            n1 INTEGER NOT NULL, n2 INTEGER NOT NULL, n3 INTEGER NOT NULL,
            n4 INTEGER NOT NULL, n5 INTEGER NOT NULL,
            special     INTEGER NOT NULL,
            source_url  TEXT NOT NULL,
            fetched_at  TEXT NOT NULL
        )
        """
    )
    return conn


def validate_draw(main: list[int], special: int) -> bool:
    if len(main) != 5 or len(set(main)) != 5:
        return False
    if any(n < 1 or n > 35 for n in main):
        return False
    if not (1 <= special <= 12):
        return False
    return True


def fetch_remote_draws(limit: int = 120) -> list[dict[str, Any]]:
    """Tải file NDJSON từ repo open-data và trả về tối đa `limit` kỳ mới nhất."""
    resp = requests.get(DATA_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
    records: list[dict[str, Any]] = []
    for line in reversed(lines):  # mới nhất trước
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            result = item.get("result") or []
            if not isinstance(result, list) or len(result) < 6:
                continue
            main = sorted(int(x) for x in result[:5])
            special = int(result[5])
            draw_id = int(item.get("id", 0))
            date_str = str(item.get("date", "")).strip()
        except (TypeError, ValueError, KeyError):
            logger.warning("Skipping malformed source record")
            continue
        if not validate_draw(main, special) or not draw_id or not date_str:
            continue
        records.append(
            {
                "draw_id": draw_id,
                "draw_date": date_str,
                "main_numbers": main,
                "special_number": special,
                "source_url": DATA_URL,
            }
        )
        if len(records) >= limit:
            break
    return records


def save_draws(draws: list[dict[str, Any]]) -> int:
    """Lưu batch để tránh mở/đóng connection nhiều lần."""
    if not draws:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            d["draw_id"],
            d["draw_date"],
            *d["main_numbers"],
            d["special_number"],
            d["source_url"],
            now,
        )
        for d in draws
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO draws
            (draw_id, draw_date, n1, n2, n3, n4, n5, special, source_url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/api/health")
def health():
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        latest = conn.execute("SELECT MAX(draw_id) FROM draws").fetchone()[0]
        latest_fetched = conn.execute(
            "SELECT MAX(fetched_at) FROM draws"
        ).fetchone()[0]
    return {
        "ok": True,
        "stored_draws": count,
        "latest_draw_id": latest,
        "last_synced_at": latest_fetched,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "vietvudanh/vietlott-data (GitHub NDJSON)",
    }


@app.get("/api/draws")
def draws(limit: int = 100):
    limit = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM draws ORDER BY draw_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "count": len(rows),
        "source": "vietvudanh/vietlott-data",
        "draws": [
            {
                "draw_id": r["draw_id"],
                "draw_date": r["draw_date"],
                "main_numbers": [r[f"n{i}"] for i in range(1, 6)],
                "special_number": r["special"],
                "source_url": r["source_url"],
                "fetched_at": r["fetched_at"],
            }
            for r in rows
        ],
    }


@app.post("/api/sync")
def sync():
    try:
        remote = fetch_remote_draws(limit=120)
    except requests.RequestException as e:
        logger.warning("Remote sync failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Không tải được dữ liệu từ nguồn mở: {e}",
        )
    if not remote:
        raise HTTPException(
            status_code=502,
            detail="Nguồn trả về rỗng hoặc không parse được kết quả hợp lệ.",
        )

    to_save = remote[:100]
    saved = save_draws(to_save)

    return {
        "ok": True,
        "saved": saved,
        "latest_detected": remote[0]["draw_id"] if remote else None,
        "source": DATA_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# Khởi tạo DB khi start
@app.on_event("startup")
def startup():
    connect().close()


# --- Analytics and ML extension ---
import logging
from collections import Counter
from itertools import combinations
from functools import lru_cache

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("vietlott535")


def load_draw_rows(limit: int = 500) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT draw_id, draw_date, n1,n2,n3,n4,n5,special FROM draws ORDER BY draw_id DESC LIMIT ?",
            (max(1, min(int(limit), 5000)),),
        ).fetchall()
    return [{"draw_id": r["draw_id"], "draw_date": r["draw_date"],
             "main_numbers": [r[f"n{i}"] for i in range(1, 6)],
             "special_number": r["special"]} for r in reversed(rows)]


def analytics_summary(draw_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive analytics on chronological draw data; no predictive claims."""
    draws = sorted(draw_list, key=lambda d: int(d["draw_id"]))
    main_freq = Counter(n for d in draws for n in d["main_numbers"])
    special_freq = Counter(d["special_number"] for d in draws)
    pair_freq: Counter = Counter()
    triple_freq: Counter = Counter()
    gaps: dict[int, list[int]] = {n: [] for n in range(1, 36)}
    last_seen: dict[int, int] = {}
    streaks: dict[int, int] = {n: 0 for n in range(1, 36)}
    prev: set[int] = set()
    for idx, d in enumerate(draws):
        nums = sorted(set(d["main_numbers"]))
        pair_freq.update(combinations(nums, 2))
        triple_freq.update(combinations(nums, 3))
        current = set(nums)
        for n in range(1, 36):
            if n in current:
                if n in last_seen:
                    gaps[n].append(idx - last_seen[n])
                last_seen[n] = idx
                streaks[n] = streaks[n] + 1 if n in prev else 1
            else:
                streaks[n] = 0
        prev = current
    total_main = max(1, len(draws) * 5)
    return {
        "draw_count": len(draws),
        "main_frequency": [{"number": n, "count": main_freq[n],
                            "rate": round(main_freq[n] / total_main, 6)} for n in range(1, 36)],
        "special_frequency": [{"number": n, "count": special_freq[n]} for n in range(1, 13)],
        "top_pairs": [{"numbers": list(k), "count": v} for k, v in pair_freq.most_common(20)],
        "top_triples": [{"numbers": list(k), "count": v} for k, v in triple_freq.most_common(10)],
        "gap_distribution": [{"number": n, "observed_gaps": len(gaps[n]),
                              "mean_gap": round(sum(gaps[n]) / len(gaps[n]), 3) if gaps[n] else None,
                              "current_gap": (len(draws) - 1 - last_seen[n]) if n in last_seen else len(draws)}
                             for n in range(1, 36)],
        "current_streaks": [{"number": n, "draws": streaks[n]} for n in range(1, 36)],
        "notes": ["Mô tả dữ liệu lịch sử, không hàm ý quan hệ nhân quả hay xác suất kỳ tới."]
    }


def _feature_vector(history: list[dict[str, Any]], window: int = 20) -> list[float]:
    recent = history[-window:]
    nums = [set(d["main_numbers"]) for d in history]
    features: list[float] = []
    for n in range(1, 36):
        features.append(sum(n in d for d in recent) / max(1, len(recent)))
        gap = next((i for i, d in enumerate(reversed(nums)) if n in d), len(history))
        features.append(min(gap, 100) / 100.0)
        features.append(sum(n in d for d in history[-5:]) / 5.0)
    features.append(len(history) / 500.0)
    # Special-ball context
    for n in range(1, 13):
        features.append(sum(d["special_number"] == n for d in recent) / max(1, len(recent)))
    return features


def _target_vector(draw: dict[str, Any]) -> list[int]:
    selected = set(draw["main_numbers"])
    return [int(n in selected) for n in range(1, 36)]


def model_recommendation(draw_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Optional sklearn RandomForest multi-output model, trained only on past draws."""
    draws = sorted(draw_list, key=lambda d: int(d["draw_id"]))
    if len(draws) < 35:
        raise ValueError("Cần ít nhất 35 kỳ dữ liệu để tạo gợi ý ML có ý nghĩa kỹ thuật.")
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError as exc:
        raise RuntimeError("Thiếu scikit-learn; hãy cài requirements.txt.") from exc
    X = [_feature_vector(draws[:i]) for i in range(10, len(draws))]
    y = [_target_vector(draws[i]) for i in range(10, len(draws))]
    model = RandomForestRegressor(n_estimators=120, max_depth=5, min_samples_leaf=2,
                                  random_state=535, n_jobs=-1)
    model.fit(X, y)
    scores = model.predict([_feature_vector(draws)])
    ranked = sorted(range(1, 36), key=lambda n: float(scores[0][n-1]), reverse=True)
    special_counts = Counter(d["special_number"] for d in draws[-20:])
    special_ranked = sorted(range(1, 13), key=lambda n: (special_counts[n], -n), reverse=True)
    return {
        "model": "RandomForestRegressor multi-output",
        "main_numbers_ranked": [{"number": n, "score": round(float(scores[0][n-1]), 5)} for n in ranked],
        "suggested_main": sorted(ranked[:5]),
        "suggested_special": special_ranked[0],
        "training_draws": len(y),
        "warning": "Điểm mô hình không phải xác suất trúng. Lotto công bằng khiến mọi tổ hợp hợp lệ có xác suất như nhau."
    }


@app.get("/api/analytics")
def analytics():
    return analytics_summary(load_draw_rows())


@app.get("/api/model/recommend")
def ml_recommend():
    try:
        return model_recommendation(load_draw_rows())
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("ML recommendation failed")
        raise HTTPException(status_code=500, detail="Không thể tạo gợi ý ML lúc này.")


@app.get("/api/model/backtest")
def model_backtest(min_train: int = 40, max_draws: int = 12):
    """Walk-forward evaluation: every prediction uses strictly earlier draws."""
    draws = load_draw_rows()
    min_train = max(20, min(int(min_train), 400))
    max_draws = max(1, min(int(max_draws), 25))
    if len(draws) <= min_train:
        raise HTTPException(status_code=422, detail=f"Cần hơn {min_train} kỳ; hiện có {len(draws)}.")
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        raise HTTPException(status_code=503, detail="Cần cài scikit-learn để chạy backtest ML.")
    start = max(min_train, len(draws) - max_draws)
    ml_hits, freq_hits, random_expected, evaluated = [], [], 0.0, 0
    for i in range(start, len(draws)):
        history = draws[:i]
        target = set(draws[i]["main_numbers"])
        train_start = 10
        # Bound the training set to recent examples to keep request latency predictable on small hosts.
        train_indices = list(range(train_start, len(history)))[-160:]
        X = [_feature_vector(history[:j]) for j in train_indices]
        y = [_target_vector(history[j]) for j in train_indices]
        if not X:
            continue
        model = RandomForestRegressor(n_estimators=16, max_depth=4, min_samples_leaf=2,
                                      random_state=535, n_jobs=1)
        model.fit(X, y)
        scores = model.predict([_feature_vector(history)])[0]
        ml_top = set(sorted(range(1, 36), key=lambda n: scores[n-1], reverse=True)[:5])
        counts = Counter(n for d in history[-20:] for n in d["main_numbers"])
        freq_top = set(sorted(range(1, 36), key=lambda n: (counts[n], -n), reverse=True)[:5])
        ml_hits.append(len(ml_top & target))
        freq_hits.append(len(freq_top & target))
        random_expected += 25 / 35
        evaluated += 1
    if not evaluated:
        raise HTTPException(status_code=422, detail="Không đủ dữ liệu huấn luyện.")
    return {
        "method": "walk-forward / expanding window",
        "evaluated_draws": evaluated,
        "ml_mean_hits": round(sum(ml_hits) / evaluated, 4),
        "frequency_baseline_mean_hits": round(sum(freq_hits) / evaluated, 4),
        "random_uniform_expected_hits": round(random_expected / evaluated, 4),
        "ml_hit_counts": dict(Counter(ml_hits)),
        "baseline_hit_counts": dict(Counter(freq_hits)),
        "warning": "Backtest ngắn hạn dễ nhiễu, không đảm bảo hiệu quả tương lai hoặc tăng xác suất trúng. Không dùng làm lời khuyên mua vé."
    }
