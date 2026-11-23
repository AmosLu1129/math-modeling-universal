# LaTeX / Typst 排版与三线表避坑手册

## 1. 跨平台字体与电子版规范
- **ctex 字体**：模板已去掉 `fontset=mac` 写死，由 `ctexart` 按系统自动选择（Windows 用宋体/黑体，macOS 用 Songti SC/Heiti SC，Linux 用 Fandol）。
- **listings 防未嵌入仿宋（STFangsong）**：`\ttfamily` 默认可能映射仿宋，导致 `pdffonts` 报 `non-embedded font`；在 `\lstset` 使用 `basicstyle=\ttfamily\songti\small`（中文回宋体）或先试英文等宽，编译后用 `pdffonts` 复查无 Type 3 / 未嵌入字体。
- **国赛电子版**：去掉承诺书、编号页与目录页（删除 `\tocpage` 与旧页码重置），首页即为摘要专用页（页码从 1 开始）。
- **链接框清零**：`\usepackage[hidelinks]{hyperref}`，防止 `\cite`/`\ref` 在 PDF 中出现彩色边框。
- **tectonic 慢编译**：首次加载大中文字体需数分钟且内存高，先观察日志勿强杀；离线可加 `--only-cached`。

## 2. 路径、宏包与增量编译陷阱
- **文件路径纪律**：被 `main.tex` 从同目录 `\input` 的文件（如 `references.tex`）必须写在 `main.tex` 同目录，勿误写进 `sections/` 导致编译仍读模板占位文献。
- **插图与表格相对路径**：模板在 `output/paper/` 时，引用 `work/figures/` 与 `work/tables/` 必须写 `../../work/figures/...` 与 `../../work/tables/...`。
- **编辑 `main.tex` 后查宏包**：确保 `graphicx / float / amsmath / amssymb / booktabs / listings / hyperref / array` 齐全且无重复定义。
- **Overfull 清洁查法**：增量编译时 `main.log` 可能残留旧行号 Overfull，复核前先删除旧 `.log/.aux` 再干净重编两遍。

## 3. 三线表生成（`make_tables.py`）四条硬契约（防静默出错）
1. **`%` 双转义吞整行**：`replace("%", "\\\\%")` 会生成 `\\%`，在 `tabular` 中 `\\` 被当换行、`%` 成注释，导致整行后半静默消失。正确写法：`re.sub(r"(?<!\\)%", r"\\%", s)`。
2. **`_ # &` 只在数学模式外转义**：按 `re.split(r"(\$[^$]*\$)")` 分段，保护 `$Z_1$` 下标，同时转义正文明文 `N_pen0`。
3. **题注里的 `#` 必须转义**（`caption.replace("#", "\\#")`），否则 `nameref` 报错。
4. **浮动体不嵌套**：若生成的 `*.tex` 已自带 `\begin{table}`，正文直接 `\input`，禁止再套一层 `\begin{table}`；表头缩短、单位移入题注；长表格用 `\small`/`\footnotesize` 或改为逐行记录式，换行用 `>{\raggedright\arraybackslash}p{宽}`。

## 4. 公式与页数预算
- 公式编号一律 `\label` + `\eqref`，禁止硬编码“式(5)”；多行长盒式公式用 `\boxed{\begin{gathered}...\end{gathered}}`。
- 参考文献优先用 Crossref API 按 DOI 补全卷/期/页，先 `html.unescape` 再转义 `&`→`\&`，严禁出现本机绝对路径。
- **压页数纪律**：国赛正文含摘要通常 ≤20 页，美赛总页数 ≤25 页（Report on Use of AI 不计入）。**压页数优先删并冗余文字与明细表，禁止通过缩小插图（导致字号 <5pt）绕过。**
