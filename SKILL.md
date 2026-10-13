---
name: cast-image-studio
description: Turn one piece of raw material (a story, transcript, screenshot, article, release note, chat log or brief) into a finished manga page — anime/cel art with real panel layout, a beat of story per panel and exact captions, dialogue and sound effects — using a registry of named characters. Propose concepts from the material, stop once for the user to choose, then freeze the assignment, build prompts, generate, run the automatic gates and report the review gates that only a human may pass. Use for 剧情生图, 素材生图, 多角色漫画, 四格漫画, 同人小剧场, 条漫, or when several registered characters must appear together in one page with lettering, a fixed art style and a consistent proportion register. Default to stopping once after concept selection.
---

# Cast Image Studio（多角色漫画工作室）

一条流水线：素材进，**成品漫画页**出。画面上出现的角色**只有**作业里声明过的那些——没有默认主角，也不会有谁被自动塞进画面。

每一张图都是**一页漫画**：有分格、有景别、有剧情推进、有精确的对白/旁白/拟声字。画风默认走 `manga`（二次元赛璐璐），由 `references/art-presets.json` 的契约锁定。

## 按需加载参考文档

- `references/pipeline.md` — 逐步操作流程（0–10 步）。
- `references/assignment-schema.md` — 作业的全部字段，含可运行示例。
- `references/cast-rules.md` — 角色注册表、选角、头身档、缩放与画风一致性。
- `references/art-presets.json` — 画风预设（默认 `manga`）及其契约。
- `references/text-styles.json` — 字行（对白/怒吼/心声/旁白/拟声）目录，以及每个模板自带的 `template.md`。
- `references/text-style-templates/<name>/template.md` — 该字行写进提示词的那段话；它的 `reference.webp` 作为该图唯一的字行参考图。
- `references/qa-rubric.md` — 自动门禁与六项人工门禁。
- `references/provider-routing.md` — 渠道顺序、错误分类、预算与并行。
- `references/example-assignment.json` — 可运行的作业模板（`assets/...` 相对路径自动解析）。

## 先把请求定下来

1. **素材** — `input.kind` 是 `material`（一段文字或一个文件）或 `brief`（一段简述）。记下主题、有原文出处的桥段，以及素材真正涉及的角色。
2. **模式** — 默认 `propose`：先出**正好五个**方案（七列表格：选择／方案／核心场景／剧情走向与反转／分镜构图／关键台词／推荐程度与理由），停一次等你选；选定后再汇总张数等你确认（Gate 2），两次都点头才开始跑图。`direct`：方案已定，直接冻结。
3. **选角** — 只能来自注册表。`id`、显示名、别名都能解析。绝不凭空造角色，也绝不为了凑画面加人。
4. **故事分格** — 一张图就是一页。定 `comic.layout` 与 `comic.panel_count`（`single` / `top-bottom` / `left-right` / `2x2` / `1x3` / `1x4` / `2x3` / `3x3`），再逐格写 `panels[]`：景别、动作、表情、道具、转到下一格的衔接。
5. **文字** — 每页必须有字。`lettering.text_style` 选字行，`lettering.core_text[]` 写**逐字精确**的文本，每条标明 `panel`、`speaker`（角色 id / 别名 / `narrator` / `device`）与 `delivery`（`speech` / `thought` / `caption` / `sfx`）。**每一格都必须至少有一条字**。
6. **画风与头身** — 整个 run 一个 preset（默认 `manga`），一页一个 register，或 `mixed` 并写清相对身高。角色自己人设图的头身比**永远不能**变成这一页的头身比。
7. **输出** — 默认 3:4、PNG、provider 原生分辨率、无 alpha；一页内所有分格由同一张图承载（`comic.mode: whole-canvas`），这样线宽和对比度天然统一。

## 两道闸门，顺序不可颠倒

**Gate 1｜选方案。** 用 `references/pipeline.md` 第 2 步的七列表格摆出**正好五个**真正不同的方案：核心场景、剧情走向与反转、分镜与构图、关键台词、`★★★ 首推`/`★★☆ 推荐`/`★☆☆ 可选` 加具体理由。表格直接显示，不要包在代码块里。给完推荐就停，不要写作业文件、不要预构建提示词。

**Gate 2｜确认张数。** 用户选完，把张数汇总一次（默认每个入选方案 1 页），拿到肯定答复再动手。

- Gate 1 的字母只是编号，不代表排名。
- Gate 1 就说"就 A，开始吧"也要先摆出总张数等确认。
- 改了方案或张数就要重新汇总、重新确认，不复用上一次的确认。
- 小改动（措辞、站位）不重发方案表，记进 `selection_detail.adjustments`；核心落点被换掉就要重走 Gate 1。
- 只做规划的指令一直有效，直到用户明确授权生成。

## 花钱之前先确认

用中文呈现，用户明确确认后才冻结：

