# 《大逼兜》上集 · 用现有能力卡制作手册

> 目标：不新增任何功能，用现在这套（image.c16 / h3.i2v / h3.flf2v / h3.r2v9 / h3.u30 / 剪辑页）做出
> **12 镜、约 70 秒**的竖屏短剧开场，验证"能不能拍出这个味道"。
> 做完能用同一套方法扩到 24 镜 / 168 秒。

---

## 一、设计取舍（为什么这么拍）

| 原稿要求 | 现有能力 | 我们的做法 |
|---|---|---|
| 母版派生，人物绝对一致 | ❌ 没有参考图生图卡 | **文字锚点**：把人物描述写成一段固定英文模块，逐字复用到每镜首帧；第一张满意的立刻存进素材库当参考图 |
| 逐句对白、精确控制 | ✅ H3 原生出声 | 对白写进视频提示词：`(S1)` + `<d>[Chinese] 台词</d>`，每镜 ≤2 句 |
| 三色字幕 | ⚠️ 只能单一样式 | 先用剪辑页"逐镜字幕"单色；三色留到以后 |
| 侧链闪避 BGM | ❌ | 用手动音量：对白镜选轻的 BGM，或干脆不加 BGM |
| 首尾帧同图隐形剪辑 | ✅ `h3.flf2v` | 连续对话镜全部用它 |
| 1080×1920 | ⚠️ 显存 | 先 0.4MP 出片（480×832），成片导出 720×1280；确认味道对了再提分辨率 |

**一句话**：这个版本不追求"电影级"，追求"**同一套流程能重复出 12 镜，且人物不崩、剪辑不跳**"。

---

## 二、角色锚点（复制粘贴用，别改字）

这三段是整套片子的地基。**每镜首帧提示词里都要原样带上对应人物的那段**，一个字都别改。

### 刘义隆（儿子，文帝）

```text
a thin pale Chinese man in his early forties, short thin beard, wearing a black ceremonial crown
with a flat rectangular board on top and SHORT strings of white beads hanging only to his eyebrows,
black ceremonial robe with a high white collar, slight stoop, nervous and eager to please
```

### 刘裕（父亲，武帝鬼魂）

```text
a weathered Chinese man in his sixties, grey-streaked beard, hair tied back with a dark cloth,
wearing a plain dark grey-black long robe, worn but completely intact with no tears or patches,
brown leather belt, no sword, hands clasped behind his back, straight back, chin slightly raised,
calm and intimidating
```

### 拓跋焘（北魏太武帝）

```text
a lean Chinese man in his late thirties, short black beard, dark lamellar armour with a grey fur
collar, round helmet, holding a small bundle of herbs, relaxed confident half-smile, cocky
```

### 场景锚点

```text
inside a Liu-Song ancestral temple hall, grey stone walls, dark wooden columns,
plain BLANK wooden tablets with absolutely no writing on them, tall bronze candlesticks with
small candle flames, a bronze incense burner with thin drifting smoke, cold ambient light,
cinematic, shallow depth of field, vertical 9:16
```

### 负面词（每镜都加）

```text
no text, no calligraphy, no plaques, no banners, no couplets, no Chinese characters anywhere,
no extra people in the background, no modern objects, no bare head
```

> **为什么负面词要写死**：试跑三镜里，牌位全被模型写上了自造汉字。"无反光、无文字"这种话必须点名。

---

## 三、12 镜分镜表

