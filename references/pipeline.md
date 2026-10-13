# 流水线

完整操作流程。按顺序执行；编号与 `SKILL.md` 的步骤一一对应。

这一版产出的是**漫画页**：多格、有剧情推进、有精确文字。默认 `comic.mode: whole-canvas`——一页里所有分格由同一张图承载，这样线宽、上色层数和对比度天然统一，不会出现"这一格渲染风、那一格平涂风"的割裂。

**两道人工闸门，顺序不可颠倒**：先把方案表摆出来等用户选（Gate 1），再把张数汇总一次等用户确认（Gate 2）。拿到 Gate 2 的肯定答复之前，一个字都不许生成。

## 0. 先定模式

第一次给方案时，同一条消息里问一次要用哪种模式：

- **propose**（默认）：素材进，方案出，Gate 1 等选，Gate 2 等确认，然后出图。
- **direct**：方案与张数已经定了，直接跳到第 5 步。

用户没回答就用 propose。两种模式在第 5 步做完之前都不要开始生成。

## 1. 读素材

`input.kind` 二选一：

- `material`：故事、转录、聊天记录、文章、更新日志、截图转录或自由文字。放进 `input.text`，或用 `input.path` 指向文件。`input.language` 记录素材语言，并成为默认文字语言。
- `brief`：用户已经用一段话描述了要什么。用 `input.brief`。

提案之前先写下来：

- **主题**：这个素材真正在讲的一句话。
- **桥段**：3–8 个值得画出来的瞬间。每个桥段都要带一小段**原文引文**作为出处。
- **固有阵容**：素材真正涉及哪些已登记角色，以及为什么。绝不为了凑数加人；只有一个角色的页面是合法结果。
- **可复用台词**：能直接变成画面上文字的原文句子，注明说话人。

凡是追不到引文的东西都是你自己的发明，提案时要标出来。

## 2. Gate 1：摆出五个方案

准备**正好五个**真正不同的方案。每一个都要是已经想过一轮的：故事怎么走、落在几格、画面里发生什么、最后一句台词是什么。

**必须用下面这个七列表格**，一行一个选择；把每个占位符换成具体内容。字母只标识选择，不代表排名、版式或笑点类型。

| 选择 | 方案 | 核心场景 | 剧情走向与反转 | 分镜／构图 | 关键台词 | 推荐程度与理由 |
|---|---|---|---|---|---|---|
| A | 具体标题 | 画面里的那件事 | 预期→翻转→落点 | 页数、格数、镜头、互动 | 准备上图的关键文字 | ★★★ 首推＋具体理由 |
| B | … | … | … | … | … | … |
| C | … | … | … | … | … | … |
| D | … | … | … | … | … | … |
| E | … | … | … | … | … | … |

列的含义与写法：

- **选择**：`A`–`E`，只当编号用。
- **方案**：短而具体的标题，不要写成类型标签。
- **核心场景**：这一页里实际发生的事，一句话。
- **剧情走向与反转**：起→承→转→合，要写清哪里翻、翻成什么样。这是"有剧情"的核心，不许只写"两人争执"这种笼统话。
- **分镜／构图**：页数与格数（默认 1 页；也可以写 2 页）、版式、每格景别与谁在哪。要能一眼看出格与格的差别。
- **关键台词**：准备上图的那几句原文或半成品台词，标明谁说的。
- **推荐程度与理由**：`★★★ 首推` / `★★☆ 推荐` / `★☆☆ 可选`，加**针对这个素材**的具体理由。不要为了好看强行凑出评级分布，也不要把你已经否掉的方案填进来占位。

排版要求：单元格写短句；内容里有 `|` 要转义；换行用 `<br>`。表格**直接显示**，不要包在代码块里。

表格下面问：

> **你想生成哪些方案？** 可选一个或多个。推荐〈编号〉，因为〈具体理由〉。
>
> **张数：**每个入选方案默认 **1 页**（1 张图，页内多格）。选两个共 2 张。某个方案想展开成多页（同一创意的不同演绎）请直接说，例如"C 出 3 页"。
>
> 选完我会汇总方案与张数，请你确认后再开始生成。

然后**停下**。不要建完整作业、不要预构建提示词、不要为了填满方案就花掉出图次数。

