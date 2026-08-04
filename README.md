## 杭电保卫公众号-安全教育自动答题脚本。一键完成安全教育课程。
## ⚠️ 免责声明

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。



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

关注公众号杭电保卫，点击服务师生，选择新生安全，进入平台，进入「学习课程」页面，

在浏览器菜单中选择「复制链接」：

![在浏览器中复制平台链接](docs/images/copy-link.png)


> 本项目只面向杭州电子科技大学，`collegeId` 已内置，无需手动填写。


### ah 过期后怎么办

`ah` 是会话 token，过期后接口返回 `code:303`。重新登录平台，从 URL 复制新 `ah`：

```bash
python3 xy_auto.py --exam --exam-type 2 --yes --ah 新的token
```
##  原理

平台是纯明文 HTTP 接口😓，无加密、无签名、无防重放：

**关键**：`/wap/wrong/list` 返回的错题里带 `answer` 字段（正确答案）。所以脚本可以先猜答案提交，错了自动学正确答案进题库，重试直到全对。`--learn-all` 进一步利用这点：提交无效答案让 50 题全错，一次学完全部正确答案。

倒计时（20 秒/30 分钟）是纯前端 `setInterval`，后端不校验，直接调 API 秒提交。
##  文件说明

| 文件 | 说明 |
|---|---|
| `xy_auto.py` | 主脚本 |
| `xy_bank.json` | 杭电题库（780 题，可直接使用）|
| `xy_schools.json` | 已知使用本系统的学校列表（collegeId → 校名）|

题库 `xy_bank.json` 按题干文本归一化匹配，可备份复用。杭电的题库已包含 780 题，杭电用户下载后可直接跑正式考，无需再刷。
