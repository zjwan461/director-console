# 《大逼兜》上集 · 傻瓜式操作手册 v3.1（去美型 / 全提示词 / 已实测）

> 12 镜 / 约 80 秒 / 竖屏 9:16。
> v3.1 改动：**已用真机验证**——刘义隆改成 45 岁疲惫文官脸（冕板写死），拓跋焘改成歪鼻疤脸糙兵，
> 并把「反美颜」负面词加进每一段。
> 所有提示词完整可直接复制，不需要替换任何内容。

---

## v3 改了什么（先看这段）

v2 的提示词会被模型理解成"古装偶像剧定妆照"，出俊男美女。历史幽默短剧要的是**能演的人脸**：

| 项 | v2（错） | v3（对） |
|---|---|---|
| 脸 | pale / handsome / 俊美 | **ordinary, uneven, tired** |
| 皮肤 | 细腻质感 | **rough skin, visible pores, slight blemishes, stubble** |
| 年龄感 | 四十出头像二十几 | **四十多就该有眼袋、法令纹、颈纹** |
| 光 | 电影感柔光 | **纪录片式硬光，脸上有阴影和油光** |
| 气质 | 英气 | **窝囊 / 阴沉 / 欠揍** |

**核心手法**：每段人物描述里塞进三个"反美颜"词 —— `ordinary-looking`、`unflattering`、`visible skin flaws`，再加一组负面词封死滤镜。

---

## 实测结论（三张锚点已跑过）

![锚点实测](/D:/temp/anchors_final.png)

| 角色 | 结果 | 备注 |
|---|---|---|
| 刘裕 | ✅ 一次就对 | 六十多岁、深皱纹、花白胡子、眼神阴沉，正是要的感觉 |
| 刘义隆 | ✅ 改后可用 | v3 是三十岁小白脸；v3.1 加了"45 岁/眼袋/灰胡茬/冕板平顶"后变疲惫文官 |
| 拓跋焘 | ⚠️ 仍偏好看 | 加了歪鼻、疤、小痘坑后好一些，但模型对"胡人武将"默认还是帅。**再多跑几张挑**，或者接受"帅而欠揍" |

**三条经验**（比提示词本身重要）：

1. 年龄必须写**数字**（`45 years old`），只写 `mid forties` 模型会往年轻画
2. 冕冠必须描述**结构**（"a flat black rectangular board resting on top of his head like a small table"），
   只写 `mian crown` 会给你乌纱帽
3. 拓跋焘这类"帅角色"要**给缺陷**：歪鼻、疤、痘坑、脏指甲，比写 `ugly` 有用

---

## 第 0 步 · 建项目

1. 打开 `http://127.0.0.1:6006/?tab=edit`
2. 左上角 →「新建项目」→ **《大逼兜》上集 v1**
3. 成片设置：画幅 **9:16**，分辨率 **720 × 1280**

---

## 第 1 步 · 三张角色锚点

「创作台」→ 卡选 **剧照 / 角色图（C16）** → 9:16 → **1.0 MP**。

### 1-A 刘义隆（儿子 · 窝囊相）

```text
写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：
a gaunt, clearly middle-aged Chinese man, 45 years old, thin worn face with hollow cheeks and sunken temples, sallow greyish uneven skin, visible pores and old acne marks, heavy dark eye bags, deep forehead lines and deep nasolabial folds, graying stubble, a tired downturned mouth, thinning hair with grey at the temples, wearing a proper mian crown: a flat black rectangular board resting on top of his head like a small table, slightly tilted forward, with only a few short strings of white beads hanging in front of his forehead, black ceremonial robe with an oversized high white collar, stooped shoulders, anxious and slightly pathetic, looking like a nervous middle-aged official who has not slept
documentary-style hard side light from a candle, shadows on the face, some oily shine on the skin, no beauty retouching, plain grey stone wall background, shallow depth of field
no text, no calligraphy, no plaques, no Chinese characters, no extra people, no bare head, no modern objects, handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup, k-pop, young man, youthful face, boyish look, clean-shaven model, porcelain skin
```

### 1-B 刘裕（父亲 · 阴沉老卒）

