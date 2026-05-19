"""
数据获取层 - 基于 akshare 获取 A股行情数据。

功能：
  - 自选股列表持久化（JSON）
  - 全市场快照
  - 单股 K线 + 技术指标计算
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"


def _require_ak():
    if ak is None:
        raise RuntimeError("akshare 未安装，请执行 pip install akshare")


# ---------------------------------------------------------------------------
# 自选股持久化
# ---------------------------------------------------------------------------
def load_watchlist() -> dict[str, list[dict]]:
    """加载自选股分组数据，文件不存在则自动创建空模板。"""
    if not WATCHLIST_PATH.exists():
        WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST_PATH.write_text(
            json.dumps({"默认": []}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))


def save_watchlist(groups: dict[str, list[dict]]) -> None:
    WATCHLIST_PATH.write_text(
        json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_stock(group: str, code: str, name: str = "", note: str = "") -> None:
    """向指定分组添加股票（自动去重）。"""
    groups = load_watchlist()
    items = groups.setdefault(group, [])
    if any(item["code"] == code for item in items):
        return
    items.append({"code": code, "name": name or code, "note": note})
    save_watchlist(groups)


def remove_stock(group: str, code: str) -> None:
    """从指定分组移除股票。"""
    groups = load_watchlist()
    if group in groups:
        groups[group] = [item for item in groups[group] if item["code"] != code]
        save_watchlist(groups)


def add_group(group: str) -> None:
    """新建分组。"""
    groups = load_watchlist()
    if group not in groups:
        groups[group] = []
        save_watchlist(groups)


def delete_group(group: str) -> None:
    """删除整个分组。"""
    groups = load_watchlist()
    groups.pop(group, None)
    save_watchlist(groups)


# ---------------------------------------------------------------------------
# 行情数据
# ---------------------------------------------------------------------------
def fetch_market_snapshot() -> pd.DataFrame:
    """
    获取 A股全市场实时快照（东方财富源），返回标准化 DataFrame。
    列名统一为英文方便后续处理。
    """
    _require_ak()
    df = ak.stock_zh_a_spot_em()

    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "成交量": "volume",
        "成交额": "turnover",
        "振幅": "amplitude",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "prev_close",
        "换手率": "turnover_rate",
        "市盈率-动态": "pe",
        "市净率": "pb",
        "总市值": "market_cap",
        "流通市值": "float_cap",
        "量比": "volume_ratio",
        "60日涨跌幅": "pct_60d",
        "年初至今涨跌幅": "pct_ytd",
    }
    df = df.rename(columns=col_map)
    keep = [c for c in col_map.values() if c in df.columns]
    df = df[keep].copy()

    # 统一为数值
    num_cols = [c for c in keep if c not in ("code", "name")]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_quotes(codes: list[str]) -> pd.DataFrame:
    """从全市场快照中过滤指定代码的行情。"""
    if not codes:
        return pd.DataFrame()
    snap = fetch_market_snapshot()
    return snap[snap["code"].isin(codes)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# K线 + 技术指标
# ---------------------------------------------------------------------------
def get_kline(
    code: str,
    period: str = "daily",
    days: int = 120,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    获取单股 K线数据。

    Args:
        code: 6 位代码，如 '600519'
        period: daily / weekly / monthly
        days: 回看天数
        adjust: qfq(前复权) / hfq(后复权) / 空字符串(不复权)
    """
    _require_ak()
    end = pd.Timestamp.today().strftime("%Y%m%d")
    start = (pd.Timestamp.today() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")

    df = ak.stock_zh_a_hist(
        symbol=code, period=period, start_date=start, end_date=end, adjust=adjust
    )
    if df.empty:
        return df

    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "turnover", "振幅": "amplitude",
        "涨跌幅": "pct_change", "涨跌额": "change", "换手率": "turnover_rate",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(days).reset_index(drop=True)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    为 K线 DataFrame 添加技术指标：
      MA5 / MA10 / MA20 / MA60
      MACD (DIF / DEA / MACD柱)
      RSI(14)
      KDJ(9,3,3)
    """
    if df.empty or "close" not in df.columns:
        return df

    out = df.copy()

    # MA
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = out["close"].rolling(n).mean()

    # MACD
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["dif"] = ema12 - ema26
    out["dea"] = out["dif"].ewm(span=9, adjust=False).mean()
    out["macd_bar"] = (out["dif"] - out["dea"]) * 2

    # RSI(14)
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["rsi14"] = 100 - 100 / (1 + rs)

    # KDJ(9,3,3)
    low9 = out["low"].rolling(9).min()
    high9 = out["high"].rolling(9).max()
    rsv = (out["close"] - low9) / (high9 - low9) * 100
    out["k"] = rsv.ewm(com=2, adjust=False).mean()
    out["d"] = out["k"].ewm(com=2, adjust=False).mean()
    out["j"] = 3 * out["k"] - 2 * out["d"]

    return out
