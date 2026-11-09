"""Tests for research.screen — no live HTTP calls."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# 1. sec.parse_frames_response — pure
# ---------------------------------------------------------------------------

class TestParseFramesResponse:
    def test_parses_data_rows(self):
        from research.screen.sec import parse_frames_response
        raw = json.loads((FIXTURES / "frames_revenue.json").read_text())
        result = parse_frames_response(raw)
        assert result[1001] == 500_000_000.0
        assert result[1002] == 1_200_000_000.0
        assert result[1003] == 300_000_000.0

    def test_empty_data_field(self):
        from research.screen.sec import parse_frames_response
        result = parse_frames_response({"data": []})
        assert result == {}

    def test_missing_data_key(self):
        from research.screen.sec import parse_frames_response
        result = parse_frames_response({})
        assert result == {}

    def test_cik_coerced_to_int(self):
        from research.screen.sec import parse_frames_response
        result = parse_frames_response({"data": [{"cik": "42", "val": 1.0}]})
        assert 42 in result


# ---------------------------------------------------------------------------
# 2. metrics.compute_debt — pure, no double-counting
# ---------------------------------------------------------------------------

class TestComputeDebt:
    def test_uses_lt_debt_total_when_available(self):
        from research.screen.metrics import compute_debt
        # LongTermDebt = 100, plus components that would double-count if added
        result = compute_debt(lt_debt=100.0, lt_debt_nc=80.0, lt_debt_c=20.0, st_debt=10.0)
        # Must use 100 (not 100+80+20), plus st_debt=10
        assert result == 110.0

    def test_sums_nc_plus_c_when_no_total(self):
        from research.screen.metrics import compute_debt
        result = compute_debt(lt_debt=None, lt_debt_nc=60.0, lt_debt_c=15.0, st_debt=5.0)
        assert result == 80.0

    def test_all_none_returns_zero(self):
        from research.screen.metrics import compute_debt
        assert compute_debt(None, None, None, None) == 0.0

    def test_only_st_debt(self):
        from research.screen.metrics import compute_debt
        assert compute_debt(None, None, None, 25.0) == 25.0

    def test_nc_only_no_c(self):
        from research.screen.metrics import compute_debt
        result = compute_debt(lt_debt=None, lt_debt_nc=50.0, lt_debt_c=None, st_debt=None)
        assert result == 50.0


# ---------------------------------------------------------------------------
# 3. metrics.fcf_consistency — pure
# ---------------------------------------------------------------------------

class TestFcfConsistency:
    def test_counts_positive_fcf_years(self):
        from research.screen.metrics import fcf_consistency
        ocf   = {2020: 10, 2021: 20, 2022: 5,  2023: 30, 2024: 15}
        capex = {2020:  5, 2021: 25, 2022: 3,  2023: 10, 2024:  8}
        # FCF: 5, -5, 2, 20, 7  → 4 positive
        assert fcf_consistency(ocf, capex) == 4

    def test_all_negative(self):
        from research.screen.metrics import fcf_consistency
        ocf   = {2020: 1, 2021: 2}
        capex = {2020: 5, 2021: 5}
        assert fcf_consistency(ocf, capex) == 0

    def test_missing_capex_treated_as_zero(self):
        from research.screen.metrics import fcf_consistency
        ocf   = {2020: 10, 2021: 20}
        capex = {}
        assert fcf_consistency(ocf, capex) == 2


# ---------------------------------------------------------------------------
# 4. scoring — percentile-rank correctness
# ---------------------------------------------------------------------------

class TestScoring:
    def _make_df(self):
        return pd.DataFrame({
            "fcf_yield":      [0.10, 0.05, 0.02],
            "ev_oi":          [5.0,  10.0, 20.0],
            "pb":             [1.0,   2.0,  3.0],
            "pct_below_hi":   [0.3,   0.1,  0.0],
            "fcf_consistency":[5,     3,     1],
            "op_margin":      [0.20,  0.10,  0.05],
            "nd_ebit":        [-1.0,  1.0,   4.0],
            "analysts":       [2,     5,    10],
            "news_count":     [1,     5,    20],
            "inst_pct":       [0.1,   0.4,   0.8],
            "market_cap":     [300e6, 1e9,  4.5e9],
        })

    def test_first_row_scores_highest_cheapness(self):
        from research.screen.scoring import score_cheapness
        df = self._make_df()
        s = score_cheapness(df)
        assert s.iloc[0] > s.iloc[1] > s.iloc[2]

    def test_first_row_scores_highest_quality(self):
        from research.screen.scoring import score_quality
        df = self._make_df()
        s = score_quality(df)
        assert s.iloc[0] > s.iloc[1] > s.iloc[2]

    def test_first_row_most_neglected(self):
        from research.screen.scoring import score_neglect
        df = self._make_df()
        s = score_neglect(df)
        assert s.iloc[0] > s.iloc[1] > s.iloc[2]

    def test_scores_in_0_100_range(self):
        from research.screen.scoring import combine_scores, add_scores, add_neglect_scores
        df = self._make_df()
        df = add_scores(df)
        df = add_neglect_scores(df)
        df = combine_scores(df)
        assert (df["score"] >= 0).all() and (df["score"] <= 100).all()

    def test_nan_scores_50_fallback(self):
        from research.screen.scoring import score_cheapness
        df = pd.DataFrame({"fcf_yield": [float("nan"), float("nan")]})
        s = score_cheapness(df)
        # Both NaN should produce identical scores (50 median fallback)
        assert s.iloc[0] == s.iloc[1]


# ---------------------------------------------------------------------------
# 5. filters.is_financial_sic — pure
# ---------------------------------------------------------------------------

class TestSicFilter:
    def test_bank_sic_is_financial(self):
        from research.screen.filters import is_financial_sic
        assert is_financial_sic(6020) is True

    def test_insurer_sic_is_financial(self):
        from research.screen.filters import is_financial_sic
        assert is_financial_sic(6311) is True

    def test_reit_sic_is_financial(self):
        from research.screen.filters import is_financial_sic
        assert is_financial_sic(6798) is True

    def test_manufacturer_sic_not_financial(self):
        from research.screen.filters import is_financial_sic
        assert is_financial_sic(3714) is False

    def test_none_sic_not_financial(self):
        from research.screen.filters import is_financial_sic
        assert is_financial_sic(None) is False

    def test_name_heuristic_bank(self):
        from research.screen.filters import is_financial_name
        assert is_financial_name("First National Bancorp") is True

    def test_name_heuristic_tech(self):
        from research.screen.filters import is_financial_name
        assert is_financial_name("Acme Software Inc") is False
