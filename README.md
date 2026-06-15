# Crypto Salience Replication

本项目是对论文 **"Salience and Cryptocurrency Returns: Evidence from Bitcoin-Based Predictive Signals"** 的部分复刻研究。

## 项目目标
- 复现论文中 STR（回报显著性）和 STV（成交量显著性）两个核心指标
- 复现 Table 1（投资组合排序）和 Table 2（Fama-MacBeth 回归）
- 验证以比特币为参考基准的显著性理论在加密货币市场的有效性

## 数据来源说明
- 原论文使用 CoinMarketCap 完整历史数据（含 delisted 币种）
- 本复刻目前使用公开 API 数据（CoinGecko / CryptoCompare），样本为 Top 200-500 币种
- 详细数据局限性见 `reports/replication_notes.md`

## 文件结构
- `src/`：核心代码模块
- `notebooks/`：探索性分析与验证
- `data/`：数据文件
- `results/`：复刻结果表格

## 如何运行
（后续补充）

## 参考文献
- 原论文标题及作者（待补充）
- Bordalo et al. (2013) Salience and Asset Prices
- Liu et al. (2022) Common Risk Factors in Cryptocurrency

## 作者
TidalFlux
复刻日期：2026年6月
