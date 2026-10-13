# 公司电脑：把 benchmark-kit 提交进 ocr-benchmark-dataset，再用 skill 跑一次验收

两步：**① 装进仓库并提交**（纯文件操作，不跑任何检查）；**② 用 skill 跑一次 INF 的历史输出**，
看 skill 能不能自己把流程走完、报告数字是否与已知结果一致。第 ② 步就是验收，不另做核对。

判分代码本身已在本仓库用历史 INF 跑数核对过（金融 1,153/1,153、扰动 500/500、ParseBench 512/513 一致），
所以第 ② 步看到的数字应与已有结论一致，例如金融 amount 类通过率 97.9%。

## 准备（手动，2 分钟）

1. GitHub 上把分支 `claude/cool-planck-j8dsb2` 下载成 zip（Code → Download ZIP），解压到**仓库以外**的目录，
   例如 `D:\work\kit-src\`。里面那一层 `doc-parser-eval-claude-cool-planck-j8dsb2\` 下文叫**源目录**。
2. 改下面 Prompt 开头三个路径，整段粘给 Copilot。

## 第 ① 步 Prompt：装进仓库并提交

```text
先在 PowerShell 里执行（路径按实际改）：
$SRC = "D:\work\kit-src\doc-parser-eval-claude-cool-planck-j8dsb2"   # 解压出来的源目录
$OLD = "D:\work\doc-parser-eval-main"                                 # 旧评测仓库（有 runs\）
$DS  = "D:\work\ocr-benchmark-dataset"                                # 数据集仓库
$env:PYTHONUTF8 = "1"; Set-Location $DS; git switch -c add-eval-kit

规则：不修改 data\、gt\、metadata\ 下任何文件；不改 $SRC\benchmark-kit\eval 里的代码。

1. 复制：
   Copy-Item -Recurse $SRC\benchmark-kit\eval, $SRC\benchmark-kit\.github $DS
   New-Item -ItemType Directory -Force $DS\docs ; Copy-Item $SRC\benchmark-kit\docs\protocol.md $DS\docs\
   把 $SRC\benchmark-kit\.gitignore 里的行追加到 $DS\.gitignore（已有的行不重复）。
2. README：
   a. 现有 README.md 的「3. Get the data」「8. Limits and safe reuse」「9. Sources, attribution and rights」
      三节原文移到 docs\sources.md（不改写）。
   b. 把现有 README.md 第 4–7 节里的评分规则（含「Strict financial scoring contract」）与 docs\protocol.md
      第 3 节对比，把 protocol.md 没覆盖或说法不同的地方列出来告诉我（只列，不改）。
   c. 用 $SRC\benchmark-kit\README.md 替换 README.md。
3. git add 后 git commit -m "Add evaluation kit: scorers, protocol, Copilot skill"。不要 push，告诉我 2b 的结果。
```

## 第 ② 步：用 skill 验收

先导出 INF 的历史输出（一条命令，在旧仓库目录执行；各 run 目录名按 run_meta.json 的 note 找）：

```powershell
Set-Location $OLD
python $SRC\tools\export_predictions.py --out $DS\predictions\inf-flash --model Infinity-Parser2-Flash `
  --financial runs\<note 含「第三层自建金融场景集 210 页」的 run> `
  --perturbed runs\<note 含「T2 扰动组」的 run> `
  --olmocr runs\<note 含「olmOCR-Bench 抽样子集 120 页」的 run> `
  --parsebench runs\<parsebench_inf_ 开头、不带 _nodeep 的 run>
```

然后在 VS Code 打开数据集仓库，Copilot agent 模式里说：

```text
run the ocr-benchmark skill on predictions/inf-flash
```

skill 会自己装依赖、跑自检、校验数据、判分、汇总。**你只看三件事**：

1. skill 有没有中途停下来或要你手工处理（这是在验 skill 本身）
2. 汇总里的数字与已有结论是否一致（金融 amount 97.9% 一类）
3. 有没有大量 `missing`（说明文件命名或目录对不上）

把 skill 的最后汇总拍照发我。数字对不上时，再用 `$SRC\tools\kit_parity.py` 逐条查（用法见脚本开头注释）。

`predictions\` 和 `results\` 已在 .gitignore 里，不会被提交。
