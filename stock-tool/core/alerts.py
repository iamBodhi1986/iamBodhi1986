"""
提醒规则引擎。

规则持久化到 data/alerts.json，支持以下触发类型：
  - price_above    价格 ≥ 阈值
  - price_below    价格 ≤ 阈值
  - pct_above      涨幅 ≥ 阈值(%)
  - pct_below      跌幅 ≤ 阈值(%)
  - turnover_above 换手率 ≥ 阈值(%)

evaluate() 接受行情快照，返回所有被触发的规则列表。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

ALERTS_PATH = Path(__file__).resolve().parent.parent / "data" / "alerts.json"

RULE_TYPES = {
    "price_above": "价格 ≥",
    "price_below": "价格 ≤",
    "pct_above": "涨跌幅 ≥",
    "pct_below": "涨跌幅 ≤",
    "turnover_above": "换手率 ≥",
}


@dataclass
class TriggeredAlert:
    """一条被触发的提醒。"""
    rule_id: str
    code: str
    name: str
    rule_type: str
    threshold: float
    current: float
    message: str


# ---------------------------------------------------------------------------
# 规则持久化
# ---------------------------------------------------------------------------
def _load_raw() -> dict:
    if not ALERTS_PATH.exists():
        ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALERTS_PATH.write_text(
            json.dumps({"rules": []}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return json.loads(ALERTS_PATH.read_text(encoding="utf-8"))


def _save_raw(data: dict) -> None:
    ALERTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_rules() -> list[dict]:
    return _load_raw().get("rules", [])


def save_rules(rules: list[dict]) -> None:
    _save_raw({"rules": rules})


def add_rule(
    code: str,
    name: str,
    rule_type: str,
    value: float,
    note: str = "",
) -> dict:
    """新增一条规则，返回完整规则字典。"""
    if rule_type not in RULE_TYPES:
        raise ValueError(f"不支持的规则类型: {rule_type}，可选: {list(RULE_TYPES.keys())}")
    rules = load_rules()
    rule = {
        "id": uuid.uuid4().hex[:8],
        "code": code,
        "name": name,
        "type": rule_type,
        "value": float(value),
        "enabled": True,
        "note": note,
    }
    rules.append(rule)
    save_rules(rules)
    return rule


def delete_rule(rule_id: str) -> None:
    rules = [r for r in load_rules() if r["id"] != rule_id]
    save_rules(rules)


def toggle_rule(rule_id: str, enabled: bool) -> None:
    rules = load_rules()
    for r in rules:
        if r["id"] == rule_id:
            r["enabled"] = enabled
    save_rules(rules)


# ---------------------------------------------------------------------------
# 规则评估
# ---------------------------------------------------------------------------
def _check(rule: dict, row: pd.Series) -> Optional[TriggeredAlert]:
    """对单行快照检查单条规则。"""
    t = rule["type"]
    val = rule["value"]
    price = row.get("price")
    pct = row.get("pct_change")
    tr = row.get("turnover_rate")

    triggered = False
    current: Optional[float] = None

    if t == "price_above" and pd.notna(price):
        triggered, current = price >= val, price
    elif t == "price_below" and pd.notna(price):
        triggered, current = price <= val, price
    elif t == "pct_above" and pd.notna(pct):
        triggered, current = pct >= val, pct
    elif t == "pct_below" and pd.notna(pct):
        triggered, current = pct <= val, pct
    elif t == "turnover_above" and pd.notna(tr):
        triggered, current = tr >= val, tr

    if not triggered or current is None:
        return None

    label = RULE_TYPES.get(t, t)
    msg = f"⚠️ [{rule['code']} {rule['name']}] {label} {val} | 当前值: {current:.2f}"
    return TriggeredAlert(
        rule_id=rule["id"],
        code=rule["code"],
        name=rule["name"],
        rule_type=t,
        threshold=val,
        current=current,
        message=msg,
    )


def evaluate(snapshot: pd.DataFrame, rules: list[dict] | None = None) -> list[TriggeredAlert]:
    """
    对行情快照评估所有已启用规则，返回被触发的提醒列表。

    Args:
        snapshot: 含 code/price/pct_change/turnover_rate 列的 DataFrame
        rules: 可选，不传则从文件加载
    """
    if rules is None:
        rules = load_rules()

    alerts: list[TriggeredAlert] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        match = snapshot[snapshot["code"] == rule["code"]]
        if match.empty:
            continue
        result = _check(rule, match.iloc[0])
        if result:
            alerts.append(result)
    return alerts
