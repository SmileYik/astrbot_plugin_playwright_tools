# Playwright Tool 控制台源码 (web-src)

本目录为 PlaywrightTool 统一控制台的 Web 前端工程源代码，基于 Material Design 3 大圆角设计风格构建，运行于 AstrBot 管理后台插件页面环境中。

## 技术栈与设计规范

- **框架与构建**：React 18 + TypeScript + Vite
- **样式方案**：CSS Modules (`*.module.css`)，零额外运行时 UI 组件库依赖
- **主题适配**：自适应 AstrBot 宿主白天/暗黑模式，遵循 Material Design 3 表面色与 16~24px 大圆角体系
- **通信桥接**：基于 `window.AstrBotPluginView` Bridge SDK 与后端模块化 Web API 通信

## 常用命令

进入 `web-src` 目录：

```bash
cd web-src
```

### 1. 安装依赖
```bash
npm install
# 或使用 yarn
yarn install
```

### 2. 本地开发与调试
```bash
npm run dev
```

### 3. 构建发布产物
编译并自动将产物同步至 `views/browser/` 目录：

```bash
npm run build
```
