## 杭电保卫公众号-安全教育自动答题脚本。一键完成安全教育课程。
## ⚠️ 免责声明

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。


##  原理

平台是纯明文 HTTP 接口😓，无加密、无签名、无防重放：

**关键**：`/wap/wrong/list` 返回的错题里带 `answer` 字段（正确答案）。所以脚本可以先猜答案提交，错了自动学正确答案进题库，重试直到全对。`--learn-all` 进一步利用这点：提交无效答案让 50 题全错，一次学完全部正确答案。

倒计时（20 秒/30 分钟）是纯前端 `setInterval`，后端不校验，直接调 API 秒提交。

## 安装

Python 3.6+，无需任何第三方依赖，纯标准库实现。

```bash
git clone https://github.com/yuaiccc/HDU-xiaoyuananquantong.git
cd HDU-xiaoyuananquantong
```

## 使用方法（以杭州电子科技大学为例）

### Web 一键答题

```bash
python3 server.py
```

浏览器打开 <http://localhost:8090>，粘贴平台链接即可。系统会自动提取
`userId`、`collegeId`、`ah`，完成未完成章节并参加正式考试，直到通过并获取证书。
解析器也能从残缺链接或聊天文字中优先提取 `ah=` 后的 token；浏览器会记住上一次成功的
`userId`，`collegeId` 固定使用杭电参数，但不会保存登录 token。

![Web 一键答题界面](docs/images/web-home.png)

### 1. 获取你的三个参数

关注公众号杭电保卫，点击服务师生，选择新生安全，进入平台，进入「学习课程」页面，从地址栏复制 3 个参数：

在浏览器菜单中选择「复制链接」：

![在浏览器中复制平台链接](docs/images/copy-link.png)

| 参数 | 说明 | 杭电示例 |
|---|---|---|
| `userId` | 用户 ID | `20---------69` |
| `collegeId` | 学校 ID | `19--------01` |
| `ah` | 登录 token（会话凭证，过期需重新登录获取）| `f6---------fd` |

URL 形如：
```
http://wap.xiaoyuananquantong.com/guns-vip-main/wap/compulsory?courseType=1&userId=...&collegeId=...&ah=...
```

> 本项目只面向杭州电子科技大学，`collegeId` 已内置，无需手动填写。

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

##  文件说明

| 文件 | 说明 |
|---|---|
| `xy_auto.py` | 主脚本 |
| `xy_bank.json` | 杭电题库（780 题，可直接使用）|
| `xy_schools.json` | 已知使用本系统的学校列表（collegeId → 校名）|

题库 `xy_bank.json` 按题干文本归一化匹配，可备份复用。杭电的题库已包含 780 题，杭电用户下载后可直接跑正式考，无需再刷。

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
