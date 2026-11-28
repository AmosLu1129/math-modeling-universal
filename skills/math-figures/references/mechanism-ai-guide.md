# AI 视觉资产 + 矢量总装配双层机理图指南（形态 A & 形态 B，v4.2）

> 定位：解决“纯手写 SVG 缺写实工业/物理质感、纯生图工具无法控制精确数学公式与字母”的双重矛盾。**常规纯逻辑框图仍可用纯 HTML/SVG+Math 或 `matplotlib`；涉及物理设备、地形/古建筑、生物组织等实体视觉组件时，优先走下方双层管线。**

## 一、双模态架构选择与预算

- **形态 A（首选，复杂架构 / 设备机理双层总装）**：只外包生成 **2–4 个独立写实 3D 组件**（纯白底 + 零文字），经 `asset_cutout.py` 边界泛洪去背裁剪出透明 RGBA PNG 后，交由 `render_html_figure.py` 将 **HTML CSS 网格卡片 + 语义 SVG 贝塞尔箭头 + 印刷级数学公式 + 去背 3D 组件** 确定性合成为 300 DPI PNG 与矢量 PDF。
  - **组件生成预算控制**：全篇论文建议 **1–2 张核心枢纽图**采用外包 3D 组件总装；其余流程图与模型框图直接使用纯 HTML+SVG+Math 模板，避免视觉风格飘移或生图耗时过长。
- **形态 B（连续空间不可拆场景）**：适用于流场、热传导切片、微观组织交互等连续背景，生成无文字低饱和基底图后，用原生视觉测出安全区相对坐标，再叠 SVG 编号胶囊与引线并过 `svg_audit.py`。

### 形态 A 标准工具链与 Nano Banana 人工外包接力模板

1. **生成起手画布**（零外包资产也可直接画出顶刊卡片架构图）：
   ```bash
   python _shared/scripts/render_html_figure.py --init-template work/figures/fig_arch.html
   ```
2. **如需人工在 Nano Banana 生成独立 3D 视觉组件**（严格不自行乱改，按 `work/human_requests/req_XX.md` 提交工单并自带纯 SVG Fallback）：
   可直接复制下方英文结构化 Prompt（修改方括号主题即可）：
   ```text
   Isolated semi-realistic 3D isometric scientific render of [OBJECT: e.g., cross-section of a smartphone lithium-ion battery pack / weathered sandstone church stair tread], clean pure white solid background (#FFFFFF), soft studio key light from upper-left 45 degrees, subtle neutral soft contact shadow underneath only. Palette constrained strictly to muted Morandi scientific tones: slate steel blue (#4E6E8E), muted terracotta (#C86D5B), sage green (#6D9A87), warm sandstone gray (#9BA4AE), crisp clean edges, subtle matte material texture. STRICTLY NO text, NO letters, NO numbers, NO callout lines, NO arrows, NO labels, NO watermarks anywhere in the image.
   ```
3. **自动泛洪去背与羽化裁剪**（完整保留物体内部白色高光，绝不穿透镂空）：
   ```bash
   python _shared/scripts/asset_cutout.py --in work/figures/assets/raw_comp.png --out work/figures/assets/comp_cutout.png --threshold 242 --feather 1.5 --pad 8
   ```
4. **HTML + SVG + Math 确定性渲染与自检**：
   ```bash
   python _shared/scripts/render_html_figure.py --html work/figures/fig_arch.html --out-png work/figures/fig_arch.png --out-pdf work/figures/fig_arch.pdf --width 1200 --height 660 --scale 2.5 --dpi 300
   python _shared/scripts/figure_qa.py check work/figures/fig_arch.png --min-dpi 300
   python _shared/scripts/figure_qa.py access work/figures/fig_arch.png
   ```

---

## 二、什么时候用形态 B（连续基底图 + SVG 标注）

- 建议用：生物/医学**有机形态**（细胞、组织、信号通路）、连续物理场"期刊图形摘要"质感。
- 不建议用：纯逻辑流程、离散组件拓扑——优先走上面形态 A。
- 铁律：**图字分离**——AI 只生成无文字基底图，中文/英文数学标注一律用 SVG/HTML 叠加；AI 图里依赖生成文字 = 必然乱码。

## 三、形态 B 工作流总览（原有流程兼容保留）

1. 生成**无文字基底图**：
   - **首选（宿主生图能力）**：调用当前 Agent 内置生图工具或子代理，严格传入下方「图字分离」结构化提示词，保存至 `work/figures/mech_xx_base.png`。
   - **CLI 兜底**（无内置生图能力时）：按需使用路径 A / B 调用 `_shared/scripts/ai_figure_gen.py`。
