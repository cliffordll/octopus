# Organization Navigation And Heartbeat UI Design

## Goal

Align the UI navigation hierarchy with the upstream layout while exposing only
organization capabilities already supported by the current server:

- Preserve top-level navigation for messages, agents, tasks, and organization.
- Move organization switching and organization management behind the avatar
  control.
- Add an organization-scoped secondary navigation for organization structure,
  projects, and heartbeat runs.
- Add an organization heartbeat page backed by the existing heartbeat run API.

## Scope

### Included

- Reshape the shell so the organization top-level entry enters the currently
  selected organization's workspace rather than the global management list.
- Keep `/organizations` for organization listing and creation, reachable from
  the avatar menu.
- Provide a route for current organization settings from the avatar menu, not
  from organization secondary navigation.
- Add organization secondary navigation items for:
  - organization structure
  - projects
  - heartbeat
- Add an organization structure view using existing agent list data and
  reporting relationships.
- Add an organization heartbeat view using existing run listing, run detail,
  and run event APIs.
- Preserve module-level tab navigation, including the agent detail tabs.

### Excluded

- Secondary navigation entries for resources, workspaces, goals, skills, or
  costs. These do not yet have a complete organization-level server and UI
  surface in the current delivery sequence.
- Secondary navigation for approvals. Existing approval routes remain
  available to existing workflows, but approvals are not part of the
  requested organization navigation hierarchy.
- Secondary navigation for organization settings. Settings belongs to the
  avatar management surface.
- New server contracts or schema changes.

## Information Architecture

### Primary Navigation

The primary navigation remains product-wide and contains:

- `消息` -> `/orgs/:orgId/chats`
- `智能体` -> `/orgs/:orgId/agents`
- `任务` -> `/orgs/:orgId/issues`
- `组织` -> `/orgs/:orgId/structure`

All entries are scoped to the currently selected organization. When no
organization exists, the entries remain unavailable until an organization is
created.

### Avatar Menu

The avatar menu is the only persistent management surface for organizations:

- show current organization identity
- switch to another organization while retaining the current primary area
  where meaningful
- `组织设置` -> `/orgs/:orgId/settings`
- `管理组织` -> `/organizations`

Navigating through the avatar menu closes the menu. Switching from an
organization secondary page defaults the target organization to the same
secondary area when supported.

### Organization Secondary Navigation

Organization workspace pages share a secondary navigation panel containing:

- `组织架构` -> `/orgs/:orgId/structure`
- `项目` -> `/orgs/:orgId/projects`
- `心跳` -> `/orgs/:orgId/heartbeat-runs`

The panel is shown only for these organization-focused pages. Primary modules
such as chats, agents, and tasks keep their own contextual secondary panels.
Approval pages remain functional without an organization menu entry.

### Tertiary Navigation

Tabs inside a resource remain tertiary navigation. Existing agent detail tabs
(`概览`, `配置`, `运行`) remain unchanged. The organization heartbeat view may
use local selection/details rather than adding another global navigation tier.

## Routes And Views

| Route | View | Navigation Source |
| --- | --- | --- |
| `/orgs/:orgId` | Redirect to organization structure | legacy compatibility |
| `/orgs/:orgId/structure` | Organization structure | primary organization entry and secondary nav |
| `/orgs/:orgId/projects` | Existing project list/detail surface | secondary nav |
| `/orgs/:orgId/heartbeat-runs` | New organization heartbeat page | secondary nav |
| `/orgs/:orgId/settings` | Existing organization edit form | avatar menu |
| `/organizations` | Existing organization list/create view | avatar menu |

Existing project detail routes stay within the project secondary-navigation
context. Existing approval routes remain reachable from their current
workflows and are not renamed as part of this change.

## Components And Data Flow

### Shell

`AppShell` continues to own the active organization identity and avatar menu.
It updates the primary organization link to the organization structure route
and adds a current organization settings link in the avatar menu. The global
organization management link is removed from primary navigation.

### Organization Workspace

The existing organization workspace wrapper becomes the reusable secondary
navigation layout for structure, projects, and heartbeat pages. Project pages
are wrapped by it rather than defining their own unrelated navigation.
Organization settings uses organization data but is entered from the avatar
surface and does not advertise itself in the secondary menu.

### Organization Structure

The structure view fetches `GET /api/orgs/{orgId}/agents`. It presents the
organization's current agents and available `reportsTo` relationship in a
structure-oriented list. Empty organizations show an empty state and an
existing path to create the first agent. No organization-chart backend or new
relationship semantics are introduced.

### Organization Heartbeat

The heartbeat view uses:

- `GET /api/orgs/{orgId}/heartbeat-runs` for organization runs
- existing agent listing to label each run with the agent name
- `GET /api/heartbeat-runs/{runId}` for selected run detail
- `GET /api/heartbeat-runs/{runId}/events` for selected run events

The list can filter by an existing agent query parameter when an agent is
selected. A selected run shows its status, invocation source, error where
present, and chronological events. An empty result presents a neutral empty
state.

The UI does not add scheduling, cancellation, cost totals, or workspace
controls because those organization-level capabilities are not currently
implemented.

## Error And Empty States

- Query failures use the existing `ErrorNotice` presentation.
- Organization structure displays an empty-state prompt when no agents exist.
- Heartbeat displays an empty-state message when there are no runs for the
  current filter.
- A run detail panel is shown only after a list item is selected; selecting a
  different agent clears a run that no longer belongs to the filtered list.

## Testing

UI tests cover:

- primary navigation keeps messages, agents, tasks, and organization, with
  organization pointing at `/orgs/:orgId/structure`
- avatar menu exposes organization switching, organization settings, and
  organization management
- organization secondary navigation contains only structure, projects, and
  heartbeat
- structure page renders agent relationship information and empty state
- heartbeat page requests organization runs, supports agent filtering, and
  loads selected run details/events
- approvals and settings do not appear as organization secondary items

Verification after implementation follows the repository and UI requirements:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `uv run pyright .`
- `npm test` in `ui/`
- `npm run typecheck` in `ui/`
- `npm run build` in `ui/`
