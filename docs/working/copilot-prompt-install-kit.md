# 公司电脑：把 benchmark-kit 装进 ocr-benchmark-dataset，并做一致性核对

本仓库 `benchmark-kit/` 的目录结构与数据集仓库根目录一致：`eval/`（判分器）、`docs/protocol.md`、
`.github/skills/ocr-benchmark/SKILL.md`、新版 `README.md`、`.gitignore`。
本地已核对：金融 1,153/1,153、扰动 500/500 与旧判分器逐条一致；**olmOCR 本地拿不到 GT，必须在公司电脑核对**。

## 准备

1. 从 GitHub 分支 `claude/cool-planck-j8dsb2` 下载整个仓库 zip，解压后取出：
   - `benchmark-kit/` 整个目录
   - `tools/kit_parity.py`（放到公司电脑的 `doc-parser-eval-main\tools\`）
2. 在 ocr-benchmark-dataset 里**新建分支**再改，不要直接改 main。

然后把下面整段粘给 Copilot。

## Prompt

```text
先运行 $env:PYTHONUTF8 = "1"。在 ocr-benchmark-dataset 仓库里工作，先新建分支 add-eval-kit。
<KIT> 是解压出来的 benchmark-kit 目录，<OLD> 是 doc-parser-eval-main 目录。

硬性规则：不修改 data/、gt/、metadata/ 下任何文件；不改 eval/ 下的代码（发现问题就报告，不要自己修）；
不 git commit，最后由我检查后提交；不调用任何模型 API。

1. 复制：把 <KIT>\eval、<KIT>\docs\protocol.md、<KIT>\.github 复制到仓库根目录对应位置。
   .gitignore：把 <KIT>\.gitignore 里的行追加到仓库已有 .gitignore（已有的行不重复）。

2. README：
   a. 先把现有 README.md 中「3. Get the data」「8. Limits and safe reuse」「9. Sources, attribution and rights」
      三节原文移到新文件 docs\sources.md（保持原文，不改写）。
   b. 把现有 README.md「4. Use the financial collection with another model」里「Strict financial scoring contract」
      一节与 docs\protocol.md 第 3 节逐条对比，列出 protocol.md 没覆盖或说法不同的规则（只列，不改）。
   c. 用 <KIT>\README.md 替换 README.md。

3. 环境与自检：
   python -m pip install -r eval\requirements.txt
   python -m eval.tests
   python -m eval verify
   python -m eval inputs
   确认：eval.tests 全部 OK；verify 0 problems；inputs.csv 共 540 行（financial 210 + olmocr 120 + perturbed 210）。
   如果 perturbed 报找不到 data\perturbed\manifest.csv，列出 data\perturbed\ 下两个 csv 的文件名和表头。

4. 一致性核对（新判分器 vs 旧判分器，用旧 run 的原始响应）。在 <OLD> 目录执行：
   python tools\kit_parity.py runs\<金融 run>   --collection financial --dataset <ocr-benchmark-dataset 路径>
   python tools\kit_parity.py runs\<扰动 run>   --collection perturbed --dataset <ocr-benchmark-dataset 路径>
   python tools\kit_parity.py runs\<olmOCR run> --collection olmocr    --dataset <ocr-benchmark-dataset 路径>
   run 目录：金融 = run_meta.json 里 note 含「第三层自建金融场景集 210 页」的那个；
   扰动 = note 含「T2 扰动组」；olmOCR = note 含「olmOCR-Bench 抽样子集 120 页」。

5. 最后告诉我：第 2b 步列出的差异；第 3 步四条命令各自的最后一行；第 4 步三次「比对 N 条…一致…不一致…」那一行，
   以及不一致时打印的前 5 条。
```

## 预期

- 金融：比对条数会比 1,153 略少。9/23 复核改过 2 条 target，这 2 条不比；
  当时是 draft、现在是 confirmed 的 76 条，旧结果里没有分数，也不比。不一致应为 0。
- 扰动：比对条数取决于当时那次 run 用的 GT 版本，不一致应为 0。
- olmOCR：不带 `--with-math` 时 math 类不比，其余 499 条左右不一致应为 0。
  有不一致就把前 5 条发回来，不要改代码。
