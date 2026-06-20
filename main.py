"""
NMNDL 물품 구매 승인 봇 (모달 폼 버전)

워크플로우:
  1. 구성원이 /물품주문 입력 → 모달 폼 표시
  2. 모달 제출 → 랩장에게 DM으로 승인/거절 버튼 전송
  3-A. 승인 → 랩장 DM 확인 메시지 + 채널에 원문 게시 (수정/삭제 버튼 포함)
  3-B. 거절 → 모달 팝업으로 사유 입력 → 주문자 DM으로 사유 전달

권한 제어:
  수정: 주문자 본인만 가능
  삭제: 주문자 본인 또는 랩장
"""

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

LAB_MANAGER_ID = os.environ.get("LAB_MANAGER_ID", "")
ORDER_CHANNEL  = os.environ.get("CHANNEL_ID", "")


# ── 상수 ──────────────────────────────────────────────────────────────────────

ORDER_LOCATIONS = ["83709A", "36719", "36721", "36817", "25421"]

USAGE_OPTIONS = [
    {"text": {"type": "plain_text", "text": "개인연구용"}, "value": "개인연구용"},
    {"text": {"type": "plain_text", "text": "과제연구용"}, "value": "과제연구용"},
    {"text": {"type": "plain_text", "text": "공용"},       "value": "공용"},
]

COMPANY_OPTIONS = [
    {"text": {"type": "plain_text", "text": "그린텍"},     "value": "그린텍"},
    {"text": {"type": "plain_text", "text": "성호씨그마"}, "value": "성호씨그마"},
    {"text": {"type": "plain_text", "text": "(주)웰코스"}, "value": "(주)웰코스"},
    {"text": {"type": "plain_text", "text": "극동유류"},   "value": "극동유류"},
    {"text": {"type": "plain_text", "text": "드림디포"},   "value": "드림디포"},
    {"text": {"type": "plain_text", "text": "직접입력"},   "value": "직접입력"},
]

UNIT_OPTIONS = [
    {"text": {"type": "plain_text", "text": "EA"}, "value": "EA"},
    {"text": {"type": "plain_text", "text": "PK"}, "value": "PK"},
    {"text": {"type": "plain_text", "text": "CS"}, "value": "CS"},
    {"text": {"type": "plain_text", "text": "BX"}, "value": "BX"},
]


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def get_dm_channel(client, user_id: str) -> str:
    resp = client.conversations_open(users=user_id)
    return resp["channel"]["id"]


# ── 모달 빌드 ─────────────────────────────────────────────────────────────────

