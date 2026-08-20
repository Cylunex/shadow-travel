import { CalendarDays, Check, LockKeyhole, Users } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import { Visit } from "../types";
import { Modal } from "./Shared";

type VisitDraft = { visitedOn: string; note: string; rating: string };

export function VisitDialog({
  placeName,
  visits,
  onClose,
  onSave,
  onReuse
}: {
  placeName: string;
  visits: Visit[];
  onClose: () => void;
  onSave: (draft: { visitedOn: string; note?: string; rating?: number }) => Promise<void>;
  onReuse?: (visit: Visit) => void;
}) {
  const [draft, setDraft] = useState<VisitDraft>({
    visitedOn: new Date().toISOString().slice(0, 10),
    note: "",
    rating: ""
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const existing = useMemo(
    () => visits.find((visit) => visit.date === draft.visitedOn),
    [draft.visitedOn, visits]
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (existing) return;
    setSaving(true);
    setError(undefined);
    try {
      await onSave({
        visitedOn: draft.visitedOn,
        note: draft.note.trim() || undefined,
        rating: draft.rating ? Number(draft.rating) : undefined
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存到访失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`标记去过 · ${placeName}`} onClose={onClose}>
      <form className="form-stack visit-dialog" onSubmit={submit}>
        <label>
          <span><CalendarDays size={15} /> 到访日期</span>
          <input type="date" value={draft.visitedOn} onChange={(event) => setDraft({ ...draft, visitedOn: event.target.value })} required />
        </label>
        {existing && (
          <div className="duplicate-visit-note">
            <Check size={18} />
            <div><strong>这一天已有到访记录</strong><span>建议复用已有记录，避免同一天重复创建。</span></div>
            {onReuse && <button className="secondary-button" type="button" onClick={() => onReuse(existing)}>查看已有记录</button>}
          </div>
        )}
        <div className="optional-fields">
          <label>简短记录 <small>可选</small><textarea rows={3} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} placeholder="可以稍后再补" /></label>
          <label>评分 <small>可选</small><select value={draft.rating} onChange={(event) => setDraft({ ...draft, rating: event.target.value })}><option value="">暂不评分</option>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 分</option>)}</select></label>
        </div>
        <div className="visit-privacy-note">
          <Users size={17} />
          <p><strong>完成状态会与当前主题同行共享</strong><span><LockKeyhole size={13} /> 照片、评分和个人记录默认仍然私密。</span></p>
        </div>
        {error && <div className="map-search-error">{error}</div>}
        <div className="form-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" type="submit" disabled={saving || Boolean(existing)}>{saving ? "保存中…" : "确认去过"}</button>
        </div>
      </form>
    </Modal>
  );
}
