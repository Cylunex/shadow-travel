import { Check, X } from "lucide-react";
import { ReactNode } from "react";

import { Member } from "../types";

export function AvatarStack({ members, label }: { members: Member[]; label?: string }) {
  return (
    <span className="avatar-stack-wrap" title={members.map((member) => member.name).join("、")}>
      <span className="avatar-stack">
        {members.slice(0, 4).map((member) => (
          <span key={member.id} style={{ background: member.color }}>
            {member.initials}
          </span>
        ))}
      </span>
      {label && <small>{label}</small>}
    </span>
  );
}

export function ProgressRing({ value, label }: { value: number; label: string }) {
  return (
    <span className="progress-ring-wrap">
      <span className="progress-ring" style={{ "--progress": `${value * 3.6}deg` } as React.CSSProperties}>
        <strong>{value}%</strong>
      </span>
      <small>{label}</small>
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}

export function Modal({
  title,
  children,
  onClose
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span className="eyebrow">SHADOW TRAVEL</span>
            <h2 id="modal-title">{title}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭">
            <X size={21} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

export function Toast({ children }: { children: ReactNode }) {
  return (
    <div className="toast" role="status">
      <Check size={17} />
      {children}
    </div>
  );
}