2. **原生视觉复核基底图**：用原生看图/读取工具审查乱码/畸形/多余文字或编号/结构错误/配色，不过关就重出。
3. **定位安全区坐标**：用视觉读出主体区域与空白区相对坐标（%），确保标注只放安全区。
4. SVG 叠标注（编号胶囊 + 引线 + 标题带/图例带，规范见下）。
5. `render_svg.py` 合成渲染（`<image>` 嵌入基底图，白底画布）。
6. 运行 `svg_audit.py` 几何与对比度审计 + 原生视觉复核，双过后再进 `work/figures/`。

## 三、路径 A：OpenAI 兼容生图接口（如 gpt-image-2）

### 前置
- 若当前网络环境需要通过 HTTP/HTTPS 代理访问目标 API，请按实际网络配置标准环境变量 `HTTPS_PROXY` / `HTTP_PROXY`（直连可忽略）。

### 命令
```bash
export OPENAI_API_KEY='<YOUR_OPENAI_API_KEY>'
export OPENAI_BASE_URL='<YOUR_OPENAI_COMPATIBLE_BASE_URL>'   # 例如 https://api.openai.com/v1 或自定义 OpenAI 兼容端点
python _shared/scripts/ai_figure_gen.py \
  --prompt "$(cat prompts/mech_prompt.txt)" \
  --out work/figures/mech_xx_base.png \
  --model gpt-image-2 --size 1536x1024,1024x1024 --quality low,medium --retries 4
```

### 提示词模板（图字分离，复制后改主题）
```
Scientific graphical abstract illustration, [主题一句话],
Composition: [左/中/右三段布局描述]. Style: semi-realistic 3D scientific
illustration, soft studio lighting from upper left, smooth gradients, subtle
film grain texture, glossy material highlights, professional limited color
palette of deep navy blue, forest green, amber brown and indigo purple, clean
white background with very light blue gradient, high detail, elegant and
academic. No text, no letters, no labels, no numbers, no watermark.
```

### 常见网关注意事项
1. 部分 API 网关可能拦截默认 SDK 的 User-Agent（返回 403）→ 脚本已默认发送标准浏览器 UA。
2. 网关常见 60s 硬超时（nginx 默认）→ `high`/`medium` 档易被掐断，**`low` 档稳定性更高**；脚本会自动按 `size × quality` 降档重试。
3. 接口返回 `data[0].url`（非 `b64_json`）→ 脚本已支持自动下载保存。
4. 遇到 503 服务繁忙（如 `"No available compatible accounts"`）→ 脚本会在等待后自动重试。
5. 若目标端点报 502 不兼容错误，请检查并切换到对应兼容的模型名称（例如 `gpt-image-2`）。

## 四、路径 B：火山引擎 Seedream-5.0（可选）

### 配置
```bash
export OPENAI_API_KEY='<YOUR_ARK_API_KEY>'
export OPENAI_BASE_URL='https://ark.cn-beijing.volces.com/api/v3'
```
**国内直连，通常无需代理**（配置全局代理反而可能导致连接异常）。

### 命令
```bash
python _shared/scripts/ai_figure_gen.py \
  --prompt "$(cat prompts/mech_prompt.txt)" \
  --out work/figures/mech_xx_base.png \
  --model doubao-seedream-5-0-260128 \
  --size 2048x2048,2560x1440,1440x2560 --quality low --watermark false --retries 2
```

### 常见接口注意事项
1. **模型名**：实际可用模型 ID 请通过 `/v3/models` 查询，例如 `doubao-seedream-5-0-260128`；未在控制台开通的模型会返回 `ModelNotOpen`。
2. **尺寸下限**：`size` 像素数必须 ≥ 3,686,400（约 1920×1920 起）；`1536x1024` 等会报 `InvalidParameter`。脚本已对 seedream 自动用 `2048x2048,2560x1440,1440x2560`。
3. 响应同样返回 `data[0].url`（TOS 签名链接，24h 有效），脚本自动下载；生成约 10-20s，无 60s 网关超时问题。
4. `quality` 参数接受但可能被忽略，不依赖它。
5. **默认带"AI生成"水印**：论文图必须加 `--watermark false`（脚本已支持）。

### 已踩坑补充（2026-08-14，2024 国赛 E 实测）

