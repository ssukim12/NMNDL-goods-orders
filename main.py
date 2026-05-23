"""
NMNDL 물품 구매 승인 봇

워크플로우:
  1. 구성원이 /물품주문 [내용] 입력
  2. 랩장에게 DM으로 승인/거절 버튼 전송
  3-A. 승인 -> 랩장 DM 확인 메시지 + #order-chemicals 채널에 원문 게시 (수정/삭제 버튼 포함)
  3-B. 거절 -> 모달 팝업으로 사유 입력 -> 주문자 DM으로 사유 전달 (채널 미게시)
  4. 채널 게시 후 주문자는 [내용 수정], 주문자·랩장은 [요청 삭제] 가능
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


def get_dm_channel(client, user_id: str) -> str:
    resp = client.conversations_open(users=user_id)
    return resp["channel"]["id"]


def make_channel_blocks(requester_id: str, text: str) -> list:
    """채널 게시용 블록: 주문 내용 + 수정/삭제 버튼"""
    value = f"{requester_id}|{text}"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*주문자:* <@{requester_id}>\n*내용:* {text}"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "내용 수정 (주문자 전용)"},
                    "action_id": "edit_order",
                    "value": value
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "요청 삭제"},
                    "style": "danger",
                    "action_id": "delete_order",
                    "value": value
                }
            ]
        }
    ]


# ── /물품주문 커맨드 ───────────────────────────────────────────────────────────

@app.command("/물품주문")
def handle_order_command(ack, body, client):
    ack()

    user_id = body["user_id"]
    text    = body["text"].strip()

    if not text:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text="주문 내용을 입력해주세요.\n예: /물품주문 Dimethyl sulfoxide / 67-68-5 / 154938 / 500mL / 1 / 85,000원"
        )
        return

    dm_channel = get_dm_channel(client, LAB_MANAGER_ID)

    client.chat_postMessage(
        channel=dm_channel,
        text=f"새로운 물품 구매 요청: {text}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*새로운 물품 구매 요청*\n"
                        f"*요청자:* <@{user_id}>\n"
                        f"*내용:* {text}"
                    )
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "승인"},
                        "style": "primary",
                        "action_id": "approve_order",
                        "value": f"{user_id}|{text}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "거절"},
                        "style": "danger",
                        "action_id": "deny_order",
                        "value": f"{user_id}|{text}"
                    }
                ]
            }
        ]
    )


# ── 승인 버튼 ─────────────────────────────────────────────────────────────────

@app.action("approve_order")
def handle_approval(ack, body, client):
    ack()

    if body["user"]["id"] != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="권한이 없습니다."
        )
        return

    val = body["actions"][0]["value"]
    requester_id, order_text = val.split("|", 1)
    dm_channel = body["channel"]["id"]

    client.chat_update(
        channel=dm_channel,
        ts=body["message"]["ts"],
        text=f"[승인 완료] <@{requester_id}>님 요청: {order_text}",
        blocks=[]
    )

    client.chat_postMessage(
        channel=dm_channel,
        text="물품 구매가 승인되었습니다."
    )

    client.chat_postMessage(
        channel=ORDER_CHANNEL,
        text=f"주문자: <@{requester_id}> | {order_text}",
        blocks=make_channel_blocks(requester_id, order_text)
    )


# ── 거절 버튼 → 모달 오픈 ────────────────────────────────────────────────────

@app.action("deny_order")
def handle_denial(ack, body, client):
    ack()

    if body["user"]["id"] != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="권한이 없습니다."
        )
        return

    val = body["actions"][0]["value"]
    requester_id, order_text = val.split("|", 1)

    metadata = json.dumps({
        "requester_id": requester_id,
        "order_text":   order_text,
        "dm_channel":   body["channel"]["id"],
        "message_ts":   body["message"]["ts"],
    }, ensure_ascii=False)

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "denial_reason_modal",
            "private_metadata": metadata,
            "title":  {"type": "plain_text", "text": "거절 사유 입력"},
            "submit": {"type": "plain_text", "text": "전송"},
            "close":  {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*요청자:* <@{requester_id}>\n*내용:* {order_text}"
                    }
                },
                {
                    "type": "input",
                    "block_id": "reason_block",
                    "label": {"type": "plain_text", "text": "거절 사유"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "reason_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "거절 사유를 입력해주세요."}
                    }
                }
            ]
        }
    )


# ── 거절 모달 제출 ────────────────────────────────────────────────────────────

@app.view("denial_reason_modal")
def handle_denial_modal(ack, client, view):
    ack()

    meta         = json.loads(view["private_metadata"])
    requester_id = meta["requester_id"]
    order_text   = meta["order_text"]
    dm_channel   = meta["dm_channel"]
    message_ts   = meta["message_ts"]
    reason       = view["state"]["values"]["reason_block"]["reason_input"]["value"]

    client.chat_update(
        channel=dm_channel,
        ts=message_ts,
        text=f"[거절] <@{requester_id}>님 요청: {order_text}",
        blocks=[]
    )

    client.chat_postMessage(
        channel=dm_channel,
        text="물품 구매가 거절되었습니다."
    )

    requester_dm = get_dm_channel(client, requester_id)
    client.chat_postMessage(
        channel=requester_dm,
        text=(
            f"*물품 구매 요청이 거절되었습니다.*\n"
            f"*요청 내용:* {order_text}\n"
            f"*거절 사유:* {reason}"
        )
    )


# ── 수정 버튼 (주문자 전용) ───────────────────────────────────────────────────

@app.action("edit_order")
def handle_edit_order(ack, body, client):
    ack()

    clicker_id = body["user"]["id"]
    val = body["actions"][0]["value"]
    requester_id, order_text = val.split("|", 1)

    if clicker_id != requester_id:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=clicker_id,
            text="🚫 본인이 작성한 주문 요청만 수정할 수 있습니다."
        )
        return

    metadata = json.dumps({
        "requester_id": requester_id,
        "channel_id":   body["channel"]["id"],
        "message_ts":   body["message"]["ts"],
    }, ensure_ascii=False)

    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_order_modal",
            "private_metadata": metadata,
            "title":  {"type": "plain_text", "text": "주문 내용 수정"},
            "submit": {"type": "plain_text", "text": "수정"},
            "close":  {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "edit_block",
                    "label": {"type": "plain_text", "text": "수정할 내용"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "edit_input",
                        "multiline": True,
                        "initial_value": order_text,
                        "placeholder": {"type": "plain_text", "text": "수정할 내용을 입력해주세요."}
                    }
                }
            ]
        }
    )


# ── 수정 모달 제출 ────────────────────────────────────────────────────────────

@app.view("edit_order_modal")
def handle_edit_order_modal(ack, client, view):
    ack()

    meta         = json.loads(view["private_metadata"])
    requester_id = meta["requester_id"]
    channel_id   = meta["channel_id"]
    message_ts   = meta["message_ts"]
    new_text     = view["state"]["values"]["edit_block"]["edit_input"]["value"]

    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"주문자: <@{requester_id}> | {new_text}",
        blocks=make_channel_blocks(requester_id, new_text)
    )


# ── 삭제 버튼 (주문자·랩장 전용) ─────────────────────────────────────────────

@app.action("delete_order")
def handle_delete_order(ack, body, client):
    ack()

    clicker_id   = body["user"]["id"]
    val          = body["actions"][0]["value"]
    requester_id = val.split("|", 1)[0]

    if clicker_id != requester_id and clicker_id != LAB_MANAGER_ID:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=clicker_id,
            text="🚫 이 요청을 삭제할 권한이 없습니다. (주문자 및 랩장 전용)"
        )
        return

    client.chat_delete(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"]
    )


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("물품 구매 승인 봇 가동 시작...")
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