| # | 镜 | 卡 | 时长 | 谁在说 | 目的 |
|---|---|---|---|---|---|
| 1 | A1 上香 | `h3.i2v` | 6s | — | 交代地点与人 |
| 2 | A2 拍肩 | `h3.i2v` | 4s | — | 惊吓点，只有手和肩 |
| 3 | A3 回头 | `h3.i2v` | 4s | — | 视线接父亲 |
| 4 | A4 「爹。」 | `h3.r2v9` | 8s | 刘义隆→刘裕 | 双人第一次同框 |
| 5 | B1 「打到长安了吗」 | `h3.flf2v` | 10s | 刘裕→刘义隆 | 连续对话，首尾同图 |
| 6 | B2 「围了多久」「二百多天」 | `h3.flf2v` | 8s | 刘裕→刘义隆 | 数字砸下来 |
| 7 | C1 「他退到长江了」 | `h3.i2v` | 6s | 拓跋焘（画外） | 先声后人 |
| 8 | C2 拓跋焘出场 | `h3.i2v` | 7s | 拓跋焘 | 赢家登场 |
| 9 | C3 「滚滚滚…等会」 | `h3.r2v9` | 9s | 刘义隆→拓跋焘 | 三人同框 |
| 10 | D1 「我当年两千七百人」 | `h3.i2v` | 10s | 刘裕 | 火到顶 |
| 11 | D2 一巴掌 | `h3.i2v` | 3s | — | 爆发 |
| 12 | E1 卡片 | 剪辑页片尾 | 3s | — | 收尾 |

合计约 **78 秒**，成片会因 4n+1 取整变成 **82~86 秒**。

---

## 四、操作流程（照做即可）

### 第 0 步 · 建项目

1. 打开 `http://127.0.0.1:6006/?tab=edit`
2. 左上角项目下拉 →「新建项目」→ 名字填 **《大逼兜》上集 v1**
3. 右侧「成片设置」：画幅 **9:16**，分辨率先选 **720×1280**

---

### 第 1 步 · 出三张角色锚点（各一次）

进「创作台」标签页，选 **剧照 / 角色图（C16）**：

**刘义隆锚点**

```text
冷调古装短剧定妆照，竖屏 9:16，太庙内殿石墙前，正面半身：
a thin pale Chinese man in his early forties, short thin beard, wearing a black ceremonial crown
with a flat rectangular board on top and SHORT strings of white beads hanging only to his eyebrows,
black ceremonial robe with a high white collar
烛光从左侧打过来，冷色环境光，电影感，浅景深
no text, no calligraphy, no plaques, no extra people
```

**刘裕锚点**（同样结构，换成刘裕那一段，加 `hands clasped behind his back`）

**拓跋焘锚点**（换成拓跋焘那段，加 `holding a small bundle of herbs`）

> 出图后点图片右下「下载」旁边不需要操作，图片会自动进素材库。
> **如果三张里有一张冠错了/脸崩了，重出一张，直到满意为止**——这三张决定全片。

---

### 第 2 步 · 逐镜出首帧（12 次出图）

每镜都用 **C16**，提示词 = 场景锚点 + 人物锚点 + 本镜动作。下面给前 3 镜全文，后面同理。

**A1 首帧（背影）**

```text
inside a Liu-Song ancestral temple hall, grey stone walls, dark wooden columns,
plain BLANK wooden tablets with absolutely no writing on them, tall bronze candlesticks,
bronze incense burner with thin drifting smoke, cold ambient light, vertical 9:16,
中景背影：a thin pale Chinese man in his early forties, black ceremonial crown with flat board,
black robe with high white collar, standing with his back to the camera, both hands holding
incense sticks up in front of his chest, slightly stiff posture
no text, no calligraphy, no plaques, no extra people
```

**A2 首帧（手 + 肩）**

```text
inside a Liu-Song ancestral temple hall, cold ambient light, vertical 9:16,
extreme close-up: only a right shoulder and sleeve are visible in frame,
a plain dark grey-black robe sleeve, worn but intact,
a wrinkled elderly male hand enters from the right edge of frame and rests lightly on the shoulder,
fingers naturally curved
no text, no calligraphy, no extra people, no face
```

**A3 首帧（回头）**

