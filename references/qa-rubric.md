# 验收标准

两层。自动层是脚本，人工层是**你必须真的看、真的判、真的记**的判断。两层都不能省，脚本也不允许你伪造第二层。

## 自动门禁

由 `scripts/validate-composite.py` 写进 `automatic.json`：

| 门禁 | 检查什么 | 判定 |
|---|---|---|
| `geometry` | 能解码、非退化、画面比例与冻结的 `output.aspect_ratio` 一致、格式与扩展名一致；`exact` 分辨率必须精确匹配，provider-native 至少 512px | PASS / FAIL / NOT-CHECKED |
| `colour_mode` | 文件里确实有所请求的色彩模式，且画面不像单色 | PASS / FAIL / NOT-CHECKED |
| `alpha_policy` | alpha 通道的存在与否正好符合 `output.alpha` | PASS / FAIL / NOT-CHECKED |
| `background` | 边缘主色与声明的纯色一致 | PASS / FAIL / NOT-CHECKED |
| `reference_integrity` | 每张冻结参考图的哈希仍与记录一致 | PASS / FAIL / NOT-CHECKED |
| `identity_required_elements` | 身份锁要求的要素只做记录，留给人工核对；脚本看不见它们 | NOT-CHECKED |

几何、色彩模式、alpha 策略或背景**颜色**任一项不合格，总判定即为 `FAIL`。有两项被**故意**设为不致命，因为判死它们会误杀好图：

- 背景不够平整。边缘按四边分别采样并报出（`border_clean_share_per_side`）；主体跑出画面是构图，不是缺陷。只有背景**颜色**与声明不符才算失败。
- `identity_required_elements`，永远是 `NOT-CHECKED`。

`candidate_sha256` 会重新计算，必须与磁盘上的字节一致。`injection_survey` 记录看过什么、没看过什么，并且永远包含一条 `NOT-CHECKED`——特征串味不是脚本能判的。**绝不要把自动层说成"身份或画风已通过"。**

门禁跑在 `scripts/materialize-image.py` 落地后的候选图上，绝不跑在渠道下载的原始文件上：渠道偶然返回了 RGB，不能当作输出规格已达成。

## 人工门禁

由评审人写进评审 JSON。六项必填：

- `style_consistency` — 画面里每个角色的线宽、上色层数、高光处理、对比度一致。通过这一项**必须**附带 ≥20 字的 `style_consistency_note`，写清比较了什么。
- `register_consistency` — 每个人都落在冻结的档位上；头身比读数一致；没有人退回自己人设图的比例。`register_evidence` 写明你拿什么做的对照。
- `anatomy_contact` — 手、遮挡关系、道具与接触点站得住：没有粘连的肢体、漂浮的手、互相穿插。
- `cast_accuracy` — 声明的角色都在、都能从身份锁认出来，且没有未声明的角色出现。
- `text_accuracy` — `lettering.core_text` 的每一个字都原样出现、落在正确的格子里，且别处没有任何多余文字。**必须逐字核对，包括标点。**
- `pose_and_story` — 画面呈现了声明的动作，且这个动作读得出素材里的那个桥段。

漫画页还要额外人眼过一遍（属于 `pose_and_story` 与 `text_accuracy` 的范围，必须写进备注）：

- 分格边界与格数是否正确，顺序是否符合 `reading_direction`。
- 每一条对白的气泡尾巴是否指向正确的说话人；旁白框没有尾巴；拟声字没有被画进气泡里。
- 每一格的文字是否落在自己的格内，没有压脸、压手、压住正在表演的动作，也没有跨过格线。
- 是否有一格明显滑向 3D 渲染风/照片风（体积光、摄影式景深、油画质感），而其余格是平涂赛璐璐——这是整页不合格，不是单格问题。

## 脚本强制的规则

- 任何门禁 `FAIL`，总判定必须是 `retry`，且 `targeted_retry` 只能指出**一个**根因。列三个原因的"重试"不算定向，会被拒绝。
- 全部门禁 `PASS` → 判定 `PASS`。总判定是 `PASS` 而任何一项不是 `PASS`，直接拒绝。
- `reference_integrity` 或 `identity_required_elements` 的 `FAIL` 不能靠改提示词重试；那意味着冻结输入变了或身份失败。记录根因，重新冻结。
- 自动判定为 `FAIL` 的候选不能记录成可晋级，也不能晋级。
- 没人看过图，就把人工门禁标成 `NOT-CHECKED`，并把该图报成未验证。不要给没评估过的门禁打 PASS。

## 汇报

如实逐图汇报：

- 晋级的成品文件，或者为什么没有；
- 哪些门禁自动通过了；
- 哪些门禁还需要人确认，具体看什么；
- 相对预算花掉了多少候选。

绝不把未验证的图说成已验证，也绝不在还有图没有晋级成品时把 run 说成完成。