```
素材与主题：<输入类型、主题一句话、命中的桥段>
模式：<propose / direct>
运行名称与输出位置：<run_name → artifacts/cast-image-studio/<run_name>>
概念清单：<五个方案：选择 / 标题 / 核心场景 / 剧情走向与反转 / 分镜构图 / 关键台词 / 推荐程度与理由>
Gate 1 用户回复：<原文>
确认选用的方案：<用户选定或我推荐的那一个>
Gate 2 张数汇总：<方案 → 页数，合计>
Gate 2 用户回复：<原文>
每一页：<name / 分格布局 / 逐格景别与动作 / 出场角色与所在格>
文字：<字行模板 / 逐条文本：第几格、谁说的、怎么说>
画风与头身：<preset、register、背景>
参考图权限：<每个角色的 identity 参考、字行参考>
模型顺序与预算：<provider 顺序、每图候选数、总候选数>
执行方式：<串行 / 并行数>
```

`confirmation.confirmed` 不是字面上的 `true`，就不要开始生成。冻结之后不得擅自扩大角色阵容、页数或预算——要改就先问。

## 执行已确认的作业

```bash
python scripts/manage-run.py validate-assignment --assignment <path>
python scripts/manage-run.py init --assignment <path>        # 冻结输入；绝不覆盖已有目录
python scripts/build-prompt.py --run-dir <run_dir> --image <image_id> --output prompt-01.txt
# 每次生成一张候选，再按冻结的输出规格落地：
python scripts/materialize-image.py --run-dir <run_dir> --image <image_id> \
  --source staging/<image_id>/01_provider.img --output staging/<image_id>/01_candidate.png
python scripts/validate-composite.py --candidate <file> --run-dir <run_dir> --image <image_id> --output automatic.json
python scripts/manage-run.py record-candidate --run-dir <run_dir> --image <image_id> \
  --provider <provider> --model <model> --candidate <file> --prompt-file prompt-01.txt \
  --automatic-json automatic.json --review review.json
python scripts/manage-run.py promote --run-dir <run_dir> --image <image_id> --candidate <file>
python scripts/manage-run.py finalize --run-dir <run_dir>
```

门禁跑在**落地之后**的候选图上，绝不跑在渠道下载的原始文件上。

命令里的 `python` 在 Windows 上就是它；Linux / macOS 上换 `python3`。脚本只依赖标准库加 **Pillow**（`pip install Pillow`）。所有路径都从脚本自身和作业文件的位置推导，**整个技能文件夹可以整体搬到任何目录、任何机器**，不需要改代码。

`probe-registry` 列出已登记角色；`status` 打印运行摘要；`tools/build-cast-registry.py --check` 只校验注册表与每张母图的哈希，不写任何东西。

不可协商的规则：

- 提示词由 `build-prompt.py` 从冻结的作业生成。脚本能产出的提示词，绝不手写、绝不改写。
- 角色的 `prompt_block` 与 `negative` 逐字进提示词。身份锁绝不转述。
- 每个在场角色都要有自己的 identity 参考图；参考图只控制身份，不控制背景、姿势或头身比。
- 所有角色共用一条线宽、一种上色层数、一套高光处理；各自只保留自己的色系。
- 一页之内每一格都必须是同一只手画的：线宽、上色层数、对比度全格一致。有一格变成渲染风/照片风，整页判不合格。
- 角色自己人设图的头身比永远不能变成画面的头身比。按 `references/cast-rules.md` 重新定档，绝不把成年角色画成小孩。
- 每页都要有字：每一格至少一条 `core_text`。文字逐字精确，不许翻译、缩写、调序或重复。
- `record-candidate` 会拒绝自动判定为 `FAIL` 的候选。修根因，不要绕着门禁晋级。
- `style_consistency` 没有 ≥20 字的 `style_consistency_note` 就不能 PASS。任何一项门禁非 `PASS` 时，总判定不得是 `PASS`。
- 渠道报 `safety` 错误就是根因级停止。绝不改写提示词绕过它。
- 没人看过图，就如实把人工门禁报成未验证。绝不声称验证过自己没看过的图。

## 并行时的安全边界

构建提示词、记录候选、晋级、收尾都是 coordinator 串行，因为它们会写 run manifest。只有生成可以并行，`requested_parallelism` 取 1–5。两张图不会同时写同一个 manifest。

## 硬性停止

- Gate 2 没拿到肯定答复之前，不要生成。作业未确认、`init` 未冻结之前，也不要生成。
- 不要超预算：每图 ≤8 个候选、每渠道 ≤3 个，整轮超过 24 个要先问。
- 不要改 run 目录里的 `assignment.json`；要改就换一个 run 名字。
- 冻结后不要擅自加角色、改头身档或改画面比例。
- 不要覆盖提示词文件、run 目录或已有的成品。
- 不要绕过安全拒绝，也不要绕过自动门禁的 `FAIL`。
- 不要仅凭自动检查就晋级；没有记录人工判定的候选不可晋级。
- 没有晋级出成品图的页，不许报成完成。
