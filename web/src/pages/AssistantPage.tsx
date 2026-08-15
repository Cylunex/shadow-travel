import {
  ArrowRight,
  Check,
  ChevronRight,
  Clock3,
  MapPin,
  MessageCircle,
  Route,
  Send,
  ShieldCheck,
  Sparkles,
  Utensils
} from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Toast } from "../components/Shared";
import { useTravel } from "../state/TravelContext";

const suggestions = [
  "北京年票里还有哪些公园没去？",
  "把贵阳美食按一天步行路线排一下",
  "找出同行人都想去的地方"
];

export function AssistantPage() {
  const { maps, places } = useTravel();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [answered, setAnswered] = useState(false);
  const [approved, setApproved] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setAnswered(true);
    setApproved(false);
  }

  const parkMap = maps.find((map) => map.id === "beijing-parks");
  const unvisited = places.filter(
    (place) => place.mapIds.includes("beijing-parks") && !place.visitedBy.includes("me")
  );

  return (
    <div className="content-page assistant-page">
      <header className="assistant-hero">
        <span className="assistant-orb"><Sparkles size={24} /></span>
        <div>
          <span className="eyebrow">TRAVEL ASSISTANT</span>
          <h1>从你的地图出发，不替你做决定</h1>
          <p>整理点位、比较同行意愿、生成路线草案；涉及写入时，都会先让你确认。</p>
        </div>
      </header>

      <section className="assistant-workspace">
        <div className="assistant-conversation">
          {!answered ? (
            <div className="assistant-welcome">
              <MessageCircle size={30} />
              <h2>有什么想整理的？</h2>
              <p>助手只会读取你有权访问的旅行内容。演示模式不会把问题或地图内容发送给模型。</p>
              <div className="suggestion-grid">
                {suggestions.map((suggestion, index) => (
                  <button key={suggestion} type="button" onClick={() => setQuery(suggestion)}>
                    {index === 0 ? <MapPin size={18} /> : index === 1 ? <Utensils size={18} /> : <Route size={18} />}
                    <span>{suggestion}</span><ChevronRight size={16} />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="assistant-result">
              <div className="user-message">{query}</div>
              <article className="assistant-answer">
                <div className="assistant-answer-heading"><span><Sparkles size={17} /></span><strong>整理好了</strong></div>
                <p>{parkMap?.title ?? "北京公园年票"}里还有 {unvisited.length} 个地点没去。我按“市区优先、同一区域尽量放在一起”的方式整理成了一个建议。</p>
                <div className="assistant-place-list">
                  {unvisited.slice(0, 4).map((place, index) => (
                    <button key={place.id} type="button" onClick={() => navigate(`/places/${place.id}`)}>
                      <span>{index + 1}</span><div><strong>{place.name}</strong><small>{place.district} · {place.category}</small></div><ArrowRight size={16} />
                    </button>
                  ))}
                </div>
                <div className="assistant-sources">
                  <strong>依据</strong>
                  <span>{parkMap?.pointIds.length ?? 0} 个地图点位</span>
                  <span>我的到访记录</span>
                  <span>地点所在区</span>
                </div>
              </article>

              <article className="agent-draft-card">
                <header><div><span className="eyebrow">ACTION DRAFT</span><h2>建立“下一次公园散步”清单</h2></div><ShieldCheck size={22} /></header>
                <ul>
                  <li><Check size={16} /> 使用现有地点，不新建重复点位</li>
                  <li><Check size={16} /> 仅对当前账户创建个人草案</li>
                  <li><Clock3 size={16} /> 不确定真实交通耗时，暂不写入</li>
                </ul>
                <div className="draft-actions"><button className="secondary-button" type="button" onClick={() => setAnswered(false)}>放弃</button><button className="primary-button" type="button" onClick={() => setApproved(true)}>确认创建草案</button></div>
              </article>
            </div>
          )}

          <form className="assistant-composer" onSubmit={submit}>
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="问问你的旅行地图……" rows={2} aria-label="向旅行助手提问" />
            <div><span><ShieldCheck size={14} /> 写操作需确认</span><button type="submit" aria-label="发送"><Send size={18} /></button></div>
          </form>
        </div>

        <aside className="assistant-context">
          <span className="eyebrow">CURRENT CONTEXT</span>
          <h2>本次可用信息</h2>
          <div className="context-stat"><strong>{maps.length}</strong><span>张可访问地图</span></div>
          <div className="context-stat"><strong>{places.length}</strong><span>个地点</span></div>
          <div className="context-stat"><strong>{places.filter((place) => place.visitedBy.includes("me")).length}</strong><span>个已到访地点</span></div>
          <div className="context-boundary"><ShieldCheck size={18} /><p>不读取其他用户地图；统计只上报模型、Token、延迟和状态，不上传旅行内容。</p></div>
        </aside>
      </section>
      {approved && <Toast>草案已创建；演示模式下不会持久保存</Toast>}
    </div>
  );
}