```text
写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：
a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, high cheekbones, deep wrinkles across the forehead and around the mouth, coarse weathered skin with age spots and stubble, messy grey-streaked beard, thinning hair tied back with a dark cloth, small hard eyes, wearing a plain dark grey-black long robe that is worn but completely intact, brown leather belt, no sword, hands clasped behind his back, straight back, chin slightly raised, cold tired intimidating expression like an old soldier who has killed people
harsh candlelight from the side, deep shadows in the eye sockets, no beauty retouching, plain grey stone wall background, shallow depth of field
no text, no calligraphy, no plaques, no Chinese characters, no extra people, no bare head, no modern objects, handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup, k-pop, young man, youthful face, boyish look, porcelain skin
```

### 1-C 拓跋焘（北魏太武帝 · 欠揍）

```text
写实历史短剧定妆照，不是偶像剧，非美型，竖屏构图，太庙内殿石墙前，正面半身：
a lean, rough, unattractive-but-charismatic Chinese soldier, 38 years old, narrow weathered face with a slightly crooked broken nose, sunburnt peeling cheeks, old smallpox scars on the jaw, deep crow feet, chapped lips, uneven patchy black beard with grey strands, a scar through one eyebrow, narrow smug eyes, dirty sweat streaks at the temples, dirty fingernails, wearing dusty dark lamellar armour with a matted grey fur collar, round dented helmet, holding a small shabby bundle of dried herbs in his right hand, relaxed arrogant posture
documentary-style hard light from above, sweat shine on the forehead, no beauty retouching, plain grey stone wall background, shallow depth of field
no text, no calligraphy, no plaques, no Chinese characters, no extra people, no modern objects, handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup, k-pop, young man, youthful face, boyish look, porcelain skin
```

> 三张出完逐一看：**是不是"普通人"而不是"演员偶像"、冠对不对、有没有多余人、有没有自造汉字**。
> 不满意就原样再执行（同提示词多跑几次）。满意的三张自动进素材库，后面按名字引用。

---

## 第 2 步 · 11 张首帧

全部 **C16** / 9:16 / **0.8 MP**。

### 2-1　A1 上香（背影 · 略寒酸）

```text
写实历史短剧，非美型，竖屏，太庙内殿但很朴素：灰色石墙、深色木柱、壁龛里竖着几块素面空白木牌位（木牌上完全空白、没有任何刻字）、两支细长铜烛台点着小火苗、石台上一个旧铜香炉冒着细香烟，冷环境光，纪录片质感，浅景深
中景背影：a gaunt middle-aged Chinese man of 45, sallow greyish skin, heavy eye bags, graying stubble, black ceremonial crown with a flat rectangular board on top and short bead strings, black ceremonial robe with an oversized high white collar that hangs loose, standing with his back to the camera, both hands holding three incense sticks up in front of his chest, slightly stiff hunched posture, shoulders raised with tension
no text, no calligraphy, no plaques, no Chinese characters anywhere, no extra people, no modern objects, handsome idol face, beauty filter, smooth skin, glamour lighting
```

### 2-2　A2 拍肩（手特写 · 粗糙的手）

```text
写实历史短剧，非美型，竖屏，太庙内殿，冷环境光，纪录片质感，浅景深
大特写：画面里只出现一个人的右肩和袖口，a plain dark grey-black robe sleeve, worn but completely intact with no tears, the fabric coarse and slightly dirty, brown leather belt edge visible at the bottom
一只粗糙的老年男性手掌从画面右侧伸进来：干裂的皮肤、突出的指关节、指甲缝里有灰、手背青筋和老年斑明显，轻轻悬在肩上，手指自然微曲
no text, no calligraphy, no extra people, no face, smooth flawless skin, beauty filter, young hands, manicured nails
```

### 2-3　A3 回头（惊愕但不美型）

```text
写实历史短剧，非美型，竖屏，太庙内殿：灰石墙、深色木柱、素面空白木牌位、铜烛台烛火、旧铜香炉香烟，冷环境光，纪录片质感，浅景深
近景：a gaunt middle-aged Chinese man of 45, sallow greyish uneven skin, visible pores and old acne marks, heavy dark eye bags, deep nasolabial folds, graying stubble, black ceremonial crown with a flat rectangular board on top and short strings of white beads, black ceremonial robe with a high white collar, body turned sharply to look over his right shoulder, eyes wide with panic, mouth slightly open showing teeth, looking toward the left edge of the frame, NOT looking at the camera, the bead strings still swinging, sweat shine on the forehead
no text, no calligraphy, no plaques, no Chinese characters, no extra people, handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup
```

