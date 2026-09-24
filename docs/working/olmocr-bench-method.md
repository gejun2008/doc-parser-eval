# olmOCR-Bench 评测口径

对应 research-plan.md §3.2 第二层（中立公开基准 · 准入门槛）。
**这一层不产生决定性结论**，决定性证据在第三层自建金融场景集。

报告附录靠本文件复现。每个可能影响分数的选择都写在这里，包括对我们不利的。

## 为什么这一层只能当门槛

厂商在 olmOCR-Bench 上自报 **87.6%**（research-plan.md §1.3）。
一个厂商报过分的 benchmark，**泄漏风险最高**：无法排除该数据集或其同源数据
进过训练集。因此：

- 这一层的分数只用于回答「够不够格进入评测」，不用于回答「能不能替代 Azure DI」
- 分数**不能**直接与 87.6% 比大小，我们跑的是抽样子集，不是全量 1,403 个 PDF
- TASKS.md 的砍项清单里，这一层排在第一个被砍的位置

## 数据

| 项 | 值 |
|---|---|
| 数据集 | `allenai/olmOCR-bench`，ODC-BY |
| 全量 | 1,403 个单页 PDF / 7,019 条 pass/fail 测试 |
| 本次抽样 | **120 个 PDF / 604 条测试** |
| 抽样脚本 | `tools/fetch_olmocr_bench.py` |
| 随机种子 | `20260918`，固定；`random.Random(f"{seed}:{subset}").sample` |
| 清单 | `data/olmocr_bench/manifest.csv`、`subset_meta.json` |

**配额按金融文档相关性分配，不按原始比例**，因此各子集在我们子集里的占比
与官方总分的构成不同——这是又一条「不能与 87.6% 直接比」的理由。

| 子集 | 抽样 PDF | 测试数 | 为什么给这个配额 |
|---|---|---|---|
| `table_tests` | 40 | 187 | 跨页表格是金融文档第一痛点 |
| `multi_column` | 20 | 68 | 阅读顺序 |
| `headers_footers` | 20 | 49 | 见下面「口径陷阱」 |
| `long_tiny_text` | 15 | 120 | 附注小字密排，最接近财报附注页 |
| `old_scans` | 15 | 75 | 影印件，对应扰动组 |
| `arxiv_math` | 5 | 30 | 相关性低，占位 |
| `old_scans_math` | 5 | 75 | 同上 |

## 调用口径

`tools/runner.py`，裸 HTTP，不走厂商 SDK（CLAUDE.md 约定 1）。
与 SDK v0.4.0 逐字对齐的部分：

| 项 | 值 | 核对方式 |
|---|---|---|
| prompt | `PROMPT_DOC2MD` | 与 SDK 源码**逐字比对通过**，sha256[:16] = `2bb52221db4ac2bd` |
| 栅格化 | PyMuPDF 300 DPI → `smart_resize` → PNG base64 | 复刻 `qwen_vl_utils.smart_resize` |
| 请求参数 | `max_tokens=32768, temperature=0.0, top_p=1.0` | 同 `backends/vllm_server.py` |
| 后处理 | `postprocess_doc2md_result`，只剥 ` ``` ` 围栏 | 逐字复制自 `utils/utils.py` |

**选 md 而不是 doc2json**：客户实际拿到的就是 md。代价是 md 口径默认丢弃
header/footer/page_footnote（sdk-findings.md §5），下面的口径陷阱因此成立。

不对齐的只有两处，都对厂商无害：走裸 HTTP、每次调用全量落盘。

并发 2、超时 900s、失败重试 2 次并记录次数——依据是 T0 §10 实测
（静默排队、吞吐不随并发上升）。

## 判定口径

**判定逻辑不自己写**，vendor 官方 `olmocr/bench` 模块，
钉在 commit `ab294c6a`，放在 `tools/vendor/olmocr/`。
与厂商报 87.6% 时用的是同一套 pass/fail 逻辑，口径不会因为我们的实现而漂。

`tools/score_olmocr.py` 只做三件事：读 runner 落盘、套 SDK 后处理、调官方判定。

六类测试：`present`（含模糊匹配 `max_diffs`）、`absent`、`order`（前后相对位置）、
`table`（单元格与表头关系）、`math`（KaTeX 渲染后比对）、`baseline`。

## 统计口径

- **按子集、按类型分层出数，不合成加权总分**（CLAUDE.md 约定 5）
- 每层给 n 与 Wilson 95% 置信区间。**604 条测试上 3 个百分点的差异不显著**，
  不得称「更好」
- 调用失败页（`finish_reason != stop` 或非 200）上的所有测试判 fail，
  但在 `failed_pages` 里单列——「调用失败」与「解析错误」是两回事，不要混读
- 判定器自身异常记为 `checker_error`，**不计入模型失分**，单独报数

## 口径陷阱（必须写进报告）

### 1. `headers_footers` 子集：两条产品路径的行为相反（原预判已被实测推翻）

该子集 49 条测试全是 `absent` 类——要求页眉页脚**不出现**在输出里。

**跑之前的预判是「丢弃即得分，天然高分」，实测推翻了它。** 实际通过 15/49。
复核 SDK 源码后确认，丢弃 header/footer 发生在**另一条路径**上：

| 产品路径 | 页眉页脚 | 依据 |
|---|---|---|
| `task_type="doc2md"`（本次所用） | **保留**，写进 markdown | 后处理只剥围栏，不过滤内容 |
| `task_type="doc2json"` → md | **丢弃** | `convert_json_to_markdown(keep_header_footer=False)` 默认过滤 `header`/`footer`/`page_footnote` |

sdk-findings.md §5 说的是后者。两条路径对同一页会给出不同的 markdown，
**报告里凡涉及页眉页脚、脚注归属的结论都必须标明走的是哪条路径**。

对本子集的读法：15/49 反映的是「doc2md 保留了页面装饰」，
既不是能力强也不是能力弱，取决于下游要不要这些文本。
真正要测脚注归属，用 doc2json 口径加 `footnote_scope` 断言（assertions.md 第 6 类）。

### 2. doc2md 输出把 LaTeX 反斜杠双写

实测 md 输出里公式写成 `\\mathbb{N}` 而非 `\mathbb{N}`（双反斜杠）。
在 LaTeX 里 `\\` 是换行，**公式无法正确渲染**。
SDK 的 `postprocess_doc2md_result` 不处理这个，所以产品输出就是双写的。

已排除是我们这边的转义问题：prompt 与 SDK 逐字一致（sha 已核对），
落盘的是 `r.json()` 解码后的字符串。

**报告口径**：`math` 类按产品实际输出判分，同时用 `--diagnose-latex`
跑一遍「把双写归一为单写」的诊断口径，两个数字并列。
差值就是这一个 bug 造成的失分，**不要用诊断数字替代产品数字**。

初步观察（n=9，样本太小，仅说明现象存在）：产品口径 0/9，归一后 4/9。

## 复现

```bash
python tools/fetch_olmocr_bench.py                       # 抽样与下载，seed 固定
python tools/runner.py --task doc2md --concurrency 2     # 逐页调用并落盘
python tools/score_olmocr.py runs/<run_id> --diagnose-latex
```

产物：`runs/<run_id>/raw/*.json`（每页原始响应）、`olmocr_results.csv`（逐条判定）、
`olmocr_summary.json`（分层汇总）、`run_meta.json` 与 `run_summary.json`（调用口径与耗时）。
