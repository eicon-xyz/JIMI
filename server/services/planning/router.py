"""
规划路由层 — OmniParser 元素检测 + LLM 执行计划生成

管道: 截图 → OmniParser :9800 → 元素列表 → LLM → 执行计划
"""
import json
import logging
import uuid
from typing import List, Optional

from server.config import settings
from server.models.schemas import (
    UIElement,
    Step,
    Blueprint,
    Intent,
    ProcessResponse,
    RedlineInfo,
)
from server.services.redline_service import check_redline
from server.services.planning.complexity_router import score_complexity, generate_l2_steps

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 执行计划 LLM Prompt
# ═══════════════════════════════════════════════════════════════════════════

EXECUTOR_SYSTEM_PROMPT = """You are a desktop automation executor. Convert user instructions into executable action plans.

## UI Elements on Screen
{element_list}

## Output (PURE JSON ONLY - no markdown, no thinking, just the JSON object)
{{
  "goal": "short task goal",
  "steps": [
    {{
      "step_index": 1,
      "action": "click",
      "description": "click Chrome icon",
      "target_element_id": "~3",
      "bbox": [120, 340, 180, 410],
      "bbox_center": [150, 375],
      "params": null
    }}
  ]
}}

## Actions
- click: left click
- double_click: left double click
- right_click: right click
- type: type text (params = text to type)
- press_key: key combo (params = "ctrl+c", "win+r", "enter")
- scroll: scroll wheel (params = positive up, negative down)
- wait: wait (params = seconds)
- move: move mouse without clicking

## Rules
1. Each step MUST reference an element from the list above with element_id, bbox, bbox_center
2. bbox_center = [int(cx), int(cy)] from the element's bbox
3. 2-5 steps max. Be concise.
4. Only output {{}} JSON. No explanation. No markdown. No thinking.
5. Prefer keyboard shortcuts over GUI clicks when possible (win+r for Run, win+e for Explorer, etc)
"""

# ═══════════════════════════════════════════════════════════════════════════
# Mock fallbacks
# ═══════════════════════════════════════════════════════════════════════════

_MOCK_FALLBACKS = {
    "wechat": [
        {"action": "click", "description": "打开浏览器", "bbox_center": [150, 375], "params": None},
        {"action": "type", "description": "输入微信官网地址", "bbox_center": [500, 70], "params": "weixin.qq.com"},
        {"action": "click", "description": "点击下载按钮", "bbox_center": [480, 525], "params": None},
        {"action": "click", "description": "运行安装程序", "bbox_center": [130, 630], "params": None},
    ],
    "notepad": [
        {"action": "press_key", "description": "按Win+R打开运行窗口", "bbox_center": None, "params": "win+r"},
        {"action": "type", "description": "输入notepad", "bbox_center": None, "params": "notepad"},
        {"action": "press_key", "description": "按回车启动记事本", "bbox_center": None, "params": "enter"},
    ],
    "calculator": [
        {"action": "press_key", "description": "按Win+R打开运行窗口", "bbox_center": None, "params": "win+r"},
        {"action": "type", "description": "输入calc", "bbox_center": None, "params": "calc"},
        {"action": "press_key", "description": "按回车启动计算器", "bbox_center": None, "params": "enter"},
    ],
    "screenshot": [
        {"action": "press_key", "description": "打开截图工具", "bbox_center": None, "params": "win+shift+s"},
        {"action": "click", "description": "选择截图区域", "bbox_center": [500, 300], "params": None},
        {"action": "click", "description": "保存截图", "bbox_center": [200, 600], "params": None},
    ],
    "default": [
        {"action": "wait", "description": "等待界面加载", "bbox_center": None, "params": 2},
        {"action": "click", "description": "点击目标元素", "bbox_center": [500, 300], "params": None},
    ],
}