- **"侧倾/倾斜"类模糊动词会被画成侧翻**：提示词写"正在调头（车身侧倾约20度）"，Seedream 直接画出一辆侧翻在地的车。修复：改为确定性描述"车身保持水平、四个车轮着地、车头略偏向左上（缓慢转弯）"，重生成后 vision 复核通过。教训：涉及车辆姿态、方向、动作的元素，一律用"水平/着地/朝向"等可核验词，禁止"侧倾/倾斜/俯仰"。

### Seedream 提示词纪律（2026-08-12 用户经验 + 实测验证，必读）

**原理**：Seedream 模型本身精度不差，但**提示词联想/推断能力弱**——给模糊描述它就会自由发挥、漏元素。因此调用 Seedream 时提示词必须**更精细、更结构化、更确定**，尽量少留"自由发挥"空间。

**写法要点**：
- 分块写：`【任务】【画布】【版面布局】【风格】【背景】【配色】【禁止】`。
- 用数字标定：版面比例（如"左侧约22%宽"）、光源角度（"左上45度柔光"）、投影不透明度（"约20%"）。
- 用**必须 / 只允许 / 禁止**句式，不给可选项；"只允许使用以下颜色…禁止出现其它颜色"。
- 每个元素写清：位置 + 形状 + 颜色（直接给 HEX）+ 细节（有无纹理、比例、朝向）。
- **禁用模糊形容词**代替具体参数（"精美/优雅"这类要翻译成"哑光质感/边缘轻微高光/胶片噪点"）。
- 提示词以"【任务】生成一张科研论文图形摘要基底图，画面内不出现任何文字、字母、数字。"开头，结尾列【禁止】清单（文字/水印/卡通/强发光/多余装饰）。

**对比验证（2026-08-12 实测）**：同一主题下，结构化确定性提示词生成结果**完全贴合规定布局、元素齐全、配色干净**；叙事型提示词生成结果**右侧图表缺失、细节模糊**。

**完整模板（本次实测可用，复制改主题）**：
```
【任务】生成一张科研论文图形摘要基底图，画面内不出现任何文字、字母、数字。
【画布】横向 16:9 构图。
【版面布局（从左到右固定三块区域，比例严格）】
第1块（左侧约22%宽）：[元素 A 描述：形状+颜色HEX+朝向+细节约束]。
第2块（中间约56%宽）：[元素 B 描述：结构+各部件颜色HEX+比例要求]。
第3块（右侧约22%宽）：[元素 C 描述：图表/面板细节+颜色HEX]。
【风格】半写实3D渲染，禁止卡通；光源为左上45度柔光，物体右下方有柔和投影（不透明度约20%）；表面为哑光质感，仅边缘轻微高光；整体叠加轻微胶片噪点纹理；轮廓线清晰。
【背景】从纯白#FFFFFF到极浅蓝#EAF1F7的纵向渐变。
【配色】整张图只允许使用以下颜色（低饱和科研期刊风格）：[HEX 列表及用途]。禁止出现其它颜色；禁止高饱和、荧光、高反差配色；背景为纯白到极浅同色系的柔和渐变。
【禁止】任何文字、字母、数字、标签、水印；禁止卡通化；禁止强烈发光或光晕；禁止多余装饰元素。
```

**路径 A（gpt-image-2）不受此限制**：其提示词联想能力强，可用叙事型提示词；但若追求同一确定性，同样适用本模板。

## 五、配色标定规范（科研期刊风格，2026-08-12 用户要求）

**总则**：专业科研期刊风格 · 颜色柔和渐变 · 高级感；**禁止高反差、禁止高饱和、禁止荧光/霓虹色**。

**技术细则**：
1. **有限色板**：整图 ≤ 10 色，全部中低饱和（HSL 饱和度建议 ≤ 40%）、中低明度差；每个颜色给 HEX + 一句话用途。
2. **背景**：纯白 → 极浅同色系纵向渐变（如 `#FFFFFF → #EFF4E8` / `#EAF1F7`），渐变幅度小、平滑，不做强对比背景。
3. **区分靠"同族邻近 + 明度微差"**：相邻结构用同色相不同明度或邻近色相（绿↔蓝绿↔蓝、紫↔蓝紫），**避免互补色直撞**（纯红+纯绿、纯橙+纯蓝）。
4. **强调色**：关键主体允许 1-2 个强调色（琥珀/靛紫）做焦点，但只占小面积，不喧宾夺主。
5. **光影**：用柔和渐变表达（边缘轻微高光、约 20% 柔和投影），禁止硬边高反差光斑。
6. **灰度可分（黑白打印）**：各结构主色相对亮度拉开（PIL 可校验），禁止"蓝紫同亮度"这类黑白下混淆的组合。
7. **提示词写法**：`【配色】整张图只允许使用以下颜色：[HEX 列表及用途]。禁止出现其它颜色；禁止高饱和、荧光、高反差配色。`

