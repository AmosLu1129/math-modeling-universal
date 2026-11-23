# 高级图模板库（现成脚本，可直接改数据复用）

`../_shared/scripts/advanced_templates/` 内置 11 个出版级图模板（含可直接运行的 Python 脚本）。当论文需要这些图型时，优先复用模板，而不是从零写。

## 模板清单

| id | 图型 | 适用场景 | 脚本 |
|---|---|---|---|
| `multiclass-shap-combo` | 多分类 SHAP 柱状 + 蜂群组合图 | 机器学习模型特征重要性解释 | `make_multiclass_shap_combo.py` |
| `paired-raincloud` | 配对云雨图 | 前后对比/配对设计，同时展示分布、散点与均值趋势 | `make_paired_raincloud.py` |
| `cv-roc-ci` | 交叉验证 ROC + 置信带 | 分类模型稳健性，AUC 均值±标准差 | `make_cv_roc_ci.py` |
| `taylor-diagram` | 泰勒图 | 多模型多指标综合评价（相关、标准差、RMSE） | `make_taylor_diagram.py` |
| `correlation-pairgrid` | 相关矩阵组合图 | 分布 + 拟合线 + 置信区间 + 相关系数 | `make_correlation_pairgrid.py` |
| `prediction-marginal-grid` | 预测 vs 真实 + 边缘分布 | 回归模型拟合效果总览 | `make_prediction_marginal_grid.py` |
| `rf-tpe-surface` | 超参调优 3D 曲面 | 展示搜索空间与响应面 | `make_rf_tpe_surface.py` |
| `grouped-corr-split-violin` | 下三角相关矩阵 + 半边小提琴 | 相关结构 + 分组分布对比 | `make_grouped_corr_split_violin.py` |
| `grouped-circular-heatmap` | 分组环形热图 | 多组多维指标环形呈现 | `make_grouped_circular_heatmap.py` |
| `urban-park-cooling-combo` | 堆叠柱 + 云雨 + 箱线组合图 | 多维指标综合对比（三面板合成） | `make_urban_park_cooling_combo.py` |
| `nature-chord-diagram` | 和弦图 | 流量/关系/转移矩阵（省份迁徙、行业关联等） | `make_nature_chord_diagram.py` |

## 用法

1. 从 `../_shared/scripts/advanced_templates/scripts/templates/` 把对应脚本复制到项目的 `work/code/` 或临时目录，替换其中的示例数据为 `results.json` 的真实数据。
2. 运行脚本（PNG/PDF/SVG 三格式输出，300 DPI）。
3. 套用本技能样式规范：最终尺寸、中文字体、编号题注，然后照常过自检闭环。

或者直接调用渲染器：

```bash
python ../_shared/scripts/advanced_templates/scripts/render_template.py --list   # 列出全部模板
python ../_shared/scripts/advanced_templates/scripts/render_template.py paired-raincloud --project 绘图复刻
```

## 实现要点（改数据时注意）

- **SHAP 组合图**：堆叠水平均值重要性条 + 每类蜂群条 + 特征值 colorbar。
- **配对云雨图**：半小提琴 + 抖动散点 + 箱体 + 均值菱形 + 连接配对均值线。
- **ROC 置信带**：各折曲线插值到共享 FPR 网格，画均值曲线 + 标准差带，图例写 AUC 均值±SD。
- **泰勒图**：极坐标，角度 = arccos(相关系数)，半径 = 模型标准差。
- **相关矩阵组合图**：下三角散点/拟合 CI，对角线直方图，上三角相关系数 + 显著性星号，发散色。
- **预测边缘分布**：预测 vs 真实散点 + 上/右直方图或 KDE。
- **3D 调优曲面**：`mpl_toolkits.mplot3d` 平滑响应面 + colorbar + 固定相机角度。
- **分割小提琴 + 相关矩阵**：带符号下三角标记矩阵 + 左右半小提琴分布对比。
- **环形热图**：极坐标条 + 翻转外标签 + 中央图例 + 分环色标。
- **和弦图**：外圈 Wedge 扇区 + 半透明 Bezier 丝带。
- **城市降温组合**：堆叠城市柱 + 云雨指标面板 + 箱线连接均值。

> 模板脚本用确定性模拟数据演示画法，**不要声称模拟值复现了某篇文献的结果**；换真实数据后所有数字以 `results.json` 为准。