### 2-4　A4 → 用 r2v9，不需要首帧

### 2-5　B1/B2 双人静帧（共用一张）

```text
写实历史短剧，非美型，竖屏，太庙内殿：灰石墙、深色木柱、素面空白木牌位、两支铜烛台、旧铜香炉香烟，冷环境光，纪录片质感，浅景深
双人中景，两人面对面站在香炉前，相距约一步，画面不要对称，构图略微歪一点：
画面左侧 a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, deep wrinkles, messy grey-streaked beard, plain dark grey-black robe worn but intact, brown leather belt, no sword, hands clasped behind his back, straight back, cold expression
画面右侧 a gaunt middle-aged Chinese man of 45, hollow cheeks, sallow greyish skin, heavy eye bags, deep nasolabial folds, graying stubble, black ceremonial crown with flat board and short bead strings, black ceremonial robe with an oversized high white collar, head slightly lowered, shoulders tense, anxious expression
两人都看向对方，没有人看镜头
no text, no calligraphy, no plaques, no Chinese characters, no extra people, no modern objects, handsome idol face, beauty filter, smooth skin, glamour lighting
```

### 2-6　C1 双人转头（画外音）

```text
写实历史短剧，非美型，竖屏，太庙内殿，冷环境光，纪录片质感，浅景深
双人中景，两人并排面对镜头略侧站，中间留一道缝：
画面左侧 a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, deep wrinkles, messy grey-streaked beard, dark grey-black robe, hands behind his back
画面右侧 a gaunt middle-aged Chinese man of 45, hollow cheeks, sallow greyish skin, heavy eye bags, graying stubble, black ceremonial crown with short bead strings, black robe with oversized high white collar
两人同时把头转向画面右外侧（画外有人说话），一个是警觉、一个是惊疑，没有人看镜头
no text, no calligraphy, no Chinese characters, no extra people, handsome idol face, beauty filter, smooth skin
```

### 2-7　C2 拓跋焘出场（从阴影里出来）

```text
写实历史短剧，非美型，竖屏，太庙内殿侧廊：深色木柱之间有一道阴影，背景是灰石墙和虚化烛火，冷环境光，纪录片质感，浅景深
中景：a lean, rough Chinese soldier of 38 with a slightly crooked broken nose, sunburnt peeling cheeks, old smallpox scars on the jaw, uneven patchy black beard with grey strands, narrow smug eyes, wearing dusty dark lamellar armour with a matted grey fur collar, round dented helmet, holding a small shabby bundle of dried herbs in his right hand, walking out of the shadow toward the camera with a smug unpleasant half-smile
只有半边脸被烛光照亮，另一边在暗部
no text, no calligraphy, no plaques, no Chinese characters, no extra people, handsome idol face, beauty filter, smooth skin, glamour lighting
```

### 2-8　C3 → 用 r2v9，不需要首帧

### 2-9　D1 刘裕逼近（胸口以上）

```text
写实历史短剧，非美型，竖屏，太庙内殿，冷环境光，纪录片质感，浅景深
近景，胸口以上：a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, high cheekbones, deep forehead and mouth wrinkles, coarse skin with age spots, messy grey-streaked beard, hair tied with a dark cloth, plain dark grey-black robe, brown leather belt, leaning slightly forward toward the camera, jaw tight, small hard eyes, angry but controlled, a vein visible on the temple
背景是虚化的石墙与烛火，光从右下往上打，眼窝有阴影
no text, no calligraphy, no Chinese characters, no extra people, handsome idol face, beauty filter, smooth skin, glamour lighting
```

### 2-10　D2 一巴掌（双人中景）

```text
写实历史短剧，非美型，竖屏，太庙内殿，冷环境光，纪录片质感，浅景深
双人中景，动作正在进行中：
画面左侧 a weathered ordinary-looking Chinese man in his mid sixties, dark grey-black robe, right arm raised with palm open mid-swing, body weight forward
画面右侧 an ordinary-looking Chinese man in his mid forties, black ceremonial crown, black robe with oversized white collar, head just starting to snap sideways, one hand half-raised too late in defence, mouth open in shock
两人距离很近，衣料被带起来，没有慢动作感
no text, no calligraphy, no Chinese characters, no extra people, handsome idol face, beauty filter, smooth skin, slow motion
```

