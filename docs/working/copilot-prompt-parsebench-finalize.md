# Copilot 任务：在公司电脑上复核并定稿 ParseBench 报告（精简版）

## 准备：从 GitHub 下载 3 个文件到工作目录

| 文件 | 放到 |
|---|---|
| `tools/parsebench_nodeep.py` | 工作目录\tools\ |
| `tools/parsebench_verify.py` | 工作目录\tools\ |
| `docs/working/parsebench-summary.md` | 工作目录\docs\working\ |

然后把下面「Prompt」整段粘给 Copilot。

## Prompt

```text
在工作目录执行，先运行 $env:PYTHONUTF8 = "1"。
规则：不调用任何 API；不改 runs\ 和 tools\ 下的任何文件；只允许改 docs\working\parsebench-summary.md。
<INF时间戳> 和 <Azure时间戳> 去 runs\ 下找实际目录名（parsebench_inf_* 和 parsebench_azure_*，不要选带 _nodeep 的）。

1. 重现消融（不调 API）：
   tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_nodeep.py runs\parsebench_inf_<INF时间戳>
   tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_score.py runs\parsebench_inf_<INF时间戳>_nodeep

2. 复核：
   tools\vendor\.venv-parsebench\Scripts\python tools\parsebench_verify.py runs\parsebench_inf_<INF时间戳> runs\parsebench_azure_<Azure时间戳>
   它会生成 docs\working\parsebench-verify.md。

3. 按复核结果修订 docs\working\parsebench-summary.md：
   a. 全部一致：把开头「数字来源说明」那段引用块替换为
      > **已复核**：<今天日期> 在公司电脑用 tools/parsebench_verify.py 逐项比对，N/N 项与落盘结果一致，明细见 docs/working/parsebench-verify.md。
   b. 有不一致：把总结里对应数字改成 parsebench-verify.md「落盘结果」列的值；
      若某项 verdict 改变（A 更高 = Infinity 更高，B 更高 = Azure 更高），同步改 §1 结论摘要和 §6 判断表里引用它的句子；
      「数字来源说明」替换为「已复核并更正 K 项」，文末加「## 复核更正」逐项列出 原值 → 更正值。
   c. 看 parsebench-verify.md 第 2 节：若 paragraphs_with_bbox 不到 files 的一半，
      在 §4 Visual Grounding 小节开头加一句：
      「**注意**：公司网关返回的 analyzeResult 中只有 X/500 份带段落 bbox，Azure 的 Visual Grounding 被系统性低估，本维度两边不可比。」
      并在 §1 第 4 条和 §6 表 bbox 一行末尾加「（不可比，见 §4）」。

4. 如果本机有 pandoc，运行 pandoc docs\working\parsebench-summary.md -o docs\working\parsebench-summary.docx；没有就跳过，不要安装。

5. 最后告诉我三件事：verify 输出的第一行（N/N 项一致）、paragraphs_with_bbox 的数字、第 3 步改了什么。
```

## 最终报告

`docs\working\parsebench-summary.md`（或 `.docx`）。附件：`parsebench-results.md`（完整数据）、`parsebench-verify.md`（复核明细）。