def build_order_modal(callback_id: str, *, company: str = "",
                      initial: dict | None = None,
                      private_metadata: str = "") -> dict:
    initial = initial or {}
    blocks = []

    # ① 물품용도 (라디오)
    radio_el = {"type": "radio_buttons", "action_id": "usage_input",
                "options": USAGE_OPTIONS}
    if initial.get("usage"):
        match = next((o for o in USAGE_OPTIONS if o["value"] == initial["usage"]), None)
        if match:
            radio_el["initial_option"] = match
    blocks.append({
        "type": "input", "block_id": "usage_block",
        "label": {"type": "plain_text", "text": "물품용도"},
        "element": radio_el,
    })

    # ② 주문장소 (드롭다운)
    loc_opts = [{"text": {"type": "plain_text", "text": v}, "value": v}
                for v in ORDER_LOCATIONS]
    loc_el = {"type": "static_select", "action_id": "location_input",
              "options": loc_opts,
              "placeholder": {"type": "plain_text", "text": "주문 장소 선택"}}
    if initial.get("location"):
        loc_el["initial_option"] = {
            "text": {"type": "plain_text", "text": initial["location"]},
            "value": initial["location"]}
    blocks.append({
        "type": "input", "block_id": "location_block",
        "label": {"type": "plain_text", "text": "주문장소"},
        "element": loc_el,
    })

    # ③ 물품명
    name_el = {"type": "plain_text_input", "action_id": "name_input",
               "placeholder": {"type": "plain_text", "text": "물품명을 입력해주세요"}}
    if initial.get("name"):
        name_el["initial_value"] = initial["name"]
    blocks.append({
        "type": "input", "block_id": "name_block",
        "label": {"type": "plain_text", "text": "물품명"},
        "hint": {"type": "plain_text",
                 "text": "Gmarket 물품의 경우 옵션까지 상세히 기입해주세요"},
        "element": name_el,
    })

    # ④ 거래처 (드롭다운 + dispatch_action)
    company_el = {"type": "static_select", "action_id": "company_input",
                  "options": COMPANY_OPTIONS,
                  "placeholder": {"type": "plain_text", "text": "거래처 선택"}}
    selected_company = company or initial.get("company", "")
    if selected_company and any(o["value"] == selected_company for o in COMPANY_OPTIONS):
        company_el["initial_option"] = {
            "text": {"type": "plain_text", "text": selected_company},
            "value": selected_company}
    blocks.append({
        "type": "input", "block_id": "company_block",
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "거래처"},
        "element": company_el,
    })

    # ④-1 거래처 직접입력 (조건부 표시)
    if selected_company == "직접입력":
        custom_el = {"type": "plain_text_input", "action_id": "company_custom_input",
                     "placeholder": {"type": "plain_text", "text": "거래처명을 입력해주세요"}}
        if initial.get("company_custom"):
            custom_el["initial_value"] = initial["company_custom"]
        blocks.append({
            "type": "input", "block_id": "company_custom_block",
            "label": {"type": "plain_text", "text": "거래처 직접입력"},
            "element": custom_el,
        })

    # ⑤ CAS/CAT No. (선택)
    cas_el = {"type": "plain_text_input", "action_id": "cas_cat_input",
              "placeholder": {"type": "plain_text", "text": "예: SL.Sti4024"}}
    if initial.get("cas_cat"):
        cas_el["initial_value"] = initial["cas_cat"]
    blocks.append({
        "type": "input", "block_id": "cas_cat_block",
        "optional": True,
        "label": {"type": "plain_text", "text": "CAS/CAT No."},
        "element": cas_el,
    })

    # ⑥ 용량 및 규격
    spec_el = {"type": "plain_text_input", "action_id": "spec_input",
               "placeholder": {"type": "plain_text", "text": "예: 150/bx"}}
    if initial.get("spec"):
        spec_el["initial_value"] = initial["spec"]
    blocks.append({
        "type": "input", "block_id": "spec_block",
        "label": {"type": "plain_text", "text": "용량 및 규격"},
        "element": spec_el,
    })

    # ⑦ 수량
    qty_el = {"type": "plain_text_input", "action_id": "quantity_input",
              "placeholder": {"type": "plain_text", "text": "숫자만 표기해주세요"}}
    if initial.get("quantity"):
        qty_el["initial_value"] = initial["quantity"]
    blocks.append({
        "type": "input", "block_id": "quantity_block",
        "label": {"type": "plain_text", "text": "수량"},
        "element": qty_el,
    })

    # ⑧ 단위 (드롭다운)
    unit_el = {"type": "static_select", "action_id": "unit_input",
               "options": UNIT_OPTIONS,
               "placeholder": {"type": "plain_text", "text": "단위 선택"}}
    if initial.get("unit"):
        match = next((o for o in UNIT_OPTIONS if o["value"] == initial["unit"]), None)
        if match:
            unit_el["initial_option"] = match
    blocks.append({
        "type": "input", "block_id": "unit_block",
        "label": {"type": "plain_text", "text": "단위"},
        "element": unit_el,
    })

    # ⑨ 가격
    price_el = {"type": "plain_text_input", "action_id": "price_input",
                "placeholder": {"type": "plain_text", "text": "숫자만 표기해주세요"}}
    if initial.get("price"):
        price_el["initial_value"] = initial["price"]
    blocks.append({
        "type": "input", "block_id": "price_block",
        "label": {"type": "plain_text", "text": "가격"},
        "hint": {"type": "plain_text", "text": "가격은 단가로 기입해주세요"},
        "element": price_el,
    })

    # ⑩ URL
    url_el = {"type": "plain_text_input", "action_id": "url_input",
              "placeholder": {"type": "plain_text", "text": "URL을 입력해주세요"}}
    if initial.get("url"):
        url_el["initial_value"] = initial["url"]
    blocks.append({
        "type": "input", "block_id": "url_block",
        "label": {"type": "plain_text", "text": "URL"},
        "hint": {"type": "plain_text",
                 "text": "URL이 없는 경우 '없음'이라고 표기해주세요"},
        "element": url_el,
    })

    # ⑪ 구매 목적
    purpose_el = {"type": "plain_text_input", "action_id": "purpose_input",
                  "multiline": True,
                  "placeholder": {"type": "plain_text", "text": "구매 목적을 입력해주세요"}}
    if initial.get("purpose"):
        purpose_el["initial_value"] = initial["purpose"]
    blocks.append({
        "type": "input", "block_id": "purpose_block",
        "label": {"type": "plain_text", "text": "구매 목적"},
        "element": purpose_el,
    })

    title = "물품 구매 요청" if callback_id == "order_request_modal" else "주문 내용 수정"
    submit = "요청" if callback_id == "order_request_modal" else "수정"
    modal = {
        "type": "modal", "callback_id": callback_id,
        "title": {"type": "plain_text", "text": title},
        "submit": {"type": "plain_text", "text": submit},
        "close": {"type": "plain_text", "text": "취소"},
        "blocks": blocks,
    }
    if private_metadata:
        modal["private_metadata"] = private_metadata
    return modal