---

## 第 3 步 · 11 段视频

按顺序：选卡 → 选参考/首帧 → 画幅 9:16 → 清晰度 → 时长 → 粘贴提示词。

### 3-1　A1 上香 ｜ `h3.i2v` ｜ 0.4 MP ｜ 6 秒

- 首帧：**2-1 生成的 A1 首帧**

```text
Camera pushes in very slowly. Incense smoke drifts upward in the candlelight, flames flicker gently. The man keeps holding the incense steady, only his sleeve and back show a very slight breathing motion. He does not turn around and does not move his head. Ambient temple room tone, faint wind outside.
```

### 3-2　A2 拍肩 ｜ `h3.i2v` ｜ 0.4 MP ｜ 4 秒

- 首帧：**2-2 生成的 A2 首帧**

```text
The rough elderly hand enters slowly from the right edge of frame and settles lightly on the shoulder, the cracked fingertips pressing down a little, the coarse sleeve fabric shifting with the movement. The camera barely moves, only a faint handheld breathing feel. Soft cloth rustle, distant wind.
```

### 3-3　A3 回头 ｜ `h3.i2v` ｜ 0.4 MP ｜ 4 秒

- 首帧：**2-3 生成的 A3 首帧**

```text
The man turns his head quickly toward the left edge of the frame, the bead strings of his crown swinging with the motion, his eyes widening and pupils trembling, breathing fast, sweat shine shifting on his forehead. The camera stays still with a slight handheld feel. Sharp intake of breath, cloth movement.
```

### 3-4　A4 「爹。」 ｜ `h3.r2v9` ｜ 0.7 MP ｜ 8 秒

- 参考图 1：**刘义隆锚点** ｜ 参考图 2：**刘裕锚点** ｜ 其余留空
- 音频槽：全部留空

```text
subject_definitions:
<Subject 1> is the son: an ordinary-looking Chinese man in his mid forties, thin hollow-cheeked face, sallow uneven skin with visible pores, dark circles, deep nasolabial folds, thin sparse beard, black ceremonial crown with a flat rectangular board and short strings of white beads, black ceremonial robe with an oversized high white collar, anxious and slightly pathetic. <Picture 1> is his appearance reference.
<Subject 2> is the father: a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, deep wrinkles, coarse skin with age spots, messy grey-streaked beard, plain dark grey-black robe worn but intact, brown leather belt, no sword, hands clasped behind his back, cold and intimidating. <Picture 2> is his appearance reference.
<Subject 3> is the ancestral temple hall: grey stone walls, dark wooden columns, plain blank wooden tablets with no writing, bronze candlesticks with small flames, a bronze incense burner with drifting smoke, cold hard light.

summary:
A two-shot dialogue scene inside a plain temple hall. The father appears behind the son and flicks ash off his shoulder; the son greets him nervously, the father answers calmly. Reference images are used only for the two characters' faces and costumes.

retention_analysis:
The son keeps his gaunt 45-year-old face, hollow cheeks, eye bags, graying stubble, mian crown and black robe from <Picture 1>. The father keeps his broad rough face, deep wrinkles, grey-streaked beard, dark robe and hands-behind-back posture from <Picture 2>. The temple environment keeps stone walls, columns, incense burner and candlelight from <Subject 3>. Framing, blocking and timing are newly generated.

detailed_description:
Static medium two-shot, vertical framing, slightly off-centre composition. <Subject 2> stands at frame-left in the middle distance, <Subject 1> stands at frame-right closer to camera, both facing each other in front of the bronze incense burner. Cold hard candlelight from the sides, thin smoke drifting between them, both faces partly in shadow.
<Subject 2> lifts his right hand and flicks a bit of incense ash off <Subject 1>'s shoulder with the back of his rough fingers, then puts the hand back behind his back.
<Subject 1> (S1) swallows and says, <d>[Chinese] 爹。</d>
<Subject 2> (S2) answers calmly, <d>[Chinese] 嗯。</d>
<Subject 1> does NOT speak again; his mouth stays closed, only his eyes move. <Subject 2> does not smile. Camera holds steady with a very slow push in. No other people enter the frame.

overall_soundscape:
Quiet stone-room ambience, faint candle flicker, thin cloth rustle when the hand moves, distant wind outside the hall.

non_diegetic_music:
None. Silence under the dialogue.
```