## 3. Gate 2：汇总张数，再等一次

按用户实际回复解析。**只选了方案没给张数，就是 1 页**。绝不把"五个方案"和"五张图"搞混。

| Gate 1 的回复 | Gate 2 的汇总 |
|---|---|
| A | 1 个方案，共 1 页 |
| A＋C | 2 个方案，各 1 页，共 2 页 |
| 五个都要 | 5 个方案，共 5 页 |
| C 出 3 页 | 1 个方案，共 3 页 |
| A 两页、C 一页 | 2 个方案，共 3 页 |
| 按推荐来 | 用表里明确标出的推荐组合，张数按上面默认 |

汇总要这样写：

> 已选择 **2 个方案，共 2 页**：
>
> - **A｜〈标题〉**：1 页
> - **C｜〈标题〉**：1 页
>
> 每页都是一张完整的漫画页，出图后逐项做质量验证。
>
> **确认按以上方案和页数开始生成吗？** 回复"确认"即可开始，也可以调整方案或页数。

规则：

- 用户对某个方案的小改动（措辞、站位、镜头）不要重发方案表：保留原方案，把改动记进 `selection_detail.adjustments`，它在执行时优先。
- **核心笑点/落点被换掉了**，就要出修订版方案表并重走 Gate 1。
- 即使用户在 Gate 1 就说"就 A，开始吧"，也必须先把总张数摆出来等确认。
- 含糊的回复要问清楚；Gate 2 的肯定答复只对**当前这份汇总**有效，改了方案或张数就得重新汇总、重新确认。不要复用上一次的确认。
- 只做规划的指令一直有效，直到用户明确授权生成。

## 4. 冻结作业

按 `references/assignment-schema.md` 写一个 JSON。把选中的东西记进 `selection`（一段话，进提示词），再用 `selection_detail` 留下可核对的选择记录：

```json
"selection": "A：……一段话说清这一页讲什么、翻在哪……",
"selection_detail": {
  "proposal_id": "A",
  "title": "……",
  "rating": "★★★ 首推",
  "frame": "1 页 / top-bottom 2 格",
  "adjustments": ["用户要求把最后一句改成……"],
  "reply": "A"
}
```

然后：

```
python scripts/manage-run.py validate-assignment --assignment <path>
python scripts/manage-run.py init --assignment <path>
```

（Windows 上是 `python`，Linux / macOS 上换 `python3`；脚本只需要标准库加 Pillow。技能文件夹可以整体搬到任何目录，路径都从脚本和作业文件自身推导。）

`init` 做三件事并且拒绝做第二遍：把冻结的作业复制进 run 目录；把每张参考图复制进 `inputs/references/` 并重新校验哈希；写 `manifest.json`。`init` 之后作业不可变；改 run 目录里的 `assignment.json` 会让 `load_run` 拒绝继续——这是设计如此。要改范围就换一个 run 名字。

`output_dir` 默认是相对工作目录的 `artifacts/cast-image-studio/<run_name>`。

**这一步要检查的漫画字段**：

- `comic.layout` 与 `comic.panel_count` 必须匹配（`single`=1、`top-bottom`/`left-right`=2、`1x3`=3、`2x2`/`1x4`=4、`2x3`=6、`3x3`=9）。
- `panels[]` 的数量必须等于 `panel_count`，且 `panel` 从 1 连续编号。
- `cast[].panels` 里出现的格号不能超过 `panel_count`。
- `lettering.core_text[]` 每一条都要有 `panel`、`speaker`、`delivery`；**每一格都必须被覆盖**，不能有沉默的格子。
- `speaker` 只能写本图阵容里的角色（id / 显示名 / 别名都行），或者 `narrator` / `device`。说话人必须在该格 `cast[].panels` 里出现。
- `references` 里必须**正好有一张**字行参考图：该图 `roles` 为 `["lettering","typography"]`，路径必须等于所选 `text_style` 模板自己的 `reference.webp`。

## 5. 构建提示词

```
python scripts/build-prompt.py --run-dir <run_dir> --image <image_id> --output prompt-01.txt
```

一张图一个提示词。提示词是确定性的：同一份冻结作业永远产出同样的字节。文件绝不覆盖——第二次调用会直接失败。