# ── 모달 상태 보존 ────────────────────────────────────────────────────────────

def _extract_current_values(state: dict) -> dict:
    data = {}

    usage = state.get("usage_block", {}).get("usage_input", {})
    if usage.get("selected_option"):
        data["usage"] = usage["selected_option"]["value"]

    loc = state.get("location_block", {}).get("location_input", {})
    if loc.get("selected_option"):
        data["location"] = loc["selected_option"]["value"]

    for key in ("name", "cas_cat", "spec", "quantity", "price", "url", "purpose"):
        block = state.get(f"{key}_block", {}).get(f"{key}_input", {})
        if block.get("value"):
            data[key] = block["value"].strip()

    company = state.get("company_block", {}).get("company_input", {})
    if company.get("selected_option"):
        data["company"] = company["selected_option"]["value"]

    custom = state.get("company_custom_block", {}).get("company_custom_input", {})
    if custom and custom.get("value"):
        data["company_custom"] = custom["value"].strip()

    unit = state.get("unit_block", {}).get("unit_input", {})
    if unit.get("selected_option"):
        data["unit"] = unit["selected_option"]["value"]

    return data


# ── 데이터 추출 ───────────────────────────────────────────────────────────────

def extract_order_fields(view) -> dict:
    values = view["state"]["values"]
    data = {}

    usage = values.get("usage_block", {}).get("usage_input", {})
    data["usage"] = (usage.get("selected_option") or {}).get("value", "")

    loc = values.get("location_block", {}).get("location_input", {})
    data["location"] = (loc.get("selected_option") or {}).get("value", "")

    name = values.get("name_block", {}).get("name_input", {})
    data["name"] = (name.get("value") or "").strip()

    company = values.get("company_block", {}).get("company_input", {})
    data["company"] = (company.get("selected_option") or {}).get("value", "")

    custom = values.get("company_custom_block", {}).get("company_custom_input", {})
    data["company_custom"] = (custom.get("value") or "").strip() if custom else ""

    cas = values.get("cas_cat_block", {}).get("cas_cat_input", {})
    data["cas_cat"] = (cas.get("value") or "").strip()

    spec = values.get("spec_block", {}).get("spec_input", {})
    data["spec"] = (spec.get("value") or "").strip()

    qty = values.get("quantity_block", {}).get("quantity_input", {})
    data["quantity"] = (qty.get("value") or "").strip()

    unit = values.get("unit_block", {}).get("unit_input", {})
    data["unit"] = (unit.get("selected_option") or {}).get("value", "")

    price = values.get("price_block", {}).get("price_input", {})
    data["price"] = (price.get("value") or "").strip()

    url = values.get("url_block", {}).get("url_input", {})
    data["url"] = (url.get("value") or "").strip()

    purpose = values.get("purpose_block", {}).get("purpose_input", {})
    data["purpose"] = (purpose.get("value") or "").strip()

    return data