**推荐低饱和科研色板**（实测范例：植物体细胞半剖图即为该风格，用户认可）：

| 用途 | 颜色 | HEX |
|---|---|---|
| 主色-冷（结构/数据主体） | 深蓝 / 森林绿 | `#4A6A92` / `#4E7A5C` |
| 强调（焦点/关键结构） | 琥珀 / 靛紫 | `#96713F` / `#5D5480` |
| 浅填充（半透明结构/液泡） | 淡蓝 / 浅绿 / 浅紫 | `#C9DFEE` / `#DCE8DA` / `#E5E1EE` |
| 中性（膜/线/界面/投影） | 灰 / 浅灰 / 白 | `#8A8F98` / `#D8DDE3` / `#FFFFFF` |
| 有机肤色（生物题材） | 肤色 | `#E8C39E` |

**自检**：vision 复核必查配色项——有无高饱和撞色、渐变是否平滑、黑白灰度可分。

## 六、标注与合成规范（与 flowchart 一致）

- 配色：低饱和四色 `#4A6A92` / `#4E7A5C` / `#96713F` / `#473B76`；白底画布；跨平台中文字体栈（`"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif`）。
- 编号胶囊：`fill=#FFFFFF fill-opacity=0.92` + 同色 1.5 描边 + 白底圆角（rx=高/2）；编号 ①②③④。
- 引线：同色 1.2 虚线（stroke-dasharray="4 4"），只指到区域边缘，不穿过主体。
- 标题带/图例带：白底 + 细灰分隔线 `#D8DDE3`；主标题 26-27 加粗、副标题 15。
- 步骤：先用原生视觉确定主体/空白区坐标（相对 %），标签只放空白区；合成用 `render_svg.py` 并过 `svg_audit.py`。

## 七、QA 铁律

- AI 基底图未过 vision 复核**禁止进论文**。
- 中文标注必须 SVG 叠加，禁止依赖 AI 图内文字。
- 合成图必跑像素检查（无裁切/留白均衡）+ vision 复核（乱码/遮挡/重叠）。
- 配色必查：低饱和、渐变平滑、灰度可分（见第五节自检）。

## 八、参考产物

- 2026-08-12 样例：`outputs/mechanism_samples/ai_base_fetal_screening.png`（基底图）、
  `ai_fetal_screening_labeled.svg/.png`（合成标注版，1536×1180 → 3000×2305）、
  `ai_base_fetal_screening_seedream_v2.png`（Seedream 结构化提示词版）、
  `ai_plant_cell_seedream.png`（植物体细胞三维半剖，配色规范范例）。

## 九、学科分类提示词模板（按题型复用，2026-08-13 新增）

把实测通过的提示词按学科沉淀，复制后改主题即可；仍需遵守图字分离 + vision 复核 + SVG 标注纪律。

### 物理/光学类：红外干涉测厚（2025 国赛 B 实测）

