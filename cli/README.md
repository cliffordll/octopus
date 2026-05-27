# Octopus CLI

独立 HTTP CLI，通过现有服务端接口操作组织、Issue 和审批。

## 使用

先按项目现有方式启动服务端，默认 API 地址为 `http://127.0.0.1:8000`：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

命令入口：

```powershell
uv run python -m cli --help
uv run python -m cli organization list
uv run python -m cli issue list --org-id <org-id> --status in_review
uv run python -m cli approval list --org-id <org-id>
uv run python -m cli --json approval get <approval-id>
```

可用 `--api-base <url>` 指向另一服务端；该选项与 `--json` 均放在资源命令之前。

## 验证

```powershell
uv run pytest cli/tests -q
uv run ruff check cli
uv run pyright cli
```
