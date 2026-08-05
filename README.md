## 杭电保卫公众号-“研新·序章”始业教育自动答题。
## 链接 is all you need
## ⚠️ 免责声明

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。



## 安装


```bash
git clone https://github.com/yuaiccc/HDU-xiaoyuananquantong.git
cd HDU-xiaoyuananquantong
```

## 使用方法（以杭电为例，不知道其他学校题库情况）

### 一键答题

```bash
python3 server.py
```

启动后，浏览器打开 <http://localhost:8090>，粘贴公众号里复制的链接即可。系统会自动解析
`userId`、`collegeId`、`ah`；确认后点击“开始答题并获取证书”，系统会完成未完成章节并参加正式考试，直到通过并获取证书。
解析器也能从残缺链接或聊天文字中优先提取 `ah=` 后的 token；浏览器会记住上一次成功的
`userId`，`collegeId` 固定使用杭电参数。

![一键答题界面](docs/images/web-home.png)

### 获取你的三个参数

关注公众号杭电保卫，点击服务师生，选择新生安全，进入平台，进入「学习课程」页面，

在浏览器菜单中选择「复制链接」：

![在浏览器中复制平台链接](docs/images/copy-link.png)


> 本项目只面向杭州电子科技大学使用，`collegeId` 已内置，无需手动填写。

### 给自己的 Agent 使用

仓库包含通用 Agent Skill：`skills/hdu-safety-answer/`。支持 Agent Skills 的客户端可从本仓库安装：

```bash
npx skills add yuaiccc/HDU-xiaoyuananquantong --skill hdu-safety-answer
```

Skill 只指导 Agent 在用户自己的电脑上启动和操作本项目；不会保存 token，且提交答题前要求 Agent 获得用户明确确认。
首次使用时，Skill 会将完整仓库（包括 `xy_bank.json` 题库）克隆到用户选择的本地目录并校验题库；Skill 安装包本身不重复携带题库。


### ah 过期后怎么办？

`ah` 是会话 token，过期后接口返回 `code:303`。重新登录平台，重新复制即可：

##  原理

平台是纯明文 HTTP 接口 😓，无加密、无签名、无防重放：

**关键**：`/wap/wrong/list` 返回的错题里带 `answer` 字段（正确答案）。所以脚本可以先猜答案提交，错了自动学正确答案进题库，重试直到全对。`--learn-all` 进一步利用这点：提交无效答案让 50 题全错，一次学完全部正确答案，直接打穿题库。

倒计时（20 秒/30 分钟）是纯前端 `setInterval`，后端不校验，直接调 API 秒提交。