```
【任务】生成一张科研论文图形摘要基底图，画面内不出现任何文字、字母、数字。
【画布】横向 16:9 构图。
【版面布局（从左到右固定三块区域，比例严格）】
第1块（左侧约22%宽）：一个简洁的红外光源装置（圆角矩形灯体，深蓝#4A6A92，正面一个极浅蓝#C9DFEE发光面），从左向右射出一束斜向下的平行红外光（琥珀色#96713F细光束，直线、带轻微透明），入射角约10度，指向右侧晶圆。
第2块（中间约56%宽）：一块半导体晶圆片半剖结构，斜放（与水平面约15度夹角），由两层组成——上层是较薄的外延层（森林绿#4E7A5C，厚度约为下层厚度的十分之一，表面平整），下层是较厚的衬底（靛紫#5D5480，带细密斜向纹理）；外延层与衬底之间有一条清晰分界线（中性灰#8A8F98细线）。从外延层上表面反射出一条较细光束（琥珀#96713F），从外延层与衬底分界面反射出一条稍粗光束（森林绿#4E7A5C），两条反射光束在晶圆右上方平行射出并轻微汇聚；两条光束之间用浅灰#D8DDE3画出极淡的干涉条纹纹路（细密明暗相间，无文字）。
第3块（右侧约20%宽）：一个横向展开的干涉光谱波形带——一条平滑连续的正弦波纹曲线（森林绿#4E7A5C），上下包络为淡绿#DCE8DA渐隐填充，波形带右端比左端略高，暗示强度随波数变化；波形带下方是一条浅灰#D8DDE3细基线。
【风格】半写实3D渲染，禁止卡通；光源为左上45度柔光，物体右下方有柔和投影（不透明度约20%）；表面为哑光质感，仅边缘轻微高光；整体叠加轻微胶片噪点纹理；轮廓线清晰；透视轻微俯视（约20度）。
【背景】从纯白#FFFFFF到极浅蓝#EAF1F7的纵向渐变。
【配色】整张图只允许使用以下颜色（低饱和科研期刊风格）：深蓝#4A6A92（光源装置）、森林绿#4E7A5C（外延层与主反射光束）、琥珀#96713F（入射光束与上表面反射光束）、靛紫#5D5480（衬底）、淡蓝#C9DFEE（光源发光面与背景细节）、浅绿#DCE8DA（波形包络）、浅紫#E5E1EE（衬底纹理淡色）、中性灰#8A8F98（分界线与细线）、浅灰#D8DDE3（干涉纹路与基线）、纯白#FFFFFF（背景）。禁止出现其它颜色；禁止高饱和、荧光、高反差配色；背景为纯白到极浅同色系的柔和渐变。
【禁止】任何文字、字母、数字、标签、水印；禁止卡通化；禁止强烈发光或光晕；禁止多余装饰元素。
```

- 标注锚点复核（必做）：先用原生看图工具读出「光源中心 / 入射光束区域 / 外延层上表面中心 / 分界面中心 / 衬底中心 / 两条反射光束出口 / 波形带中心」的相对坐标（%），再据此放编号胶囊与引线，避免偏移/溢出/遮挡。

### 交通/警务类：交巡警平台调度（2011 国赛 B 实测）

```
【任务】生成一张科研论文图形摘要基底图，画面内不出现任何文字、字母、数字、编号、序号、计数圆点。
【画布】横向 16:9 构图。
【版面布局（从左到右固定三块区域，比例严格）】
第1块（左侧约22%宽）：A区局部道路网络俯视图——浅灰色细道路线连接白色小圆点（路口节点），深蓝色实心小圆点表示交巡警平台，一辆白色警车（车身保持水平、四个车轮着地、车头朝右上）停在平台旁；平台周围有极浅绿色半透明大圆盘表示3分钟覆盖范围（直径约为画面高度的35%）。所有圆点必须是纯色，禁止圆点内/旁出现数字。
第2块（中间约56%宽）：全市六区路网俯视——六个区块分别用深蓝#4A6A92、森林绿#4E7A5C、琥珀#96713F、靛紫#5D5480、浅蓝#C9DFEE、浅绿#DCE8DA填充，每个区块是完全空白的纯色块，禁止区块内写编号；区块间由深灰道路细线连成网络，路网节点为白色小圆点，平台为深蓝实心小圆点，跨区道路为稍粗深灰线。
第3块（右侧约22%宽）：围堵封控概念——几条道路向右延伸，道路末端设置三个红色#B64342实心圆形检查点横向排列，检查点之间用半透明红色虚线弧形连接成封堵圈；一辆白色警车（车身水平、四轮着地）停在检查点旁。
【风格】半写实3D俯视渲染，禁止卡通；左上45度柔光，物体右下方柔和投影约20%；哑光质感，仅边缘轻微高光；轮廓线清晰；轻微胶片噪点。
【背景】纯白#FFFFFF到极浅蓝#EAF1F7纵向柔和渐变。
【配色】只允许：#4A6A92 #4E7A5C #96713F #5D5480 #C9DFEE #DCE8DA #E5E1EE #8A8F98 #D8DDE3 #B64342 #FFFFFF。禁止其它颜色、高饱和、荧光、高反差。
【禁止】任何文字、字母、阿拉伯数字、编号、序号、标签、水印；禁止在区块/道路/圆点/车辆上出现数字标记；禁止卡通、发光光晕、多余装饰。
```

- 实测：第一版仍画出 1/2/3/4/6 编号 → 在【任务】与【禁止】中重复强调“禁止任何编号/计数圆点、区块必须纯色”后复生成 PASS。
- 标注合成：vision 先给安全区坐标（%），SVG 只放三枚白底描边胶囊标签（覆盖圈/六区路网/最小围堵圈）+ 底部图例，引线虚线不穿主体；合成后 vision 五项 PASS。