def _choose_scenario(query: str) -> str:
    q = query.lower()
    if any(k in q for k in ["微信", "qq", "软件", "下载", "安装"]):
        return "wechat"
    if any(k in q for k in ["记事本", "notepad", "文本"]):
        return "notepad"
    if any(k in q for k in ["计算器", "calc", "calculator"]):
        return "calculator"
    if any(k in q for k in ["截图", "截屏", "snip"]):
        return "screenshot"
    return "default"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _serialize_elements(elements: List[UIElement]) -> str:
    """序列化 UI 元素列表。只传桌面区域的大按钮（图标）。"""
    lines = []
    for el in elements:
        if el.element_type != 'button':
            continue
        bbox = el.bbox
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        # Desktop icons: y between 0-300 (top area), area > 5000 (real icons)
        # Taskbar icons have y > 500 (bottom), OmniParser toolbar buttons y < 30 (too small)
        if bbox[1] > 300 or area < 5000 or bbox[3] < 50:
            continue
        cx = int((bbox[0] + bbox[2]) / 2)
        cy = int((bbox[1] + bbox[3]) / 2)
        lines.append(
            f'{el.element_id}: center=[{cx},{cy}]'
        )
    return '\n'.join(lines)


def _call_executor_llm(query: str, element_text: str = "", image_base64: Optional[str] = None) -> Optional[dict]:
    """调用 LLM 生成执行计划。有 OmniParser 元素时用精确 bbox，否则纯看图。"""
    from server.services.llm.providers import call_llm, extract_json_object

    if element_text:
        user_text = f'Elements:\n{element_text}\n\nUser: {query}. Pick the correct element_id from the list based on what you see in the screenshot. Output JSON only.'
        sp = 'Desktop automation executor. You see a screenshot with labeled bounding boxes. Output ONLY JSON: {\"goal\":\"...\",\"steps\":[{\"step_index\":1,\"action\":\"double_click\",\"description\":\"double click the target icon\",\"target_element_id\":\"~N\",\"bbox_center\":[cx,cy]}]}. Use the element list for bbox_center. No thinking. No markdown.'
        max_tok = 1024
    else:
        user_text = f'{query} - create execution plan. JSON only.'
        sp = 'Desktop automation executor. Output ONLY JSON: {\"goal\":\"...\",\"steps\":[{\"step_index\":1,\"action\":\"press_key\",\"description\":\"...\",\"params\":null}]}. Actions: click,double_click,type,press_key,wait. No thinking.'
        max_tok = 512

    images = None
    if image_base64:
        images = [{"base64Jpeg": image_base64, "label": "Screen"}]

    try:
        raw = call_llm(
            user_text=user_text, images=images, system_prompt=sp,
            temperature=0.1, max_tokens=max_tok, timeout=60,
        )
        data = extract_json_object(raw)
        return data
    except Exception as e:
        logger.warning(f"Executor LLM call failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def process_query(
    query: str,
    image_base64: Optional[str] = None,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> ProcessResponse:
    """
    完整管道：截图 → OmniParser 元素检测 → LLM 执行计划 → ProcessResponse。

    Args:
        query: 用户自然语言指令
        image_base64: Base64 截图（含 data URI 前缀）
        screen_width: 屏幕宽度
        screen_height: 屏幕高度

    Returns:
        ProcessResponse 含 step 列表，每步带 bbox_center
    """
    # 0. 红线检测
    redline = check_redline(query)
    if redline.triggered:
        return ProcessResponse(
            task_id=str(uuid.uuid4()),
            success=False,
            intent=Intent(
                category="operation_guide",
                summary="请求被拦截",
                reference_type="explicit",
                confidence=1.0,
                needs_clarification=False,
            ),
            ui_elements=[],
            blueprint=Blueprint(
                name="红线拦截",
                total_steps=1,
                current_step=1,
                state="terminated",
            ),
            steps=[],
            redline=RedlineInfo(
                triggered=True,
                category=redline.category,
                message=redline.message,
                action=redline.action,
            ),
        )

    # 1. 意图分类
    from server.services.llm_ai import classify_intent, detect_reference_type
    category, summary, confidence = classify_intent(query)
    reference_type = detect_reference_type(query)
    intent = Intent(
        category=category,
        summary=summary,
        reference_type=reference_type,
        confidence=confidence,
        needs_clarification=confidence < 0.80,
    )

    # ── 2. L2/L3 路由（MVP 阶段全部走 L3，L2 模板暂不适用自动执行）──
    complexity = score_complexity(query)
    route = "L3"  # MVP: 跳过 L2，全部走 LLM 执行计划

    ui_elements: List[UIElement] = []
    annotated_image: Optional[str] = None
    reference_resolution: Optional[List[int]] = [screen_width, screen_height]
    detection_meta: dict = {
        "route": route,
        "complexity": complexity,
        "backend": "omniparser",
    }
    raw_steps: Optional[List[dict]] = None

    # ── 3. 截图 → OmniParser 元素检测 ──
    if image_base64 and route == "L3":
        try:
            from server.services.omniparser_client import parse_screenshot_full

            parse_result = parse_screenshot_full(image_base64)
            if parse_result.elements:
                ui_elements = parse_result.elements
                annotated_image = parse_result.annotated_image
                if parse_result.reference_resolution:
                    reference_resolution = parse_result.reference_resolution
                detection_meta.update(
                    parse_result.detection_meta or {}
                )
                logger.info(
                    f"OmniParser: {len(ui_elements)} elements in "
                    f"{detection_meta.get('latency_ms', 0)}ms"
                )
            else:
                logger.warning("OmniParser returned 0 elements")
                detection_meta["element_count"] = 0
        except Exception as e:
            logger.error(f"OmniParser call failed: {e}")
            detection_meta["omni_error"] = str(e)

    # L2 快路径
    if route == "L2":
        raw_steps = generate_l2_steps(query, ui_elements)

    # ── 4. App Launch: Win+Search channel ──
    if not raw_steps and settings.USE_REAL_LLM:
        from server.services.launcher import launch_app, _extract_app_name_from_query, _extract_remaining_operation

        app_name = _extract_app_name_from_query(query)
        if app_name:
            logger.info(f"Win+Search launch: '{app_name}' extracted from '{query}'")
            launch_result = launch_app(app_name)

            if launch_result.get("success"):
                summary = app_name
                raw_steps = [{
                    "step_index": 1,
                    "action": "launch_app",
                    "description": f"Open {app_name} via Win+Search",
                    "bbox_center": None,
                    "params": app_name,
                }]

                # Multi-step: if query has remaining operations after launch
                remaining = _extract_remaining_operation(query, app_name)
                if remaining:
                    import time
                    time.sleep(4.0)  # Wait for app to fully open
                    try:
                        from core.screen_capture import capture_to_base64
                        app_img = capture_to_base64(exclude_self=True, fmt="PNG")
                        if app_img:
                            from server.services.omniparser_client import parse_screenshot_full
                            app_parse = parse_screenshot_full(app_img)
                            if app_parse.elements:
                                app_element_text = _serialize_elements(app_parse.elements)
                                llm_data = _call_executor_llm(remaining, app_element_text, app_img)
                                if llm_data and llm_data.get("steps"):
                                    for i, s in enumerate(llm_data["steps"]):
                                        s["step_index"] = i + 2
                                    raw_steps.extend(llm_data["steps"])
                                    logger.info(f"In-app plan: {len(llm_data['steps'])} steps after launch")
                    except Exception as e:
                        logger.warning(f"In-app planning failed: {e}")

        # Fallback: existing LLM plan with elements (non-launch queries)
        if not raw_steps and ui_elements:
            element_text = _serialize_elements(ui_elements)
            llm_data = _call_executor_llm(query, element_text, image_base64)

        if llm_data and llm_data.get("steps"):
            raw_steps = llm_data["steps"]
            llm_goal = llm_data.get("goal", "")
            if llm_goal and len(llm_goal) <= 100:
                summary = llm_goal
            logger.info(f"LLM plan with OmniParser: {summary} ({len(raw_steps)} steps)")

    # Fallback: pure vision (no OmniParser elements to use)
    if not raw_steps and settings.USE_REAL_LLM and image_base64:
        llm_data = _call_executor_llm(query, "", image_base64)
        if llm_data and llm_data.get("steps"):
            raw_steps = llm_data["steps"]
            logger.info(f"LLM plan (vision-only fallback): {len(raw_steps)} steps")

    # Mock fallback
    if not raw_steps:
        scenario = _choose_scenario(query)
        logger.warning(f"No LLM steps generated, using mock fallback: {scenario}")
        raw_steps = _MOCK_FALLBACKS.get(scenario, _MOCK_FALLBACKS["default"]).copy()

    # ── 6. 构建 Step 列表 ──
    steps: List[Step] = []
    for step_dict in raw_steps:
        step_idx = step_dict.get("step_index", len(steps) + 1)
        raw_action = step_dict.get("action", "click")
        raw_desc = step_dict.get("description", f"Step {step_idx}")
        raw_params = step_dict.get("params")

        # Normalize params
        if isinstance(raw_params, dict):
            if "keys" in raw_params:
                raw_params = "+".join(raw_params["keys"])
            elif "text" in raw_params:
                raw_params = raw_params["text"]
            elif "seconds" in raw_params:
                raw_params = str(raw_params["seconds"])
            elif "secs" in raw_params:
                raw_params = str(raw_params["secs"])
            elif "x" in raw_params and "y" in raw_params:
                raw_params = f"{int(raw_params['x'])},{int(raw_params['y'])}"
            else:
                raw_params = None

        # Extract bbox_center from LLM response or params
        bbox_center = step_dict.get("bbox_center")
        if bbox_center is None and isinstance(raw_params, str) and ',' in raw_params:
            parts = raw_params.split(',')
            if len(parts) == 2 and parts[0].strip().isdigit():
                bbox_center = [int(parts[0].strip()), int(parts[1].strip())]

        # Store bbox_center in params as "x,y" so engine can use it
        if bbox_center and not raw_params:
            raw_params = f'{bbox_center[0]},{bbox_center[1]}'

        steps.append(Step(
            step_index=step_idx,
            action=raw_action,
            description=raw_desc,
            target_element_id=step_dict.get("target_element_id"),
            params=raw_params if isinstance(raw_params, (str, type(None))) else str(raw_params) if raw_params else None,
            status="pending",
        ))

    blueprint = Blueprint(
        name=summary,
        total_steps=len(steps),
        current_step=1,
        state="pending_confirm",
    )

    return ProcessResponse(
        task_id=str(uuid.uuid4()),
        success=True,
        intent=intent,
        ui_elements=ui_elements,
        annotated_image=annotated_image or image_base64,
        blueprint=blueprint,
        steps=steps,
        reference_resolution=reference_resolution,
        detection_meta=detection_meta,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 兼容旧接口
# ═══════════════════════════════════════════════════════════════════════════

def generate_steps(
    query: str,
    elements: Optional[List[UIElement]] = None,
    annotated_image: Optional[str] = None,
):
    """
    [兼容] 生成操作步骤 — 供旧测试使用。
    不调用 OmniParser，需要外部传入元素。
    """
    if not elements or not settings.USE_REAL_LLM:
        scenario = _choose_scenario(query)
        return _MOCK_FALLBACKS.get(scenario, _MOCK_FALLBACKS["default"]).copy(), None

    element_text = _serialize_elements(elements)
    llm_data = _call_executor_llm(query, element_text, annotated_image)

    if llm_data and llm_data.get("steps"):
        return llm_data["steps"], llm_data.get("constraints")

    scenario = _choose_scenario(query)
    return _MOCK_FALLBACKS.get(scenario, _MOCK_FALLBACKS["default"]).copy(), None


def relocate_step(
    step_action: str,
    step_description: str,
    image_base64: str,
    screen_width: int = 1920,
    screen_height: int = 1080,
):
    """
    对当前屏幕重定位指定步骤（用于操作失败后的恢复）。
    调用 OmniParser 重新检测元素 → 匹配最接近的元素。
    """
    try:
        from server.services.omniparser_client import parse_screenshot_full
        parse_result = parse_screenshot_full(image_base64)
        elements = parse_result.elements
    except Exception:
        return None, None, []

    if not elements:
        return None, None, []

    # 找最相关元素：优先 text 匹配，否则 type=button 优先级最高
    best = None
    best_score = 0
    for el in elements:
        score = 0
        if el.text and any(w in el.text for w in step_description[:10]):
            score += 3
        if el.element_type in ("button", "icon"):
            score += 2
        if el.confidence > 0.7:
            score += 1
        if score > best_score:
            best_score = score
            best = el

    if best:
        bbox = best.bbox
        return (
            best.element_id,
            {"type": "highlight_only", "highlight_bbox": [int(v) for v in bbox]},
            [e.model_dump() for e in elements],
        )
    return None, None, []