```text
inside a Liu-Song ancestral temple hall, cold ambient light, vertical 9:16,
近景：a thin pale Chinese man in his early forties, black ceremonial crown with a flat board and
short bead strings, black robe with high white collar, turned sharply to look over his shoulder,
eyes wide, mouth slightly open, looking toward frame-left, NOT looking at the camera,
the bead strings still swinging from the turn
no text, no calligraphy, no extra people
```

> 后面 9 镜按同样公式写：**场景 + 人物 + 这一镜的姿态/景别 + 负面词**。
> 每镜出图后先看一眼：**冠对不对、牌位有没有字、有没有多出来的人**。不合格就重出，别省这一步。

---

### 第 3 步 · 首帧 → 视频（12 次生成）

回到「创作台」，选卡：

- 单人镜 → **图生视频（h3.i2v）**，首帧选刚才那张
- 双人/三人对话 → **九图多参考 + 配音（h3.r2v9）**，参考图选 2~3 张锚点
- 连续对话 → **首尾帧过渡（h3.flf2v）**，**首帧和尾帧选同一张图**

**时长**：A1 6s、A2/A3 4s、A4 8s、B1 10s、B2 8s、C1 6s、C2 7s、C3 9s、D1 10s、D2 3s

**视频提示词**（英文写画面，中文只放台词）：

**A1（无对白）**

```text
Camera pushes in very slowly. Incense smoke drifts upward in the candlelight, flames flicker
gently. The man holds the incense steady, only his sleeve and back show a slight breathing motion.
He does not turn around. Ambient temple room tone, distant wind.
```

**A4（双人对白）**

```text
Wide two-shot: the son stands facing the man in black, the older man stands slightly to frame-left,
both in the temple hall. The older man reaches out and flicks ash off the son's shoulder with
the back of his fingers.
(S1) the son swallows and says, <d>[Chinese] 爹。</d>
(S2) the older man answers calmly, <d>[Chinese] 嗯。</d>
The son does NOT speak again, his mouth stays closed.
Camera holds steady, very slow push in.
```

**B1（连续对话，首尾同图）**

```text
Two-shot, static camera, the two men facing each other at a small distance.
(S2) the older man asks, <d>[Chinese] 听说你又北伐了？打到长安了吗？</d>
(S1) the son answers hesitantly, <d>[Chinese] 没呢，爹。遇到一点小情况。</d>
Both stay in place; only slight breathing and head movement. No one else enters the frame.
```

**B2（数字砸下来）**

```text
Same two-shot, static camera. The son looks down, then back up.
(S2) the older man asks flatly, <d>[Chinese] 围了多久？</d>
(S1) the son answers quietly, <d>[Chinese] 二百多天。</d>
The older man does not move at all.
```

**C1（画外音，双人转头）**

```text
Two-shot, both men in frame facing each other.
(S3) a voice comes from OFF-SCREEN, relaxed and amused, <d>[Chinese] 他退到长江了。</d>
Both men turn their heads toward the off-screen voice at the same time.
Neither of them speaks.
```

**C2（拓跋焘出场）**

```text
Medium shot, side corridor shadows. A lean man in dark lamellar armour with grey fur collar
steps out of the shadow, round helmet, holding a small bundle of herbs in one hand.
(S3) he says casually, <d>[Chinese] 听说你吓病了。给你带了点药。</d>
Camera tracks sideways slightly as he walks in.
```

**C3（三人）**

```text
Three-shot: the son in the middle slightly back, the older man at frame-left, the armoured man
at frame-right. The two older men talk past the son.
(S1) the son snaps, <d>[Chinese] 滚滚滚，谁要你的药。</d>
then he pauses, frowns, and adds, <d>[Chinese] 等会，你怎么会在这啊。</d>
The other two do not speak.
```

**D1（火到顶）**

```text
Close shot, chest and up, the older man steps toward the son, jaw tight.
(S2) he says, low and hard, <d>[Chinese] 我当年两千七百人，破过他爹三万骑兵。你个废物点心。</d>
The son does not speak, only his eyes move.
```

**D2（一巴掌）**

