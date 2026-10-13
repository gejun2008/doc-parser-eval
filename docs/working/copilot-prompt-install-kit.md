# 公司电脑：把 benchmark-kit 装进 ocr-benchmark-dataset，并一次做完所有核对

本仓库 `benchmark-kit/` 的目录结构与数据集仓库根目录一致：`eval/`（四个集合的判分器）、`docs/protocol.md`、
`.github/skills/ocr-benchmark/SKILL.md`、新版 `README.md`、`.gitignore`。

本地已用历史 INF 跑数核对新旧判分器：

| 集合 | 一致 | 说明 |
|---|---|---|
| 金融 | 1,153 / 1,153 | |
| 扰动 | 500 / 500 | |
| ParseBench | 512 / 513 | 1 处是口径差异：`text/text_sparse__cover2` 整段输出被 ```markdown 围栏包住，新口径剥掉外层围栏 |
| olmOCR | — | 本地拿不到 GT，**只能在公司电脑核对** |

## 准备（你手动做，2 分钟）

1. 在 GitHub 上把分支 `claude/cool-planck-j8dsb2` 下载成 zip（Code → Download ZIP），
   解压到一个**仓库以外**的目录，例如 `D:\work\kit-src\`。
   解压后里面是一层 `doc-parser-eval-claude-cool-planck-j8dsb2\`，下文叫它 **源目录**，用到的只有两样：
   - `源目录\benchmark-kit\`：要装进数据集仓库的全部文件
   - `源目录\tools\kit_parity.py`：一致性核对脚本，**原地运行，不用复制**
2. 在 ocr-benchmark-dataset 里**新建分支**再改，不要直接改 main。
3. 把下面 Prompt 开头三行的路径改成你电脑上的实际路径，然后整段粘给 Copilot。
   所有命令都在 **数据集仓库目录** 里执行，只有一致性核对会去读旧仓库的 `runs\`。

## Prompt

```text
先在 PowerShell 里执行下面四行（路径按实际改），后面所有命令都用这些变量：
$SRC = "D:\work\kit-src\doc-parser-eval-claude-cool-planck-j8dsb2"   # 解压出来的源目录
$OLD = "D:\work\doc-parser-eval-main"                                 # 旧评测仓库（有 runs\）
$DS  = "D:\work\ocr-benchmark-dataset"                                # 数据集仓库
$env:PYTHONUTF8 = "1"; Set-Location $DS; git switch -c add-eval-kit

硬性规则：不修改 data\、gt\、metadata\ 下任何文件；不改 eval\ 下的代码（发现问题就报告，不要自己修）；
不 git commit，最后由我检查后提交；不调用任何模型 API；不要从 pip 安装 parse-bench（只用 eval\vendor 里的）。

1. 复制：Copy-Item -Recurse $SRC\benchmark-kit\eval, $SRC\benchmark-kit\.github $DS
   New-Item -ItemType Directory -Force $DS\docs ; Copy-Item $SRC\benchmark-kit\docs\protocol.md $DS\docs\
   .gitignore：把 $SRC\benchmark-kit\.gitignore 里的行追加到 $DS\.gitignore（已有的行不重复）。

2. README：
   a. 把现有 README.md 中「3. Get the data」「8. Limits and safe reuse」「9. Sources, attribution and rights」
      三节原文移到新文件 docs\sources.md（保持原文，不改写）。
   b. 把现有 README.md 第 4、5、6、7 节里的评分规则（包括「Strict financial scoring contract」）
      与 docs\protocol.md 第 3 节逐条对比，列出 protocol.md 没覆盖或说法不同的规则（只列，不改）。
   c. 用 $SRC\benchmark-kit\README.md 替换 $DS\README.md。

3. 环境与自检（在 $DS 执行）。建议先建虚拟环境：python -m venv .venv ; .venv\Scripts\activate
   python -m pip install -r eval\requirements.txt
   python -m pip install -r eval\requirements-parsebench.txt
   python -m eval.tests
   python -m eval verify
   python -m eval inputs
   确认：eval.tests 最后一行是 OK；verify 是 0 problems；inputs.csv 共 1040 行
   （financial 210 + olmocr 120 + perturbed 210 + parsebench 500）。
   如果报找不到 data\perturbed\manifest.csv 或 data\parsebench\manifest.csv，列出该目录下 csv 的文件名和表头。

4. 公式测试环境（可选，失败不影响其他步骤）：
   python -m pip install -r eval\requirements-math.txt
   $env:OCRBENCH_TEST_MATH = "1"; python -m eval.tests
   看 test_with_math 是 ok 还是 skipped；skipped 的话报告 python -m playwright --version 的输出，
   以及 %LOCALAPPDATA%\ms-playwright\ 下的目录名。

5. 一致性核对（新判分器 vs 旧判分器，用旧 run 的原始结果）。仍在 $DS 执行，脚本原地运行：
   python $SRC\tools\kit_parity.py $OLD\runs\<金融 run>        --collection financial  --dataset $DS
   python $SRC\tools\kit_parity.py $OLD\runs\<扰动 run>        --collection perturbed  --dataset $DS
   python $SRC\tools\kit_parity.py $OLD\runs\<olmOCR run>      --collection olmocr     --dataset $DS
   python $SRC\tools\kit_parity.py $OLD\runs\<ParseBench INF run>   --collection parsebench --dataset $DS
   python $SRC\tools\kit_parity.py $OLD\runs\<ParseBench Azure run> --collection parsebench --dataset $DS
   <…run> 是 $OLD\runs\ 下的子目录名，按下面的规则找：
   - 金融 = run_meta.json 的 note 含「第三层自建金融场景集 210 页」
   - 扰动 = note 含「T2 扰动组」
   - olmOCR = note 含「olmOCR-Bench 抽样子集 120 页」
   - ParseBench = runs\parsebench_inf_* 和 runs\parsebench_azure_*（不要选带 _nodeep 的）
   第 4 步公式测试是 ok 的话，olmOCR 那条再加 --with-math 跑一次。

6. 最后告诉我：
   - 第 2b 步列出的差异
   - 第 3 步每条命令的最后一行
   - 第 4 步 test_with_math 的结果
   - 第 5 步每次的「比对 N … 一致 … 不一致 …」那一行，以及不一致时打印的前 5 条
```

## 预期

- 金融：比对条数会比 1,153 略少。9/23 复核改过 2 条 target，这 2 条不比；当时是 draft、现在是 confirmed 的
  76 条，旧结果里没有分数，也不比。不一致应为 0。
- 扰动：比对条数取决于当时那次 run 用的 GT 版本，不一致应为 0。
- olmOCR：不带 `--with-math` 时比对 499 条左右，不一致应为 0。
- ParseBench INF：513 个文件×维度，不一致 1 条（`text/text_sparse__cover2`，原因见上表）。
- ParseBench Azure：没在本地跑过。若有不一致，先看是不是整段输出被围栏包住；不是的话把前 5 条发回来。

有任何不一致都**不要改代码**，把输出拍照发回来。
