import warnings

import numpy as np
import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, PROJECT_ROOT


warnings.filterwarnings("ignore")

SALIENCE_PATH = DATA_DIR / "panel_with_salience.parquet"
DAILY_PANEL_PATH = DATA_DIR / "crypto_panel_365days.parquet"
OUTPUT_PATH = PROJECT_ROOT / "results" / "table2_fama_macbeth.csv"
MIN_MONTHLY_COINS = 30


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
            volume=("volume", "last"),
            n_daily_obs=("date", "count"),
        )
        .sort_values(["coin_id", "month"])
    )
    monthly["ret"] = monthly["last_price"] / monthly["first_price"] - 1
    monthly["fwd_ret"] = monthly.groupby("coin_id")["ret"].shift(-1)
    monthly["log_mcap"] = np.log(monthly["market_cap"].replace(0, np.nan))
    monthly["mom"] = monthly.groupby("coin_id")["ret"].transform(
        lambda values: values.rolling(3, min_periods=3).sum().shift(1)
    )

    return monthly[["coin_id", "month", "fwd_ret", "log_mcap", "mom", "market_cap"]]


def standardize_by_month(group, columns):
    group = group.copy()
    for column in columns:
        if column not in group.columns:
            continue
        std = group[column].std(ddof=0)
        if pd.isna(std) or std == 0:
            group[column] = 0.0
        else:
            group[column] = (group[column] - group[column].mean()) / std
    return group


def newey_west_tstat(series, lag=2):
    series = pd.Series(series).dropna()
    if len(series) < 2:
        return np.nan

    values = series.to_numpy(dtype=float)
    demeaned = values - values.mean()
    sample_size = len(values)
    max_lag = min(lag, sample_size - 1)

    variance = np.dot(demeaned, demeaned) / sample_size
    for lag_idx in range(1, max_lag + 1):
        weight = 1 - lag_idx / (max_lag + 1)
        autocov = np.dot(demeaned[lag_idx:], demeaned[:-lag_idx]) / sample_size
        variance += 2 * weight * autocov

    if variance <= 0:
        return np.nan

    standard_error = np.sqrt(variance / sample_size)
    if standard_error == 0:
        return np.nan

    return values.mean() / standard_error


def fit_ols(y, X):
    x_values = np.column_stack([np.ones(len(X)), X.to_numpy(dtype=float)])
    y_values = y.to_numpy(dtype=float)
    coefficients = np.linalg.lstsq(x_values, y_values, rcond=None)[0]
    residuals = y_values - x_values @ coefficients
    degrees_of_freedom = len(y_values) - x_values.shape[1]

    if degrees_of_freedom <= 0:
        return None

    sigma2 = np.dot(residuals, residuals) / degrees_of_freedom
    covariance = sigma2 * np.linalg.pinv(x_values.T @ x_values)
    standard_errors = np.sqrt(np.diag(covariance))
    tvalues = np.divide(
        coefficients,
        standard_errors,
        out=np.full_like(coefficients, np.nan),
        where=standard_errors > 0,
    )

    names = ["const"] + list(X.columns)
    return {
        "params": dict(zip(names, coefficients)),
        "tvalues": dict(zip(names, tvalues)),
    }


def run_monthly_regression(month_data):
    variables = ["STR", "STV", "log_mcap", "mom"]
    X = month_data[variables]
    y = month_data["fwd_ret"]
    valid = X.notna().all(axis=1) & y.notna()
    X = X.loc[valid]
    y = y.loc[valid]

    if len(X) < MIN_MONTHLY_COINS:
        return None

    model = fit_ols(y, X)
    if model is None:
        return None

    return {
        "n_stocks": len(X),
        "STR_coef": model["params"].get("STR", np.nan),
        "STV_coef": model["params"].get("STV", np.nan),
        "log_mcap_coef": model["params"].get("log_mcap", np.nan),
        "mom_coef": model["params"].get("mom", np.nan),
        "STR_t": model["tvalues"].get("STR", np.nan),
        "STV_t": model["tvalues"].get("STV", np.nan),
        "log_mcap_t": model["tvalues"].get("log_mcap", np.nan),
        "mom_t": model["tvalues"].get("mom", np.nan),
    }


def main():
    print("加载数据...")
    salience = pd.read_parquet(SALIENCE_PATH)
    daily_panel = pd.read_parquet(DAILY_PANEL_PATH)

    monthly_panel = build_monthly_panel(daily_panel)
    panel = salience.merge(monthly_panel, on=["coin_id", "month"], how="left")
    panel = panel.dropna(subset=["STR", "STV", "fwd_ret"]).reset_index(drop=True)

    panel = panel.groupby("month", group_keys=False).apply(
        standardize_by_month, columns=["STR", "STV", "log_mcap", "mom"]
    )

    print(f"有效样本数: {len(panel)}")
    print("开始 Fama-MacBeth 回归...")

    results = []
    for month in tqdm(sorted(panel["month"].unique()), desc="Fama-MacBeth"):
        month_data = panel[panel["month"] == month].copy()
        regression_result = run_monthly_regression(month_data)
        if regression_result is None:
            continue

        regression_result["month"] = month
        results.append(regression_result)

    fm_results = pd.DataFrame(results)
    if fm_results.empty:
        raise RuntimeError("No monthly regressions were successfully estimated")

    print("\n" + "=" * 70)
    print("Table 2: Fama-MacBeth Regression Results (Recent 365 days)")
    print("=" * 70)

    for column in ["STR_coef", "STV_coef", "log_mcap_coef", "mom_coef"]:
        mean_coef = fm_results[column].mean()
        t_stat = newey_west_tstat(fm_results[column], lag=2)
        print(f"{column:15s}: {mean_coef:8.4f}   (t = {t_stat:6.2f})")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fm_results.to_csv(OUTPUT_PATH, index=False)
    print(f"\n详细结果已保存到 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