```text
Medium two-shot. The older man's palm swings and lands on the son's cheek.
The son's head snaps sideways, his crown tilts, hair flies.
One single clean slap, no slow motion, no camera shake.
Sound: a sharp slap, then total silence.
```

---

### 第 4 步 · 剪辑页组装

1. 进「剪辑」标签页，把 12 个镜头按顺序排好（拖拽排序）
2. **每镜填字幕**：右侧镜头设置里「字幕」一栏填台词（不填会**自动烧镜头名**，就是试跑里那个"A1 上香"）
3. 旁白：**这片子不要旁白**，全部关掉「旁白」
4. 片头：`成片设置 → 片头`，文字 **《大逼兜》上集**，1.5 秒
5. 片尾：`成片设置 → 片尾`，文字 **上集 · 完**，3 秒
6. BGM：素材库选「紧张」或「燃」里的一首；**只在 C2 之后进**（前 12 秒不加，试跑证明那样更有压迫感）
7. 字幕样式：单色白色，字号默认，底部居中

---

### 第 5 步 · 导出

`导出成片` → 720×1280 / 烧字幕 / 带 BGM → 执行。

导出后看三件事：

1. **总时长**：应该在 82~86 秒之间，明显偏短说明有镜头没进去
2. **前 15 秒是否安静**（没有 BGM、只有环境声）
3. **字幕有没有变成镜头名**（如果出现"A1 上香"，说明那一镜的字幕没填）

---

## 五、质检清单（每次导出后跑）

| 项 | 怎么查 | 不合格怎么办 |
|---|---|---|
| 伪汉字 | 每镜抽一帧看牌位 | 重出首帧，把牌位改成侧 45° 或干脆不放牌位 |
| 冠制 | A1/A3/A4 看冠 | 用刘义隆锚点那张当首帧重出（别重新画） |
| 手 | A2、D2 抽帧看手 | 换构图：手只露一半 / 用袖口挡住 |
| 人物漂移 | 12 镜连看 | 哪一镜脸不对，就换用锚点图当首帧重出那一镜 |
| 对白糊 | 听 A4/B1/B2/C3 | 把每镜台词减到 1 句，重出 |
| 剪辑点跳 | 连续镜之间看 | 连续镜必须用 `h3.flf2v` 且首尾同图 |

---

## 六、常见问题

**Q：为什么 A1 的冠总是错？**
冕冠这种"顶上一块板 + 垂珠"的结构，模型很容易画成乌纱帽。**最稳的做法**：先在锚点图里把冠画对，后面所有镜都用那张当首帧，只改表情/角度。

**Q：能不能不要那么多次出图？**
可以。同一场景的连续镜（B1→B2）可以共用一张首帧，只改视频提示词里的台词。这样 12 镜只需 7~8 张图。

**Q：对白能不能后期配音？**
能，但建议别。H3 原生出声的口型和语气是同步的；后期配音要重做对口型（`h3.lipsync`），多一道工序。

**Q：三色字幕（父白/子金/拓跋蓝）怎么实现？**
现在剪辑页只支持单一样式。要三色得走 ASS 字幕，属于后续功能。

**Q：想扩到原稿的 24 镜怎么办？**
按同一张表继续加行：连续对话用 `flf2v`，双人/三人用 `r2v9`，动作镜用 `i2v`。总时长会到 170~185 秒，导出的分辨率建议降到 608×1080 再上采样。

---

## 七、这套方法的成本

| 项 | 数量 | 单次耗时 | 合计 |
|---|---|---|---|
| 出图（锚点 + 首帧） | 3 + 12 | 40s | ≈10 分钟 |
| 出视频 | 12 | 4~8 分钟 | **≈70 分钟** |
| 合成导出 | 1 | 1~2 分钟 | 2 分钟 |
| **合计（含重试）** | | | **约 2 小时** |

试跑三镜实测：静帧 40s、视频 6 分钟/镜，与上表一致。
