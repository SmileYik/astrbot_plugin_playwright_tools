# 插件 Web 视图单页应用 (SPA) 与内部路由重构设计

**Date:** 2026-11-20  
**Status:** In Review  
**Author:** Antigravity & User  

---

## 1. 背景与意图 (Intent & Why)

此前为了在 AstrBot 的插件菜单中展示“审计日志”与“会话生命周期”，插件在构建时将同一套前端代码编译并镜像复制到了 `views/audit` 和 `views/lifecycle` 两个独立目录下，导致构建产物冗余（重复约 1.3MB），且在前端内部缺乏统一规范的 URL 路由驱动机制。

本次重构旨在将插件 Web 视图规范为标准的**单页应用（SPA）**：
- 在 AstrBot 插件菜单中提供统一入口：`browser`（网页工具控制台）；
- 消除 `views/` 下的重复目录，统一编译输出至 `views/browser`；
- 前端内部采用 **Hash 路由**（`#/audit` 与 `#/lifecycle`），实现视图切换、前进后退及刷新保持。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### Goals
1. **单一入口与清理冗余**：
   - `metadata.yaml` 声明单一视图 `name: browser`，标题为 `网页工具控制台`；
   - 清理 `views/audit` 与 `views/lifecycle`，统一编译产物至 `views/browser`；
   - `web-src/vite.config.ts` 移除镜像拷贝插件，编译输出至 `../views/browser`。
2. **SPA 内部 Hash 路由**：
   - 采用标准 Hash 路由规范（`#/audit` 与 `#/lifecycle`）；
   - 监听 `hashchange` 事件，双向绑定 `Navbar` 状态与 `window.location.hash`；
   - 支持浏览器前进/后退，支持带 Hash 直链访问并准确定位视图。
3. **回归测试保证**：
   - 更新 `tests/test_plugin_main.py` 对 `metadata.yaml` 视图声明的校验；
   - 139+ 全量测试套件 100% 通过。

### Non-Goals
- 不修改底层 Web API 接口路由路径（保持 `/audit/*` 与 `/lifecycle/*` 规范）；
- 不改动各视图（`AuditView`、`LifecycleView`）内部的核心业务逻辑。

### Anti-Goals
- **禁止采用 HTML5 History API (PushState/PopState)**：因为 AstrBot 后端静态文件服务未针对子路径配置重写路由，History 路由在刷新页面时会导致 404 错误。必须严格采用 Hash 路由。

---

## 3. 架构方案对比与选型 (Approaches)

### 方案 A：独立单页控制台 `views/browser` + Hash 路由（已采纳）
- **做法**：`metadata.yaml` 声明 `name: browser`，标题为 `网页工具控制台`。产物输出到 `views/browser`。内部通过 `#/audit` 与 `#/lifecycle` 路由。
- **优点**：语义清晰，统一控制台定位更准确；彻底避免重复编译产物，代码包体积减少约 50%；Hash 路由在 iframe/静态服务下天然免除 404 隐患。
- **缺点**：需用户在菜单中点击统一控制台后再通过内嵌 Navbar 切换。

### 方案 B：保持 `views/audit` 目录名，仅将生命周期作为内嵌二级页面
- **做法**：维持目录名 `views/audit` 与 `metadata.yaml` 中 `name: audit`，内部加上 Tab 切换。
- **缺点**：目录名与菜单项偏离“生命周期管理”的实际功能覆盖，未能体现管理控制台的全貌。

---

## 4. 详细设计 (Detailed Design)

### 4.1 元数据与构建配置调整
1. **`metadata.yaml`**：
   ```yaml
   views:
     - name: browser
       target: plugin_page
       title: 网页工具控制台
       description: Playwright 自动化网页工具的执行审计、DOM快照与会话生命周期统一管理控制台
   ```
2. **`web-src/vite.config.ts`**：
   - 移除 `copyToLifecyclePlugin`；
   - 设置 `build.outDir = "../views/browser"`，`emptyOutDir = true`。

### 4.2 前端 Hash 路由设计 (`web-src/src/App.tsx` & `Navbar.tsx`)
1. **路由映射定义**：
   - `#/audit` 或空 hash（`#` / `""`）：映射到 `audit` 视图（网页工具审计）；
   - `#/lifecycle`：映射到 `lifecycle` 视图（会话生命周期管理）。
2. **路由监听与同步**：
   - 初始化时读取 `window.location.hash`（兼容 `ctx?.viewName`），设置初始 `activeTab`；
   - 若进入时无 hash 或 hash 不符合规范，默认重定向至 `#/audit`；
   - 监听 `window.addEventListener("hashchange", ...)`，当 URL Hash 变更时平滑更新 React 组件状态；
   - 用户点击 `Navbar` 中的 Tab 时，直接执行 `window.location.hash = tab === "lifecycle" ? "#/lifecycle" : "#/audit"`，由 `hashchange` 驱动界面重渲染，保持单向数据流与浏览器历史记录一致。

### 4.3 目录与产物清理
- 物理删除 `views/audit/` 与 `views/lifecycle/` 目录；
- 执行 `npm run build --prefix web-src` 输出全新的单页应用静态产物至 `views/browser/`。

### 4.4 自动化测试维护
- 更新 `tests/test_plugin_main.py` 中的 `test_metadata_views_declared`，校验 `metadata.yaml` 中存在唯一的 `name: browser` 视图声明，且 `target: plugin_page`。

---

## 5. 验证计划 (Verification Plan)
1. **构建验证**：运行 `npm run build --prefix web-src` 成功，检查仅生成 `views/browser/index.html` 及对应 `assets/`；
2. **路由验证**：检查直接访问、切换 Tab、浏览器前进后退、刷新操作下 Hash 与视图的正确对应关系；
3. **全量回归**：执行 `python -m unittest discover tests` 确保所有 139 项单测 100% 通过。
