# cast-image-studio

**素材进，成品漫画页出。**

给我一段故事、一段聊天记录、一张截图、一篇文章、一条发布说明，我产出一页**真正的漫画**：有分格布局、每格一个剧情节拍、逐字精确的对白/旁白/拟声字，画面上出现的角色**只有你声明过的那些**。

这不是"AI 画张插画"，而是把漫画当作**有契约的工程产出**：角色身份、头身档、画风、文字、预算、验收标准全部先冻结，再生成，最后经两层门禁裁决。

---

## 它到底解决什么问题

单张文生图有三个反复出现的坑，这个技能就是为它们造的：

| 坑 | 表现 | 本技能的对策 |
|---|---|---|
| **角色不像** | 同一个角色第二张就换脸、换发色、换衣服 | 角色**注册表**：每个角色一份身份锁 + 母图 sha256，身份块逐字进提示词，参考图只控身份 |
| **多角色同框崩** | 五个人凑一页，画风打架、比例失控 | 全页**一套线宽/上色层数/对比度**，一个画风 preset，头身档按注册表重新定档，绝不把成年角色画成小孩 |
| **文字画不对** | 中文字乱码、"差不多"的错字、气泡指向错人 | 文字**逐字**写进作业，字行走字行模板，人工门禁逐字核对（含标点） |

另外它顺手解决两件事：**不偷跑**（动手前两道确认闸门）和**不撒谎**（自动门禁判定不了的，如实报成未验证）。

---

## 核心概念

### 角色注册表

角色不是每次现编的，而是登记在 `assets/characters/character-registry.json`（schema v2）。每个角色有 `id`、显示名、中英别名、身份锁（`identity_lock`）、签名要素、色系、**`drawn_ratio`**（自己人设图的头身比）、**`register`**（`chibi` / `compact` / `mature`）、**`personality`**（怎么演她，逐字进提示词）。

目前登记 8 位：

| Id | 角色 | 别名 | 人设头身 | 档位 |
|---|---|---|---|---|
| `c01` | Gemini | 双星, 星猫, Spectral Star Cat | ≈6.0 | compact |
| `c02` | ChatGPT | GPT, 白龙, White Dragon Envoy | ≈7.1 | mature |
| `c03` | Qwen | 千问, 通义千问, Indigo Fan Lady | ≈8.2 | mature |
| `c04` | Kimi | 银之乐谱, 乐谱, Rainbow Score | ≈6.1 | mature |
| `c05` | Claude | 琥珀书, 书吏, Amber Archivist | ≈5.6 | compact |
| `c06` | Grok | 金恶魔, 恶魔, Crimson Raider | ≈5.8 | compact |
| `c07` | MiniMax | 小麦, 麦麦, Apricot Field | ≈6.8 | mature |
| `whalechan` | Whale-chan | 鲸鱼娘, 小鲸鱼 | 2.8 | chibi |

注册表是**权威**，不是装饰：加载时逐张校验母图哈希；`init` 时冻结注册表哈希，冻结后再改会被检测到，而不是悄悄生效。改人设改注册表，不改提示词。

### 作业（assignment）

一次生成任务的全部声明，一个 JSON：素材类型、模式、选角、逐格分镜、逐条文字、画风、输出规格、预算、并行度、确认状态。字段全表见 `references/assignment-schema.md`，可直接跑的模板见 `references/example-assignment.json`。

### 字行（lettering）

每页**必须有字**，而且每格至少一条。字行目录在 `references/text-styles.json`，共 7 种：

`01_speech-balloon` 对白气泡 · `02_burst-shout` 怒吼 · `03_thought-cloud` 心声 · `04_caption-box` 旁白框 · `05_manga-impact` 冲击 · `07_casual-dialogue` 日常口语 · `08_sfx-style` 拟声字

每种是一个文件夹，`template.md` 是逐字进提示词的那段话，`reference.webp` 是这一页唯一的字行参考图。

### 画风预设

`references/art-presets.json`，默认 `manga`（Manga cel）。另有 `house`（贴齐现有 Whale-chan 画风）、`clean-anime`、`soft-cel`。**一次 run 只用一套**，整页所有分格同一只手画的——有一格滑向 3D 渲染风/照片风，整页判不合格。

