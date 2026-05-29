from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_organization_list_json_output() -> None:
    client = ApiClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": "org-1", "name": "Core"}])
        )
    )
    output = io.StringIO()

    result = main(["--json", "organization", "list"], client=client, stdout=output)

    assert result == 0
    assert '"name": "Core"' in output.getvalue()


def test_organization_create_posts_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/orgs"
        assert request.read() == b'{"name":"Core"}'
        return httpx.Response(200, json={"id": "org-1", "name": "Core"})

    output = io.StringIO()
    result = main(
        ["organization", "create", "--name", "Core"],
        client=ApiClient(transport=httpx.MockTransport(handler)),
        stdout=output,
    )

    assert result == 0
    assert "Core" in output.getvalue()


def test_organization_commands_support_budget_and_brand_color() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "org-1", "name": "Core"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "organization",
                "create",
                "--name",
                "Core",
                "--budget-monthly-cents",
                "500000",
                "--brand-color",
                "#3366ff",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "organization",
                "update",
                "org-1",
                "--budget-monthly-cents",
                "600000",
                "--brand-color",
                "#2244dd",
            ],
            client=client,
        )
        == 0
    )
    assert requests[0].read() == (
        b'{"name":"Core","budgetMonthlyCents":500000,"brandColor":"#3366ff"}'
    )
    assert requests[1].read() == (
        b'{"budgetMonthlyCents":600000,"brandColor":"#2244dd"}'
    )


def test_organization_commands_support_policy_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "org-1", "name": "Core"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "organization",
                "create",
                "--name",
                "Core",
                "--require-board-approval-for-new-agents",
                "--default-chat-issue-creation-mode",
                "manual",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "organization",
                "update",
                "org-1",
                "--no-require-board-approval-for-new-agents",
                "--default-chat-issue-creation-mode",
                "disabled",
            ],
            client=client,
        )
        == 0
    )

    assert requests[0].read() == (
        b'{"name":"Core","requireBoardApprovalForNewAgents":true,'
        b'"defaultChatIssueCreationMode":"manual"}'
    )
    assert requests[1].read() == (
        b'{"requireBoardApprovalForNewAgents":false,'
        b'"defaultChatIssueCreationMode":"disabled"}'
    )


def test_organization_resource_and_skill_commands_cover_step17_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "ok"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["organization", "resource-list", "--org-id", "org-1"], client=client) == 0
    assert main([
        "organization",
        "resource-create",
        "--org-id",
        "org-1",
        "--name",
        "Repo",
        "--kind",
        "url",
        "--locator",
        "https://example.test/repo",
        "--metadata",
        '{"owner":"team"}',
    ], client=client) == 0
    assert main([
        "organization",
        "resource-update",
        "--org-id",
        "org-1",
        "res-1",
        "--description",
        "Updated",
    ], client=client) == 0
    assert main(["organization", "resource-delete", "--org-id", "org-1", "res-1"], client=client) == 0
    assert main(["organization", "skill-list", "--org-id", "org-1"], client=client) == 0
    assert main(["organization", "skill-get", "--org-id", "org-1", "skill-1"], client=client) == 0
    assert main([
        "organization",
        "skill-create",
        "--org-id",
        "org-1",
        "--name",
        "Review",
        "--slug",
        "review",
    ], client=client) == 0
    assert main(["organization", "skill-file", "--org-id", "org-1", "skill-1", "--path", "SKILL.md"], client=client) == 0
    assert main([
        "organization",
        "skill-file-update",
        "--org-id",
        "org-1",
        "skill-1",
        "--path",
        "SKILL.md",
        "--content",
        "# Review",
    ], client=client) == 0
    assert main(["organization", "skill-update-status", "--org-id", "org-1", "skill-1"], client=client) == 0
    assert main(["organization", "skill-delete", "--org-id", "org-1", "skill-1"], client=client) == 0

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/resources",
        "/api/orgs/org-1/resources",
        "/api/orgs/org-1/resources/res-1",
        "/api/orgs/org-1/resources/res-1",
        "/api/orgs/org-1/skills",
        "/api/orgs/org-1/skills/skill-1",
        "/api/orgs/org-1/skills",
        "/api/orgs/org-1/skills/skill-1/files",
        "/api/orgs/org-1/skills/skill-1/files",
        "/api/orgs/org-1/skills/skill-1/update-status",
        "/api/orgs/org-1/skills/skill-1",
    ]
    assert requests[1].read() == (
        b'{"name":"Repo","kind":"url","locator":"https://example.test/repo",'
        b'"metadata":{"owner":"team"}}'
    )
    assert requests[8].read() == b'{"path":"SKILL.md","content":"# Review"}'
