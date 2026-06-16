import warnings

import numpy as np
import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, PROJECT_ROOT


warnings.filterwarnings("ignore")

SALIENCE_PATH = DATA_DIR / "panel_with_salience.parquet"
DAILY_PANEL_PATH = DATA_DIR / "crypto_panel_365days.parquet"
DETAILED_OUTPUT_PATH = PROJECT_ROOT / "results" / "table1_detailed.csv"
SUMMARY_OUTPUT_PATH = PROJECT_ROOT / "results" / "table1_summary.csv"
MIN_MONTHLY_COINS = 20


def weighted_average(values, weights):
    values = pd.Series(values, dtype="float64")
    weights = pd.Series(weights, dtype="float64")
    valid = values.notna() & weights.notna() & (weights > 0)

    if not valid.any():
        return np.nan

    return np.average(values[valid], weights=weights[valid])


def assign_quintiles(frame, column):
    ranks = frame[column].rank(method="first")
    return pd.qcut(ranks, 5, labels=False, duplicates="drop") + 1


def build_monthly_returns(daily_panel):
    daily_panel = daily_panel.copy()
    daily_panel["date"] = pd.to_datetime(daily_panel["date"])
    daily_panel["month"] = daily_panel["date"].dt.to_period("M").astype(str)
    daily_panel = daily_panel.sort_values(["coin_id", "date"])

    monthly = (
        daily_panel.groupby(["coin_id", "month"], as_index=False)
        .agg(
            first_price=("price", "first"),
            last_price=("price", "last"),
            market_cap=("market_cap", "last"),
            n_daily_obs=("date", "count"),
        )
        .sort_values(["coin_id", "month"])
    )
    monthly["month_ret"] = monthly["last_price"] / monthly["first_price"] - 1
    monthly["fwd_ret"] = monthly.groupby("coin_id")["month_ret"].shift(-1)

    return monthly[["coin_id", "month", "month_ret", "fwd_ret", "market_cap", "n_daily_obs"]]


def append_portfolio_results(results, month, month_data, measure):
    month_data = month_data.copy()
    month_data["quintile"] = assign_quintiles(month_data, measure)

    for quintile in range(1, 6):
        group = month_data[month_data["quintile"] == quintile]
        if group.empty:
            continue

        results.append(
            {
                "month": month,
                "measure": measure,
                "quintile": quintile,
                "ew_ret": group["fwd_ret"].mean(),
                "vw_ret": weighted_average(group["fwd_ret"], group["market_cap"]),
                "n_stocks": len(group),
            }
        )


def add_high_low_rows(summary):
    rows = []
    for measure in sorted(summary["measure"].unique()):
        sub = summary[summary["measure"] == measure]
        high = sub[sub["quintile"] == 5]
        low = sub[sub["quintile"] == 1]
        if high.empty or low.empty:
            continue

        rows.append(
            {
                "measure": measure,
                "quintile": "H-L",
                "ew_ret": high["ew_ret"].iloc[0] - low["ew_ret"].iloc[0],
                "vw_ret": high["vw_ret"].iloc[0] - low["vw_ret"].iloc[0],
                "n_stocks": np.nan,
            }
        )

    return pd.concat([summary, pd.DataFrame(rows)], ignore_index=True)


def main():
    print("加载数据...")
    salience = pd.read_parquet(SALIENCE_PATH)
    daily_panel = pd.read_parquet(DAILY_PANEL_PATH)

    monthly_returns = build_monthly_returns(daily_panel)
    panel = salience.merge(monthly_returns, on=["coin_id", "month"], how="left")
    panel = panel.dropna(subset=["fwd_ret", "STR", "STV"]).reset_index(drop=True)
    panel = panel.sort_values(["month", "coin_id"])

    print(f"有效样本数: {len(panel)}")

    results = []
    for month in tqdm(sorted(panel["month"].unique()), desc="Portfolio Sorts"):
        month_data = panel[panel["month"] == month].copy()
        if len(month_data) < MIN_MONTHLY_COINS:
            continue

        append_portfolio_results(results, month, month_data, "STR")
        append_portfolio_results(results, month, month_data, "STV")

    results_df = pd.DataFrame(results)
    if results_df.empty:
        raise RuntimeError("No portfolio sort results were produced")

    summary = (
        results_df.groupby(["measure", "quintile"], as_index=False)
        .agg({"ew_ret": "mean", "vw_ret": "mean", "n_stocks": "mean"})
        .sort_values(["measure", "quintile"])
    )
    summary_with_high_low = add_high_low_rows(summary)

    print("\n" + "=" * 60)
    print("Table 1: Average Next-Month Returns by Quintile (Recent 365 days)")
    print("=" * 60)

    for measure in ["STR", "STV"]:
        print(f"\n--- {measure} ---")
        sub = summary[summary["measure"] == measure]
        print(sub[["quintile", "ew_ret", "vw_ret", "n_stocks"]].to_string(index=False))

        high = sub.loc[sub["quintile"] == 5, "ew_ret"].iloc[0]
        low = sub.loc[sub["quintile"] == 1, "ew_ret"].iloc[0]
        print(f"High - Low (EW): {high - low:.4f}")

        high_vw = sub.loc[sub["quintile"] == 5, "vw_ret"].iloc[0]
        low_vw = sub.loc[sub["quintile"] == 1, "vw_ret"].iloc[0]
        print(f"High - Low (VW): {high_vw - low_vw:.4f}")

    DETAILED_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(DETAILED_OUTPUT_PATH, index=False)
    summary_with_high_low.to_csv(SUMMARY_OUTPUT_PATH, index=False)
    print(f"\n详细结果已保存到: {DETAILED_OUTPUT_PATH}")
    print(f"汇总结果已保存到: {SUMMARY_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