### 头身档

`chibi` ≈2.5–3.5 头 · `compact` ≈4.5–6 头 · `mature` ≈6–8 头。

关键规矩：**角色自己人设图的头身比永远不能变成画面的头身比。** 一页冻结一个档位（或 `mixed` 并写清相对身高），成年角色被压进小档位要重新配比例、**不能变幼**。

---

## 工作流：两道闸门 + 十步流水线

```
素材  →  [Gate 1 选方案]  →  [Gate 2 确认张数]  →  冻结  →  生成  →  自动门禁  →  人工门禁  →  晋级  →  收尾
         ↑ 停一次               ↑ 再停一次
```

**Gate 1｜选方案。** 从素材出**正好五个**真正不同的方案，摆成七列表格：选择／方案／核心场景／剧情走向与反转／分镜构图／关键台词／推荐程度与理由（`★★★ 首推`/`★★☆ 推荐`/`★☆☆ 可选`）。给完推荐就停——不写作业文件、不预构建提示词。

**Gate 2｜确认张数。** 你选完，把张数汇总一次（默认每个入选方案 1 页），拿到肯定答复才动手。

小改动（措辞、站位）不重发方案表，记进 `selection_detail.adjustments`；核心落点被换掉就要重走 Gate 1。

十步细流程见 `references/pipeline.md`：0 定模式 → 1 读素材 → 2 Gate 1 → 3 Gate 2 → 4 冻结 → 5 构建提示词 → 6 生成 → 6b 落地 → 7 自动门禁 → 8 人工门禁 → 9 记录与晋级 → 10 收尾。

---

## 两层验收

**自动层**（`validate-composite.py` → `automatic.json`）：几何／色彩模式／alpha 策略／背景完整性／alpha 覆盖／平涂色彩／参考图哈希／注入排查（`injection_survey`）。几何、色彩、alpha、背景**颜色**任一不合格即总判 `FAIL`。有两项**故意不判死**：背景不够平整（主体出画是构图不是缺陷）、`identity_required_elements`（脚本看不见，永远 `NOT-CHECKED`）。身份、画风、解剖、文字准确性**一律是人工门禁**，脚本只报 `NOT-CHECKED`，绝不报成通过。

**人工层**（评审 JSON，六项必填）：`style_consistency`（附 ≥20 字说明）· `register_consistency` · `anatomy_contact` · `cast_accuracy` · `text_accuracy`（逐字核对含标点）· `pose_and_story`。漫画页还要人眼看分格边界与顺序、气泡尾巴指向、文字有没有压脸/跨格线。

脚本强制的诚实规则：任何门禁 `FAIL` → 总判 `retry` 且只能指定**一个**根因；总判 `PASS` 而任一项非 `PASS` → 直接拒绝；没人看过图就标 `NOT-CHECKED` 并报成未验证。**绝不要把自动层说成"身份或画风已通过"。**

---

## 渠道与预算

四个渠道，固定顺序：`codex` → `openai` → `nano-banana` → `seedream`。顺序由脚本强制，记录表外渠道会被拒绝。错误分五类：`authentication`（不重试，换下家并告诉用户修哪个凭据）· `rate_limit`（等一等，同渠道重试一次）· `timeout`（重试一次再换）· `service`（换下家）· **`safety`（根因级停止，绝不改提示词绕过）**。

预算：每图 ≤8 个候选、每渠道 ≤3 个、一轮超过 24 个要先问。`record-error` 不花图像额度。

渠道返回的文件**从不直接采用**：必须经 `materialize-image.py` 落地（修容器/尺寸/alpha 策略，裁剪 >2% 要重新生成而不是硬切，禁止静默原地覆盖），门禁跑在**落地后**的候选图上。

并行只允许发生在生成步骤（1–5），构建提示词/记录/晋级/收尾都是串行，因为它们写 run manifest。

---

## 安装

技能就是**一个文件夹**，`SKILL.md` 在根。DSH 的发现目录：

```
C:\Users\<你>\.dsh\skills\cast-image-studio\      # Windows
~/.dsh/skills/cast-image-studio/                  # Linux / macOS
```