# ── 메시지 포맷터 ─────────────────────────────────────────────────────────────

def _resolve_company(data: dict) -> str:
    if data.get("company") == "직접입력" and data.get("company_custom"):
        return data["company_custom"]
    return data.get("company", "")


def format_order_message(requester_id: str, data: dict,
                         edited: bool = False) -> str:
    company = _resolve_company(data)
    lines = [
        "[물품등록]",
        f"물품용도: {data.get('usage', '')}",
        f"주문장소: {data.get('location', '')}",
        f"물품명: {data.get('name', '')}",
        f"거래처: {company}",
    ]
    if data.get("cas_cat"):
        lines.append(f"CAS/CAT No.: {data['cas_cat']}")
    lines.append(f"용량 및 규격: {data.get('spec', '')}")
    lines.append(f"수량: {data.get('quantity', '')} {data.get('unit', '')}")
    lines.append(f"가격: {data.get('price', '')}원")
    if data.get("url"):
        lines.append(f"URL: {data['url']}")
    if data.get("purpose"):
        lines.append(f"구매 목적: {data['purpose']}")
    lines.append(f"주문자: <@{requester_id}>")
    if edited:
        lines.append("_(수정됨)_")
    return "\n".join(lines)


def order_channel_blocks(requester_id: str, data: dict,
                         edited: bool = False) -> list:
    payload = json.dumps({"requester_id": requester_id, "data": data},
                         ensure_ascii=False)
    return [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": format_order_message(requester_id, data, edited)}},
        {"type": "actions",
         "elements": [
             {"type": "button",
              "text": {"type": "plain_text", "text": "내용 수정 (주문자 전용)"},
              "action_id": "edit_order",
              "value": payload},
             {"type": "button",
              "text": {"type": "plain_text", "text": "요청 삭제"},
              "style": "danger",
              "action_id": "delete_order",
              "value": payload}]}]


# ── /물품주문 커맨드 ───────────────────────────────────────────────────────────

@app.command("/물품주문")
def handle_order_command(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_order_modal("order_request_modal"),
    )


# ── 거래처 변경 시 모달 동적 갱신 ─────────────────────────────────────────────

@app.action("company_input")
def handle_company_change(ack, body, client):
    ack()

    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]
    state = view["state"]["values"]

    initial = _extract_current_values(state)

    client.views_update(
        view_id=view["id"],
        view=build_order_modal(
            view["callback_id"],
            company=selected,
            initial=initial,
            private_metadata=view.get("private_metadata", "")),
    )


# ── 주문 모달 제출 ────────────────────────────────────────────────────────────