### 3-5　B1 「打到长安了吗」｜ `h3.flf2v` ｜ 0.4 MP ｜ 10 秒

- 首帧和尾帧：**都选 2-5 那张双人静帧**

```text
Static two-shot, both men stay in place facing each other, only slight breathing and small head movements. The father holds his hands behind his back and does not move his feet; the son lowers his head slightly, then lifts it again while answering. No camera movement. No other people enter the frame.
(S2) the father asks, <d>[Chinese] 听说你又北伐了？打到长安了吗？</d>
(S1) the son answers hesitantly, <d>[Chinese] 没呢，爹。遇到一点小情况。</d>
The father does not reply.
```

### 3-6　B2 「二百多天」｜ `h3.flf2v` ｜ 0.4 MP ｜ 8 秒

- 首帧/尾帧：**同一张 2-5 静帧**

```text
Static two-shot, same framing, no camera movement. The son looks down at the floor, then lifts his eyes back to the father.
(S2) the father asks flatly, <d>[Chinese] 围了多久？</d>
(S1) the son answers quietly, <d>[Chinese] 二百多天。</d>
The father does not move at all, his expression stays flat.
```

### 3-7　C1 「他退到长江了」｜ `h3.i2v` ｜ 0.4 MP ｜ 6 秒

- 首帧：**2-6 生成的 C1 首帧**

```text
Both men stand still, then turn their heads toward the off-screen right at the same time, as if hearing someone behind them.
(S3) a relaxed amused male voice comes from OFF-SCREEN, <d>[Chinese] 他退到长江了。</d>
Neither of the two men speaks; their mouths stay closed. Camera holds steady.
```

### 3-8　C2 拓跋焘出场 ｜ `h3.i2v` ｜ 0.4 MP ｜ 7 秒

- 首帧：**2-7 生成的 C2 首帧**

```text
The armoured man walks out of the shadow toward the camera at an easy pace, the dusty fur collar and armour plates shifting with each step, the shabby bundle of herbs swinging slightly in his hand.
(S3) he says casually, <d>[Chinese] 听说你吓病了。给你带了点药。</d>
Camera tracks sideways a little as he walks in.
```

### 3-9　C3 三人同框 ｜ `h3.r2v9` ｜ 0.7 MP ｜ 9 秒

- 参考图 1：**刘义隆锚点** ｜ 参考图 2：**刘裕锚点** ｜ 参考图 3：**拓跋焘锚点**

```text
subject_definitions:
<Subject 1> is the son: a gaunt middle-aged Chinese man of 45, hollow cheeks, sallow greyish uneven skin, heavy dark eye bags, graying stubble, black ceremonial crown with a flat board and short bead strings, black robe with an oversized high white collar. <Picture 1> is his appearance reference.
<Subject 2> is the father: a weathered ordinary-looking Chinese man in his mid sixties, broad rough face, deep wrinkles, messy grey-streaked beard, dark grey-black robe, hands behind his back. <Picture 2> is his appearance reference.
<Subject 3> is the northern emperor: a lean rough Chinese soldier of 38, crooked broken nose, sunburnt peeling skin, old smallpox scars, uneven patchy black beard with grey strands, dusty dark lamellar armour with matted grey fur collar, round dented helmet, holding a small shabby bundle of dried herbs. <Picture 3> is his appearance reference.
<Subject 4> is the ancestral temple hall: grey stone walls, dark wooden columns, blank wooden tablets, bronze candlesticks, incense smoke, cold hard light.

summary:
A three-shot scene in the temple hall. The son is sandwiched between the two older men; the two elders talk past him. Only the son speaks, twice. Reference images lock the three characters' faces and costumes.

retention_analysis:
Faces, beards, crown, helmet, armour and robes of the three characters are preserved from <Picture 1>, <Picture 2> and <Picture 3>. The temple is preserved from <Subject 4>. Blocking, timing and camera are newly designed.

detailed_description:
Static three-shot, vertical framing, slightly off-centre. <Subject 2> stands at frame-left, <Subject 3> at frame-right, both facing slightly inward; <Subject 1> stands in the middle but one step further back so the two elders can look past him. Cold hard candlelight from both sides, incense smoke drifting, all faces partly in shadow.
<Subject 1> (S1) snaps at <Subject 3>, <d>[Chinese] 滚滚滚，谁要你的药。</d>
Then <Subject 1> pauses, frowns, and adds while turning his head slightly, <d>[Chinese] 等会，你怎么会在这啊。</d>
<Subject 2> and <Subject 3> do not speak; their mouths stay closed. <Subject 2> keeps his hands behind his back, <Subject 3> keeps the herbs in his hand. Camera holds steady with a very slight push in.

overall_soundscape:
Stone hall ambience, faint candle flicker, armour plates clinking softly when <Subject 3> shifts his weight.

non_diegetic_music:
None.
```