两种装法：**直接拷贝文件夹**（宿主热加载，不用重启），或用画布底部 Dock 的**技能库面板**上传 zip／贴 git 链接。

依赖：**Python 标准库 + Pillow**（`pip install Pillow`）。命令里 Windows 写 `python`，Linux/macOS 写 `python3`。所有路径都从脚本自身和作业文件的位置推导，**整个文件夹搬到任何目录、任何机器都能跑**，不用改代码。

装完自检：

```bash
python scripts/manage-run.py probe-registry        # 列出 8 个角色
python tools/build-cast-registry.py --check        # 只校验注册表和每张母图的哈希
python tests/test_cast_studio.py                   # 64 项测试
python scripts/manage-run.py validate-assignment --assignment references/example-assignment.json
```

---

## 最快的试用路径

1. 把 `references/example-assignment.json` 复制到别处（避免动到模板）。
2. `validate-assignment` → `init` 冻结它。
3. 给某个 `image` 跑 `build-prompt.py` 出提示词，读一遍，确认身份块和文字都在。
4. 用你配置好的生图渠道出图，`materialize-image.py` 落地。
5. `validate-composite.py` 跑自动门禁，然后**自己看图**填人工门禁，`record-candidate` → `promote` → `finalize`。

---

## 边界与不做什么

- **不造角色。** 选角只能来自注册表；绝不为了凑画面加人。单页最多 6 人，宁可分页也不把人缩小。
- **不偷跑。** Gate 2 没确认、作业没 `init` 冻结，就不生成。不超预算。不覆盖已有的提示词、run 目录和成品。
- **不绕门禁。** 自动 `FAIL` 的候选不能晋级；`safety` 拒绝就是停止。
- **不改冻结物。** 冻结后不加角色、不改头身档、不改画幅；要改就换一个 `run_name`。
- **不外扩。** 同名技能 `whalechan-image-character` / `whalechan-image-comic` 各自的目录完全不动——这个库是**附加层**，不进入它们的目录，也不改它们的计数。
- **不假装看过。** 没人看过的图，人工门禁如实报未验证。
- **只认文字准确。** 模型仍可能写错字——所以文字是**逐字写进作业**并**逐字人工核对**的，而不是让模型自由发挥。

---

## 文件地图

```
SKILL.md                          技能入口：闸门、确认格式、不可协商规则
README.md                         本文件
references/
  pipeline.md                     0–10 步逐步流程
  assignment-schema.md            作业全部字段 + 可运行示例
  cast-rules.md                   注册表、选角、头身档、画风一致性
  art-presets.json                4 个画风预设及契约（默认 manga）
  text-styles.json                7 种字行目录
  qa-rubric.md                    自动门禁 + 六项人工门禁
  provider-routing.md             渠道顺序、错误分类、预算、并行
  example-assignment.json         可运行的两格漫画示例
scripts/
  manage-run.py                   probe-registry / validate-assignment / init /
                                  record-candidate / promote / record-error /
                                  finalize / status
  build-prompt.py                 从冻结作业生成提示词（绝不手写、绝不改写）
  materialize-image.py            把渠道返回落地成冻结的输出规格
  validate-composite.py           完整自动门禁套件（背景完整性、alpha 覆盖、
                                  平涂色彩、参考图哈希、注入排查）→ automatic.json
  validate-image.py               单图自动门禁：几何 / 色彩模式 / alpha 策略
tools/
  build-cast-registry.py          从两个 whalechan 技能重建注册表（--check 只读校验）
tests/
  test_cast_studio.py             64 项测试
assets/
  characters/                     8 张角色母图 + character-registry.json
  text-style-templates/           7 套字行模板（template.md + reference.webp）
```

---

## 一句话总结

**先把角色、画风、文字和花钱上限冻死，再让模型画；能自动判的自动判，判不了的如实说没判。**

---

## 许可

**代码**以 MIT 许可发布，见 `LICENSE`。

**角色母图与字行模板图**（`assets/` 下的图片文件）是随技能运行的素材，按 MIT 一并提供，供**本技能运行**时加载与验证哈希使用。这些图是 AI 生成的二次元形象；其中 Whale-chan 为 DeepSeek 相关形象。如果你要拿它们做本技能之外的用途，请自行确认你所在场景下的权利与授权。

