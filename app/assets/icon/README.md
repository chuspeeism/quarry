# Quarry 图标规格

按 [design-playful-app-icons](https://github.com/chunkithwang/design-playful-app-icons) 的方法产出，用 codex CLI 的 `imagegen` skill 生成。

## 概念

| 项 | 值 |
|----|----|
| Brief（object + action + emotion） | 一块刚开采出来、顶部被切开的原石 + 把散在各平台的素材开采成一层层可检索的沉淀 + clever / curious |
| Lane | `soft_3d_object_character` |
| Palette preset | `violet_tech` |
| Signature hook | 形状双关：矿石内部的地质层理 = 三片堆叠的内容切片 |

## 三个方向与取舍

| 方向 | 隐喻 | 结论 |
|------|------|------|
| **A. Ore Cut 原石切面** | 切开的原石，层理即内容切片 | **采用**。产品含义最强，剪影独特，形状双关是自造的 |
| B. Pickaxe Bite 镐击 | 镐头咬进矿脉 | 否。镐子能代表任意「挖掘/建造」类 app，违反「一个隐喻不能同时代表三个无关品类」 |
| C. Vein Face 矿脉小家伙 | 有眼睛的矿石 | 否。加了脸反而挤掉了「分层沉淀」这个真正的产品含义 |

## 色板

| 角色 | 值 | 用在哪 |
|------|-----|--------|
| dominant | `#4237C6` | 矿石本体 |
| contrast | `#3FA1F9` | 中间那片切片 |
| neutral | `#F8F6F5` | 顶部切片与高光 |
| accent | `#FDDA34` | 只用在翻起的盖片受光边缘 |

## 小尺寸校验

按 rubric 在 1024 / 180 / 60 / 32 px 各查一遍：

- **v1 未通过**：三片切片之间只有色相差没有明度差，60 px 以下糊成一整块蓝，唯一的记忆点丢失。
- **v2（当前版本）通过**：改了两处——切片加厚到约矿石高度的 1/6，三片改成「白 / 天蓝 / 深蓝」的硬明度台阶。32 px 下三条亮度带仍可分离，灰度下前后景分离干净。

v1 作为被否掉的稿留在内容层 `vault/archive/legacy/icon-drafts/`，不进仓库。

## 文件

| 文件 | 用途 |
|------|------|
| `quarry-icon-1024.png` | 母版，iOS 规格：1024×1024、sRGB、不透明、未烘焙圆角遮罩 |
| `quarry-icon-512/256/180/128/60/32.png` | 派生尺寸，`256` 被 `app/index.html` 用作 favicon |

改图标时改母版，然后重跑：

```bash
cd app/assets/icon && for s in 512 256 180 128 60 32; do sips -Z $s -s format png quarry-icon-1024.png --out quarry-icon-$s.png; done
```
