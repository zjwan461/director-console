"""《大逼兜》上集 · 参考生视频提示词（以用户静帧素材为参考图）。

原则：
- 角色一律「以参考图为准」，文字不再描述年龄/皮肤，避免和参考图打架
- 场景按素材里的暖烛光石殿写
- 拓跋焘按「笑面赢家」写，不用严肃版
- 参考图顺序：<Picture 1> = 刘裕, <Picture 2> = 刘义隆, <Picture 3> = 拓跋焘（各镜按需裁剪）
"""

# 场景：与素材保持一致（暖烛光、石墙、空白木牌）
HALL = ("<Subject 3> is the ancestral temple hall: grey stone walls, dark wooden beams and columns, tall "
        "bronze candlesticks with warm candle flames, a bronze incense burner with drifting smoke, a few "
        "plain blank wooden tablets with no writing on them, warm golden candlelight, shallow depth of "
        "field, documentary look.")

FATHER_DEF = ("<Subject 1> is the father: the man in <Picture 1>, keep his face, grey beard, hair bun with "
              "a dark cloth band, plain dark grey-black robe with a brown belt and his hands-clasped-"
              "behind-the-back posture EXACTLY as in the reference image.")
SON_DEF = ("<Subject 2> is the son: the man in <Picture 2>, keep his face, short beard, black mian crown "
           "with a flat board and hanging bead strings, black ceremonial robe with a high white collar "
           "EXACTLY as in the reference image.")
EMPEROR_DEF = ("<Subject 4> is the northern emperor: the man in <Picture 3>, keep his face, black beard, "
               "dark lamellar armour with a grey fur collar, round leather-and-metal helmet and his bundle "
               "of dried herbs EXACTLY as in the reference image.")

A3_PROMPT = (
    "subject_definitions:\n" + SON_DEF + f" <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nA single close-up: the son turns his head sharply, startled by a hand on his shoulder.\n\n"
    "retention_analysis:\nThe son's face, crown, bead strings and robe are preserved from <Picture 2>. The "
    "hall keeps its stone walls, candles and warm light from <Subject 3>. Camera, timing and expression are "
    "newly generated.\n\n"
    "detailed_description:\nStatic close shot, vertical framing, the son fills the frame from the chest up, "
    "standing in front of the incense burner, warm candlelight from the left, smoke drifting past him. He "
    "whips his head around to look over his right shoulder toward camera-left, the bead strings swinging "
    "sideways, eyes wide with panic, mouth slightly open, breathing fast. He does NOT look at the camera and "
    "does not speak; his mouth stays closed after the initial gasp. Camera holds steady with a very slight "
    "handheld tremble.\n\n"
    "overall_soundscape:\nSharp cloth rustle, a quick intake of breath, quiet stone-room ambience.\n\n"
    "non_diegetic_music:\nNone."
)

A4_PROMPT = (
    "subject_definitions:\n" + FATHER_DEF + " <Picture 1> is his appearance reference.\n" + SON_DEF +
    " <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nA two-shot dialogue inside the temple hall. The father flicks incense ash off the son's "
    "shoulder; the son greets him nervously, the father answers calmly.\n\n"
    "retention_analysis:\nBoth men keep their faces, hair, crowns and robes exactly as in <Picture 1> and "
    "<Picture 2>. The hall keeps its stone walls, candles and warm light from <Subject 3>.\n\n"
    "detailed_description:\nStatic medium two-shot, vertical framing. <Subject 1> stands at frame-left, "
    "<Subject 2> at frame-right, both facing each other in front of the bronze incense burner, warm "
    "candlelight from the sides, smoke drifting between them.\n"
    "<Subject 1> lifts his right hand and flicks a bit of incense ash off <Subject 2>'s shoulder with the "
    "back of his fingers, then puts the hand back behind his back.\n"
    "<Subject 2> (S1) swallows and says, <d>[Chinese] 爹。</d>\n"
    "<Subject 1> (S2) answers calmly, <d>[Chinese] 嗯。</d>\n"
    "<Subject 2> does NOT speak again; his mouth stays closed. <Subject 1> does not smile. Camera holds "
    "steady with a very slow push in. No other people in frame.\n\n"
    "overall_soundscape:\nQuiet stone-room ambience, faint candle flicker, thin cloth rustle.\n\n"
    "non_diegetic_music:\nNone. Silence under the dialogue."
)

