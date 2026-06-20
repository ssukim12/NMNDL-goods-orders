"""
NMNDL 물품 구매 승인 봇 (모달 폼 버전)

워크플로우:
  [개인연구용 / 과제연구용]
    1. /물품주문 → 모달 폼 → 랩장 DM 승인/거절 → 채널 게시
  [공용]
    1. /물품주문 → 간소화 모달 (분류·물품명·수량) → 승인 없이 바로 채널 게시

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

# 공용물품 목록 (Public goods list.xlsx 기반)
PUBLIC_GOODS = {
    "Vial": {
        "Screw vial, 5ml":  {"company": "그린텍", "unit": "BX", "spec": "15*45mm, 500/bx",  "cas_cat": "-",         "price": "101200"},
        "Screw vial, 10ml": {"company": "그린텍", "unit": "BX", "spec": "22*49mm, 250/bx",  "cas_cat": "-",         "price": "59400"},
        "Screw vial, 30ml": {"company": "그린텍", "unit": "BX", "spec": "30*75mm, 150/bx",  "cas_cat": "-",         "price": "75900"},
        "Screw vial, 80ml": {"company": "그린텍", "unit": "BX", "spec": "42*80mm, 65/bx",   "cas_cat": "-",         "price": "150700"},
        "Amber vial, 10ml": {"company": "그린텍", "unit": "BX", "spec": "22*49mm, 250/bx",  "cas_cat": "-",         "price": "74800"},
        "Amber vial, 30ml": {"company": "그린텍", "unit": "BX", "spec": "30*75mm, 150/bx",  "cas_cat": "-",         "price": "84700"},
    },
    "KIMTECH": {
        "Kimtowls S":  {"company": "그린텍", "unit": "BX", "spec": "50/band, 24 bands/bx", "cas_cat": "41705",     "price": "72600"},
        "Kimwipes M":  {"company": "그린텍", "unit": "BX", "spec": "30/bx",                "cas_cat": "41117",     "price": "75900"},
    },
    "Glove": {
        "Nitrile glove, S":       {"company": "그린텍", "unit": "BX", "spec": "100/pk, 10 pk/bx", "cas_cat": "-",         "price": "203500"},
        "Nitrile glove, M":       {"company": "그린텍", "unit": "BX", "spec": "100/pk, 10 pk/bx", "cas_cat": "-",         "price": "203500"},
        "Latex glove, Black, XL": {"company": "그린텍", "unit": "CS", "spec": "1000/cs",          "cas_cat": "UN.KXXC05", "price": "135300"},
    },
    "Conical tube": {
        "Conical tubes, 50ml": {"company": "그린텍", "unit": "BX", "spec": "500/bx", "cas_cat": "H20050", "price": "95700"},
    },
    "Pipet tips": {
        "Pipet tips, 10μl, Axygen":   {"company": "그린텍", "unit": "PK", "spec": "1000/pk", "cas_cat": "AX.T-300",       "price": "20900"},
        "Pipet tips, 200μl, Axygen":  {"company": "그린텍", "unit": "PK", "spec": "1000/pk", "cas_cat": "AX.T-200-Y",     "price": "20900"},
        "Pipet tips, 1000μl, Axygen": {"company": "그린텍", "unit": "PK", "spec": "1000/pk", "cas_cat": "AX.T-1000-B",    "price": "23100"},
        "Pipet tips, 5ml, Eppendorf": {"company": "그린텍", "unit": "PK", "spec": "500/pk",  "cas_cat": "EP.0030000978",  "price": "96800"},
        "Pipet tips, 10ml, Axygen":   {"company": "그린텍", "unit": "PK", "spec": "200/pk",  "cas_cat": "AX.T-10ML-C",    "price": "70950"},
    },
    "Label tape": {
        "Label tape, 3/4\", White":  {"company": "그린텍", "unit": "EA", "spec": "1/ea", "cas_cat": "BE.F13463.0075", "price": "14850"},
        "Label tape, 3/4\", Yellow": {"company": "그린텍", "unit": "EA", "spec": "1/ea", "cas_cat": "BE.F13463.2075", "price": "14850"},
        "Label tape, 3/4\", Orange": {"company": "그린텍", "unit": "EA", "spec": "1/ea", "cas_cat": "BE.F13463.5075", "price": "14850"},
    },
    "Weighin paper": {
        "Disposable weighing paper, 10*10cm": {"company": "그린텍", "unit": "PK", "spec": "500 strips/pk", "cas_cat": "DH.WEP002", "price": "2200"},
    },
    "Petridish": {
        "Petridish, 60*15mm, SPL": {"company": "그린텍", "unit": "BX", "spec": "500/bx", "cas_cat": "H10060", "price": "66000"},
        "Petridish, 90*15mm, SPL": {"company": "그린텍", "unit": "BX", "spec": "500/bx", "cas_cat": "H10090", "price": "58300"},
    },
    "Squeeze bottle": {
        "광구 라벨세척병 Acetone 500ml": {"company": "그린텍", "unit": "EA", "spec": "500ml", "cas_cat": "KA.30-00A", "price": "3630"},
        "광구 라벨세척병 Ethanol 500ml": {"company": "그린텍", "unit": "EA", "spec": "500ml", "cas_cat": "KA.30-00E", "price": "3630"},
        "광구 라벨세척병 Water 500ml":   {"company": "그린텍", "unit": "EA", "spec": "500ml", "cas_cat": "KA.30-00W", "price": "3630"},
    },
    "Stirrer bar": {
        "Stirrer Bar, Tepered, Φ5×L15mm": {"company": "그린텍", "unit": "EA", "spec": "1/ea", "cas_cat": "SL.Sti4050", "price": "1500"},
        "Stirrer Bar, Tepered, Φ7×L20mm": {"company": "그린텍", "unit": "EA", "spec": "1/ea", "cas_cat": "SL.Sti4051", "price": "2000"},
    },
    "일회용 스포이드": {
        "Disposable transfer pipet, 3ml": {"company": "그린텍", "unit": "PK", "spec": "500/pk", "cas_cat": "KA.TP-3M", "price": "29700"},
    },
}

PUBLIC_CATEGORIES = list(PUBLIC_GOODS.keys()) + ["기타"]


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def get_dm_channel(client, user_id: str) -> str:
    resp = client.conversations_open(users=user_id)
    return resp["channel"]["id"]


# ── 모달 빌드 ─────────────────────────────────────────────────────────────────

def build_order_modal(callback_id: str, *, usage: str = "",
                      company: str = "", category: str = "",
                      public_name: str = "",
                      initial: dict | None = None,
                      private_metadata: str = "") -> dict:
    initial = initial or {}
    blocks = []

    # ── 공통: ① 물품용도 (라디오, dispatch_action) ─────────────────────────
    radio_el = {"type": "radio_buttons", "action_id": "usage_input",
                "options": USAGE_OPTIONS}
    selected_usage = usage or initial.get("usage", "")
    if selected_usage:
        match = next((o for o in USAGE_OPTIONS if o["value"] == selected_usage), None)
        if match:
            radio_el["initial_option"] = match
    blocks.append({
        "type": "input", "block_id": "usage_block",
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "물품용도"},
        "element": radio_el,
    })

    # ── 공통: ② 주문장소 ──────────────────────────────────────────────────
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

    # ── 분기: 공용 vs 일반 ────────────────────────────────────────────────
    if selected_usage == "공용":
        _append_public_blocks(blocks, category=category,
                              public_name=public_name, company=company,
                              initial=initial)
    else:
        _append_regular_blocks(blocks, company=company, initial=initial)

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


def _append_public_blocks(blocks: list, *, category: str,
                          public_name: str, company: str,
                          initial: dict) -> None:
    selected_cat = category or initial.get("category", "")

    # ③ 분류 (드롭다운, dispatch_action)
    cat_opts = [{"text": {"type": "plain_text", "text": c}, "value": c}
                for c in PUBLIC_CATEGORIES]
    cat_el = {"type": "static_select", "action_id": "category_input",
              "options": cat_opts,
              "placeholder": {"type": "plain_text", "text": "분류 선택"}}
    if selected_cat:
        cat_el["initial_option"] = {
            "text": {"type": "plain_text", "text": selected_cat},
            "value": selected_cat}
    blocks.append({
        "type": "input", "block_id": "category_block",
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "분류"},
        "element": cat_el,
    })

    if selected_cat == "기타":
        # 기타: 물품명 직접입력 + 일반 모드와 동일한 세부 필드
        custom_el = {"type": "plain_text_input",
                     "action_id": "public_name_custom_input",
                     "placeholder": {"type": "plain_text",
                                     "text": "물품명을 입력해주세요"}}
        if initial.get("public_name_custom"):
            custom_el["initial_value"] = initial["public_name_custom"]
        elif initial.get("name"):
            custom_el["initial_value"] = initial["name"]
        blocks.append({
            "type": "input", "block_id": "public_name_custom_block",
            "label": {"type": "plain_text", "text": "물품명"},
            "hint": {"type": "plain_text",
                     "text": "Gmarket 물품의 경우 옵션까지 상세히 기입해주세요"},
            "element": custom_el,
        })
        _append_detail_blocks(blocks, company=company, initial=initial)
    else:
        # 프리셋 분류: 물품명 드롭다운 + 수량만
        selected_name = public_name or initial.get("public_name", "")

        if selected_cat:
            items = list(PUBLIC_GOODS.get(selected_cat, {}).keys())
            name_opts = [{"text": {"type": "plain_text", "text": n}, "value": n}
                         for n in items]
            name_opts.append({"text": {"type": "plain_text", "text": "직접 입력"},
                              "value": "직접 입력"})
            name_el = {"type": "static_select", "action_id": "public_name_input",
                       "options": name_opts,
                       "placeholder": {"type": "plain_text", "text": "물품 선택"}}
            if selected_name and any(o["value"] == selected_name for o in name_opts):
                name_el["initial_option"] = {
                    "text": {"type": "plain_text", "text": selected_name},
                    "value": selected_name}
            blocks.append({
                "type": "input", "block_id": "public_name_block",
                "dispatch_action": True,
                "label": {"type": "plain_text", "text": "물품명"},
                "element": name_el,
            })

        # 직접 입력 필드 ('직접 입력' 선택 시)
        if selected_name == "직접 입력":
            custom_el = {"type": "plain_text_input",
                         "action_id": "public_name_custom_input",
                         "placeholder": {"type": "plain_text",
                                         "text": "물품명을 입력해주세요"}}
            if initial.get("public_name_custom"):
                custom_el["initial_value"] = initial["public_name_custom"]
            blocks.append({
                "type": "input", "block_id": "public_name_custom_block",
                "label": {"type": "plain_text", "text": "물품명 직접입력"},
                "element": custom_el,
            })

        # 수량
        qty_el = {"type": "plain_text_input", "action_id": "quantity_input",
                  "placeholder": {"type": "plain_text", "text": "숫자만 표기해주세요"}}
        if initial.get("quantity"):
            qty_el["initial_value"] = initial["quantity"]
        blocks.append({
            "type": "input", "block_id": "quantity_block",
            "label": {"type": "plain_text", "text": "수량"},
            "element": qty_el,
        })


def _append_regular_blocks(blocks: list, *, company: str,
                           initial: dict) -> None:
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

    _append_detail_blocks(blocks, company=company, initial=initial)


def _append_detail_blocks(blocks: list, *, company: str,
                          initial: dict) -> None:
    # 거래처 (드롭다운 + dispatch_action)
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

    # 거래처 직접입력
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

    # CAS/CAT No.
    cas_el = {"type": "plain_text_input", "action_id": "cas_cat_input",
              "placeholder": {"type": "plain_text", "text": "예: SL.Sti4024"}}
    if initial.get("cas_cat"):
        cas_el["initial_value"] = initial["cas_cat"]
    blocks.append({
        "type": "input", "block_id": "cas_cat_block", "optional": True,
        "label": {"type": "plain_text", "text": "CAS/CAT No."},
        "element": cas_el,
    })

    # 용량 및 규격
    spec_el = {"type": "plain_text_input", "action_id": "spec_input",
               "placeholder": {"type": "plain_text", "text": "예: 150/bx"}}
    if initial.get("spec"):
        spec_el["initial_value"] = initial["spec"]
    blocks.append({
        "type": "input", "block_id": "spec_block",
        "label": {"type": "plain_text", "text": "용량 및 규격"},
        "element": spec_el,
    })

    # 수량
    qty_el = {"type": "plain_text_input", "action_id": "quantity_input",
              "placeholder": {"type": "plain_text", "text": "숫자만 표기해주세요"}}
    if initial.get("quantity"):
        qty_el["initial_value"] = initial["quantity"]
    blocks.append({
        "type": "input", "block_id": "quantity_block",
        "label": {"type": "plain_text", "text": "수량"},
        "element": qty_el,
    })

    # 단위
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

    # 가격
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

    # URL
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

    # 구매 목적
    purpose_el = {"type": "plain_text_input", "action_id": "purpose_input",
                  "multiline": True,
                  "placeholder": {"type": "plain_text",
                                  "text": "구매 목적을 입력해주세요"}}
    if initial.get("purpose"):
        purpose_el["initial_value"] = initial["purpose"]
    blocks.append({
        "type": "input", "block_id": "purpose_block",
        "label": {"type": "plain_text", "text": "구매 목적"},
        "element": purpose_el,
    })


# ── 모달 상태 보존 ────────────────────────────────────────────────────────────

def _extract_current_values(state: dict) -> dict:
    data = {}

    usage = state.get("usage_block", {}).get("usage_input", {})
    if usage.get("selected_option"):
        data["usage"] = usage["selected_option"]["value"]

    loc = state.get("location_block", {}).get("location_input", {})
    if loc.get("selected_option"):
        data["location"] = loc["selected_option"]["value"]

    # 일반 모드 텍스트 필드
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

    # 공용 모드 필드
    cat = state.get("category_block", {}).get("category_input", {})
    if cat.get("selected_option"):
        data["category"] = cat["selected_option"]["value"]

    pn = state.get("public_name_block", {}).get("public_name_input", {})
    if pn.get("selected_option"):
        data["public_name"] = pn["selected_option"]["value"]

    pnc = state.get("public_name_custom_block", {}).get("public_name_custom_input", {})
    if pnc and pnc.get("value"):
        data["public_name_custom"] = pnc["value"].strip()

    return data


# ── 데이터 추출 ───────────────────────────────────────────────────────────────

def extract_order_fields(view) -> dict:
    values = view["state"]["values"]
    data = {}

    usage = values.get("usage_block", {}).get("usage_input", {})
    data["usage"] = (usage.get("selected_option") or {}).get("value", "")

    loc = values.get("location_block", {}).get("location_input", {})
    data["location"] = (loc.get("selected_option") or {}).get("value", "")

    if data["usage"] == "공용":
        cat = values.get("category_block", {}).get("category_input", {})
        data["category"] = (cat.get("selected_option") or {}).get("value", "")

        if data["category"] == "기타":
            # 기타: 물품명 직접입력 + 일반 모드와 동일한 세부 필드
            pnc = values.get("public_name_custom_block", {}).get("public_name_custom_input", {})
            data["name"] = (pnc.get("value") or "").strip() if pnc else ""
            _extract_detail_values(data, values)
        else:
            # 프리셋 분류
            pn = values.get("public_name_block", {}).get("public_name_input", {})
            data["public_name"] = (pn.get("selected_option") or {}).get("value", "")

            pnc = values.get("public_name_custom_block", {}).get("public_name_custom_input", {})
            data["public_name_custom"] = (pnc.get("value") or "").strip() if pnc else ""

            if data["public_name"] == "직접 입력":
                data["name"] = data["public_name_custom"]
            else:
                data["name"] = data["public_name"]

            qty = values.get("quantity_block", {}).get("quantity_input", {})
            data["quantity"] = (qty.get("value") or "").strip()

            # 프리셋 데이터 채우기
            preset = PUBLIC_GOODS.get(data["category"], {}).get(data["name"], {})
            if preset:
                data["company"]  = preset["company"]
                data["unit"]     = preset["unit"]
                data["spec"]     = preset["spec"]
                data["cas_cat"]  = preset["cas_cat"]
                data["price"]    = preset["price"]
    else:
        name = values.get("name_block", {}).get("name_input", {})
        data["name"] = (name.get("value") or "").strip()
        _extract_detail_values(data, values)

    return data


def _extract_detail_values(data: dict, values: dict) -> None:
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


# ── 메시지 포맷터 ─────────────────────────────────────────────────────────────

def _resolve_company(data: dict) -> str:
    if data.get("company") == "직접입력" and data.get("company_custom"):
        return data["company_custom"]
    return data.get("company", "")


def format_order_message(requester_id: str, data: dict,
                         edited: bool = False) -> str:
    if data.get("usage") == "공용" and data.get("category") != "기타":
        lines = [
            "[공용물품 등록]",
            f"주문장소: {data.get('location', '')}",
            f"분류: {data.get('category', '')}",
            f"물품명: {data.get('name', '')}",
        ]
        if data.get("company"):
            lines.append(f"거래처: {data['company']}")
        if data.get("spec"):
            lines.append(f"용량 및 규격: {data['spec']}")
        unit_str = f" {data['unit']}" if data.get("unit") else ""
        lines.append(f"수량: {data.get('quantity', '')}{unit_str}")
        if data.get("price"):
            lines.append(f"가격: {data['price']}원")
        lines.append(f"주문자: <@{requester_id}>")
    else:
        company = _resolve_company(data)
        is_public_etc = data.get("usage") == "공용" and data.get("category") == "기타"
        lines = [
            "[공용물품 등록]" if is_public_etc else "[물품등록]",
            f"물품용도: {data.get('usage', '')}",
            f"주문장소: {data.get('location', '')}",
        ]
        if is_public_etc:
            lines.append(f"분류: {data.get('category', '')}")
        lines.extend([
            f"물품명: {data.get('name', '')}",
            f"거래처: {company}",
        ])
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


# ── 물품용도 변경 시 모달 동적 갱신 ───────────────────────────────────────────

@app.action("usage_input")
def handle_usage_change(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]
    initial = _extract_current_values(view["state"]["values"])

    client.views_update(
        view_id=view["id"],
        view=build_order_modal(
            view["callback_id"], usage=selected, initial=initial,
            private_metadata=view.get("private_metadata", "")))


# ── 거래처 변경 시 모달 동적 갱신 ─────────────────────────────────────────────

@app.action("company_input")
def handle_company_change(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]
    initial = _extract_current_values(view["state"]["values"])

    client.views_update(
        view_id=view["id"],
        view=build_order_modal(
            view["callback_id"], usage=initial.get("usage", ""),
            company=selected,
            category=initial.get("category", ""),
            public_name=initial.get("public_name", ""),
            initial=initial,
            private_metadata=view.get("private_metadata", "")))


# ── 분류 변경 시 물품명 드롭다운 갱신 ─────────────────────────────────────────

@app.action("category_input")
def handle_category_change(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]
    initial = _extract_current_values(view["state"]["values"])
    initial.pop("public_name", None)
    initial.pop("public_name_custom", None)

    public_name = "직접 입력" if selected == "기타" else ""

    client.views_update(
        view_id=view["id"],
        view=build_order_modal(
            view["callback_id"], usage="공용",
            category=selected, public_name=public_name,
            initial=initial,
            private_metadata=view.get("private_metadata", "")))


# ── 물품명 변경 시 직접입력 필드 토글 ─────────────────────────────────────────

@app.action("public_name_input")
def handle_public_name_change(ack, body, client):
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    view = body["view"]
    initial = _extract_current_values(view["state"]["values"])

    cat = initial.get("category", "")

    client.views_update(
        view_id=view["id"],
        view=build_order_modal(
            view["callback_id"], usage="공용",
            category=cat, public_name=selected,
            initial=initial,
            private_metadata=view.get("private_metadata", "")))


# ── 주문 모달 제출 ────────────────────────────────────────────────────────────

@app.view("order_request_modal")
def handle_order_modal(ack, body, client, view):
    data = extract_order_fields(view)
    errors = _validate_order(data)
    if errors:
        ack(response_action="errors", errors=errors)
        return
    ack()

    requester_id = body["user"]["id"]

    if data["usage"] == "공용":
        client.chat_postMessage(
            channel=ORDER_CHANNEL,
            text=format_order_message(requester_id, data),
            blocks=order_channel_blocks(requester_id, data))
    else:
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


def _validate_order(data: dict) -> dict:
    errors = {}
    if not data.get("usage"):
        errors["usage_block"] = "물품용도를 선택해주세요."
    if not data.get("location"):
        errors["location_block"] = "주문장소를 선택해주세요."
    if not data.get("quantity"):
        errors["quantity_block"] = "수량을 입력해주세요."

    if data.get("usage") == "공용":
        if not data.get("category"):
            errors["category_block"] = "분류를 선택해주세요."

        if data.get("category") == "기타":
            # 기타: 일반 모드와 동일한 검증
            if not data.get("name"):
                errors["public_name_custom_block"] = "물품명을 입력해주세요."
            if not data.get("company"):
                errors["company_block"] = "거래처를 선택해주세요."
            if data.get("company") == "직접입력" and not data.get("company_custom"):
                errors["company_custom_block"] = "거래처명을 입력해주세요."
            if not data.get("spec"):
                errors["spec_block"] = "용량 및 규격을 입력해주세요."
            if not data.get("unit"):
                errors["unit_block"] = "단위를 선택해주세요."
            if not data.get("price"):
                errors["price_block"] = "가격을 입력해주세요."
            if not data.get("purpose"):
                errors["purpose_block"] = "구매 목적을 입력해주세요."
        else:
            # 프리셋 분류
            if not data.get("name"):
                if data.get("public_name") == "직접 입력":
                    errors["public_name_custom_block"] = "물품명을 입력해주세요."
                else:
                    errors["public_name_block"] = "물품명을 선택해주세요."
    else:
        if not data.get("name"):
            errors["name_block"] = "물품명을 입력해주세요."
        if not data.get("company"):
            errors["company_block"] = "거래처를 선택해주세요."
        if data.get("company") == "직접입력" and not data.get("company_custom"):
            errors["company_custom_block"] = "거래처명을 입력해주세요."
        if not data.get("spec"):
            errors["spec_block"] = "용량 및 규격을 입력해주세요."
        if not data.get("unit"):
            errors["unit_block"] = "단위를 선택해주세요."
        if not data.get("price"):
            errors["price_block"] = "가격을 입력해주세요."
        if not data.get("purpose"):
            errors["purpose_block"] = "구매 목적을 입력해주세요."
    return errors


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
            usage=data.get("usage", ""),
            category=data.get("category", ""),
            public_name=data.get("public_name", ""),
            initial=data,
            private_metadata=metadata))


# ── 수정 모달 제출 ────────────────────────────────────────────────────────────

@app.view("edit_order_modal")
def handle_edit_modal(ack, body, client, view):
    data = extract_order_fields(view)
    errors = _validate_order(data)
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
