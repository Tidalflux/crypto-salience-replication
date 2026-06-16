# Crypto Salience Replication

本项目是对论文 **"Salience and Cryptocurrency Returns: Evidence from Bitcoin-Based Predictive Signals"** 的**部分复刻研究**。项目使用公开数据重新构建以 Bitcoin 为参考资产的加密货币显著性指标，并检验这些指标在近期市场中的预测能力。

## 项目目标

- 复现论文中的两个核心显著性指标：
  - **STR**：Return-based Salience，回报显著性
  - **STV**：Volume-based Salience，成交量显著性
- 复现主要实证检验：
  - **Table 1**：Quintile Portfolio Sorts，投资组合排序
  - **Table 2**：Fama-MacBeth 横截面回归
- 进行稳健性分析：
  - Top 50 大市值币种筛选
  - 显著性扭曲参数 `delta` 的敏感性检验
- 评估显著性理论在 2025--2026 年加密货币市场中的适用性。

## 数据来源与局限性

原论文使用 CoinMarketCap 的长周期历史数据，并包含已下架币种。由于公开数据可得性限制，本项目采用 CoinGecko 公共 API 构建近期样本：

- **主要数据源**：CoinGecko public API
- **样本窗口**：2025-06-15 至 2026-06-14，共 365 天
- **样本范围**：按 CoinGecko 当前市值下载 Top 150 加密货币的近一年数据
- **参考资产**：Bitcoin，作为 STR/STV 计算的基准资产
- **配置文件**：`config.yaml`

重要说明：本项目是**部分复刻**，样本期只有 13 个自然月，无法完全覆盖原论文 2016--2025 年的长周期数据，也未纳入完整 delisted coins。因此，本复刻更适合作为指标构建与实证流程的可复现验证，而不是对原论文数值结果的一比一重现。详细说明见 `reports/replication_notes.md`。

## 仓库结构

```text
crypto-salience-replication/
├── data/
│   ├── raw/                              # CoinGecko 单币种原始 parquet 文件
│   ├── btc_daily.parquet                 # Bitcoin 日度价格、成交量与收益
│   ├── coingecko_365days_coin_list.parquet
│   ├── crypto_panel_365days.parquet      # 合并后的日度面板数据
│   └── panel_with_salience.parquet       # 月度 STR/STV 指标
├── notebooks/
│   └── test_cryptocompare_key.py         # API 验证与探索性脚本
├── references/
│   └── salience-and-cryptocurrency-returns.pdf
├── reports/
│   ├── replication_notes.md              # 数据限制与复刻说明
│   ├── replication_report.tex            # LaTeX 复刻报告
│   └── replication_report.pdf            # 编译后的报告
├── results/
│   ├── table1_summary.csv
│   ├── table1_detailed.csv
│   ├── table2_fama_macbeth.csv
│   ├── robustness_top50_summary.csv
│   ├── robustness_top50_table1.csv
│   ├── sensitivity_delta_summary.csv
│   └── sensitivity_delta.csv
├── src/
│   ├── coingecko_data_utils.py           # CoinGecko 数据工具函数
│   ├── download_coingecko_365days.py     # 下载 CoinGecko 近 365 天数据
│   ├── merge_panel_and_returns.py        # 合并日度面板并计算日收益
│   ├── compute_str_stv.py                # 计算 STR/STV
│   ├── table1_portfolio_sorts.py         # Table 1 投资组合排序
│   ├── table2_fama_macbeth.py            # Table 2 Fama-MacBeth 回归
│   ├── robustness_top50.py               # Top 50 稳健性检验
│   └── sensitivity_delta.py              # delta 参数敏感性分析
├── config.yaml                           # 数据窗口、样本数与 salience 参数
├── requirements.txt
└── README.md
```

## 环境配置

建议使用 Python 3.11。

```bash
git clone https://github.com/Tidalflux/crypto-salience-replication.git
cd crypto-salience-replication

conda create -n crypto_replication python=3.11
conda activate crypto_replication

pip install -r requirements.txt
```

