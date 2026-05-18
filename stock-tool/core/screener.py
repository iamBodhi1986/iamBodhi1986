"""
多条件股票筛选器。

对全市场快照 DataFrame 进行过滤，支持：
  - 价格 / PE / PB / 市值 / 换手率 / 涨跌幅 范围
  - 排除 ST / 创业板 / 科创板 / 北交所
  - 名称关键词搜索
  - 预设模板（小资金低吸、高换手活跃、低估值蓝筹）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class ScreenCriteria:
    """筛选条件，所有字段为 None 表示不限制。"""

    price_min: Optional[float] = None
    price_max: Optional[float] = None
    pe_min: Optional[float] = None
    pe_max: Optional[float] = None
    pb_min: Optional[float] = None
    pb_max: Optional[float] = None
    market_cap_min: Optional[float] = None   # 单位：元
    market_cap_max: Optional[float] = None
    turnover_rate_min: Optional[float] = None  # %
    turnover_rate_max: Optional[float] = None
    pct_change_min: Optional[float] = None   # %
    pct_change_max: Optional[float] = None

    exclude_st: bool = True
    exclude_chinext: bool = False   # 创业板 300/301
    exclude_star: bool = False      # 科创板 688
    exclude_bj: bool = False        # 北交所

    name_keyword: Optional[str] = None


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------
def _range_mask(series: pd.Series, lo: Optional[float], hi: Optional[float]) -> pd.Series:
    mask = pd.Series(True, index=series.index)
    if lo is not None:
        mask &= series >= lo
    if hi is not None:
        mask &= series <= hi
    return mask


def _is_chinext(code: str) -> bool:
    return code.startswith(("300", "301"))


def _is_star(code: str) -> bool:
    return code.startswith("688")


def _is_bj(code: str) -> bool:
    return code.startswith(("43", "83", "87", "88", "920"))


# ---------------------------------------------------------------------------
# 核心筛选
# ---------------------------------------------------------------------------
def screen(df: pd.DataFrame, c: ScreenCriteria) -> pd.DataFrame:
    """
    对 DataFrame 执行多条件筛选，返回符合条件的子集。
    所有条件取交集（AND 逻辑）。
    """
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if "price" in df.columns:
        mask &= _range_mask(df["price"], c.price_min, c.price_max)
    if "pe" in df.columns:
        mask &= _range_mask(df["pe"], c.pe_min, c.pe_max)
    if "pb" in df.columns:
        mask &= _range_mask(df["pb"], c.pb_min, c.pb_max)
    if "market_cap" in df.columns:
        mask &= _range_mask(df["market_cap"], c.market_cap_min, c.market_cap_max)
    if "turnover_rate" in df.columns:
        mask &= _range_mask(df["turnover_rate"], c.turnover_rate_min, c.turnover_rate_max)
    if "pct_change" in df.columns:
        mask &= _range_mask(df["pct_change"], c.pct_change_min, c.pct_change_max)

    # 排除 ST
    if c.exclude_st and "name" in df.columns:
        mask &= ~df["name"].str.contains("ST", case=False, na=False)

    # 排除板块
    if "code" in df.columns:
        codes = df["code"].astype(str)
        if c.exclude_chinext:
            mask &= ~codes.map(_is_chinext)
        if c.exclude_star:
            mask &= ~codes.map(_is_star)
        if c.exclude_bj:
            mask &= ~codes.map(_is_bj)

    # 名称关键词
    if c.name_keyword and "name" in df.columns:
        mask &= df["name"].str.contains(c.name_keyword, na=False)

    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 预设模板
# ---------------------------------------------------------------------------
def preset_small_account() -> ScreenCriteria:
    """小资金低吸：价格 2-30 元，换手率 2-20%，排除 ST/北交所。"""
    return ScreenCriteria(
        price_min=2.0,
        price_max=30.0,
        turnover_rate_min=2.0,
        turnover_rate_max=20.0,
        pct_change_min=-5.0,
        pct_change_max=7.0,
        exclude_st=True,
        exclude_bj=True,
    )


def preset_active_turnover() -> ScreenCriteria:
    """高换手活跃股：换手率 ≥ 5%，成交活跃。"""
    return ScreenCriteria(
        turnover_rate_min=5.0,
        price_min=3.0,
        exclude_st=True,
        exclude_bj=True,
    )


def preset_value() -> ScreenCriteria:
    """低估值蓝筹：PE 5-20，PB 0.5-3，市值 ≥ 200 亿。"""
    return ScreenCriteria(
        pe_min=5.0,
        pe_max=20.0,
        pb_min=0.5,
        pb_max=3.0,
        market_cap_min=200e8,
        exclude_st=True,
    )


PRESETS = {
    "小资金低吸": preset_small_account,
    "高换手活跃": preset_active_turnover,
    "低估值蓝筹": preset_value,
}
