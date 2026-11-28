# 高级图模板库（现成脚本，可直接改数据复用）

`_shared/scripts/advanced_templates/` 内置 **16 个**出版级图模板（含可直接运行的 Python 脚本，支持零参数默认演示及 `--config data.json --out-stem ...` 注入赛题数据）。当论文需要这些图型时，优先复用模板，而不是从零写。

## 模板清单

| id | 图型 | 适用场景 | 脚本 |
|---|---|---|---|
| `morandi-3d-bar-heatmap` | **莫兰迪 2D 瓷砖热图 + 3D 立体柱状热图双联** | 二维参数空间/耗电/磨损率全貌展示（左精读+右立体冲击力，自动防遮挡视角） | `make_morandi_3d_bar_heatmap.py` |
| `morandi-3d-surface-proj` | **莫兰迪 3D 响应曲面 + 底面等高投影** | 连续二元相变场、温度×老化悬崖、双参数敏感曲面 | `make_morandi_3d_surface_proj.py` |
| `morandi-ridgeline` | **莫兰迪多组层叠山脊图（KDE）** | 多情景/多时代/多方案后验分布形态对比 | `make_morandi_ridgeline.py` |
| `morandi-dumbbell` | **莫兰迪前后对比哑铃图 + 增益徽章** | Before-vs-After 结构性改进视觉证明（替代呆板分组柱图） | `make_morandi_dumbbell.py` |
| `morandi-sankey-flow` | **莫兰迪多级流动桑基图** | 能耗预算、客流/资金/票权流向分配展示 | `make_morandi_sankey_flow.py` |
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

1. 从 `_shared/scripts/advanced_templates/scripts/templates/` 把对应脚本复制到项目的 `work/code/` 或临时目录，替换示例数据（其中 `morandi-*` 模板可直接传 `--config work/tables/fig_data.json --out-stem work/figures/fig_xx` 零改代码出图）。
2. 运行脚本（PNG/PDF/SVG 三格式输出，300 DPI，纯矢量无位图嵌入）。
3. 套用本技能样式规范：最终尺寸、跨平台字体、`stixsans` 数学上下标、编号题注，然后照常过自检闭环。

或者直接调用渲染器：

```bash
python _shared/scripts/advanced_templates/scripts/render_template.py --list   # 列出全部 16 个模板
python _shared/scripts/advanced_templates/scripts/render_template.py morandi-3d-bar-heatmap --project work/scratch
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
