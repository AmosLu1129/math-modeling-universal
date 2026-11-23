# 模型选型目录（问题类型 → 模型族 → 工具）

按赛题小问的类型查表选型。每个小问至少准备「主模型 + 对照模型」。

## 问题类型映射表

| 问题类型 | 常用模型族 | Python 工具 |
|---|---|---|
| 优化决策（资源配置/排班/路径/选址） | 线性/整数/混合整数规划、多目标规划（加权/ε-约束）、动态规划、启发式（遗传/模拟退火） | scipy.optimize.linprog/milp、PuLP、OR-Tools、pymoo、DEAP |
| 预测（回归/时间序列） | 线性/岭回归、ARIMA/SARIMA、Prophet、XGBoost/LightGBM、LSTM/GRU、灰色预测 GM(1,1) | statsmodels、scikit-learn、xgboost、PyTorch |
| 分类/识别 | Logistic、SVM、随机森林、集成学习、CNN | scikit-learn、PyTorch |
| 聚类/分区/划片 | K-Means、DBSCAN、层次聚类、谱聚类、模糊 C 均值 | scikit-learn |
| 评价/决策 | 层次分析 AHP、TOPSIS、熵权法、灰色关联分析、模糊综合评价、主成分分析 | numpy/pandas 手工实现 |
| 动态系统（物理/工程） | ODE/PDE、差分方程、状态空间、系统动力学 | scipy.integrate.solve_ivp、数值差分 |
| 排队/随机过程 | M/M/c 排队、马尔可夫链、蒙特卡洛模拟、随机游走 | simpy、numpy.random |
| 网络/图 | 最短路、最大流、最小生成树、关键节点、PageRank | networkx |
| 统计检验/实验设计 | 假设检验、方差分析、回归诊断、信度效度 | scipy.stats、statsmodels |
| 图像/信号处理 | 滤波、傅里叶变换、特征提取、图像分割 | numpy、scipy.signal、OpenCV |

## 选型原则

- **可解释性优先**：竞赛论文要讲清机理，优先统计/机理模型；数据量大且机理不清时再上机器学习。
- **复杂度匹配**：模型复杂度与数据量、求解时间匹配；能用简单模型说清就不用复杂模型。
- **多目标问题**：先建单目标主模型 + 灵敏度分析，再讨论多目标权衡（加权/帕累托）。
- **数据不足**：优先机理模型、排队论、蒙特卡洛；数据充足才考虑数据驱动模型。
- **对照设计**：每个小问保留 1 个对照模型，用于检验环节的鲁棒性对比。

## 常用指标速查

- 回归：R²、RMSE、MAE、MAPE
- 分类：准确率、精确率、召回率、F1、AUC
- 聚类：轮廓系数、Davies-Bouldin、CH 指数
- 优化：目标函数值、约束违反量、与上下界的差距
- 时序：RMSE、MAE、MAPE、方向准确率