运行前可以先检查 `config.yaml`：

```yaml
data:
  start_date: "2025-06-15"
  end_date: "2026-06-14"
  top_n_coins: 150

salience:
  theta: 0.1
  delta: 0.7
```

注意：CoinGecko 免费 API 可能触发限流。完整下载 Top 150 币种需要较长时间；调试时可先把 `top_n_coins` 临时改为 20 或 50。

## 运行流程

按以下顺序运行即可复现主要结果。

### 1. 下载 CoinGecko 近 365 天数据

```bash
python src/download_coingecko_365days.py
```

输出：

- `data/raw/*.parquet`
- `data/coingecko_365days_coin_list.parquet`
- `data/coingecko_365days_failures.txt`，如存在下载失败记录

### 2. 合并日度面板并计算日收益

```bash
python src/merge_panel_and_returns.py
```

输出：

- `data/crypto_panel_365days.parquet`
- `data/btc_daily.parquet`

### 3. 计算 STR 和 STV

```bash
python src/compute_str_stv.py
```

输出：

- `data/panel_with_salience.parquet`

### 4. 复现 Table 1：投资组合排序

```bash
python src/table1_portfolio_sorts.py
```

输出：

- `results/table1_summary.csv`
- `results/table1_detailed.csv`

### 5. 复现 Table 2：Fama-MacBeth 回归

```bash
python src/table2_fama_macbeth.py
```

输出：

- `results/table2_fama_macbeth.csv`

### 6. 运行稳健性检验

```bash
python src/robustness_top50.py
python src/sensitivity_delta.py
```

输出：

- `results/robustness_top50_summary.csv`
- `results/robustness_top50_table1.csv`
- `results/sensitivity_delta_summary.csv`
- `results/sensitivity_delta.csv`

### 7. 编译复刻报告

如本地已安装 LaTeX，可运行：

```bash
cd reports
latexmk -pdf -interaction=nonstopmode -halt-on-error replication_report.tex
```

输出：

- `reports/replication_report.pdf`

## 当前进度

- [x] CoinGecko 近 365 天数据下载与处理
- [x] Bitcoin 基准资产提取
- [x] STR/STV 指标构建
- [x] Table 1：Quintile Portfolio Sorts
- [x] Table 2：Fama-MacBeth 回归
- [x] Top 50 大市值币种稳健性检验
- [x] `delta` 参数敏感性分析
- [x] LaTeX 复刻报告撰写

## 主要结果文件

| 文件 | 内容 |
| --- | --- |
| `results/table1_summary.csv` | STR/STV 五分位组合平均收益与 H-L 组合收益 |
| `results/table2_fama_macbeth.csv` | 每月 Fama-MacBeth 回归系数 |
| `results/robustness_top50_summary.csv` | Top 50 大市值样本的组合排序结果 |
| `results/sensitivity_delta_summary.csv` | 不同 `delta` 下的 H-L 组合结果 |
| `reports/replication_report.pdf` | 完整复刻报告 |

## 参考文献

- Cai, C. X., & Zhao, R. (2024). Salience theory and cryptocurrency returns. *Journal of Banking & Finance*, 159, 107052.
- Bordalo, P., Gennaioli, N., & Shleifer, A. (2012). Salience theory of choice under risk. *The Quarterly Journal of Economics*, 127(3), 1243--1285.
- Bordalo, P., Gennaioli, N., & Shleifer, A. (2013). Salience and asset prices. *American Economic Review*, 103(3), 623--628.
- Liu, Y., Tsyvinski, A., & Wu, X. (2022). Common risk factors in cryptocurrency. *The Journal of Finance*, 77(2), 1133--1177.

## 作者与联系方式

- 作者：TidalFlux
- 复刻日期：2026 年 6 月
- GitHub：<https://github.com/Tidalflux/crypto-salience-replication>

如有问题或建议，欢迎提交 Issue。
