# 公司电脑：导出 ocr-benchmark-dataset 的结构清单（只导结构，不导内容）

公司电脑的数据不能带出。用一个脚本把数据集仓库的**结构**汇成一页，拍照带回，
用于设计共享评测的判分接口与预测文件命名。
输出只含目录名、文件名规律、计数、字段名、类型、白名单内的短标签、哈希比对结果；
**不含文档正文、GT 的值、模型输出、分数、绝对路径**。

> 上一版让 Copilot 自己逐节探索，跑 10 分钟以上不结束。现在 A–D、F 节改由脚本一次跑完，
> E 节改成你自己回答的几个问题。

## 第 1 步：跑脚本（约 1–2 分钟）

1. 从 GitHub 分支 `claude/cool-planck-j8dsb2` 下载 `tools/dataset_inventory.py`，
   放到数据集仓库**外面**的任意目录，例如 `D:\tmp\dataset_inventory.py`
2. 确认数据集仓库已经拉过 LFS（`git lfs pull`），否则 D3 哈希全部对不上
3. 在数据集仓库根目录运行：

```powershell
$env:PYTHONUTF8 = "1"
python D:\tmp\dataset_inventory.py
```

生成 `inventory-for-photo.md`（在仓库根目录，**不要提交**；拍完照就删掉）。
没装 PyYAML 时金融集 YAML 会跳过，先 `pip install pyyaml`。
网络探测卡住就加 `--no-network`；哈希太慢就加 `--no-hash`。

也可以让 Copilot 代跑，整段粘给它：

```text
在 ocr-benchmark-dataset 仓库根目录执行，先运行 $env:PYTHONUTF8 = "1"，
然后运行 python D:\tmp\dataset_inventory.py 。
只运行这一条命令，不要修改任何文件，不要自己额外探索目录。
运行结束后告诉我：「未拉取的 LFS 指针文件数」、D 节所有表里「不一致 / 找不到 / 不在」列的数字。
```

## 第 2 步：拍照前检查一眼

脚本是启发式的。拍照前扫一遍 `inventory-for-photo.md`，**如果任何地方出现了正文、金额、
单元格内容或内部路径，把那一行删掉**再拍。重点看 B 节「枚举列取值」和 C 节「C3 枚举键取值」。

## 第 3 步：E 节，你直接回答（不用跑脚本）

1. 每个集合（金融、olmOCR、ParseBench、扰动）当时用哪个判分脚本？自写还是上游官方代码？
   上游的话钉在哪个 commit / 版本？
2. 四家 OCR（Infinity-Parser2-Flash、Azure DI layout、Mistral OCR、PaddleOCR 1.6 dev）的原始输出：
   markdown 还是 JSON？带不带 bbox？带不带置信度？逐页调还是整份文档一次调？（只写有/无）
3. 「用模型解析后按难易挑选文档」：挑选结果记在哪个文件、有哪些字段？
   规则有没有写成文档或脚本？（看 B 节末尾「可能与难度/选页相关的列」是否已经覆盖）
4. 公司电脑上 Copilot 能否识别 `.github/skills/` 下的 skill？（可以等写好 skill 后再试）
