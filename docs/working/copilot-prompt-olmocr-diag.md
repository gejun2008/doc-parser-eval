# Copilot 任务：olmOCR-Bench 两项补充诊断（页眉页脚注释 / old_scans 归因）

适用环境：公司电脑，Windows PowerShell，没有 git。上一轮 Azure run：`azure_di_layout_20260929T133601Z`。

## 你（人）要做的准备

1. GitHub 网页 **Code → Download ZIP**，解压到新目录。
2. 只需要把新版里的一个文件复制进工作目录：`tools\olmocr_diag.py`。
   其他文件不用动，不用重跑 Azure，也不会覆盖已有结果。
3. 把下面 Prompt 里的两个路径改成实际路径，整段粘给 Copilot agent。

## Prompt

```text
环境：Windows PowerShell，没有 git。
  工作目录：C:\Users\<用户名>\<路径>\doc-parser-eval-main
  新版目录：C:\Users\<用户名>\Downloads\doc-parser-eval-main

硬性规则：
- 不修改 tools\score_olmocr.py、tools\compare_systems.py、tools\vendor\ 下任何文件、
  runs\ 下任何已有文件。不调用任何 API，不重跑 Azure。
- 只把新版目录的 tools\olmocr_diag.py 复制到工作目录的 tools\ 下（覆盖同名文件即可）。

在工作目录执行：
  $env:PYTHONUTF8 = "1"
  .\.venv\Scripts\python tools\olmocr_diag.py `
      --inf   runs\inf-mllm_doc2md_20260918T065831Z `
      --azure runs\azure_di_layout_20260929T133601Z `
      --skip-math

脚本第 [0] 步会核对「产品口径重算结果」与已落盘的 olmocr_results.csv 完全一致，
如果报不一致并退出，原样把输出贴给我，不要自己改脚本。

跑完后把以下内容原样贴给我（不写结论性判断）：
1. 终端完整输出（[0] 核对、[1] 注释统计和两张「产品口径 → 诊断口径」表、
   compare_systems 的配对表、[2] 初判统计与配对分布）
2. runs\azure_di_layout_20260929T133601Z\diag\old_scans_review.csv 中
   「配对」列为「只INF对」的全部行（预计约 19 行），列：pdf、test_id、type、测试文本、
   Azure初判、Azure片段、INF片段
```

## 人工复核（第 2 件事的关键一步，约 20 分钟）

Copilot 跑完后，你自己打开 `diag\old_scans_review.csv`（Excel 可直接打开，已带 BOM）：

1. 只看「配对 = 只INF对」的行，从中挑 **5 行，尽量覆盖不同 pdf**。
2. 每行打开对应的 PDF（`data\olmocr_bench\bench_data\pdfs\old_scans\<n>.pdf`）
   和 `diag\old_scans_review\old_scans__<n>.md`（两边完整输出并排）。
3. 填两列：
   - **手写或打字**：该测试文本在原件上是手写还是打字机/印刷。
   - **人工结论**：从下面四个里选一个
     - `Azure漏识别`：原件上有，Azure 输出里没有
     - `Azure识别错`：有，但字错了
     - `格式问题`：字对，只是断行/连字符/大小写/标点导致判分失败
     - `测试本身有问题`：参考文本与原件不符
4. 把这 5 行拍照发回。

## 结果回来后怎么用

- **诊断 1**：诊断口径下如果 headers_footers、absent 两层的显著性消失，报告里这两层就写
  「差异来自 Azure 以 HTML 注释标注页眉页脚，判定器不剥注释；删除注释后未观察到显著差异」，
  产品口径与诊断口径并列。
- **诊断 2**：如果 Azure 的失败集中在手写，报告写「old_scans 的差距主要来自手写识别，
  与 HSBC 打印/电子文档场景相关性有限」；如果打字件上也大量漏识别，才算 Azure 在老扫描件上的真实弱项。
