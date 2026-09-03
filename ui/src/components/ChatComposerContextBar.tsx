import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";

interface ComposerSkill {
  active?: boolean;
  label: string;
}

export function ChatComposerContextBar({
  agentControl,
  issueCreationModeControl,
  locked = false,
  planMode,
  projectControl,
  skills,
  skillsEmptyText,
  submitAriaLabel,
  submitDisabled,
  submitLabel,
}: {
  agentControl: ReactNode;
  issueCreationModeControl: ReactNode;
  locked?: boolean;
  planMode: {
    checked: boolean;
    disabled?: boolean;
    onChange: (checked: boolean) => void;
  };
  projectControl: ReactNode;
  skills: ComposerSkill[];
  skillsEmptyText: string;
  submitAriaLabel?: string;
  submitDisabled: boolean;
  submitLabel: string;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const helpRef = useRef<HTMLDetailsElement | null>(null);
  const skillsRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    if (!skillsOpen) return;
    function closeWhenOutside(event: Event) {
      if (event.target instanceof Node && !skillsRef.current?.contains(event.target)) setSkillsOpen(false);
    }
    document.addEventListener("pointerdown", closeWhenOutside);
    document.addEventListener("focusin", closeWhenOutside);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("focusin", closeWhenOutside);
    };
  }, [skillsOpen]);

  useEffect(() => {
    if (!helpOpen) return;
    function closeWhenOutside(event: Event) {
      if (event.target instanceof Node && !helpRef.current?.contains(event.target)) setHelpOpen(false);
    }
    document.addEventListener("pointerdown", closeWhenOutside);
    document.addEventListener("focusin", closeWhenOutside);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("focusin", closeWhenOutside);
    };
  }, [helpOpen]);

  return (
    <div
      aria-label={locked ? "当前对话上下文" : "对话上下文设置"}
      className={`chat-context-bar${locked ? " chat-context-bar-locked" : ""}`}
    >
      <ContextSlot label="项目" locked={locked}>{projectControl}</ContextSlot>
      <ContextSlot label="Agent" locked={locked}>{agentControl}</ContextSlot>
      <ContextSlot label="审批" locked={locked}>{issueCreationModeControl}</ContextSlot>
      <label className="chat-plan-mode-toggle" title="先制定执行计划，再开始执行">
        <input
          aria-label="计划模式"
          checked={planMode.checked}
          disabled={planMode.disabled}
          onChange={(event: ChangeEvent<HTMLInputElement>) => planMode.onChange(event.target.checked)}
          type="checkbox"
        />
        计划模式
      </label>
      <details
        className="chat-skill-dropdown"
        onToggle={(event) => setSkillsOpen(event.currentTarget.open)}
        open={skillsOpen}
        ref={skillsRef}
      >
        <summary aria-label={`技能列表，${skills.length} 项`}>
          技能{skills.length > 0 && <strong>{skills.length}</strong>}
        </summary>
        <div className="chat-skill-list">
          {skills.map((skill, index) => (
            <span className={`chat-skill-chip${skill.active ? " active" : ""}`} key={`${skill.label}-${index}`}>
              {skill.label}
            </span>
          ))}
          {skills.length === 0 && <span className="muted">{skillsEmptyText}</span>}
        </div>
      </details>
      <details
        className="chat-context-help"
        onToggle={(event) => setHelpOpen(event.currentTarget.open)}
        open={helpOpen}
        ref={helpRef}
      >
        <summary aria-label="任务创建规则" title="任务创建规则">帮助</summary>
        <div>
          <p>计划模式默认关闭；打开后，任务建议会先停留在规划和修改方案阶段，不会自动创建任务。</p>
          <p>任务创建模式由对话设置决定；智能体只提交任务建议，不能在回复里自行切换自动创建。</p>
        </div>
      </details>
      <button aria-label={submitAriaLabel} className="chat-create-submit" disabled={submitDisabled} type="submit">{submitLabel}</button>
    </div>
  );
}

function ContextSlot({ children, label, locked }: { children: ReactNode; label: string; locked: boolean }) {
  return (
    <div className="chat-context-slot">
      <span>{label}</span>
      {children}
      {locked && (
        <svg aria-label={`${label}已锁定`} className="chat-context-lock" fill="none" role="img" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 16 16">
          <rect height="7" rx="1.5" width="10" x="3" y="7" />
          <path d="M5 7V5a3 3 0 0 1 6 0v2" />
        </svg>
      )}
    </div>
  );
}
