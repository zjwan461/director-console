# 《大逼兜》上集 · 傻瓜式操作手册（全提示词版）

> 12 镜 / 约 80 秒 / 竖屏 9:16。
> **所有提示词都是完整可直接复制的**，不需要你自己替换任何内容。
> 每步告诉你：点哪里、选哪张卡、填什么、粘贴哪一段。

---

## 目录

- [第 0 步 · 建项目](#第-0-步--建项目)
- [第 1 步 · 三张角色锚点](#第-1-步--三张角色锚点)
- [第 2 步 · 12 张首帧](#第-2-步--12-张首帧)
- [第 3 步 · 12 段视频](#第-3-步--12-段视频)
- [第 4 步 · 剪辑页组装](#第-4-步--剪辑页组装)
- [第 5 步 · 导出与质检](#第-5-步--导出与质检)

---

## 第 0 步 · 建项目

1. 浏览器打开 `http://127.0.0.1:6006/?tab=edit`
2. 左上角项目下拉框 → 点「新建项目」→ 输入 **《大逼兜》上集 v1** → 确定
3. 右侧「成片设置」：
   - 画幅：**9:16**
   - 分辨率：**720 × 1280**

---

## 第 1 步 · 三张角色锚点

切到「创作台」标签页，能力卡选 **剧照 / 角色图（C16）**。
每张都按：画幅 **9:16** → 清晰度 **1.0 MP** → 粘贴下面整段 → 执行。

### 1-A 刘义隆（儿子）

```text
冷调古装短剧定妆照，竖屏构图，太庙内殿的石墙前，正面半身，人物居中略偏右：
a thin pale Chinese man in his early forties, short thin beard, wearing a black ceremonial crown with a flat rectangular board on top and short strings of white beads hanging only to his eyebrows, black ceremonial robe with a high white collar, slightly stooped shoulders, nervous and eager expression
烛光从画面左侧打来，冷色环境光，浅景深，电影质感，皮肤有细微质感
no text, no calligraphy, no plaques, no banners, no Chinese characters, no extra people, no bare head, no modern objects
```

### 1-B 刘裕（父亲）

```text
冷调古装短剧定妆照，竖屏构图，太庙内殿的石墙前，正面半身，人物居中：
a weathered Chinese man in his sixties, grey-streaked beard, hair tied back with a dark cloth, wearing a plain dark grey-black long robe, worn but completely intact with no tears and no patches, brown leather belt, no sword, hands clasped behind his back, straight back, chin slightly raised, calm and intimidating expression
烛光从画面右侧打来，冷色环境光，浅景深，电影质感
no text, no calligraphy, no plaques, no banners, no Chinese characters, no extra people, no bare head, no modern objects
```

### 1-C 拓跋焘（北魏太武帝）

```text
冷调古装短剧定妆照，竖屏构图，太庙内殿的石墙前，正面半身，人物居中：
a lean Chinese man in his late thirties, short black beard, dark lamellar armour with a grey fur collar, round helmet, holding a small bundle of herbs in his right hand, relaxed confident half-smile, cocky expression
烛光从画面左侧打来，冷色环境光，浅景深，电影质感
no text, no calligraphy, no plaques, no banners, no Chinese characters, no extra people, no modern objects
```

> 三张出完后**逐一检查**：冠对不对、有没有多出来的人、有没有自造汉字。
> 不满意就原样再执行一次（同一段提示词，模型每次结果不同）。
> 满意的三张会自动进素材库，后面步骤按名字引用它们：**刘义隆锚点 / 刘裕锚点 / 拓跋焘锚点**。

---

## 第 2 步 · 12 张首帧

全部用 **C16**，画幅 **9:16**，清晰度 **0.8 MP**。

---

### 2-1　A1 上香（背影）

```text
冷调古装短剧，竖屏，太庙内殿：灰色石墙、深色木柱、壁龛里竖着几块素面木牌位（木牌上完全空白，没有任何刻字）、长柄铜烛台点着小火苗、石台上一个铜香炉冒着细细的香烟，冷色环境光，浅景深，电影质感
中景背影：a thin pale Chinese man in his early forties, black ceremonial crown with a flat board on top, black ceremonial robe with a high white collar, standing with his back to the camera, both hands holding three incense sticks up in front of his chest, slightly stiff and nervous posture, shoulders a little raised
no text, no calligraphy, no plaques, no banners, no Chinese characters anywhere, no extra people, no modern objects
```

### 2-2　A2 拍肩（手特写）

```text
冷调古装短剧，竖屏，太庙内殿，冷色环境光，浅景深
大特写：画面里只出现一个人的右肩和袖口，a plain dark grey-black robe sleeve, worn but completely intact with no tears, brown leather belt edge visible at the bottom
一只布满皱纹的老年男性手掌从画面右侧伸进来，手背青筋明显，轻轻悬在肩上，手指自然微曲，还没完全落下
no text, no calligraphy, no extra people, no face
```

### 2-3　A3 回头

```text
冷调古装短剧，竖屏，太庙内殿：灰色石墙、深色木柱、素面空白木牌位、铜烛台烛火、铜香炉香烟，冷色环境光，浅景深
近景：a thin pale Chinese man in his early forties, short thin beard, black ceremonial crown with a flat rectangular board on top and short strings of white beads, black ceremonial robe with a high white collar, body turned sharply to look over his right shoulder, eyes wide open, mouth slightly open, looking toward the left edge of the frame, NOT looking at the camera, the bead strings still swinging from the turn
no text, no calligraphy, no plaques, no Chinese characters, no extra people
```

### 2-4　A4 双人同框（儿子 + 父亲）

> 这一镜的视频用 `h3.r2v9`，**不需要首帧图**。跳过本张。

### 2-5　B1/B2 双人对话静帧（共用一张）

```text
冷调古装短剧，竖屏，太庙内殿：灰色石墙、深色木柱、素面空白木牌位、长柄铜烛台、铜香炉香烟，冷色环境光，浅景深
双人中景，两人面对面站在香炉前，相距约一步：
画面左侧 a weathered Chinese man in his sixties, grey-streaked beard, hair tied back with a dark cloth, plain dark grey-black long robe worn but intact, brown leather belt, no sword, hands clasped behind his back, straight back, calm expression
画面右侧 a thin pale Chinese man in his early forties, short thin beard, black ceremonial crown with a flat board and short bead strings, black ceremonial robe with a high white collar, head slightly lowered, shoulders tense, uneasy expression
两人都看向对方，没有人看镜头
no text, no calligraphy, no plaques, no Chinese characters, no extra people, no modern objects
```

### 2-6　C1 双人转头（画外音）

```text
冷调古装短剧，竖屏，太庙内殿，冷色环境光，浅景深
双人中景，两人并排面对镜头略侧，画面左侧 a weathered Chinese man in his sixties, grey-streaked beard, dark grey-black robe, hands behind his back；画面右侧 a thin pale Chinese man in his early forties, black ceremonial crown with short bead strings, black robe with high white collar
两人同时把头转向画面右外侧（画外有人说话），表情一个是警觉、一个是惊疑，没有人看镜头
no text, no calligraphy, no Chinese characters, no extra people
```

### 2-7　C2 拓跋焘出场

```text
冷调古装短剧，竖屏，太庙内殿的侧廊：深色木柱之间有一道阴影，背景是灰色石墙与虚化的烛火，冷色环境光，浅景深
中景：a lean Chinese man in his late thirties, short black beard, dark lamellar armour with a grey fur collar, round helmet, holding a small bundle of herbs in his right hand, walking out of the shadow toward the camera, relaxed confident half-smile
画面偏暗，只有半边脸被烛光照亮
no text, no calligraphy, no plaques, no Chinese characters, no extra people
```

### 2-8　C3 三人同框

> 这一镜的视频用 `h3.r2v9`，**不需要首帧图**。跳过本张。

### 2-9　D1 刘裕逼近（胸口以上）

```text
冷调古装短剧，竖屏，太庙内殿，冷色环境光，浅景深
近景，胸口以上：a weathered Chinese man in his sixties, grey-streaked beard, hair tied back with a dark cloth, plain dark grey-black robe, brown leather belt, no sword, leaning slightly forward toward the camera, jaw tight, eyes hard, angry but controlled
背景是虚化的石墙与烛火，光从右下往上打，脸部有阴影
no text, no calligraphy, no Chinese characters, no extra people
```

### 2-10　D2 一巴掌（双人中景）

```text
冷调古装短剧，竖屏，太庙内殿，冷色环境光，浅景深
双人中景：画面左侧 a weathered Chinese man in his sixties, dark grey-black robe, right arm raised with palm open, mid-swing；画面右侧 a thin pale Chinese man in his early forties, black ceremonial crown, black robe with high white collar, head just starting to snap sideways, one hand half-raised in defence
两人距离很近，动作有力度，衣料被带动
no text, no calligraphy, no Chinese characters, no extra people
```

### 2-11　E1 片尾卡片

> 不用生成图。剪辑页用「片尾」文字实现。

---

## 第 3 步 · 12 段视频

切到「创作台」，**逐镜**按下面选卡、填时长、粘贴提示词。

---

### 3-1　A1 上香

- 卡：**图生视频（h3.i2v）**
- 首帧：选 **A1 首帧**（2-1 生成的那张）
- 画幅 9:16 / 清晰度 **0.4 MP** / 时长 **6 秒**

```text
Camera pushes in very slowly. Incense smoke drifts upward in the candlelight, the candle flames flicker gently. The man keeps holding the incense steady, only his sleeve and back show a very slight breathing motion. He does not turn around and does not move his head. Ambient temple room tone, faint wind outside.
```

### 3-2　A2 拍肩

- 卡：**图生视频（h3.i2v）**
- 首帧：选 **A2 首帧**
- 9:16 / 0.4 MP / **4 秒**

```text
The wrinkled elderly hand enters slowly from the right edge of frame and settles lightly on the shoulder, fingertips pressing down a little, the sleeve fabric shifting slightly with the movement. The camera barely moves, only a faint handheld breathing feel. Soft cloth rustle, distant wind.
```

### 3-3　A3 回头

- 卡：**图生视频（h3.i2v）**
- 首帧：选 **A3 首帧**
- 9:16 / 0.4 MP / **4 秒**

```text
The man turns his head quickly toward the left edge of the frame, the bead strings of his crown swinging with the motion, his eyes widening and pupils trembling, breathing fast. The camera stays still with a slight handheld feel. Sharp intake of breath, cloth movement.
```

### 3-4　A4 「爹。」

- 卡：**九图多参考 + 配音（h3.r2v9）**
- 参考图 1：**刘义隆锚点**　参考图 2：**刘裕锚点**　其余留空
- 音频槽：全部留空
- 9:16 / **0.7 MP** / **8 秒**
- 提示词（六段式，整段粘贴）：

```text
subject_definitions:
<Subject 1> is the son: a thin pale Chinese man in his early forties, short thin beard, black ceremonial crown with a flat rectangular board on top and short strings of white beads, black ceremonial robe with a high white collar, nervous and eager. <Picture 1> is his appearance reference.
<Subject 2> is the father: a weathered Chinese man in his sixties, grey-streaked beard, hair tied with a dark cloth, plain dark grey-black robe worn but intact, brown leather belt, no sword, hands clasped behind his back, calm and intimidating. <Picture 2> is his appearance reference.
<Subject 3> is the ancestral temple hall: grey stone walls, dark wooden columns, plain blank wooden tablets with no writing, tall bronze candlesticks, a bronze incense burner with drifting smoke, cold ambient light.

summary:
A two-shot dialogue scene inside the temple hall. The father appears behind the son and flicks ash off his shoulder; the son greets him, the father answers calmly. Reference images are used only for character appearance and the costume design.

retention_analysis:
The son keeps his face, crown, beard and black robe from <Picture 1>. The father keeps his face, grey beard, dark grey-black robe, belt and hands-behind-back posture from <Picture 2>. The temple environment keeps the stone walls, columns, incense burner and candlelight from <Subject 3>. The camera framing, blocking and timing are newly generated for this shot.

detailed_description:
Shot 1: static medium two-shot, vertical framing. <Subject 2> stands at frame-left in the middle distance, <Subject 1> stands at frame-right closer to camera, both facing each other in front of the bronze incense burner, cold candlelight from the sides, thin smoke drifting between them. <Subject 2> lifts his right hand and flicks a bit of incense ash off <Subject 1>'s shoulder with the back of his fingers, then lowers his hand back behind his back.
<Subject 1> (S1) swallows and says, <d>[Chinese] 爹。</d>
<Subject 2> (S2) answers calmly, <d>[Chinese] 嗯。</d>
<Subject 1> does NOT speak again; his mouth stays closed, only his eyes move. <Subject 2> does not smile. Camera holds steady with a very slow push in. No other people enter the frame.

overall_soundscape:
Quiet stone-room ambience, faint candle flicker, thin cloth rustle when the hand moves, distant wind outside the hall.

non_diegetic_music:
None. Silence under the dialogue.
```

### 3-5　B1 「打到长安了吗」

- 卡：**首尾帧过渡（h3.flf2v）**
- 首帧：**B1/B2 双人静帧**　尾帧：**同一张**（再选一次那张图）
- 9:16 / 0.4 MP / **10 秒**

```text
Static two-shot, both men stay in place facing each other, only slight breathing and small head movements. The father holds his hands behind his back and does not move his feet; the son lowers his head slightly, then looks up again while answering. No camera movement. No other people enter the frame.
(S2) the father asks, <d>[Chinese] 听说你又北伐了？打到长安了吗？</d>
(S1) the son answers hesitantly, <d>[Chinese] 没呢，爹。遇到一点小情况。</d>
The father does not reply.
```

### 3-6　B2 「二百多天」

- 卡：**首尾帧过渡（h3.flf2v）**
- 首帧/尾帧：**同一张 B1/B2 双人静帧**
- 9:16 / 0.4 MP / **8 秒**

```text
Static two-shot, same framing, no camera movement. The son looks down at the floor, then lifts his eyes back to the father.
(S2) the father asks flatly, <d>[Chinese] 围了多久？</d>
(S1) the son answers quietly, <d>[Chinese] 二百多天。</d>
The father does not move at all, his expression stays flat.
```

### 3-7　C1 「他退到长江了」

- 卡：**图生视频（h3.i2v）**
- 首帧：**C1 首帧**
- 9:16 / 0.4 MP / **6 秒**

```text
Both men stand still, then turn their heads toward the off-screen right at the same time, as if hearing someone behind them.
(S3) a relaxed amused male voice comes from OFF-SCREEN, <d>[Chinese] 他退到长江了。</d>
Neither of the two men speaks; their mouths stay closed. Camera holds steady.
```

### 3-8　C2 拓跋焘出场

- 卡：**图生视频（h3.i2v）**
- 首帧：**C2 首帧**
- 9:16 / 0.4 MP / **7 秒**

```text
The armoured man walks out of the shadow toward the camera at an easy pace, the fur collar and armour plates shifting with each step, the herbs swinging slightly in his hand.
(S3) he says casually, <d>[Chinese] 听说你吓病了。给你带了点药。</d>
Camera tracks sideways a little as he walks in.
```

### 3-9　C3 三人同框

- 卡：**九图多参考 + 配音（h3.r2v9）**
- 参考图 1：**刘义隆锚点**　参考图 2：**刘裕锚点**　参考图 3：**拓跋焘锚点**　其余留空
- 9:16 / **0.7 MP** / **9 秒**

```text
subject_definitions:
<Subject 1> is the son: thin pale Chinese man in his early forties, black ceremonial crown with short bead strings, black robe with high white collar. <Picture 1> is his appearance reference.
<Subject 2> is the father: weathered Chinese man in his sixties, grey-streaked beard, dark grey-black robe, hands behind his back. <Picture 2> is his appearance reference.
<Subject 3> is the northern emperor: lean Chinese man in his late thirties, short black beard, dark lamellar armour with grey fur collar, round helmet, holding a small bundle of herbs. <Picture 3> is his appearance reference.
<Subject 4> is the ancestral temple hall: grey stone walls, dark wooden columns, blank wooden tablets, bronze candlesticks, incense smoke, cold light.

summary:
A three-shot scene in the temple hall. The son is sandwiched between the two older men; the two elders talk past him. Only the son speaks twice. Reference images lock the three characters' faces and costumes.

retention_analysis:
Faces, beard, crown, helmets and costumes of the three characters are preserved from <Picture 1>, <Picture 2> and <Picture 3>. The temple environment is preserved from <Subject 4>. Blocking, timing and camera are newly designed.

detailed_description:
Static three-shot, vertical framing. <Subject 2> stands at frame-left, <Subject 3> at frame-right, both facing slightly inward; <Subject 1> stands in the middle but one step further back, so the two elders can look past him. Cold candlelight from both sides, incense smoke drifting.
<Subject 1> (S1) snaps at <Subject 3>, <d>[Chinese] 滚滚滚，谁要你的药。</d>
Then <Subject 1> pauses, frowns, and adds, turning his head slightly, <d>[Chinese] 等会，你怎么会在这啊。</d>
<Subject 2> and <Subject 3> do not speak; their mouths stay closed. <Subject 2> keeps his hands behind his back, <Subject 3> keeps the herbs in his hand. Camera holds steady, very slight push in.

overall_soundscape:
Stone hall ambience, faint candle flicker, armour plates clinking softly when <Subject 3> shifts his weight.

non_diegetic_music:
None.
```

### 3-10　D1 「我当年两千七百人」

- 卡：**图生视频（h3.i2v）**
- 首帧：**D1 首帧**
- 9:16 / 0.4 MP / **10 秒**

```text
The father leans a step closer to the camera, jaw tight, eyes hard, breathing slow and heavy, the cloth of his collar shifting slightly.
(S2) he says low and hard, <d>[Chinese] 我当年两千七百人，破过他爹三万骑兵。</d>
He pauses, then adds with contempt, <d>[Chinese] 你个废物点心。</d>
No other person is in frame. Camera holds steady with the slightest push in.
```

### 3-11　D2 一巴掌

- 卡：**图生视频（h3.i2v）**
- 首帧：**D2 首帧**
- 9:16 / 0.4 MP / **3 秒**

```text
One single clean slap: the father's open palm swings across and lands on the son's cheek. The son's head snaps sideways, his crown tilts, his hair flies, one hand comes up too late. No slow motion, no camera shake, no extra movement. Sharp slap sound, then total silence.
```

### 3-12　E1 片尾

> 不需要生成。第 4 步在剪辑页用「片尾」文字做。

---

## 第 4 步 · 剪辑页组装

1. 进「剪辑」标签页，把 **11 段视频**（A1 A2 A3 A4 B1 B2 C1 C2 C3 D1 D2）按顺序拖好
2. **逐镜填字幕**（右侧镜头设置里的「字幕」框）——留空会把镜头名烧进画面：

| 镜头 | 字幕文本 |
|---|---|
| A1 上香 | （留空，但要把「字幕」勾掉） |
| A2 拍肩 | （留空，同上） |
| A3 回头 | （留空，同上） |
| A4 | `爹。` |
| B1 | `听说你又北伐了？打到长安了吗？` |
| B2 | `围了多久？` |
| C1 | `他退到长江了。` |
| C2 | `听说你吓病了。给你带了点药。` |
| C3 | `滚滚滚，谁要你的药。` |
| D1 | `我当年两千七百人，破过他爹三万骑兵。` |
| D2 | （留空，勾掉字幕） |

> 一镜两句台词的（A4、B1、C3、D1），字幕只填**前一句**，后一句靠对白本身听；这是当前单行字幕的限制。

3. 旁白：**全部关掉**
4. 片头：`成片设置 → 片头`：文字 **《大逼兜》上集**，时长 **1.5 秒**
5. 片尾：`成片设置 → 片尾`：文字 **上集 · 完**，时长 **3 秒**
6. BGM：素材库选一首「紧张」类的，**音量调到 15%**；不要选「燃」类，会盖住对白

---

## 第 5 步 · 导出与质检

点「导出成片」→ 720×1280 / 烧字幕 / 带 BGM → 执行。

导出后依次检查：

| # | 检查 | 不合格怎么办 |
|---|---|---|
| 1 | 总时长 80~90 秒 | 明显偏短 → 有镜头没进时间线 |
| 2 | 前 10 秒没有 BGM | 检查 BGM 起点 |
| 3 | 画面底部没有「A1 上香」这类字 | 那镜的「字幕」没清空 |
| 4 | 每镜牌位上没有字 | 重出那一镜首帧，把牌位改成侧面或裁掉 |
| 5 | A1 与 A3 的冠一致 | 重出时用「刘义隆锚点」那张当首帧 |
| 6 | A2 的手没有多余手指 | 重出，或把 A2 换成「只有袖口 + 半只手」的构图 |
| 7 | 对白听得清、口型对得上 | 那句台词减半，重出该镜 |
| 8 | 连续镜之间没有跳变 | B1/B2 必须首尾同图 |

---

## 附：一键复制清单（按顺序用）

1. 1-A 刘义隆锚点
2. 1-B 刘裕锚点
3. 1-C 拓跋焘锚点
4. 2-1 A1 首帧
5. 2-2 A2 首帧
6. 2-3 A3 首帧
7. 2-5 B1/B2 双人静帧
8. 2-6 C1 首帧
9. 2-7 C2 首帧
10. 2-9 D1 首帧
11. 2-10 D2 首帧
12. 3-1 → 3-11 共 11 段视频提示词
13. 第 4 步字幕表

总计：**11 张图 + 11 段视频**。按实测节奏（图 40 秒 / 视频 6~8 分钟），全程约 **2 小时**。