### 3-10　D1 「我当年两千七百人」｜ `h3.i2v` ｜ 0.4 MP ｜ 10 秒

- 首帧：**2-9 生成的 D1 首帧**

```text
The father leans a step closer to the camera, jaw tight, small hard eyes, breathing slow and heavy, the coarse collar shifting slightly.
(S2) he says low and hard, <d>[Chinese] 我当年两千七百人，破过他爹三万骑兵。</d>
He pauses, then adds with contempt, <d>[Chinese] 你个废物点心。</d>
No other person is in frame. Camera holds steady with the slightest push in.
```

### 3-11　D2 一巴掌 ｜ `h3.i2v` ｜ 0.4 MP ｜ 3 秒

- 首帧：**2-10 生成的 D2 首帧**

```text
One single clean slap: the father's open rough palm swings across and lands on the son's cheek. The son's head snaps sideways, his crown tilts, hair flies, one hand comes up too late. No slow motion, no camera shake, no extra movement. Sharp slap sound, then total silence.
```

---

## 第 4 步 · 剪辑页组装

1. 「剪辑」标签页 → 11 段按顺序排：A1 A2 A3 A4 B1 B2 C1 C2 C3 D1 D2
2. 逐镜填字幕（右侧镜头设置「字幕」）：

| 镜头 | 字幕 |
|---|---|
| A1 / A2 / A3 / D2 | **留空并关掉字幕**（否则会烧镜头名） |
| A4 | `爹。` |
| B1 | `听说你又北伐了？打到长安了吗？` |
| B2 | `围了多久？` |
| C1 | `他退到长江了。` |
| C2 | `听说你吓病了。给你带了点药。` |
| C3 | `滚滚滚，谁要你的药。` |
| D1 | `我当年两千七百人，破过他爹三万骑兵。` |

3. 旁白：**全部关掉**
4. 片头：文字 **《大逼兜》上集**，1.5 秒
5. 片尾：文字 **上集 · 完**，3 秒
6. BGM：选一首「紧张」类，**音量 15%**

---

## 第 5 步 · 导出与质检

导出：720×1280 / 烧字幕 / 带 BGM。

| # | 检查 | 不合格怎么办 |
|---|---|---|
| 1 | 人是不是"普通人"而不是偶像脸 | 回第 1 步重出锚点，负面词那段**一个字别删** |
| 2 | A1 与 A3 的冠一致 | 用刘义隆锚点当首帧重出 A1 |
| 3 | 牌位有没有字 | 重出首帧，把牌位改成侧面或裁掉 |
| 4 | A2 手指数量 | 重出，或把构图改成"只露半只手" |
| 5 | 总时长 80~90 秒 | 有镜头没进时间线 |
| 6 | 底部没有"A1 上香" | 那镜字幕没关 |
| 7 | 前 10 秒没有 BGM | 调 BGM 起点 |
| 8 | 对白清楚、口型对得上 | 那一镜台词减半重出 |

---

## 附：为什么"美型"这么难去掉

模型训练数据里"古装 + 定妆照"几乎全是偶像剧，所以只要出现"古装人物特写"，默认就往美型走。压制它需要**三件事同时做**：

1. 文字里明确 `ordinary-looking` / `uneven skin` / `tired`
2. 负面词点名 `handsome idol face, beauty filter, smooth flawless skin, glamour lighting, makeup`
3. 光要"难看"——纪录片硬光、脸上有阴影和油光，而不是柔光轮廓光

三条缺一条，就会回到偶像剧。这也是为什么 v3 把负面词写进了**每一段**。
