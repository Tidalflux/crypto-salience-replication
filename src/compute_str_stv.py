import warnings

import numpy as np
import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, load_config


warnings.filterwarnings("ignore")

PANEL_PATH = DATA_DIR / "crypto_panel_365days.parquet"
BTC_PATH = DATA_DIR / "btc_daily.parquet"
OUTPUT_PATH = DATA_DIR / "panel_with_salience.parquet"
MIN_MONTHLY_OBS = 5


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


def compute_str_stv(group, theta, delta):
    if len(group) < MIN_MONTHLY_OBS:
        return pd.Series({"STR": np.nan, "STV": np.nan})

    str_value = salience_covariance(
        group["ret"].to_numpy(dtype=float),
        group["btc_ret"].to_numpy(dtype=float),
        theta,
        delta,
    )
    stv_value = salience_covariance(
        group["volume"].to_numpy(dtype=float),
        group["btc_volume"].to_numpy(dtype=float),
        theta,
        delta,
    )

    return pd.Series({"STR": str_value, "STV": stv_value})


def main():
    config = load_config()
    salience_config = config.get("salience", {})
    theta = float(salience_config.get("theta", 0.1))
    delta = float(salience_config.get("delta", 0.7))

    print("正在加载数据...")
    panel = pd.read_parquet(PANEL_PATH)
    btc = pd.read_parquet(BTC_PATH)

    panel["date"] = pd.to_datetime(panel["date"])
    btc["date"] = pd.to_datetime(btc["date"])

    panel = panel.merge(
        btc[["date", "price", "volume", "ret"]].rename(
            columns={
                "price": "btc_price",
                "volume": "btc_volume",
                "ret": "btc_ret",
            }
        ),
        on="date",
        how="left",
    )
    panel["month"] = panel["date"].dt.to_period("M")
    panel = panel.sort_values(["coin_id", "date"])

    print(f"数据加载完成，共 {len(panel)} 行，{panel['coin_id'].nunique()} 个币种")
    print("开始计算 STR 和 STV...")

    results = []
    grouped = panel.groupby(["month", "coin_id"], sort=True)
    for (month, coin_id), group in tqdm(grouped, total=grouped.ngroups, desc="Processing coin-months"):
        result = compute_str_stv(group, theta, delta)
        result["coin_id"] = coin_id
        result["month"] = str(month)
        results.append(result)

    salience_df = pd.DataFrame(results)
    salience_df = salience_df.dropna(subset=["STR", "STV"]).reset_index(drop=True)
    salience_df = salience_df[["coin_id", "month", "STR", "STV"]]

    print("\nSTR 和 STV 计算完成！")
    print(f"有效样本数: {len(salience_df)}")
    print(f"涉及币种数: {salience_df['coin_id'].nunique()}")
    print(f"涉及月份数: {salience_df['month'].nunique()}")

    salience_df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\n结果已保存至: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