提示词的区块顺序：`TASK` → `MATERIAL` → `SELECTED TREATMENT` → `SELECTED TREATMENT (frozen selection record)` → `CAST NOTES` → `CAST` → `IDENTITY` → `ART CONTRACT` → `PANEL LAYOUT` → `FRAMING` → `REFERENCE ROLES` → `LETTERING` → `OUTPUT`。

## 6. 生成

把提示词和提示词 `REFERENCE ROLES` 里列出的冻结参考图一起发给配置好的渠道。一次调用出一张候选。顺序、重试与错误分类见 `references/provider-routing.md`。

**文字渲染提醒**：中文小字有翻车概率。生成之后必须逐字核对实际画出来的文字与 `core_text` 是否一致，把差异如实记进 `text_accuracy` 门禁，不要放过。

## 6b. 落地返回的文件

渠道结果还不是候选图，必须先转成冻结的输出规格：

```
python scripts/materialize-image.py --run-dir <run_dir> --image <image_id> \
  --source staging/<image_id>/01_provider.img --output staging/<image_id>/01_candidate.png \
  --report staging/<image_id>/01_candidate.materialize.json
```

它定死容器格式、像素尺寸与 alpha 策略；裁剪超过 2% 会拒绝，不加 `--allow-scale` 就不许缩放。原始渠道文件留在候选图旁边当证据，绝不删除。所有门禁都跑在落地后的候选图上，绝不跑在原始下载文件上。

## 7. 自动门禁

```
python scripts/validate-composite.py --candidate <file> --run-dir <run_dir> --image <image_id> --output automatic.json
```

这会写出 `record-candidate` 需要的 `automatic.json`。判定来自恰好三项门禁——几何、色彩模式、alpha 策略——外加参考图哈希校验。背景分析会报出来，但只有当实际颜色与声明的颜色确实不符时才会拖垮判定；背景不够平只是一条备注，因为主体跑出画面边缘是合法构图。只需要那三项时，可以单独跑 `validate-image.py`。

它还会记录 `injection_survey` 和 `identity_required_elements`，判定为 `NOT-CHECKED`——特征串味与像不像，脚本判不了。

自动判定为 `FAIL` 的候选绝不能晋级。修根因（通常是提示词或输出规格不匹配），然后重新生成。

**漫画专用的人工检查点**（脚本判不了，必须人眼过）：分格边界是否正确、分格顺序是否按阅读方向、对白气泡的尾巴是否指向正确的角色、每一格的文字是否落在自己的格子里且没压脸。

## 8. 人工门禁与人工判定

填一份评审 JSON。门禁：

`style_consistency`、`register_consistency`、`anatomy_contact`、`cast_accuracy`、`text_accuracy`、`pose_and_story`。

每一项都要有判定。`style_consistency` 只有同时给出 ≥20 字的 `style_consistency_note`（写清实际比较了什么：线宽、上色层数、高光处理、色彩饱和度、头身档）时才能是 `PASS`。总判定是 `PASS` 而任何一项门禁不是 `PASS`，会被拒绝；不合格的候选标成 `retry`，并用 `targeted_retry` 指出唯一根因。

`text_accuracy` 要逐字对照实际画面文字与 `core_text`，包括标点。

没人看过图，就如实说明并把人工门禁标成未验证，而不是给它们 PASS。

## 9. 记录与晋级

```
python scripts/manage-run.py record-candidate --run-dir <run_dir> --image <image_id> \
  --provider <provider> --model <model> --candidate <file> --prompt-file prompt-01.txt \
  --automatic-json automatic.json --review review.json
python scripts/manage-run.py promote --run-dir <run_dir> --image <image_id> --candidate <file>
```

`record-candidate` 会重新校验候选图哈希，拒绝两份 QA 记录互相矛盾，拒绝超出预算的候选，也拒绝自动判定为 `FAIL` 的候选。`promote` 把文件复制进 `final/`，只接受两份判定都为 `PASS` 的候选。

## 10. 收尾

```
python scripts/manage-run.py finalize --run-dir <run_dir>
```

报告状态、每个成品文件、每个没产出成品的页，以及候选总数。因记录过 safety 错误而中止的 run 不能收尾成成功。还有未完成页的 run 收尾为 `finalized-partial`，并列出那些 id。
