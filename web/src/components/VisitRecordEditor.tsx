import { useState, type FormEvent } from "react";
import { request } from "../api";
import type { Visit } from "../types";
import { Modal } from "./Shared";

export function VisitRecordEditor({
  visit,
  onClose,
  onSaved,
}: {
  visit: Visit;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [note, setNote] = useState(visit.note || "");
  const [rating, setRating] = useState(String(visit.rating || ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [makePrivate, setMakePrivate] = useState(false);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await request(`api/browser/v1/visits/${visit.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          note,
          rating: rating ? Number(rating) : null,
          expected_version: visit.version,
          ...(makePrivate ? { record_visibility: "private" } : {}),
        }),
      });
      await onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={`补充个人记录 · ${visit.date}`}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="form-stack" onSubmit={save}>
        <p>编辑这一次到访的文字和评分，不创建新到访。默认保留原有共享范围。</p>
        {visit.recordVisibility === "shared" && (
          <label>
            <input
              type="checkbox"
              checked={makePrivate}
              onChange={(e) => setMakePrivate(e.target.checked)}
            />
            将这条记录和所属照片改为私密（原共享成员将无法查看）
          </label>
        )}
        <label>
          个人记录
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={10000}
            rows={5}
          />
        </label>
        <label>
          评分
          <select value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="">暂不评分</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n} 分
              </option>
            ))}
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="primary-button" disabled={busy}>
          {busy ? "保存中…" : "保存个人记录"}
        </button>
      </form>
    </Modal>
  );
}
