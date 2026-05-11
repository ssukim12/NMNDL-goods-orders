"""
NMNDL 물품 구매 승인 봇

워크플로우:
  1. 구성원이 /물품주문 [내용] 입력
  2. 랩장에게 DM으로 승인/거절 버튼 전송
  3-A. 승인 -> 랩장 DM 확인 메시지 + #order-chemicals 채널에 원문 게시
  3-B. 거절 -> 모달 팝업으로 사유 입력 -> 주문자 DM으로 사유 전달 (채널 미게시)
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
    requester_id, reagent_text = val.split("|", 1)
    dm_channel = body["channel"]["id"]

    client.chat_update(
        channel=dm_channel,
        ts=body["message"]["ts"],
        text=f"[승인 완료] <@{requester_id}>님 요청: {reagent_text}",
        blocks=[]
    )

    client.chat_postMessage(
        channel=dm_channel,
        text="시약 구매가 승인되었습니다."
    )

    client.chat_postMessage(
        channel=ORDER_CHANNEL,
        text=f"주문자: <@{requester_id}> | {reagent_text}"
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
    requester_id, reagent_text = val.split("|", 1)

    metadata = json.dumps({
        "requester_id": requester_id,
        "reagent_text": reagent_text,
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
                        "text": f"*요청자:* <@{requester_id}>\n*내용:* {reagent_text}"
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


# ── 모달 제출 처리 ────────────────────────────────────────────────────────────

@app.view("denial_reason_modal")
def handle_denial_modal(ack, client, view):
    ack()

    meta         = json.loads(view["private_metadata"])
    requester_id = meta["requester_id"]
    reagent_text = meta["reagent_text"]
    dm_channel   = meta["dm_channel"]
    message_ts   = meta["message_ts"]
    reason       = view["state"]["values"]["reason_block"]["reason_input"]["value"]

    client.chat_update(
        channel=dm_channel,
        ts=message_ts,
        text=f"[거절] <@{requester_id}>님 요청: {reagent_text}",
        blocks=[]
    )

    client.chat_postMessage(
        channel=dm_channel,
        text="시약 구매가 거절되었습니다."
    )

    requester_dm = get_dm_channel(client, requester_id)
    client.chat_postMessage(
        channel=requester_dm,
        text=(
            f"*시약 구매 요청이 거절되었습니다.*\n"
            f"*요청 내용:* {reagent_text}\n"
            f"*거절 사유:* {reason}"
        )
    )


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("물품 구매 승인 봇 가동 시작...")
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