@app.view("order_request_modal")
def handle_order_modal(ack, body, client, view):
    data = extract_order_fields(view)

    errors = {}
    if not data.get("usage"):
        errors["usage_block"] = "물품용도를 선택해주세요."
    if not data.get("location"):
        errors["location_block"] = "주문장소를 선택해주세요."
    if not data.get("name"):
        errors["name_block"] = "물품명을 입력해주세요."
    if not data.get("company"):
        errors["company_block"] = "거래처를 선택해주세요."
    if data.get("company") == "직접입력" and not data.get("company_custom"):
        errors["company_custom_block"] = "거래처명을 입력해주세요."
    if not data.get("spec"):
        errors["spec_block"] = "용량 및 규격을 입력해주세요."
    if not data.get("quantity"):
        errors["quantity_block"] = "수량을 입력해주세요."
    if not data.get("unit"):
        errors["unit_block"] = "단위를 선택해주세요."
    if not data.get("price"):
        errors["price_block"] = "가격을 입력해주세요."
    if not data.get("purpose"):
        errors["purpose_block"] = "구매 목적을 입력해주세요."
    if errors:
        ack(response_action="errors", errors=errors)
        return
    ack()

    requester_id = body["user"]["id"]
    payload = json.dumps({"requester_id": requester_id, "data": data},
                         ensure_ascii=False)
    dm_channel = get_dm_channel(client, LAB_MANAGER_ID)
    preview = format_order_message(requester_id, data)

    client.chat_postMessage(
        channel=dm_channel,
        text=f"새로운 물품 구매 요청: {data.get('name', '')}",
        blocks=[
            {"type": "section",
             "text": {"type": "mrkdwn",
                      "text": (f"*새로운 물품 구매 요청*\n"
                               f"*요청자:* <@{requester_id}>\n"
                               f"```{preview}```")}},
            {"type": "actions",
             "elements": [
                 {"type": "button",
                  "text": {"type": "plain_text", "text": "승인"},
                  "style": "primary",
                  "action_id": "approve_order",
                  "value": payload},
                 {"type": "button",
                  "text": {"type": "plain_text", "text": "거절"},
                  "style": "danger",
                  "action_id": "deny_order",
                  "value": payload}]}])


# ── 승인 버튼 ─────────────────────────────────────────────────────────────────

@app.action("approve_order")
def handle_approval(ack, body, client):
    ack()

    if body["user"]["id"] != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"], user=body["user"]["id"],
            text="권한이 없습니다.")
        return

    payload = json.loads(body["actions"][0]["value"])
    requester_id = payload["requester_id"]
    data = payload["data"]
    dm_channel = body["channel"]["id"]

    client.chat_update(
        channel=dm_channel, ts=body["message"]["ts"],
        text=f"[승인 완료] <@{requester_id}>님 요청: {data.get('name', '')}",
        blocks=[])
    client.chat_postMessage(channel=dm_channel, text="물품 구매가 승인되었습니다.")

    client.chat_postMessage(
        channel=ORDER_CHANNEL,
        text=format_order_message(requester_id, data),
        blocks=order_channel_blocks(requester_id, data))


# ── 거절 버튼 → 모달 오픈 ────────────────────────────────────────────────────

@app.action("deny_order")
def handle_denial(ack, body, client):
    ack()

    if body["user"]["id"] != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"], user=body["user"]["id"],
            text="권한이 없습니다.")
        return

    payload = json.loads(body["actions"][0]["value"])
    requester_id = payload["requester_id"]
    data = payload["data"]

    metadata = json.dumps({
        "requester_id": requester_id, "data": data,
        "dm_channel": body["channel"]["id"],
        "message_ts": body["message"]["ts"],
    }, ensure_ascii=False)

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal", "callback_id": "denial_reason_modal",
            "private_metadata": metadata,
            "title":  {"type": "plain_text", "text": "거절 사유 입력"},
            "submit": {"type": "plain_text", "text": "전송"},
            "close":  {"type": "plain_text", "text": "취소"},
            "blocks": [
                {"type": "section",
                 "text": {"type": "mrkdwn",
                          "text": (f"*요청자:* <@{requester_id}>\n"
                                   f"*물품명:* {data.get('name', '')}")}},
                {"type": "input", "block_id": "reason_block",
                 "label": {"type": "plain_text", "text": "거절 사유"},
                 "element": {
                     "type": "plain_text_input", "action_id": "reason_input",
                     "multiline": True,
                     "placeholder": {"type": "plain_text",
                                     "text": "거절 사유를 입력해주세요."}}}]})


# ── 거절 모달 제출 ────────────────────────────────────────────────────────────

