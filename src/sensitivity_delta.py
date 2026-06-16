import warnings

import numpy as np
import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, PROJECT_ROOT


warnings.filterwarnings("ignore")

PANEL_PATH = DATA_DIR / "crypto_panel_365days.parquet"
BTC_PATH = DATA_DIR / "btc_daily.parquet"
OUTPUT_PATH = PROJECT_ROOT / "results" / "sensitivity_delta.csv"
SUMMARY_OUTPUT_PATH = PROJECT_ROOT / "results" / "sensitivity_delta_summary.csv"
THETA = 0.1
DELTAS = [0.5, 0.7, 0.9]
MIN_MONTHLY_OBS = 5
MIN_MONTHLY_COINS = 20


def salience_covariance(values, benchmark_values, theta, delta):
    valid = np.isfinite(values) & np.isfinite(benchmark_values)
    values = values[valid]
    benchmark_values = benchmark_values[valid]

    if len(values) < MIN_MONTHLY_OBS:
        return np.nan

    sigma = np.abs(values - benchmark_values) / (
        np.abs(values) + np.abs(benchmark_values) + theta
    )
    ranks = pd.Series(sigma).rank(ascending=False).to_numpy()

    pi = 1 / len(values)
    pi_tilde = pi * (delta**ranks)
    pi_tilde = pi_tilde / pi_tilde.sum()
    weight_distortion = pi_tilde / pi

    return np.cov(weight_distortion, values)[0, 1]


def compute_str_stv(group, delta):
    if len(group) < MIN_MONTHLY_OBS:
        return pd.Series({"STR": np.nan, "STV": np.nan})

    return pd.Series(
        {
            "STR": salience_covariance(
                group["ret"].to_numpy(dtype=float),
                group["btc_ret"].to_numpy(dtype=float),
                THETA,
                delta,
            ),
            "STV": salience_covariance(
                group["volume"].to_numpy(dtype=float),
                group["btc_volume"].to_numpy(dtype=float),
                THETA,
                delta,
            ),
        }
    )


def build_monthly_returns(panel):
    monthly = (
        panel.groupby(["coin_id", "month"], as_index=False)
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

    return monthly[["coin_id", "month", "fwd_ret", "market_cap", "n_daily_obs"]]


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


def compute_salience_for_delta(panel, delta):
    results = []
    grouped = panel.groupby(["month", "coin_id"], sort=True)
    for (month, coin_id), group in tqdm(
        grouped, total=grouped.ngroups, desc=f"delta={delta}"
    ):
        result = compute_str_stv(group, delta)
        result["coin_id"] = coin_id
        result["month"] = month
        results.append(result)

    salience = pd.DataFrame(results).dropna(subset=["STR", "STV"]).reset_index(drop=True)
    return salience[["coin_id", "month", "STR", "STV"]]


def run_portfolio_sorts(salience, monthly_returns, delta):
    merged = salience.merge(monthly_returns, on=["coin_id", "month"], how="left")
    merged = merged.dropna(subset=["fwd_ret", "STR", "STV"]).reset_index(drop=True)

    results = []
    for month in sorted(merged["month"].unique()):
        month_data = merged[merged["month"] == month].copy()
        if len(month_data) < MIN_MONTHLY_COINS:
            continue

        for measure in ["STR", "STV"]:
            month_data[f"{measure}_quintile"] = assign_quintiles(month_data, measure)

            for quintile in range(1, 6):
                group = month_data[month_data[f"{measure}_quintile"] == quintile]
                if group.empty:
                    continue

                results.append(
                    {
                        "delta": delta,
                        "month": month,
                        "measure": measure,
                        "quintile": quintile,
                        "ew_ret": group["fwd_ret"].mean(),
                        "vw_ret": weighted_average(group["fwd_ret"], group["market_cap"]),
                        "n_obs": len(group),
                    }
                )

    return results


def add_high_low_rows(summary):
    rows = []
    for delta in sorted(summary["delta"].unique()):
        for measure in ["STR", "STV"]:
            sub = summary[(summary["delta"] == delta) & (summary["measure"] == measure)]
            high = sub[sub["quintile"] == 5]
            low = sub[sub["quintile"] == 1]
            if high.empty or low.empty:
                continue

            rows.append(
                {
                    "delta": delta,
                    "measure": measure,
                    "quintile": "H-L",
                    "ew_ret": high["ew_ret"].iloc[0] - low["ew_ret"].iloc[0],
                    "vw_ret": high["vw_ret"].iloc[0] - low["vw_ret"].iloc[0],
                    "n_obs": np.nan,
                }
            )

    return pd.concat([summary, pd.DataFrame(rows)], ignore_index=True)


def main():
    print("加载数据...")
    panel = pd.read_parquet(PANEL_PATH)
    btc = pd.read_parquet(BTC_PATH)

    panel["date"] = pd.to_datetime(panel["date"])
    btc["date"] = pd.to_datetime(btc["date"])

    panel = panel.merge(
        btc[["date", "volume", "ret"]].rename(
            columns={"volume": "btc_volume", "ret": "btc_ret"}
        ),
        on="date",
        how="left",
    )
    panel["month"] = panel["date"].dt.to_period("M").astype(str)
    panel = panel.sort_values(["coin_id", "date"])

    monthly_returns = build_monthly_returns(panel)
    all_results = []

    for delta in DELTAS:
        print(f"\n正在计算 delta = {delta} ...")
        salience = compute_salience_for_delta(panel, delta)
        all_results.extend(run_portfolio_sorts(salience, monthly_returns, delta))

    results_df = pd.DataFrame(all_results)
    if results_df.empty:
        raise RuntimeError("No sensitivity analysis results were produced")

    summary = (
        results_df.groupby(["delta", "measure", "quintile"], as_index=False)
        .agg({"ew_ret": "mean", "vw_ret": "mean", "n_obs": "mean"})
        .sort_values(["delta", "measure", "quintile"])
    )
    summary_with_high_low = add_high_low_rows(summary)

    print("\n" + "=" * 75)
    print("Sensitivity Analysis: Different delta values (High-Low)")
    print("=" * 75)

    for delta in DELTAS:
        print(f"\n--- delta = {delta} ---")
        for measure in ["STR", "STV"]:
            sub = summary_with_high_low[
                (summary_with_high_low["delta"] == delta)
                & (summary_with_high_low["measure"] == measure)
                & (summary_with_high_low["quintile"] == "H-L")
            ]
            if sub.empty:
                continue
            print(
                f"{measure}: High-Low (EW) = {sub['ew_ret'].iloc[0]:.4f}, "
                f"High-Low (VW) = {sub['vw_ret'].iloc[0]:.4f}"
            )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(OUTPUT_PATH, index=False)
    summary_with_high_low.to_csv(SUMMARY_OUTPUT_PATH, index=False)
    print(f"\n详细结果已保存到: {OUTPUT_PATH}")
    print(f"汇总结果已保存到: {SUMMARY_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
