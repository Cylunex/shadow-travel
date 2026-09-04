import { useState } from "react";
import { api, type PlanState, type PlanDocument } from "./lifecycle";
import { stableClientId } from "../offline";
import { orderedStops } from "./planTime";
export function PlanV2Panel({
  plan,
  draft,
  editing,
  dirty,
  onChange,
}: {
  plan: PlanState;
  draft: PlanDocument;
  editing: boolean;
  dirty: boolean;
  onChange: (doc: PlanDocument) => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (draft.schema_version === 1)
    return (
      <div className="lifecycle-hint">
        <p>
          旧版计划可继续使用。升级后按独立路段编辑交通时间，并支持每站时区；旧确认版本不会变化。
        </p>
        <button
          className="secondary-button"
          disabled={!editing || dirty || busy || !plan.revision}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const result = await api<{ document: PlanDocument }>(
                `trips/${plan.trip.id}/plan/upgrade-preview`,
                "POST",
                { base_revision: plan.revision },
              );
              onChange(result.document);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          预览升级到 Plan v2 草稿
        </button>
        {error && <p role="alert">{error}</p>}
      </div>
    );
  const stops = orderedStops(draft.stops, draft.timezone || plan.trip.timezone);
  return (
    <details className="plan-v2">
      <summary>Plan v2 · 时区与独立路段</summary>
      <details>
        <summary>候选偏好与备选分组</summary>
        {draft.candidates.map((id) => {
          const meta = draft.candidate_metadata?.[id] || {
            priority: "normal" as const,
            reason: "",
            duration_minutes: 60,
            alternate_group: null,
          };
          const update = (patch: Partial<typeof meta>) =>
            onChange({
              ...draft,
              candidate_metadata: {
                ...draft.candidate_metadata,
                [id]: { ...meta, ...patch },
              },
            });
          return (
            <fieldset key={id} disabled={!editing}>
              <legend>
                {plan.places.find((p) => p.id === id)?.name || id}
              </legend>
              <label>
                优先级
                <select
                  value={meta.priority}
                  onChange={(e) =>
                    update({ priority: e.target.value as typeof meta.priority })
                  }
                >
                  <option value="optional">可选</option>
                  <option value="normal">普通</option>
                  <option value="must">优先保留</option>
                </select>
              </label>
              <label>
                收藏理由
                <input
                  maxLength={2000}
                  value={meta.reason}
                  onChange={(e) => update({ reason: e.target.value })}
                />
              </label>
              <label>
                预估停留分钟
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={meta.duration_minutes}
                  onChange={(e) =>
                    update({ duration_minutes: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                互为备选（同组名称）
                <input
                  maxLength={80}
                  value={meta.alternate_group || ""}
                  onChange={(e) =>
                    update({ alternate_group: e.target.value || null })
                  }
                />
              </label>
            </fieldset>
          );
        })}
      </details>
      <p>
        交通属于两次停留之间的路段。重排后旧路段会移除，未核验不等于 0 分钟。
      </p>
      {(draft.migration_notes || []).map((note, i) => (
        <p className="lifecycle-alert" key={i}>
          {note}
        </p>
      ))}
      {stops.map((s, i) => {
        const next = stops[i + 1],
          segment = draft.segments?.find(
            (seg) => seg.from_stop_id === s.id && seg.to_stop_id === next?.id,
          );
        const update = (
          patch: Partial<NonNullable<PlanDocument["segments"]>[number]>,
        ) => {
          if (!next) return;
          const value = {
            id: segment?.id || stableClientId("segment"),
            from_stop_id: s.id,
            to_stop_id: next.id,
            mode: s.mode,
            manual_minutes: null,
            note: "",
            ...segment,
            ...patch,
          };
          onChange({
            ...draft,
            segments: [
              ...(draft.segments || []).filter((seg) => seg.id !== segment?.id),
              value,
            ],
          });
        };
        return (
          <div className="form-stack" key={s.id}>
            <strong>
              {s.day} {s.start} ·{" "}
              {plan.places.find((p) => p.id === s.place_id)?.name || s.id}
            </strong>
            <label>
              当地时区
              <input
                disabled={!editing}
                value={s.timezone || ""}
                placeholder={draft.timezone || plan.trip.timezone}
                onChange={(e) =>
                  onChange({
                    ...draft,
                    stops: draft.stops.map((row) =>
                      row.id === s.id
                        ? { ...row, timezone: e.target.value || null }
                        : row,
                    ),
                  })
                }
              />
            </label>
            <label>
              夏令时重复时刻
              <select
                disabled={!editing}
                value={s.fold ?? ""}
                onChange={(e) =>
                  onChange({
                    ...draft,
                    stops: draft.stops.map((row) =>
                      row.id === s.id
                        ? {
                            ...row,
                            fold:
                              e.target.value === ""
                                ? null
                                : (Number(e.target.value) as 0 | 1),
                          }
                        : row,
                    ),
                  })
                }
              >
                <option value="">通常时间 / 待消歧</option>
                <option value="0">首次出现</option>
                <option value="1">第二次出现</option>
              </select>
            </label>
            {next && (
              <fieldset disabled={!editing}>
                <legend>
                  此站 → {next.day} {next.start}
                </legend>
                <label>
                  方式
                  <select
                    value={segment?.mode || s.mode}
                    onChange={(e) =>
                      update({ mode: e.target.value as typeof s.mode })
                    }
                  >
                    <option value="walking">步行</option>
                    <option value="transit">公交</option>
                    <option value="driving">驾车</option>
                    <option value="bicycling">骑行</option>
                  </select>
                </label>
                <label>
                  我自己的交通估计（分钟）
                  <input
                    type="number"
                    min="0"
                    max="2880"
                    value={segment?.manual_minutes ?? ""}
                    placeholder="未核验"
                    onChange={(e) =>
                      update({
                        manual_minutes:
                          e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  />
                </label>
              </fieldset>
            )}
          </div>
        );
      })}
    </details>
  );
}
