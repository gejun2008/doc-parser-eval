# 公司电脑操作顺序：更新 kit → 配置新 OCR 模型 → 用 skill 跑出测试结果

路径按实际改。下文：**源目录** = 分支 zip 解压出来的 `doc-parser-eval-claude-cool-planck-j8dsb2\`；
**数据集仓库** = `ocr-benchmark-dataset`。

## 1. 更新 kit 到数据集仓库（每次 kit 有新版本时做一次）

1. GitHub 上把分支 `claude/cool-planck-j8dsb2` 重新下载成 zip（Code → Download ZIP），解压到仓库以外，
   例如 `D:\work\kit-src\`。
2. 运行安装脚本（只复制文件，不提交；分支 `add-eval-kit` 已存在会直接切过去）：
   ```powershell
   powershell -ExecutionPolicy Bypass -File D:\work\kit-src\doc-parser-eval-claude-cool-planck-j8dsb2\tools\install_kit.ps1 -DS D:\work\ocr-benchmark-dataset
   ```
   若弹出「是否覆盖 eval\ 下的文件」，选允许。
3. 列表里只有 `eval/ .github/ docs/ README.md .gitignore` 就提交并推送：
   ```powershell
   Set-Location D:\work\ocr-benchmark-dataset
   git commit -m "Update evaluation kit: model runner (OpenAI-compatible)"
   git push
   ```

## 2. 准备环境（每台电脑一次）

```powershell
Set-Location D:\work\ocr-benchmark-dataset
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r eval\requirements.txt -r eval\requirements-parsebench.txt -r eval\requirements-run.txt
```

VS Code 里 `Ctrl+Shift+P` → `Python: Select Interpreter` → 选 `.venv`，这样 Copilot 开的终端也用这个环境。

## 3. 配置新 OCR 模型

新建 `predictions\new-ocr\run_card.yaml`（`predictions\` 不会被提交）：

```yaml
model: new-ocr
version: test
input_mode: image
dpi: 300
endpoint:
  url: https://<host>/new-ocr/test/xxxx/v1/chat/completions   # 完整的 chat completions 地址
  model: <服务端要求的 model 名>
  api_key_env: NEW_OCR_API_KEY        # 只写环境变量名，密钥不写进文件
  concurrency: 4
```

在**要跑的那个终端**里设置密钥（只在这个终端有效，不落盘）：

```powershell
$env:NEW_OCR_API_KEY = "<密钥>"
```

## 4. 用 skill 跑

1. Copilot 聊天框的工具设置里**关掉 Pylance 相关工具**，切到 Agent 模式。
2. 输入：
   ```text
   Use the ocr-benchmark skill to evaluate predictions/new-ocr.
   Only run the terminal commands the skill lists; do not open or analyse source code.
   ```
3. skill 会依次：自检 → 冒烟测试（每个集合 2 个输入）→ 告诉你全量预计耗时并让你选：
   - **默认全量**：4 个集合，1,040 个输入
   - **只跑挑选的公开子集**：ParseBench 500 + olmOCR 120 = 620 个输入
   - 或任选几个集合
4. 预计超过 30 分钟时，skill 会给出一条命令让你在自己的终端里跑（终端里要先设好 `$env:NEW_OCR_API_KEY`）。
   中途断了，再跑同一条命令会接着跑，失败的自动重试。例如：
   ```powershell
   python -m eval run predictions\new-ocr                                  # 全量
   python -m eval run predictions\new-ocr --collections parsebench olmocr  # 只跑公开子集
   ```
5. 跑完回到 Copilot 说「finished」，skill 判分并汇总。报告在 `results\new-ocr\`。

## 5. 出问题时看哪里

- 冒烟测试失败：看 `predictions\new-ocr\_raw\` 下最新的 `.json`，里面有 HTTP 状态码、错误信息、`finish_reason`。
  常见原因：url 不是完整的 chat completions 地址、model 名不对、鉴权头不是 `Authorization: Bearer`
  （可在 run_card 的 endpoint 里加 `auth_header: api-key` 和 `auth_prefix: ""`）。
- `finish_reason: length`：输出被截断，按失败计；可在 endpoint 里调大 `max_tokens`。
- 大量 `missing`：说明调用失败的输入多，重跑同一条 `eval run` 命令重试。

## 可选：用 INF 历史输出核对判分

不调模型，只验证判分在公司电脑上与本地一致（金融 amount 97.9% 一类）。在旧评测仓库执行：

```powershell
python D:\work\kit-src\doc-parser-eval-claude-cool-planck-j8dsb2\tools\export_predictions.py `
  --out D:\work\ocr-benchmark-dataset\predictions\inf-flash --model Infinity-Parser2-Flash `
  --financial runs\<金融 run> --perturbed runs\<扰动 run> --olmocr runs\<olmOCR run> --parsebench runs\<parsebench_inf_ run>
```

然后让 skill 评测 `predictions/inf-flash`（没有 endpoint，它会直接判分）。
