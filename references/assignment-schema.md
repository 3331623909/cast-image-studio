# 作业格式（schema version 2）

一个 JSON 对象。`scripts/manage-run.py validate-assignment` 是唯一裁判：这份文档解释字段，脚本决定什么合法。

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema_version` | 是 | 必须是 `2` |
| `confirmation` | 是 | `{confirmed: true, confirmed_at: <ISO 时间戳>}`；`confirmed` 必须是字面上的 `true` |
| `run_name` | 是 | kebab-case；决定 run 目录名，必须唯一 |
| `image_count` | 是 | 必须等于 `len(images)` |
| `input` | 是 | 见下 |
| `images` | 是 | 非空列表；每张图最多 6 个角色 |
| `execution` | 是 | `{mode, requested_parallelism, max_parallelism, commit_strategy}` |
| `budget` | 是 | `{per_image_candidates, per_provider_candidates, run_candidates, confirmed_over_24}` |
| `selection` | 否 | 选定的概念，一段话；进入提示词的 `SELECTED TREATMENT` 区块 |
| `selection_detail` | 否 | 选定方案的可核对记录：`proposal_id`、`title`、`rating`、`frame`、`adjustments[]`、`reply`、`revision`。只在改过方案时才写 `revision` |
| `cast_markdown` | 否 | 自由 markdown，原样进入提示词 |
| `output_dir` | 否 | run 目录位置；默认 `artifacts/cast-image-studio/<run_name>` |
| `notes` | 否 | 自由文本，从不解析 |
| `skill_root` | 否 | 覆盖参考图路径的回落目录。**不写也能跑**：相对路径先按作业文件所在目录解析，找不到时自动回落到本技能自己的目录 |

## `input`

`material`：`text` 或 `path` 二选一，外加 `language`（默认 `zh-Hans`）与可选的 `theme`。

```json
{"kind": "material", "text": "……整段转录……", "language": "zh-Hans", "theme": "…"}
```

`brief`：`{"kind": "brief", "brief": "……一段话……", "language": "zh-Hans"}`。

## `images[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 小写 `snake_case`，全 run 唯一，作为图片 id |
| `title` | 否 | 默认等于 `name`；出现在提示词里 |
| `framing` | 是 | 机位距离与裁切，例如 `waist-up three-quarter view` |
| `shot` | 是 | 短标签，例如 `medium two-shot`；整页基调 |
| `subject` | 是 | 这一页在讲谁、讲什么 |
| `expression` | 否 | 默认 `as the action requires` |
| `action` | 否 | 整页层面的动作；逐格动作写在 `panels[]` |
| `interaction` | 否 | 谁碰到谁；两个角色有接触时应当写 |
| `composition` | 否 | 构图指令 |
| `props` | 否 | 整页道具列表 |
| `comic` | **是** | 分格布局，见下 |
| `panels` | **是** | 逐格内容，见下 |
| `cast` | 是 | 见下 |
| `art` | 是 | 见下 |
| `background` | 是 | `{mode, description, color?}`，`mode ∈ {solid, scene, transparent}` |
| `lettering` | **是** | 精确文字与字行，见下 |
| `references` | 是 | 类型化参考图；每个在场角色一张 identity，外加**正好一张**字行参考 |
| `output` | 是 | `{format, aspect_ratio, alpha, resolution}` |

### `comic`

```json
{"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom",
 "reading_direction": "top panel first, then the bottom panel",
 "gutters": "clean even white gutters between panels, with a thin dark panel border"}
```

- `mode ∈ {whole-canvas, panel-strip}`。默认、也是推荐 `whole-canvas`：**一页里所有分格由同一张图承载**，线宽与对比度天然统一。`panel-strip` 是每格单独出图再拼版，只在单页太大、渠道尺寸不够时才用。
- `layout` 与 `panel_count` 必须匹配：

| layout | panel_count |
|---|---|
| `single` | 1 |
| `top-bottom` / `left-right` | 2 |
| `1x3` | 3 |
| `2x2` / `1x4` | 4 |
| `2x3` | 6 |
| `3x3` | 9 |

- `reading_direction` 与 `gutters` 可省略，省略时用默认值（从上到下、左右分栏；均匀白槽 + 细深色格线）。

### `panels[]`

```json
{"panel": 1, "shot": "medium two-shot", "action": "Gemini 甩出一只手宣布完成",
 "expression": "Gemini 笑得很开，Claude 面瘫", "props": [], "transition": "Claude 的冷回话落下来，气氛翻转"}
```

- `panel` 从 1 连续编号，数量必须等于 `comic.panel_count`。
- `shot` 与 `action` 必填；`expression`、`props`、`transition` 可选。`transition` 为空字符串表示不与下一格衔接。
- 每一格都要有具体的动作，不要写"他们在聊天"这种笼统描述。

### `lettering`

```json
{
  "text_style": "01_speech-balloon",
  "language": "zh-Hans",
  "style_reason": "普通的对话加一句吐槽",
  "core_text": [
    {"index": 0, "text": "我把图跑完了！", "panel": 1, "speaker": "gemini", "delivery": "speech"},
    {"index": 1, "text": "你确定？我这边还在排队。", "panel": 2, "speaker": "claude", "delivery": "speech"}
  ]
}
```

- `text_style` 必须是 `references/text-styles.json` 里的键。可用值：

| 值 | 用途 | 允许的 delivery |
|---|---|---|
| `01_speech-balloon` | 默认对白 | `speech` |
| `02_burst-shout` | 怒吼、指责、突然发火 | `speech` |
| `03_thought-cloud` | 心声 | `thought` |
| `04_caption-box` | 旁白、时间地点、故事自己的声音 | `caption` |
| `05_manga-impact` | 整页一次的极端冲击 | `speech` / `sfx` |
| `07_casual-dialogue` | 日常闲聊、温柔吐槽 | `speech` |
| `08_sfx-style` | 拟声字（撞击、摔门、东西落地） | `sfx` |

- `core_text[].index` 从 0 连续编号。
- `panel` 必须在 `1..panel_count` 之内，且**每一格都至少被覆盖一次**——没有沉默的格子。
- `speaker`：本图阵容里的角色（id / 显示名 / 别名都行），或 `narrator`、`device`。说话人必须在该格 `cast[].panels` 里出现，否则被拒绝。`sfx` 允许 `device`（物件发出的声音）。
- `delivery ∈ {speech, thought, caption, sfx}`。
- 文字**逐字精确**，不翻译、不缩写、不调序、不重复。中文小字有翻车风险，出图后必须逐字核对。

### `cast[]`

```json
{"character": "gemini", "representation": "physical", "panels": [1, 2], "staging": "…", "reason": "…"}
```

- `character` 接受 id（`c01`）、显示名（`Gemini`）或别名（`双星`）。歧义或未知会被拒绝。
- `representation ∈ {physical, avatar, offscreen, absent}`。`physical` 与 `avatar` 必须写 `staging`；`absent` 必须 `panels: []`；其余至少占一格。
- `panels` 不能超出 `comic.panel_count`。一个角色只能出现一次。每张图最多 6 人。

### `art`

```json
{
  "preset": "manga",
  "style": {"mode": "preset"},
  "register": {"mode": "locked", "name": "compact", "head_ratio": 5.0,
               "acceptance_range": [4.8, 5.2], "reason": "两格双人镜统一档位"}
}
```

- `preset` 取自 `references/art-presets.json`。默认 `manga`（二次元赛璐璐）。`style.mode = "custom"` 时额外给 `contract`（`line`、`shading`、`highlights`、`palette`、`finish`），它会替换预设的那几项。
- `register.mode = "locked"`：需要 `name`（`chibi` / `compact` / `mature`）、`head_ratio`、以该比值居中的 `acceptance_range`、以及 `reason`。档位区间：`chibi` 2.1–3.6、`compact` 3.6–6.0、`mature` 6.0–9.0。
- `register.mode = "follow_cast"`：需要 `of` 指定某个在场角色，整页采用她那档。
- `register.mode = "mixed"`：需要 `members`（角色 → 档位）与 `relative_height`。
- **角色自己人设图的头身比永远不能变成这一页的头身比。** 换档时绝不让成年角色变小孩。

### `references[]`

```json
{"id": "c01", "path": "assets/characters/c01/c01_gemini_01_master.jpg",
 "roles": ["identity"], "instruction": "Control identity only", "character": "c01"}
```

角色参考图：

- `id` 必须等于角色 id；`character` 必须写；`roles` 必须含 `identity`；`path` 必须是该角色登记的人设图。
- 每个在场角色（`physical` / `avatar`）**必须正好有一张**；不在场的角色不许带参考图。

字行参考图（每张图**正好一张**）：

```json
{"id": "lettering", "path": "assets/text-style-templates/01_speech-balloon/reference.webp",
 "roles": ["lettering", "typography"], "instruction": "只复制字行处理，绝不复制参考图里的文字"}
```

- `roles` 必须正好是 `["lettering", "typography"]`。
- `path` 必须等于 `lettering.text_style` 所选模板自己的 `reference.webp`，否则被拒绝。
- 声明了 `lettering` 却不带字行参考图、或带了却声明没有字，都会被拒绝。

其它：

- 每张图最多 12 张参考图。
- 相对路径先按作业文件所在目录解析；找不到时自动回落到本技能自己的目录（或你在顶层写的 `skill_root`）。绝对路径直接用。
- 可选的 `sha256` 写了就会校验。

## `execution`

`{"mode": "sequential"|"parallel", "requested_parallelism": 1..5, "max_parallelism": 5, "commit_strategy": "coordinator-serial"}`。

## `budget`

`per_image_candidates` ≤ 8，`per_provider_candidates` ≤ 3，`run_candidates` ≥ `image_count × per_image_candidates`。当这个乘积超过 24 时，`confirmed_over_24` 必须是 `true` 且必须给 `approval_note`。

## 示例

`references/example-assignment.json` 是一个**可运行**的两格漫画示例（双子星 + 克劳德 + ChatGPT，字行 `01_speech-balloon`）。它不写 `skill_root`：`assets/...` 相对路径会先按作业文件所在目录解析，找不到时自动回落到技能自己的目录，所以在任何机器上、放到任何目录都能直接跑。

## 最小可用示例

```json
{
  "schema_version": 2,
  "confirmation": {"confirmed": true, "confirmed_at": "2026-10-13T12:00:00Z"},
  "run_name": "release-day-argument",
  "image_count": 1,
  "input": {"kind": "material", "text": "……素材原文……", "language": "zh-Hans", "theme": "发布日又被鸽了"},
  "selection": "Gemini 和 Claude 争论谁该背发布延期的锅，ChatGPT 在旁边看戏",
  "selection_detail": {"proposal_id": "A", "title": "又不是我", "rating": "★★★ 首推",
                       "frame": "1 页 / top-bottom 2 格", "reply": "A"},
  "images": [
    {
      "name": "release_day_argument",
      "title": "又不是我",
      "framing": "waist-up two-shot inside each panel",
      "shot": "medium two-shot",
      "subject": "两个角色为发布延期互相甩锅，第三个人看戏",
      "comic": {"mode": "whole-canvas", "panel_count": 2, "layout": "top-bottom"},
      "panels": [
        {"panel": 1, "shot": "medium two-shot", "action": "Gemini 甩手指向 Claude",
         "expression": "Gemini 理直气壮，Claude 面瘫"},
        {"panel": 2, "shot": "closer two-shot", "action": "Claude 不动声色地回一句，ChatGPT 在旁边捂嘴笑",
         "expression": "Claude 无动于衷，ChatGPT 憋笑", "props": ["桌沿"]}
      ],
      "lettering": {
        "text_style": "01_speech-balloon",
        "style_reason": "普通对话加一句吐槽",
        "core_text": [
          {"index": 0, "text": "又不是我鸽的。", "panel": 1, "speaker": "gemini", "delivery": "speech"},
          {"index": 1, "text": "你先把日志交上来。", "panel": 2, "speaker": "claude", "delivery": "speech"}
        ]
      },
      "cast": [
        {"character": "gemini", "representation": "physical", "panels": [1], "staging": "左，甩手"},
        {"character": "claude", "representation": "physical", "panels": [1, 2], "staging": "右，抱臂"},
        {"character": "chatgpt", "representation": "physical", "panels": [2], "staging": "画格边缘，捂嘴"}
      ],
      "art": {
        "preset": "manga",
        "style": {"mode": "preset"},
        "register": {"mode": "locked", "name": "compact", "head_ratio": 5.0,
                     "acceptance_range": [4.8, 5.2], "reason": "两格双人镜统一档位"}
      },
      "background": {"mode": "scene", "description": "角色身后一面素色办公室墙，纯色无纹理"},
      "references": [
        {"id": "c01", "path": "assets/characters/c01/c01_gemini_01_master.jpg", "roles": ["identity"],
         "instruction": "Control identity only", "character": "c01"},
        {"id": "c05", "path": "assets/characters/c05/c05_claude_01_master.jpg", "roles": ["identity"],
         "instruction": "Control identity only", "character": "c05"},
        {"id": "c02", "path": "assets/characters/c02/c02_chatgpt_01_master.jpg", "roles": ["identity"],
         "instruction": "Control identity only", "character": "c02"},
        {"id": "lettering", "path": "assets/text-style-templates/01_speech-balloon/reference.webp",
         "roles": ["lettering", "typography"], "instruction": "只复制字行处理，绝不复制参考图文字"}
      ],
      "output": {"format": "png", "aspect_ratio": "3:4", "alpha": false,
                 "resolution": {"mode": "provider-native", "width": null, "height": null}}
    }
  ],
  "execution": {"mode": "sequential", "requested_parallelism": 1, "max_parallelism": 5,
                "commit_strategy": "coordinator-serial"},
  "budget": {"per_image_candidates": 4, "per_provider_candidates": 2, "run_candidates": 4,
             "confirmed_over_24": false}
}
```
