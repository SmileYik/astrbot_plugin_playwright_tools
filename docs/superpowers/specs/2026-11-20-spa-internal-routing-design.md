# 插件 Web 视图单页应用 (SPA) 与内存路由重构设计

**Date:** 2026-11-20  
**Status:** Approved  
**Author:** Antigravity & User  

---

## 1. 背景与意图 (Intent & Why)

此前为了在 AstrBot 的插件菜单中展示“审计日志”与“会话生命周期”，插件在构建时将同一套前端代码编译并镜像复制到了 `views/audit` 和 `views/lifecycle` 两个独立目录下，导致构建产物冗余（重复约 1.3MB 构建产物）。

并且，观测到 AstrBot 宿主 WebUI 自身也是采用 Hash 路由（例如 `http://<host>:6185/#/plugin-view/astrbot_plugin_playwright_tools/...`）。如果在插件 iframe 内部使用 `location.hash` 进行二级路由，会向浏览器全局历史记录栈（History Stack）插入记录，导致用户点击浏览器前进/后退时与 AstrBot 主导航发生竞争错乱。

本次重构旨在将插件 Web 视图规范为标准的**单页应用（SPA）**：
- 在 AstrBot 插件菜单中提供统一入口：`browser`（网页工具控制台）；
- 消除 `views/` 下的重复目录，统一编译输出至单一目录 `views/browser`；
- 前端内部采用**内存状态路由（Memory Router）+ 本地持久化（`localStorage`）**，彻底避免与宿主 AstrBot 的 Hash 路由冲突，并实现跨刷新无感状态恢复。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals, Anti-Goals)

### Goals
1. **单一入口与清理冗余**：
   - `metadata.yaml` 声明单一视图 `name: browser`，标题为 `网页工具控制台`；
   - 物理清理 `views/audit/` 与 `views/lifecycle/`，统一编译产物至 `views/browser/`；
   - `web-src/vite.config.ts` 移除镜像拷贝插件，编译输出至 `../views/browser`。
2. **零冲突内存路由与状态持久化**：
   - 前端采用 React State 内存驱动视图切换（`activeTab: "audit" | "lifecycle"`）；
   - 切换 Tab 时即时写入 `localStorage.setItem("astrbot_pw_tab", tab)`；
   - 初始化时优先从 `localStorage` 读取恢复上次所处视图，缺省默认为 `audit`；
   - **完全不修改 `window.location.hash`**，杜绝历史栈污染。
3. **回归测试保证**：
   - 更新 `tests/test_plugin_main.py` 对 `metadata.yaml` 视图声明的校验；
   - 139+ 全量测试套件 100% 通过。

### Non-Goals
- 不修改底层 Web API 接口路由路径（保持 `/audit/*` 与 `/lifecycle/*` 规范）；
- 不改动各视图（`AuditView`、`LifecycleView`）内部的核心业务逻辑。

### Anti-Goals
- **严禁修改 `window.location.hash` 或调用 `history.pushState`**：避免与 AstrBot 主站 Hash 路由产生任何冲突或历史栈混乱。

---

## 3. 详细设计 (Detailed Design)

### 3.1 元数据与构建配置调整
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

### 3.2 前端内存路由与持久化实现 (`web-src/src/App.tsx`)
1. **路由状态初始化**：
   ```typescript
   // 必须使用本插件名作为 localStorage 键名前缀，确保同源下绝无命名冲突
   const TAB_STORAGE_KEY = "astrbot_plugin_playwright_tools:active_tab";

   const [activeTab, setActiveTab] = useState<NavTabType>(() => {
     try {
       const saved = localStorage.getItem(TAB_STORAGE_KEY);
       if (saved === "lifecycle" || saved === "audit") {
         return saved;
       }
     } catch {
       // ignore localStorage restrictions
     }
     return "audit";
   });
   ```
2. **Tab 切换联动**：
   ```typescript
   const handleTabChange = useCallback((tab: NavTabType) => {
     setActiveTab(tab);
     try {
       localStorage.setItem(TAB_STORAGE_KEY, tab);
     } catch {
       // ignore
     }
   }, []);
   ```
3. **渲染联动**：
   - `Navbar` 绑定 `activeTab` 与 `onTabChange={handleTabChange}`；
   - 根据 `activeTab` 动态渲染 `<AuditView />` 或 `<LifecycleView />`。

### 3.3 目录与产物清理
- 物理删除 `views/audit/` 与 `views/lifecycle/` 目录；
- 执行 `npm run build --prefix web-src` 输出全新静态产物至 `views/browser/`。

### 3.4 自动化测试维护
- 更新 `tests/test_plugin_main.py` 中的 `test_metadata_views_declared`，校验 `metadata.yaml` 中存在唯一的 `name: browser` 视图声明，且 `target: plugin_page`。

---

## 4. 验证计划 (Verification Plan)
1. **构建验证**：运行 `npm run build --prefix web-src` 成功，检查仅生成 `views/browser/index.html` 及对应 `assets/`；
2. **路由持久化验证**：在页面切换至“会话生命周期管理”，刷新后仍能自动停留在“会话生命周期管理”，且浏览器 URL 无多余 hash 变更；
3. **全量回归**：执行 `python -m unittest discover tests` 确保所有单测 100% 通过。
