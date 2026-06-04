import { useState } from "react";
import { Link } from "react-router-dom";
import type { Goal } from "../api/types";
import { statusLabel } from "../utils/display";
import { Badge } from "./Badge";

interface GoalTreeProps {
  goals: Goal[];
  goalLink: (goal: Goal) => string;
}

function GoalNode({
  goal,
  goals,
  depth,
  goalLink,
}: {
  goal: Goal;
  goals: Goal[];
  depth: number;
  goalLink: (goal: Goal) => string;
}) {
  const [expanded, setExpanded] = useState(true);
  const children = goals.filter((item) => item.parentId === goal.id);
  const hasChildren = children.length > 0;
  return (
    <div>
      <Link className="goal-tree-row" style={{ paddingLeft: `${depth * 16 + 12}px` }} to={goalLink(goal)}>
        {hasChildren ? (
          <button
            className="goal-tree-toggle"
            onClick={(event) => {
              event.preventDefault();
              setExpanded(!expanded);
            }}
            type="button"
          >
            {expanded ? "v" : ">"}
          </button>
        ) : (
          <span className="goal-tree-toggle-placeholder" />
        )}
        <span className="goal-tree-level">{goal.level}</span>
        <strong>{goal.title}</strong>
        <Badge>{statusLabel(goal.status)}</Badge>
      </Link>
      {hasChildren && expanded && children.map((child) => (
        <GoalNode depth={depth + 1} goal={child} goalLink={goalLink} goals={goals} key={child.id} />
      ))}
    </div>
  );
}

export function GoalTree({ goals, goalLink }: GoalTreeProps) {
  const goalIds = new Set(goals.map((goal) => goal.id));
  const roots = goals.filter((goal) => !goal.parentId || !goalIds.has(goal.parentId));
  if (goals.length === 0) return <p className="muted">暂无目标。</p>;
  return (
    <div className="goal-tree">
      {roots.map((goal) => (
        <GoalNode depth={0} goal={goal} goalLink={goalLink} goals={goals} key={goal.id} />
      ))}
    </div>
  );
}
