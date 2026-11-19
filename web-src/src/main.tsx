import React from "react";
import ReactDOM from "react-dom/client";

function App() {
  return (
    <div style={{ padding: "24px", fontFamily: "system-ui, sans-serif" }}>
      <h1>Playwright 网页工具审计</h1>
      <p>正在初始化审计数据...</p>
    </div>
  );
}

const rootEl = document.getElementById("root");
if (rootEl) {
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
