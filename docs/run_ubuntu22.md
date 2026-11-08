# Ubuntu 运行与环境验证

## 教师机器启动

需要 Python 3.10 或更高版本，核心程序和网页服务均无需 pip。已有 Python 时不修改系统环境：

```bash
python3 --version
python3 -m unittest discover -s tests -v
python3 run_demo.py --scenario baseline --live --delay 0.2
python3 run_demo.py --scenario deadlock
python3 dashboard_server.py
```

浏览器打开 <http://127.0.0.1:8765>；端口被占用时用 `--port 8766`，然后打开对应地址。浏览器必须通过 HTTP 服务访问，不能直接双击 HTML 后期待 API 可用。

若系统没有 Python，由有权限的操作者执行 `sudo apt update`、`sudo apt install python3`。Node.js/Playwright 只供开发回归使用，不是演示运行依赖。

## 本轮实际验证（2026-11-08）

| 环境 | 结果与范围 |
|---|---|
| Ubuntu 24.04.2 / 系统 Python 3.12.3 | 52 项测试、全部 CLI 固定演示、HTTP 与网页验证通过 |
| 同一主机 / 独立 CPython 3.10.21 | 52 项测试、JSON 输入及 CSV/JSON 导出通过；不等同于 Ubuntu 22.04 桌面 |
| 本机 Microsoft Edge / Chromium | 21 项交互与动效检查、六种宽度溢出检查通过 |
| Ubuntu 22.04 容器 | 本地尝试拉取镜像时 Docker Hub 网络超时，未运行成功，不能算通过 |
| GitHub Actions / 提交 `64abbe0` | Ubuntu 22.04/Python 3.10、Ubuntu 24.04/Python 3.12 的测试、CLI、100 次回归均通过；Ubuntu 22.04/Chromium 的 21 项浏览器检查通过 |

GitHub 独立验证已通过：[运行 42493681254](https://github.com/MacSwimmm/26_OS/actions/runs/42493681254)，精简记录见 `docs/review/github-validation.json`。

容器下载失败的原因是访问 `registry-1.docker.io` 超时，不是已发现的代码兼容性失败。CI 和本机验证均不能替代教师目标桌面的最后现场检查。

## 现场运行记录模板（卞苏阳交接）

记录实际执行，不预填“通过”：

```text
日期/操作者：
系统：cat /etc/os-release
Python：python3 --version
代码版本：git rev-parse HEAD
测试命令与结果：
普通调度/三类中断：
死锁避免/只检测/检测并恢复：
网页地址、浏览器版本、关键截图：
JSON/CSV 输出位置：
异常和处置：
```

现场建议先运行测试和终端备用，再打开网页。若投影设备动画不流畅，在设置里关闭视觉动效后继续功能演示。
