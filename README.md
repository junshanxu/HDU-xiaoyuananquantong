# 杭电保卫公众号-“研新·序章”始业教育自动答题。

# 链接 is all you need

## ⚠️ 免责声明

本项目仅供学习与技术交流，**不鼓励也不协助任何违反校规的行为**。使用者需自行确认所在学校是否允许使用自动化工具完成安全教育课程，并对自己的行为负责。作者不对使用本脚本产生的任何后果承担责任。

## 一句话使用

macOS 或 Linux 用户在终端运行下面这一句，即可下载完整工具、校验题库并启动本地网页：

```bash
curl -fsSL https://raw.githubusercontent.com/yuaiccc/HDU-xiaoyuananquantong/main/install.sh | bash
```

工具默认安装到 `~/.local/share/hdu-safety-answer`，重复运行会复用已有安装，不会自动覆盖文件。服务只监听 `127.0.0.1:8090`；关闭运行命令的终端或按 `Ctrl+C` 即可停止。
安装器要求电脑已安装 Git 和 Python 3，缺少时会直接提示，不会修改其他系统配置。

如果希望先检查脚本再执行：

```bash
curl -fsSL https://raw.githubusercontent.com/yuaiccc/HDU-xiaoyuananquantong/main/install.sh -o install.sh
less install.sh
bash install.sh
```

### 给 Coding Agent 安装 Skill（可选）

如果希望让 Coding Agent 学会准备和操作本工具，可以另外安装仓库提供的 Skill：

```bash
npx skills add yuaiccc/HDU-xiaoyuananquantong --skill hdu-safety-answer
```

## 或者手动安装

```bash
git clone https://github.com/yuaiccc/HDU-xiaoyuananquantong.git
cd HDU-xiaoyuananquantong
```

## 使用方法（以杭电为例，不知道其他学校题库情况）



```bash
python3 server.py
```

启动后，浏览器打开 <http://localhost:8090>，粘贴公众号里复制的链接即可。系统会自动解析
`userId`、`collegeId`、`ah`；自动完成可处理的流程；成功后弹出证书。
解析器也能从残缺链接或聊天文字中优先提取 `ah=` 后的 token；浏览器会记住上一次成功的
`userId`，`collegeId` 固定使用杭电参数。

![一键答题界面](docs/images/web-home.png)

关注公众号杭电保卫，点击服务师生，选择新生安全，进入平台，进入「学习课程」页面，

在浏览器菜单中选择「复制链接」：

![在浏览器中复制平台链接](docs/images/copy-link.png)


> 本项目只面向杭州电子科技大学使用，`collegeId` 已内置，无需手动填写。



### ah 过期后怎么办？

`ah` 是会话 token，过期后接口返回 `code:303`。重新登录平台，重新复制即可：
