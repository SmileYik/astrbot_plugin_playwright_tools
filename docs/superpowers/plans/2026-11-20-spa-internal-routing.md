# SPA 内存路由与单一控制台视图实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将插件 Web 视图重构为纯单页应用 (SPA)，使用插件命名前缀的 localStorage 结合 React State 内存路由实现无冲突的审计与生命周期视图切换，收敛单一产物目录 `views/browser`。

**Architecture:** 
`metadata.yaml` 声明单一控制台视图 `browser`。前端应用 `web-src` 移除 Hash 修改，使用内存 State (`activeTab`) 驱动视图，并持久化于 `astrbot_plugin_playwright_tools:active_tab`。构建配置移除跨目录镜像拷贝，仅编译输出至 `views/browser`，彻底清理旧目录。

**Tech Stack:** React 18, TypeScript, Vite, Python unittest

**Spec:** `docs/superpowers/specs/2026-11-20-spa-internal-routing-design.md`

## Global Constraints

- 存储键名必须严格为：`astrbot_plugin_playwright_tools:active_tab`，避免同源 localStorage 冲突。
- 严禁修改 `window.location.hash` 或调用 `history.pushState`，杜绝与宿主 AstrBot 的 Hash 路由冲突。
- 视图产物目录严格为 `views/browser`，彻底删除旧的 `views/audit` 与 `views/lifecycle`。
- 全量单元测试（`python -m unittest discover tests`）保持 100% 通过。

## Review Focus

1. **localStorage 读写受限容错**：在无痕浏览模式或隐私策略禁止 localStorage 时，保证安全 try-catch 降级为默认 `audit` 视图，页面不白屏报错。
2. **无效存储值防御**：若存储中存在非 `"audit"` 且非 `"lifecycle"` 的脏数据，自动纠错回退为 `"audit"`。
3. **旧静态产物完全清理**：确保构建前/构建后 `views/audit` 与 `views/lifecycle` 不残留，防止插件包体积虚胖。
4. **元数据声明准确性**：`metadata.yaml` 的 views 列表仅且仅有 1 个 `browser` 视图，`target` 为 `plugin_page`。
5. **Bridge 初始化协同**：若 Bridge `ready()` 返回的 context 携带了 `viewName`，以插件内部用户持久化偏好或默认值为准，不再强制绑定已经不存在的独立 viewName。

---

### Task 1: 元数据配置与测试用例升级 (`metadata.yaml` & `tests/test_plugin_main.py`)

**Files:**
- Modify: `metadata.yaml`
- Modify: `tests/test_plugin_main.py`

**Interfaces:**
- Produces: `metadata.yaml` with single view `name: browser`, `title: 网页工具控制台`.

- [ ] **Step 1: Write the failing test**

In `tests/test_plugin_main.py`, update `test_metadata_views_declared`:
```python
    def test_metadata_views_declared(self):
        meta_path = Path("metadata.yaml")
        self.assertTrue(meta_path.exists())
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)
        self.assertIn("views", meta)
        views = meta["views"]
        self.assertIsInstance(views, list)
        self.assertEqual(len(views), 1, "Should only declare a single unified SPA view")
        browser_view = views[0]
        self.assertEqual(browser_view.get("name"), "browser")
        self.assertEqual(browser_view.get("target"), "plugin_page")
        self.assertEqual(browser_view.get("title"), "网页工具控制台")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: FAIL with `AssertionError: 2 != 1 : Should only declare a single unified SPA view`

- [ ] **Step 3: Update `metadata.yaml`**

Update `metadata.yaml` views section:
```yaml
views:
  - name: browser
    target: plugin_page
    title: 网页工具控制台
    description: Playwright 自动化网页工具的执行审计、DOM快照与会话生命周期统一管理控制台
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_plugin_main.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add metadata.yaml tests/test_plugin_main.py
git commit -m "feat(meta): unify plugin view to single browser console entry in metadata.yaml"
```

---

### Task 2: 前端单页内存路由与命名空间持久化 (`web-src/src/App.tsx`)

**Files:**
- Modify: `web-src/src/App.tsx`

**Interfaces:**
- Consumes: `localStorage`
- Produces: Safe memory routing persisted to `astrbot_plugin_playwright_tools:active_tab`.

- [ ] **Step 1: Update `App.tsx` state and tab persistence**

- 定义常量：
  ```typescript
  const TAB_STORAGE_KEY = "astrbot_plugin_playwright_tools:active_tab";
  ```
- 修改 `activeTab` 初始值：
  ```typescript
  const [activeTab, setActiveTab] = useState<NavTabType>(() => {
    try {
      const saved = localStorage.getItem(TAB_STORAGE_KEY);
      if (saved === "lifecycle" || saved === "audit") {
        return saved;
      }
    } catch {
      // ignore
    }
    return "audit";
  });
  ```
- 移除所有对 `window.location.hash`、`window.location.href` 或 URL 参数的操作。
- 修改 `handleTabChange`：
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
- 在 `Navbar` 传入 `activeTab={activeTab}` 与 `onTabChange={handleTabChange}`。

- [ ] **Step 2: Typecheck frontend**

Run: `npx --prefix web-src tsc --noEmit`
Expected: PASS with 0 errors.

- [ ] **Step 3: Commit**

```bash
git add web-src/src/App.tsx
git commit -m "feat(web): implement memory routing with plugin-namespaced localStorage persistence"
```

---

### Task 3: Vite 编译输出收敛与产物清理 (`web-src/vite.config.ts`, `views/`)

**Files:**
- Modify: `web-src/vite.config.ts`
- Remove: `views/audit/`, `views/lifecycle/`
- Create/Build: `views/browser/`

**Interfaces:**
- Produces: Single compiled distribution in `views/browser`.

- [ ] **Step 1: Update `web-src/vite.config.ts`**

移除 `copyToLifecyclePlugin`，将 `build.outDir` 设置为 `../views/browser`：
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../views/browser",
    emptyOutDir: true,
  },
});
```

- [ ] **Step 2: Clean up old view directories**

删除旧目录：
- `Remove-Item -Recurse -Force views/audit`
- `Remove-Item -Recurse -Force views/lifecycle`

- [ ] **Step 3: Build frontend**

Run: `npm run build --prefix web-src` (use BypassSandbox if required by Windows sandbox)
Expected: Build passes, `views/browser/index.html` and `views/browser/assets/*` are created.

- [ ] **Step 4: Verify build artifacts**

Check:
- `views/browser/index.html` exists.
- Neither `views/audit` nor `views/lifecycle` exists.

- [ ] **Step 5: Commit**

```bash
git add web-src/vite.config.ts views/
git commit -m "chore(build): target views/browser and clean up legacy view bundles"
```

---

### Task 4: 端到端集成验证与全量回归测试

**Files:**
- Test: All test files in `tests/`

- [ ] **Step 1: Run full python test suite**

Run: `python -m unittest discover tests`
Expected: 所有的测试全部通过（100% PASS）。

- [ ] **Step 2: Verify git status and clean working tree**

Run: `git status`
Expected: Working tree clean.

- [ ] **Step 3: Commit release tag/completion**

```bash
git commit --allow-empty -m "chore(release): complete single SPA web view with memory routing"
```
