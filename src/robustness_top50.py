import warnings

import numpy as np
import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, PROJECT_ROOT


warnings.filterwarnings("ignore")

SALIENCE_PATH = DATA_DIR / "panel_with_salience.parquet"
DAILY_PANEL_PATH = DATA_DIR / "crypto_panel_365days.parquet"
OUTPUT_PATH = PROJECT_ROOT / "results" / "robustness_top50_table1.csv"
SUMMARY_OUTPUT_PATH = PROJECT_ROOT / "results" / "robustness_top50_summary.csv"
TOP_N = 50
MIN_MONTHLY_COINS = 15


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


def build_monthly_panel(daily_panel):
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

    monthly_panel = build_monthly_panel(daily_panel)
    panel = salience.merge(monthly_panel, on=["coin_id", "month"], how="left")
    panel = panel.dropna(subset=["fwd_ret", "STR", "STV", "market_cap"]).reset_index(drop=True)

    print("正在筛选每月 Top 50 大币种...")
    top50_list = []
    for month in tqdm(sorted(panel["month"].unique())):
        month_data = panel[panel["month"] == month].copy()
        top50 = month_data[month_data["market_cap"] > 0].nlargest(TOP_N, "market_cap")
        top50_list.append(top50)

    panel_top50 = pd.concat(top50_list, ignore_index=True)
    print(f"筛选后样本数: {len(panel_top50)}")
    print(f"涉及币种数: {panel_top50['coin_id'].nunique()}")

    results = []
    for month in tqdm(sorted(panel_top50["month"].unique()), desc="Top50 Portfolio Sorts"):
        month_data = panel_top50[panel_top50["month"] == month].copy()
        if len(month_data) < MIN_MONTHLY_COINS:
            continue

        append_portfolio_results(results, month, month_data, "STR")
        append_portfolio_results(results, month, month_data, "STV")

    results_df = pd.DataFrame(results)
    if results_df.empty:
        raise RuntimeError("No Top 50 portfolio sort results were produced")

    summary = (
        results_df.groupby(["measure", "quintile"], as_index=False)
        .agg({"ew_ret": "mean", "vw_ret": "mean", "n_stocks": "mean"})
        .sort_values(["measure", "quintile"])
    )
    summary_with_high_low = add_high_low_rows(summary)

    print("\n" + "=" * 65)
    print("Robustness Check: Top 50 Coins by Market Cap (Recent 365 days)")
    print("=" * 65)

    for measure in ["STR", "STV"]:
        print(f"\n--- {measure} (Top 50) ---")
        sub = summary[summary["measure"] == measure]
        print(sub[["quintile", "ew_ret", "vw_ret", "n_stocks"]].to_string(index=False))

        high_ew = sub.loc[sub["quintile"] == 5, "ew_ret"].iloc[0]
        low_ew = sub.loc[sub["quintile"] == 1, "ew_ret"].iloc[0]
        print(f"High - Low (EW): {high_ew - low_ew:.4f}")

        high_vw = sub.loc[sub["quintile"] == 5, "vw_ret"].iloc[0]
        low_vw = sub.loc[sub["quintile"] == 1, "vw_ret"].iloc[0]
        print(f"High - Low (VW): {high_vw - low_vw:.4f}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(OUTPUT_PATH, index=False)
    summary_with_high_low.to_csv(SUMMARY_OUTPUT_PATH, index=False)
    print(f"\n详细结果已保存到: {OUTPUT_PATH}")
    print(f"汇总结果已保存到: {SUMMARY_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
