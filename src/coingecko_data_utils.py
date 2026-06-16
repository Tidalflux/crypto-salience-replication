from pathlib import Path

import pandas as pd
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "data" not in config:
        raise KeyError("config.yaml must define a top-level 'data' section")

    return config


def to_unix_timestamp(date_value, end_of_day=False):
    ts = pd.Timestamp(date_value)

    if end_of_day:
        ts = ts.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    return int(ts.timestamp())


def market_chart_to_daily_frame(data, coin_id):
    frames = []
    series_map = {
        "prices": "price",
        "market_caps": "market_cap",
        "total_volumes": "volume",
    }

    for source_key, value_col in series_map.items():
        values = data.get(source_key) or []
        if values:
            frame = pd.DataFrame(values, columns=["timestamp", value_col])
        else:
            frame = pd.DataFrame(columns=["timestamp", value_col])
        frames.append(frame)

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="timestamp", how="outer")

    columns = ["date", "price", "market_cap", "volume", "coin_id"]
    if merged.empty:
        return pd.DataFrame(columns=columns)

    merged = merged.sort_values("timestamp")
    merged["date"] = (
        pd.to_datetime(merged["timestamp"], unit="ms", utc=True)
        .dt.floor("D")
        .dt.tz_localize(None)
    )

    daily = (
        merged.groupby("date", as_index=False)
        .agg({"price": "last", "market_cap": "last", "volume": "last"})
        .sort_values("date")
    )
    daily["coin_id"] = coin_id

    return daily[columns]


def parquet_covers_date_range(path, start_date, end_date):
    if not path.exists():
        return False

    try:
        dates = pd.read_parquet(path, columns=["date"])
    except Exception:
        return False

    if dates.empty:
        return False

    observed_dates = pd.to_datetime(dates["date"])
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()

    return observed_dates.min() <= start and observed_dates.max() >= end


def add_public_api_hint(error):
    message = str(error)
    if "allowed time range" in message or "error_code': 10012" in message:
        return (
            f"{message}\n"
            "Hint: CoinGecko's public API may only allow historical range "
            "queries within the past 365 days. Use a recent date window for "
            "the free API, or switch to a paid API plan for older history."
        )
    return message
