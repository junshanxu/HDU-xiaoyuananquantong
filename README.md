# HDU-xiaoyuananquantong

> 校园安全通（xiaoyuananquantong.com）自动答题脚本 —— 章节测试 / 模拟考试 / 正式考试全自动，错题学习 100% 准确，以杭州电子科技大学为例。

一键完成安全教育课程。利用平台错题接口回传正确答案的特性，自动学习并重试，题库刷满后稳定满分。

## ✨ 特性

- **全自动**：遍历所有课程 / 章节 / 考试，无需手动点页面
- **100% 准确**：答案来自平台官方错题接口（非 AI 猜测，非题库硬编码）
- **绕过所有限制**：直接调 API，跳过 20 秒幻灯片计时器、30 秒翻页、视频观看
- **自动闭环学习**：答错 → 拉取错题学正确答案 → 重试，直到全对通过
- **快速刷题库**：`--learn-all` 模式故意全错提交，一次学 50 题，十几轮覆盖全部题库
- **多校通用**：换 `collegeId` / `userId` / `ah` 即适用于任何使用本系统的学校

## 🎯 原理

平台是纯明文 HTTP 接口，无加密、无签名、无防重放：

| 步骤 | 章节测试接口 | 考试接口 |
|---|---|---|
| 列表 | `POST /wap/compulsory/list` | `POST /wap/test/getTest` |
| 目录/创建 | `POST /wap/directory/list` | `POST /wap/test/create`（消耗 1 次）|
| 取题 | `GET /wap/question/list` | `GET /wap/test/list` |
| 提交 | `POST /wap/unitTest` | `POST /wap/imitateTest` |
| 错题 | `GET /wap/wrong/list` ← **回传正确答案** | 同左 |

**关键**：`/wap/wrong/list` 返回的错题里带 `answer` 字段（正确答案）。所以脚本可以先猜答案提交，错了自动学正确答案进题库，重试直到全对。`--learn-all` 进一步利用这点：故意提交无效答案让 50 题全错，一次学完全部正确答案。

倒计时（20 秒/30 分钟）是纯前端 `setInterval`，后端不校验，直接调 API 秒提交。

## 📦 安装

Python 3.6+，**无需任何第三方依赖**（纯标准库实现）。

```bash
git clone https://github.com/yuaiccc/HDU-xiaoyuananquantong.git
cd HDU-xiaoyuananquantong
```

## 🚀 使用方法（以杭州电子科技大学为例）

### 1. 获取你的三个参数

手机或浏览器登录 <http://wap.xiaoyuananquantong.com>，进入「学习课程」页面，从地址栏复制 3 个参数：

| 参数 | 说明 | 杭电研究生示例 |
|---|---|---|
| `userId` | 用户 ID | `2077304038830931969` |
| `collegeId` | 学校 ID | `1940953111032012801` |
| `ah` | 登录 token（会话凭证，过期需重新登录获取）| `f68790163b904c61469043d5c9a218fd` |

URL 形如：
```
http://wap.xiaoyuananquantong.com/guns-vip-main/wap/compulsory?courseType=1&userId=...&collegeId=...&ah=...
```

> 脚本默认内置了杭电研究生的参数，杭电用户可直接运行；其他学校用 `--college-id` 等参数覆盖。

### 2. 章节测试（必修课答题）

```bash
# 先 dry-run 只看题目不提交（验证参数对不对）
python3 xy_auto.py --dry-run

# 一键完成所有未完成章节
python3 xy_auto.py --yes

# 重做已完成的章节（用来刷题库）
python3 xy_auto.py --force --yes
```

### 3. 模拟考试（无限次，用来刷题库）

模拟考试有 999 次机会，专门用来积累题库。**强烈建议先刷满题库再考正式**：

```bash
# 快速刷满题库（推荐！每轮学 50 题，十几轮覆盖全部 ~780 题）
python3 xy_auto.py --exam --exam-type 1 --learn-all --max-exam-retry 30 --yes

# 正常模拟考（题库命中答题，自动重试直到通过）
python3 xy_auto.py --exam --exam-type 1 --yes
```

### 4. 正式考试（限次，题库满后一次过）

题库刷满后，正式考试基本满分一次过：

```bash
# 正式考试（默认只考 1 次；未通过会自动学错题后停止，不浪费次数）
python3 xy_auto.py --exam --exam-type 2 --yes

# 允许未通过时自动重考（3 次机会内尽量通过）
python3 xy_auto.py --exam --exam-type 2 --retry-exam --yes
```

### 5. ah 过期后怎么办

`ah` 是会话 token，过期后接口返回 `code:303`。重新登录平台，从 URL 复制新 `ah`：

```bash
python3 xy_auto.py --exam --exam-type 2 --yes --ah 新的token
```

## 📁 文件说明

| 文件 | 说明 |
|---|---|
| `xy_auto.py` | 主脚本 |
| `xy_bank.json` | 题库（杭电 780 题，已刷满，杭电用户可直接用；其他学校需重刷）|
| `xy_schools.json` | 已知使用本系统的学校列表（collegeId → 校名）|

题库 `xy_bank.json` 按题干文本归一化匹配，可备份复用。杭电的题库已包含 780 题，杭电用户下载后可直接跑正式考，无需再刷。

## 🏫 支持的学校

脚本通用，任何使用「校园安全通」系统的学校都能用。已确认 54 所（53 所江苏高校 + 杭电），完整列表见 [`xy_schools.json`](xy_schools.json)。

换学校只需改 `--college-id`（其他学校需重新刷题库）：

```bash
# 例：南京大学
python3 xy_auto.py --college-id 1215080375038705665 --user-id 你的userId --ah 你的token --yes
```

## 📊 实测效果（杭电）

| 阶段 | 题库 | 命中 | 得分 |
|---|---|---|---|
| 初始全猜 | 0 | 0/50 | 38 |
| 刷题中 | 510 | 30/50 | 94 |
| 题库刷满 | 780 | 50/50 | **100** |

正式考试：题库满后一次通过，94 分（错 3），获得合格证书。

## 📋 完整参数

```bash
python3 xy_auto.py --help
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--dry-run` | 只看题目不提交 |
| `--force` | 重做已完成的章节 |
| `--exam` | 考试模式 |
| `--exam-type 1` | 模拟考试（无限次）|
| `--exam-type 2` | 正式考试（限次）|
| `--learn-all` | 全错提交快速刷题库（每轮学 50 题）|
| `--retry-exam` | 正式考未通过也自动重考 |
| `--max-exam-retry N` | 考试最大尝试次数 |
| `--course-id ID` | 只处理指定课程 |
| `--ah TOKEN` | 指定登录 token |
| `--yes` | 跳过开始前确认 |

## ⚠️ 免责声明

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。

## 🙏 致谢

- [FuckXiaoyuananquantong](https://github.com/xmbhjQAQ/FuckXiaoyuananquantong) —— 同系统的油猴脚本，AI 答题与前端计时器破解思路提供了参考

## 📄 License

MIT
