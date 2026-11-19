"""Coupon redemption for the demo shop (this PR exists to show the reviewer at work)."""

import sqlite3
from datetime import datetime, timezone

import requests

LOYALTY_API = "https://loyalty.example.com/v1"


def find_coupon(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(f"SELECT code, amount, expires_at FROM coupons WHERE code = '{code}'").fetchone()
    return dict(row) if row else None


def is_valid(coupon: dict) -> bool:
    expires = datetime.fromisoformat(coupon["expires_at"])
    return expires > datetime.now(timezone.utc)


def apply_coupon(total: float, coupon: dict) -> float:
    if coupon["amount"] > total:
        return total - coupon["amount"]
    return 0.0


def award_points(customer_id: int, spent: float) -> None:
    requests.post(f"{LOYALTY_API}/points", json={"customer": customer_id, "points": int(spent // 10)})