B1_PROMPT = (
    "subject_definitions:\n" + FATHER_DEF + " <Picture 1> is his appearance reference.\n" + SON_DEF +
    " <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nA static two-shot dialogue: the father asks about the northern campaign, the son makes an "
    "excuse.\n\n"
    "retention_analysis:\nFaces, beards, crown and robes preserved from <Picture 1> and <Picture 2>; hall "
    "preserved from <Subject 3>.\n\n"
    "detailed_description:\nStatic medium two-shot, vertical framing, the two men facing each other at a "
    "small distance, warm candlelight from the side, smoke drifting. <Subject 1> keeps his hands behind his "
    "back and does not move his feet; <Subject 2> lowers his head slightly, then lifts it while answering. "
    "No camera movement, no other people.\n"
    "(S2) the father asks, <d>[Chinese] 听说你又北伐了？打到长安了吗？</d>\n"
    "(S1) the son answers hesitantly, <d>[Chinese] 没呢，爹。遇到一点小情况。</d>\n"
    "The father does not reply; his mouth stays closed.\n\n"
    "overall_soundscape:\nQuiet stone-room ambience, faint candle flicker.\n\n"
    "non_diegetic_music:\nNone."
)

B2_PROMPT = (
    "subject_definitions:\n" + FATHER_DEF + " <Picture 1> is his appearance reference.\n" + SON_DEF +
    " <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nSame two-shot, same framing: the father asks how long the siege lasted, the son answers.\n\n"
    "retention_analysis:\nFaces and costumes preserved from <Picture 1> and <Picture 2>; hall preserved from "
    "<Subject 3>.\n\n"
    "detailed_description:\nStatic medium two-shot, identical framing to the previous beat, same positions, "
    "same warm candlelight, no camera movement. <Subject 2> looks down at the floor, then lifts his eyes "
    "back to <Subject 1>.\n"
    "(S2) the father asks flatly, <d>[Chinese] 围了多久？</d>\n"
    "(S1) the son answers quietly, <d>[Chinese] 二百多天。</d>\n"
    "<Subject 1> does not move at all; his expression stays flat and his mouth stays closed afterwards.\n\n"
    "overall_soundscape:\nQuiet stone-room ambience, a faint swallow.\n\n"
    "non_diegetic_music:\nNone."
)

C3_PROMPT = (
    "subject_definitions:\n" + FATHER_DEF + " <Picture 1> is his appearance reference.\n" + SON_DEF +
    " <Picture 2> is his appearance reference.\n" + EMPEROR_DEF + " <Picture 3> is his appearance "
    "reference.\n" + HALL + "\n\n"
    "summary:\nA three-shot: the son is sandwiched between the two older men; the two elders talk past him. "
    "Only the son speaks, twice. The northern emperor is smiling and pleased with himself.\n\n"
    "retention_analysis:\nFaces, beards, crown, helmet, armour and robes preserved from <Picture 1>, "
    "<Picture 2> and <Picture 3>.\n\n"
    "detailed_description:\nStatic three-shot, vertical framing. <Subject 1> stands at frame-left, "
    "<Subject 4> at frame-right with his herbs in hand and a smug smile, both facing slightly inward; "
    "<Subject 2> stands in the middle one step further back so the two elders can look past him. Warm "
    "candlelight, smoke drifting.\n"
    "<Subject 2> (S1) snaps at <Subject 4>, <d>[Chinese] 滚滚滚，谁要你的药。</d>\n"
    "Then <Subject 2> pauses, frowns, and adds while turning his head slightly, "
    "<d>[Chinese] 等会，你怎么会在这啊。</d>\n"
    "<Subject 1> and <Subject 4> do not speak; their mouths stay closed. <Subject 4> keeps smiling. Camera "
    "holds steady.\n\n"
    "overall_soundscape:\nStone hall ambience, faint candle flicker, armour plates clinking softly.\n\n"
    "non_diegetic_music:\nNone."
)

D2_PROMPT = (
    "subject_definitions:\n" + FATHER_DEF + " <Picture 1> is his appearance reference.\n" + SON_DEF +
    " <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nA single hard slap in a two-shot: the father's palm lands on the son's cheek, the head snaps "
    "sideways, the crown tilts. Martial-arts physicality, no slow motion.\n\n"
    "retention_analysis:\nBoth faces, the father's grey beard, the son's crown, bead strings and black robe "
    "preserved from <Picture 1> and <Picture 2>.\n\n"
    "detailed_description:\nMedium two-shot, vertical framing, the two men very close, warm candlelight from "
    "the left, smoke drifting. Contact physics matters: the father's right arm swings in a short tight arc "
    "and his open palm hits the son's left cheek; on contact the cheek deforms slightly, the son's head "
    "whips to his right, his crown tilts, the bead strings fly sideways, his left hand comes up half a beat "
    "too late, his weight shifts onto the back foot. The father's shoulder follows through, weight on the "
    "front foot, robe and belt swinging. One single clean strike, fast and heavy, no slow motion, no motion "
    "blur, no camera shake, no second strike. The son does not speak; his mouth is open in shock. The father "
    "does not speak.\n\n"
    "overall_soundscape:\nSharp hard slap at the contact frame, cloth snap, then brief silence.\n\n"
    "non_diegetic_music:\nNone."
)

