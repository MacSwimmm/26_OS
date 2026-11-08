# 上位机模板移植与验证

## 来源和移植范围

来源：[MacSwimmm/upper-computer-template](https://github.com/MacSwimmm/upper-computer-template)，本次对照提交 `71f6c076b7723165c5e875ad8a2ecdb82b27a908`（`fix: prevent cross-surface hover stalls and live-data resets`）。直接读取该提交的源码，移植其原生 Canvas 视效，接入本项目真实 Python 调度器；不使用模板的示例适配器数据。

| 模板能力 | 本项目文件 | 行为 |
|---|---|---|
| 黑绿功能区、响应式轮播/抽屉 | `dashboard-effects.css`、`signal-theme.css` | 总览和详情保持统一主题 |
| 点阵算法与 Worker | `pixel-field.js`、`dashboard-effects.js` | OffscreenCanvas，失败后主线程回退 |
| 共享位移网格 | `distortion-grid.js` | 15×15 网格、鼠标局部输入、时间阻尼和采样 |
| 页底大字震颤 | `footer-distortion.js` | 自有 TeaFlow OS 字标，可改中文；停下后恢复 |
| 功能区局部撕裂 | `signal-distortion.js` | 预热/替换内容缓存，保留跨卡片衰减，超时恢复原生内容 |
| 外观设置 | `dashboard-app.js`、`config.json` | 项目名、标题、说明、页底字、颜色、指标和模块显隐 |

原模板的 `dashboard.js/dashboard.css` 在本项目沿用旧资源名 `dashboard-effects.js/dashboard-effects.css`；原行内业务逻辑拆到 `dashboard-app.js`。动效事件和浏览器存储使用 `teaflow-*`，原项目的外观保存键保持兼容。

## 与调度业务的衔接

- 新增 FCFS 入口及五策略对照；保留三种死锁处理。
- 任务进度按整个任务 `completed_work/duration` 计算，避免跨阶段后进度跳回。
- t=0 是执行前边界，甘特图区间来自当时运行状态；完成事件与快照一致。
- 资源占用由真实 `holders` 计算，故障造成的不可用不再伪装成“100% 已占用”。共享公告板不进入四资源占用图。
- 日志增加依赖、普通请求、去重和恢复；实验日志带方案名，避免把不同组的事件混为同一运行。
- 设置导入校验对象、文字、颜色、指标和模块开关；自定义文字经转义再显示。

## 交互与资源生命周期

功能区 Canvas 覆盖层不接收鼠标事件；点击或键盘聚焦时回到原生界面，按钮、输入、选择框正常操作。设置抽屉支持焦点限制、Escape 关闭和焦点恢复；相邻预览不进入键盘焦点顺序。轮播有标签、箭头、方向键、Home/End 和横向触摸切换。

点阵、功能区震颤、页底震颤有独立开关。系统“减少动态效果”或只有触摸输入时使用静态界面；滚动、窗口变化、失焦和隐藏时清除不适用的扰动。功能区缓存与动画有数量和像素预算，失效/延迟时显示实时原生内容。关闭动效不改变调度算法。

浏览器执行 `/api/run` 后回放离散快照，不把计算已完成提示为用户刚开始播放的“仿真已结束”。请求过程中防重入；错误保持可见并提供重试。实验与单场景数据分别保存，返回总览可以继续播放。

## 复现检查

```bash
npm ci
npx playwright install chromium
npm run test:browser
```

已安装 Edge/Chromium 时可以使用 `BROWSER_PATH=/usr/bin/microsoft-edge npm run test:browser`。检查脚本自动启动并关闭独立测试服务，不依赖日常演示端口。

21 项浏览器检查包括开始/暂停/倍速/拖动/重播、防重复请求、场景与五组对照、死锁三组、设置和模块显隐、键盘、错误重试、导出、六种宽度无页面横向溢出、页底变形/复原、功能区覆盖层生成/释放、动效关闭持久化及未捕获错误。减少动态效果和正常动效分别检查；截图和报告生成到 `results/browser/`。

本次截图见 `docs/review/dashboard-overview.png` 和 `dashboard-footer.png`。这不是全浏览器逐像素或逐帧一致性证明；本次模板源码和功能验收范围均在上文列明。
