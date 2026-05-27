# Octopus UI

独立的 Web 操作界面，仅通过现有 HTTP API 与服务端交互。

## 启动

先在仓库根目录启动现有服务端：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

服务端默认监听 `http://127.0.0.1:8000`。然后启动 UI：

```powershell
cd ui
npm install
npm run dev
```

Vite 将 `/api` 请求代理到端口 `8000`，不改变服务端启动方式。

## 验证

```powershell
npm test
npm run typecheck
npm run build
```
