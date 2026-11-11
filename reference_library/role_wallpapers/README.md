# 角色壁纸参考图资料库

这个目录用于放你提供的参考图，让 `Eproducts` 后端可以直接扫描并在出图时作为参考图传给生图服务。

## 推荐目录结构

```text
reference_library/role_wallpapers/
  roles/
    xavier/              # 沈星回
      01.png             # ✅ 最省事：完整角色参考图可以直接丢这里
      02.jpg
      complete/          # ✅ 也可以把完整参考图统一丢这里
      identity/          # 可选增强：脸、发型、五官、体态识别参考
      outfit/            # 可选增强：服装、材质、配色参考
      expression/        # 可选增强：表情、眼神、情绪参考
      pose/              # 可选增强：姿态、构图、身体比例参考
      mood/              # 可选增强：光影、氛围、场景参考
    rafayel/             # 祁煜
    zayne/               # 黎深
    sylus/               # 秦彻
    caleb/               # 夏以昼
  scenes/
    bedroom_morning/     # 场景参考，可选
    rain_window/
    ...
  outputs/               # 生成后的精选图，可手动归档
```

## 你应该怎么给我参考图

你不需要把图片拆成脸、服装、表情、姿态这些小类。第一版最推荐：

```text
roles/xavier/01.png
roles/xavier/02.png
roles/xavier/03.png
roles/rafayel/01.png
roles/zayne/01.png
roles/sylus/01.png
roles/caleb/01.png
```

或者：

```text
roles/xavier/complete/01.png
roles/xavier/complete/02.png
```

系统会把这些图识别为 `complete` 综合参考图，生图时同时用于脸、发型、体态、服装、气质等整体参考。

如果以后你愿意精修资料库，再补这些可选目录即可：

- `identity/`：5-8 张，优先清晰正脸、侧脸、半身，确保发型和五官稳定。
- `outfit/`：3-5 张，常服、正式服、角色高识别服装各一些。
- `expression/`：3-5 张，温柔、冷脸、笑、压迫感、撒娇等不同情绪。
- `pose/`：3-5 张，半身、坐姿、侧身、回眸。
- `mood/`：3-5 张，花窗、雨夜、卧室、海边、书房等氛围图。

文件名建议：

```text
01_full_reference.png
02_card_reference.png
03_side_or_half_body.png
complete/04_full_body.png
```

## 重要风险标记

如果图片来自官方卡面、PV、游戏截图或高度还原二创，请默认视为 `high_ip_risk`，只用于粉丝向/测试/私域参考，不要直接标记为可商用素材。

后端会扫描这些图片，但不会自动下载官方素材，也不会把图片提交到 Git。你本地放图后，接口会以 data URL 的形式传给当前生图 provider。
