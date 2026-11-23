# 项目骨架（可直接复制）

```bash
cp -R examples/project-skeleton ~/my-project
cd ~/my-project
# 1) 把题面放进 input/problem.pdf（或 problem.docx），数据放 input/data/
# 2) 复制控制面模板
cp ../path/to/math-modeling/_shared/templates/run_manifest.yaml work/run_manifest.yaml
# 3) 让 agent 用 $math-modeling-workflow 启动
```

产物契约：`output/paper/paper.pdf`、`output/code_appendix.pdf`、`output/submission/`。
