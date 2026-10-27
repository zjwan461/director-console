# 内置 BGM 素材说明

以下 17 首音乐已下载到 `data/uploads/music/`，并注册进资产库（`kind=audio`）。

## 版权与署名

- **作者**：Kevin MacLeod
- **来源**：https://incompetech.com/ ，镜像：https://archive.org/details/KevinMacLeod_2019-04_Discography
- **许可**：Creative Commons Attribution 4.0 (CC BY 4.0)
- **要求**：公开使用时需署名。建议在视频简介里写：

```
Music: "曲名" by Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 4.0
https://creativecommons.org/licenses/by/4.0/
```

## 曲目清单

| 情绪 | 曲名 | 时长 |
|---|---|---|
| 轻快 | Monkeys Spinning Monkeys | 2:05 |
| 轻快 | Happy Alley | 1:20 |
| 轻快 | Life of Riley | 3:55 |
| 搞笑 | Sneaky Snitch | 2:17 |
| 搞笑 | Fluffing a Duck | 1:07 |
| 燃 | Volatile Reaction | 2:45 |
| 燃 | Five Armies | 2:36 |
| 燃 | Killers | 5:05 |
| 燃 | Who Likes to Party | 4:17 |
| 史诗 | Achilles | 1:01 |
| 治愈 | Continue Life | 1:54 |
| 治愈 | Gymnopedie No 1 | 3:07 |
| 治愈 | Carefree | 3:25 |
| 电子 | Digital Lemonade | 3:00 |
| 电子 | Pamgaea | 2:49 |
| 电子 | Electro Cabello | 3:11 |
| 悬念 | Ominous | 0:34 |

## 为什么不是抖音/B站热门曲

那些曲目通常是唱片公司或平台的版权音乐，直接下载分发属于侵权，不能内置。

这 17 首是可商用的 CC BY 素材，覆盖短视频常用情绪（轻快/搞笑/燃/治愈/电子/悬念），
实际剪辑效果与热曲接近；要追热曲请自行购买授权后从「资产 → 上传」导入。

## 已授权曲目的导入方式

购买过（iTunes / Amazon MP3 / 其他提供无 DRM 文件的商店）后，把文件放到
`data/uploads/music/`，命名沿用 `情绪_曲名.mp3`，再登记 asset：

```python
# meta 里必须带 license / artist / source，面板才认作音乐素材
{"mood": "燃", "title": "曲名", "license": "已购买（注明商店与订单号）",
 "artist": "Block B", "duration": 0.0, "purpose": "music"}
```

流媒体平台（Melon / Spotify / YouTube Music / QQ 音乐）没有导出权，
从它们那里下载或录音轨仍然属于侵权复制，不要走这条路。
