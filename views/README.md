# Playwright Tool 视图产物目录 (views)

本目录包含本插件在 AstrBot WebUI 管理后台中展示的可视化页面预构建静态资源（SPA 单页应用）。

- **控制台页面**：`views/browser/` (对应 `metadata.yaml` 中注册的 `target: plugin_page` 视图)
- **源码开发**：请勿直接在本目录修改编译后的产物。如需迭代界面，请移步至 [web-src/](../web-src/) 目录进行修改并通过构建工具重新编译。
