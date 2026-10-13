# 公司电脑：把 benchmark-kit 提交进 ocr-benchmark-dataset，再用 skill 跑一次验收

两步：**① 装进仓库并提交**（纯文件操作，自己执行，不跑任何检查）；**② 用 skill 跑一次 INF 的历史输出**，
看 skill 能不能自己把流程走完、报告数字是否与已知结果一致。第 ② 步就是验收，不另做核对。

判分代码本身已在本仓库用历史 INF 跑数核对过（金融 1,153/1,153、扰动 500/500、ParseBench 512/513 一致），
所以第 ② 步看到的数字应与已有结论一致，例如金融 amount 类通过率 97.9%。

## 准备（手动，2 分钟）

1. GitHub 上把分支 `claude/cool-planck-j8dsb2` 下载成 zip（Code → Download ZIP），解压到**仓库以外**的目录，
   例如 `D:\work\kit-src\`。里面那一层 `doc-parser-eval-claude-cool-planck-j8dsb2\` 下文叫**源目录**。
2. 改下面命令开头三个路径。

## 第 ① 步：装进仓库并提交（自己在 PowerShell 里执行，不用 Copilot）

纯文件复制，交给 Copilot 反而容易跑偏（例如反复调用 Pylance 去分析 vendor 里的代码）。

```powershell
$SRC = "D:\work\kit-src\doc-parser-eval-claude-cool-planck-j8dsb2"   # 解压出来的源目录
$OLD = "D:\work\doc-parser-eval-main"                                 # 旧评测仓库（有 runs\）
$DS  = "D:\work\ocr-benchmark-dataset"                                # 数据集仓库
Set-Location $DS
git switch -c add-eval-kit            # 分支已存在就用 git switch add-eval-kit
git status --short -- data gt metadata   # 必须没有输出；有的话 git restore -- data gt metadata

Copy-Item -Recurse -Force $SRC\benchmark-kit\eval $DS
New-Item -ItemType Directory -Force $DS\.github\skills\ocr-benchmark, $DS\docs | Out-Null
Copy-Item -Force $SRC\benchmark-kit\.github\skills\ocr-benchmark\SKILL.md $DS\.github\skills\ocr-benchmark\
Copy-Item -Force $SRC\benchmark-kit\docs\protocol.md $DS\docs\
Copy-Item -Force README.md docs\README-previous.md      # 旧 README 原样保留，之后再拆到 docs\sources.md
Copy-Item -Force $SRC\benchmark-kit\README.md README.md
Get-Content $SRC\benchmark-kit\.gitignore | Where-Object { -not (Select-String -Path .gitignore -SimpleMatch -Pattern $_ -Quiet) } | Add-Content .gitignore

git add -A ; git status --short | Select-Object -First 30   # 只应出现 eval\ .github\ docs\ README.md .gitignore
git commit -m "Add evaluation kit: scorers, protocol, Copilot skill"
```

旧 README 里的 Get the data / Limits / Sources 三节先留在 `docs\README-previous.md`，以后再整理，不阻塞提交。

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

然后在 VS Code 打开数据集仓库，Copilot agent 模式里说（建议先在聊天框的工具设置里关掉 Pylance 相关工具，
让它只用终端跑命令）：

```text
run the ocr-benchmark skill on predictions/inf-flash
```

skill 会自己装依赖、跑自检、校验数据、判分、汇总。**你只看三件事**：

1. skill 有没有中途停下来或要你手工处理（这是在验 skill 本身）
2. 汇总里的数字与已有结论是否一致（金融 amount 97.9% 一类）
3. 有没有大量 `missing`（说明文件命名或目录对不上）

把 skill 的最后汇总拍照发我。数字对不上时，再用 `$SRC\tools\kit_parity.py` 逐条查（用法见脚本开头注释）。

`predictions\` 和 `results\` 已在 .gitignore 里，不会被提交。