D3_PROMPT = (
    "subject_definitions:\n" + SON_DEF + " <Picture 1> is his appearance reference.\n" + FATHER_DEF +
    " <Picture 2> is his appearance reference.\n" + HALL + "\n\n"
    "summary:\nThe son turns and runs out of frame with a hand over his cheek; the father stays where he "
    "is.\n\n"
    "retention_analysis:\nThe son keeps his face, crown and black robe from <Picture 1>; the father keeps "
    "his face, grey beard and dark robe from <Picture 2>.\n\n"
    "detailed_description:\nMedium two-shot, vertical framing, the father standing at frame-left, the son at "
    "frame-right already turning. The son claps his right hand over his reddened left cheek, spins, and runs "
    "out of the right side of the frame in a clumsy panicked stagger, robe and crown swinging, bead strings "
    "flying. The father does not chase him; he stays planted, hands behind his back, watching him go, then "
    "exhales and lowers his chin. Slight handheld shake tracking the son's exit, then settle back on the "
    "father. Neither man speaks.\n\n"
    "overall_soundscape:\nRunning footsteps on stone, cloth flapping, then the father's long tired exhale.\n\n"
    "non_diegetic_music:\nNone."
)

# ---------------- 轻量卡（h3.r2v）叙述式 ----------------
A3_PROMPT_PLAIN = (
    "Single character close shot, vertical 9:16, inside a warm candle-lit stone ancestral hall. Keep the "
    "face, the black mian crown with its bead strings and the black robe EXACTLY as in the reference image. "
    "The man whips his head around to look over his right shoulder toward camera-left, the bead strings "
    "swinging, eyes wide with panic, mouth slightly open, breathing fast. He does not look at the camera and "
    "does not speak. Camera holds steady with a very slight handheld tremble. Warm golden candlelight, "
    "shallow depth of field."
)

C1_PROMPT_PLAIN = (
    "Two-shot, vertical 9:16, inside a warm candle-lit stone ancestral hall with blank wooden tablets and "
    "drifting incense smoke. <Picture 1> is the father: grey-bearded man in a plain dark robe with his hands "
    "clasped behind his back. <Picture 2> is the son: young man in a black mian crown and black robe with a "
    "high white collar. Keep both faces and costumes EXACTLY as in the reference images. They stand facing "
    "each other, both still, then both turn their heads toward the off-screen right at the same time, one "
    "alert and one alarmed. Neither looks at the camera, neither speaks. "
    "(S3) a relaxed amused male voice comes from OFF-SCREEN, <d>[Chinese] 他退到长江了。</d> "
    "Warm candlelight, documentary look."
)

C2_PROMPT_PLAIN = (
    "Medium shot, vertical 9:16, inside the same warm candle-lit stone hall. Keep the face, the armour, the "
    "fur collar and the helmet EXACTLY as in the reference image. The man walks toward the camera at an easy "
    "unhurried pace, armour plates and fur collar shifting with each step, a small bundle of dried herbs "
    "held up in his right hand, a smug pleased smile on his face. Camera tracks slightly as he walks in. "
    "(S1) he says casually, <d>[Chinese] 听说你吓病了。给你带了点药。</d> No other people in frame."
)

D1_PROMPT_PLAIN = (
    "Close shot, chest and up, vertical 9:16, warm candle-lit stone hall behind him. Keep the face, the grey "
    "beard, the dark robe and the hands-behind-back posture EXACTLY as in the reference image. He turns his "
    "head toward the camera-left and speaks, jaw tight, tired hard eyes, breathing slow and heavy. "
    "(S1) he says low and hard, <d>[Chinese] 我当年两千七百人，破过他爹三万骑兵。</d> "
    "He pauses, then adds with contempt, <d>[Chinese] 你个废物点心。</d> "
    "No other person in frame, camera holds steady with the slightest push in."
)