@app.view("denial_reason_modal")
def handle_denial_modal(ack, client, view):
    ack()
    meta = json.loads(view["private_metadata"])
    requester_id = meta["requester_id"]
    data         = meta["data"]
    dm_channel   = meta["dm_channel"]
    message_ts   = meta["message_ts"]
    reason = view["state"]["values"]["reason_block"]["reason_input"]["value"]

    client.chat_update(
        channel=dm_channel, ts=message_ts,
        text=f"[거절] <@{requester_id}>님 요청: {data.get('name', '')}",
        blocks=[])
    client.chat_postMessage(channel=dm_channel, text="물품 구매가 거절되었습니다.")

    requester_dm = get_dm_channel(client, requester_id)
    client.chat_postMessage(
        channel=requester_dm,
        text=(f"*물품 구매 요청이 거절되었습니다.*\n"
              f"*요청 내용:* {data.get('name', '')}\n"
              f"*거절 사유:* {reason}"))


# ── 수정 버튼 → 모달 오픈 (주문자 전용) ──────────────────────────────────────

@app.action("edit_order")
def handle_edit_order(ack, body, client):
    ack()

    payload = json.loads(body["actions"][0]["value"])
    requester_id = payload["requester_id"]
    data = payload["data"]

    if body["user"]["id"] != requester_id:
        client.chat_postEphemeral(
            channel=body["channel"]["id"], user=body["user"]["id"],
            text="🚫 본인이 작성한 주문 요청만 수정할 수 있습니다.")
        return

    metadata = json.dumps({
        "requester_id": requester_id,
        "channel_id":   body["channel"]["id"],
        "message_ts":   body["message"]["ts"],
    }, ensure_ascii=False)

    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_order_modal(
            "edit_order_modal",
            initial=data,
            private_metadata=metadata))


# ── 수정 모달 제출 ────────────────────────────────────────────────────────────

@app.view("edit_order_modal")
def handle_edit_modal(ack, body, client, view):
    data = extract_order_fields(view)

    errors = {}
    if not data.get("usage"):
        errors["usage_block"] = "물품용도를 선택해주세요."
    if not data.get("location"):
        errors["location_block"] = "주문장소를 선택해주세요."
    if not data.get("name"):
        errors["name_block"] = "물품명을 입력해주세요."
    if not data.get("company"):
        errors["company_block"] = "거래처를 선택해주세요."
    if data.get("company") == "직접입력" and not data.get("company_custom"):
        errors["company_custom_block"] = "거래처명을 입력해주세요."
    if not data.get("spec"):
        errors["spec_block"] = "용량 및 규격을 입력해주세요."
    if not data.get("quantity"):
        errors["quantity_block"] = "수량을 입력해주세요."
    if not data.get("unit"):
        errors["unit_block"] = "단위를 선택해주세요."
    if not data.get("price"):
        errors["price_block"] = "가격을 입력해주세요."
    if not data.get("purpose"):
        errors["purpose_block"] = "구매 목적을 입력해주세요."
    if errors:
        ack(response_action="errors", errors=errors)
        return
    ack()

    meta = json.loads(view["private_metadata"])
    requester_id = meta["requester_id"]
    channel_id   = meta["channel_id"]
    message_ts   = meta["message_ts"]

    client.chat_update(
        channel=channel_id, ts=message_ts,
        text=format_order_message(requester_id, data, edited=True),
        blocks=order_channel_blocks(requester_id, data, edited=True))


# ── 삭제 버튼 (주문자·랩장 전용) ─────────────────────────────────────────────

@app.action("delete_order")
def handle_delete_order(ack, body, client):
    ack()

    payload = json.loads(body["actions"][0]["value"])
    requester_id = payload["requester_id"]
    clicker_id = body["user"]["id"]

    if clicker_id != requester_id and clicker_id != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"], user=clicker_id,
            text="🚫 이 요청을 삭제할 권한이 없습니다. (주문자 및 랩장 전용)")
        return

    client.chat_delete(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"])


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("물품 구매 승인 봇 가동 시작...")
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
