from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from shadow_sdk import LLMRequestError

from shadow_travel.api.travel import _editable_map
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    AuditEvent,
    TravelAgentDraft,
    TravelMapPlace,
    TravelPlace,
)
from shadow_travel.integrations.llm import LLMGateway, LLMGatewayNotConfigured

router = APIRouter(prefix="/api/browser/v1", tags=["assistant"])


class RouteDraftRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2_000)
    mode: str = Field(default="walking", pattern=r"^(walking|driving|transit|bicycling)$")
    max_stops: int = Field(default=8, ge=2, le=16)


class RouteStopNote(BaseModel):
    place_id: str
    note: str = Field(max_length=1_000)


class RouteDraftResult(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    ordered_place_ids: list[str] = Field(min_length=2, max_length=16)
    summary: str = Field(default="", max_length=2_000)
    stop_notes: list[RouteStopNote] = Field(default_factory=list, max_length=16)


@router.post(
    "/travel-maps/{map_id}/assistant/route-drafts",
    status_code=status.HTTP_201_CREATED,
)
async def create_route_draft(
    map_id: str,
    body: RouteDraftRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with request.app.state.database.session_factory() as session:
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        links = session.scalars(
            select(TravelMapPlace)
            .where(TravelMapPlace.map_id == map_id)
            .order_by(TravelMapPlace.position)
        ).all()
        place_ids = [link.place_id for link in links]
        if len(place_ids) < 2:
            raise HTTPException(status_code=422, detail={"code": "route_requires_two_places"})
        places_by_id = {
            place.place_id: place
            for place in session.scalars(
                select(TravelPlace).where(TravelPlace.place_id.in_(place_ids))
            ).all()
        }
        map_context = {
            "map": {
                "title": travel_map.title,
                "city": travel_map.city,
                "country_code": travel_map.country_code,
                "period": travel_map.period,
            },
            "requested_goal": body.goal.strip(),
            "mode": body.mode,
            "max_stops": min(body.max_stops, len(place_ids)),
            "places": [
                {
                    "id": place.place_id,
                    "name": place.name,
                    "address": place.address,
                    "district": place.district,
                    "category": place.category,
                    "tags": place.tags,
                    "note": place.note,
                    "longitude": place.longitude,
                    "latitude": place.latitude,
                }
                for place_id in place_ids
                if (place := places_by_id.get(place_id)) is not None
            ],
        }

    gateway: LLMGateway = request.app.state.llm
    try:
        response = await gateway.client("reasoning-default").create(
            request_id=request.state.request_id,
            agent_id="travel-planner",
            instructions=(
                "你是 Shadow Travel 的路线草案助手。只使用输入中已有的地点 ID，"
                "根据地理位置、用户目标和出行方式排序；不要虚构营业时间、价格或交通信息。"
                "输出必须符合给定 JSON Schema，结果只是待用户确认的草案。"
            ),
            input=json.dumps(map_context, ensure_ascii=False, separators=(",", ":")),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "travel_route_draft",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "ordered_place_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": body.max_stops,
                            },
                            "summary": {"type": "string"},
                            "stop_notes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "place_id": {"type": "string"},
                                        "note": {"type": "string"},
                                    },
                                    "required": ["place_id", "note"],
                                },
                            },
                        },
                        "required": ["title", "ordered_place_ids", "summary", "stop_notes"],
                    },
                }
            },
        )
    except LLMGatewayNotConfigured as exc:
        raise HTTPException(status_code=503, detail={"code": "llm_unavailable"}) from exc
    except LLMRequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_request_failed", "kind": exc.kind},
        ) from exc

    try:
        result = RouteDraftResult.model_validate_json(_response_text(response))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_invalid_result"}) from exc
    if len(result.ordered_place_ids) != len(set(result.ordered_place_ids)):
        raise HTTPException(status_code=502, detail={"code": "llm_invalid_result"})
    if len(result.ordered_place_ids) > body.max_stops:
        raise HTTPException(status_code=502, detail={"code": "llm_invalid_result"})
    if not set(result.ordered_place_ids).issubset(set(place_ids)):
        raise HTTPException(status_code=502, detail={"code": "llm_invalid_result"})
    result.stop_notes = [
        note for note in result.stop_notes if note.place_id in result.ordered_place_ids
    ]
    payload = {
        **result.model_dump(),
        "mode": body.mode,
        "requested_goal": body.goal.strip(),
    }
    with request.app.state.database.session_factory() as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        linked_count = session.scalar(
            select(func.count()).select_from(TravelMapPlace).where(
                TravelMapPlace.map_id == map_id,
                TravelMapPlace.place_id.in_(result.ordered_place_ids),
            )
        )
        if linked_count != len(result.ordered_place_ids):
            raise HTTPException(status_code=409, detail={"code": "travel_map_changed"})
        draft = TravelAgentDraft(
            map_id=map_id,
            agent_id="travel-planner",
            created_by_user_id=user.shadow_user_id,
            draft_type="route",
            title=result.title,
            payload=payload,
            status="pending",
        )
        session.add(draft)
        session.flush()
        session.add(
            AuditEvent(
                actor_type="user",
                actor_id=user.shadow_user_id,
                owner_app="shadow-travel",
                action="travel.llm_route_draft.create",
                resource_type="travel_agent_draft",
                resource_id=draft.draft_id,
                request_id=request.state.request_id,
                result="success",
                details={"map_id": map_id, "model_alias": "reasoning-default"},
            )
        )
        return {
            "id": draft.draft_id,
            "map_id": map_id,
            "status": "pending",
            "draft_type": "route",
            "payload": payload,
            "direct_domain_write": False,
        }


def _response_text(response: dict[str, object]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
    raise ValueError("LLM response did not contain output text")
