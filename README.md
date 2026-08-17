# 杭电保卫公众号「研新·序章」始业教育自动答题工具

macOS / Linux 用户在终端运行下面这一句，即可下载完整工具、校验题库并自动打开本地网页：

```bash
curl -fsSL https://raw.githubusercontent.com/yuaiccc/HDU-xiaoyuananquantong/main/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/yuaiccc/HDU-xiaoyuananquantong/main/install.ps1 | iex
```

> 隐私说明：服务只在 `127.0.0.1` 本地运行。粘贴的链接和 `ah` token 只从你的电脑直接发送给安全教育平台，不会上传到任何第三方，也不会被持久化保存（仅 `userId` 保存在浏览器本地，方便下次自动填充）。

如果希望让 Coding Agent 学会准备和操作本工具，可以另外安装仓库提供的 Skill：

```bash
npx skills add yuaiccc/HDU-xiaoyuananquantong --skill hdu-safety-answer
```

## 手动安装

```bash
git clone https://github.com/yuaiccc/HDU-xiaoyuananquantong.git
cd HDU-xiaoyuananquantong
python3 server.py
```

## 使用方法（以杭电为例，其他学校题库情况未知）

关注公众号杭电保卫，点击服务师生，选择新生安全，进入平台，进入「学习课程」页面：

![一键答题界面](docs/images/web-home.png)

在浏览器菜单中选择「复制链接」：

![在浏览器中复制平台链接](docs/images/copy-link.png)

把链接粘贴到网页输入框，点击「开始答题并获取证书」。工具会自动完成整个流程，实时进度显示在右侧「运行记录」中：

1. 完成未完成的课程章节（自动提交单元测试，并从错题接口学习正确答案）
2. 参加正式考试并获取证书

如果考试次数已经用完、但平台里存在合格证书，工具会直接展示已有证书，无需重新学习课程。证书图片只在内存中保留 10 分钟，请及时点击「保存证书图片」。

> 本项目只面向杭州电子科技大学使用，`collegeId` 已内置，无需手动填写。

## 常见问题

### ah 过期后怎么办？

`ah` 是会话 token，过期后接口返回 `code:303`。重新登录平台，重新复制链接粘贴即可。

### 端口被占用？

服务默认使用 `8090` 端口，可用环境变量指定其他端口：

```bash
PORT=8091 python3 server.py
```

### 只想安装、暂不启动？

```bash
curl -fsSL https://raw.githubusercontent.com/yuaiccc/HDU-xiaoyuananquantong/main/install.sh | env HDU_SAFETY_INSTALL_ONLY=1 bash
```

安装位置默认为 `~/.local/share/hdu-safety-answer`，可用 `HDU_SAFETY_DIR` 自定义。

## 开发

运行全部测试：

```bash
python3 -m unittest tests.test_phase1 tests.test_server_flow
```

## ⚠️

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。
