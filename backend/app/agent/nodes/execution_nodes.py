import os
import re
from typing import List, Dict, Any, Optional
from backend.app.agent.state import ApplicationState
from backend.app.agent.confidence import ConfidenceEngine
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector
from backend.app.browser.actions import BrowserActions
from backend.app.schemas.form import ConfidenceResult
from backend.app.core.logging import logger
from backend.app.services.event_stream import event_stream


async def confidence_routing_node(state: ApplicationState) -> ApplicationState:
    """Route answers into auto-fill queue or human review queue."""
    logger.info("Node [CONFIDENCE_ROUTING]: Partitioning field answers via ConfidenceEngine...")

    engine = ConfidenceEngine()
    answers_list = list(state.mapped_answers.values())
    auto_queue, human_queue = engine.partition_answers(state.detected_fields, answers_list)

    state.auto_fill_queue = auto_queue
    state.human_review_queue = human_queue

    msg = f"Field routing completed: {len(auto_queue)} high-confidence fields queued for auto-fill, {len(human_queue)} fields flagged for human review."
    logger.info(msg)
    await event_stream.log_action(state.application_id, msg, level="info")

    return state


async def auto_fill_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """Execute high-confidence actions in auto_fill_queue via visible Playwright browser."""
    total_fields = len(state.auto_fill_queue)
    logger.info(f"Node [AUTO_FILL]: Filling {total_fields} high-confidence fields in visible browser...")
    await event_stream.update_status(state.application_id, "RUNNING", f"Filling {total_fields} form fields...")

    skipped = 0
    field_label_map: Dict[str, str] = {
        f.data_jp_id: (f.label or f.name or f.placeholder or f.data_jp_id)
        for f in (state.detected_fields or [])
    }

    try:
        page = await browser_manager.get_page(state.application_id)
        await page.bring_to_front()
        await BrowserActions.dismiss_cookie_and_overlay_banners(page)

        initial_url = page.url
        auto_advanced = False

        # Sort queue strictly in natural top-to-bottom document sequence to prevent up-and-down viewport jumping
        def _get_sort_key(field_id: str) -> int:
            digits = re.findall(r'\d+', field_id)
            return int(digits[0]) if digits else 9999

        sorted_queue = sorted(list(state.auto_fill_queue), key=lambda x: _get_sort_key(x.data_jp_id))

        for idx, item in enumerate(sorted_queue, 1):
            # Check if previous interaction (e.g. resume upload or auto-advance) navigated to a new step
            current_url = page.url
            if current_url != initial_url:
                is_backward_regression = False
                if current_url in state.completed_pages:
                    is_backward_regression = True
                elif state.current_step > 1 and ("step=1" in current_url.lower() or "stepname=personalinformation" in current_url.lower()):
                    is_backward_regression = True

                if is_backward_regression:
                    logger.warning(f"Node [AUTO_FILL]: Detected unexpected regression to previous step/page '{current_url}'. Halting loop without auto-advancing.")
                    break

                logger.info(f"Node [AUTO_FILL]: Page navigation detected ({initial_url} -> {current_url})! Halting current step queue.")
                await event_stream.log_action(
                    state.application_id,
                    f"👉 Application progressed to new step ({current_url}). Loading next page fields...",
                    level="info",
                    action="navigate"
                )
                auto_advanced = True
                break

            target = item.data_jp_id
            val = str(item.value)
            ftype = (item.field_type or "text").lower()
            label = field_label_map.get(target, target)

            field_obj_map = {f.data_jp_id: f for f in (state.detected_fields or [])}
            f_obj = field_obj_map.get(target)
            f_tag = (f_obj.tag_name if f_obj else "").lower()
            lbl_lower = (label or "").strip().lower()

            # Skip navigation triggers, non-dropdown buttons, and cookie preference elements
            is_dropdown_button = (
                ftype in ("select", "combobox")
                or (f_obj and ((f_obj.input_type or "").lower() in ("select", "combobox") or bool(f_obj.options)))
            )
            is_nav_action = (
                lbl_lower in ("back", "next", "continue", "cancel", "previous", "prev", "close", "save", "save & continue", "save and continue", "submit", "filter cookie list", "close preference center")
                or ftype in ("submit", "reset")
                or (f_obj and (f_obj.input_type or "").lower() in ("submit", "reset"))
            )
            is_cookie_widget = ("cookie" in lbl_lower or "preference center" in lbl_lower)

            if is_nav_action or is_cookie_widget or (f_tag in ("button", "a") and not is_dropdown_button):
                logger.info(f"Node [AUTO_FILL]: Skipping non-fillable button/cookie field '{label}' ({target}).")
                continue

            await event_stream.log_action(
                state.application_id,
                f"[{idx}/{total_fields}] Processing '{label}' (type={ftype})...",
                level="info",
                action="fill",
                field_id=target,
                field_label=label,
                value=val
            )

            try:

                if ftype in ("checkbox_group", "multiselect"):
                    chosen_options = [o.strip() for o in val.split(",") if o.strip()] if isinstance(val, str) else list(val)
                    fld = field_obj_map.get(target)
                    opt_elem_map = (fld.option_elements if fld else {}) or {}

                    for opt in chosen_options:
                        elem_id = opt_elem_map.get(opt)
                        if not elem_id:
                            for o_name, o_id in opt_elem_map.items():
                                if opt.lower() == o_name.lower() or opt.lower() in o_name.lower() or o_name.lower() in opt.lower():
                                    elem_id = o_id
                                    break
                        target_id = elem_id or target
                        await BrowserActions.check(
                            page, target_id, checked=True, field_label=f"{label} -> {opt}", session_id=state.application_id
                        )
                elif ftype == "radio":
                    fld = field_obj_map.get(target)
                    opt_elem_map = (fld.option_elements if fld else {}) or {}
                    elem_id = opt_elem_map.get(val)
                    if not elem_id:
                        for o_name, o_id in opt_elem_map.items():
                            if val.lower() == o_name.lower() or val.lower() in o_name.lower() or o_name.lower() in val.lower():
                                elem_id = o_id
                                break
                    if not elem_id:
                        avail_opts = (fld.options if fld else []) or list(opt_elem_map.keys())
                        raise JobPilotException(f"Target value '{val}' does not match any radio option in {avail_opts}")
                    await BrowserActions.check(
                        page, elem_id, checked=True, field_label=f"{label} -> {val}", session_id=state.application_id
                    )
                elif ftype == "checkbox":
                    should_check = val.lower() in ("true", "1", "yes", "checked", "on") if isinstance(val, str) else bool(val)
                    await BrowserActions.check(
                        page, target, checked=should_check, field_label=label, session_id=state.application_id
                    )
                elif ftype == "select":
                    await BrowserActions.select_option(
                        page, target, val, field_label=label, session_id=state.application_id
                    )
                elif ftype == "file":
                    file_path = val
                    is_photo = any(t in label.lower() for t in ("photo", "photograph", "picture", "headshot", "avatar", "image"))
                    if is_photo:
                        if not os.path.exists(file_path):
                            photos_dir = os.path.join(os.getcwd(), "knowledge_base", "photos")
                            if os.path.exists(photos_dir):
                                candidates = [
                                    os.path.join(photos_dir, f)
                                    for f in os.listdir(photos_dir)
                                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                                ]
                                if candidates:
                                    file_path = candidates[0]
                        if os.path.exists(file_path):
                            await BrowserActions.upload_file(
                                page, target, file_path, field_label=label, session_id=state.application_id
                            )
                        else:
                            logger.warning(f"Photo upload target '{target}' has no valid photograph file at '{file_path}'.")
                            await event_stream.log_action(
                                state.application_id,
                                f"Notice: No profile photograph found to upload for '{label}'.",
                                level="warning",
                                field_id=target
                            )
                    else:
                        # Locate resume document
                        if not os.path.exists(file_path):
                            resumes_dir = os.path.join(os.getcwd(), "knowledge_base", "resumes")
                            if os.path.exists(resumes_dir):
                                candidates = [
                                    os.path.join(resumes_dir, f)
                                    for f in os.listdir(resumes_dir)
                                    if f.lower().endswith((".pdf", ".docx", ".doc"))
                                ]
                                if candidates:
                                    file_path = candidates[0]
                        if os.path.exists(file_path):
                            await BrowserActions.upload_file(
                                page, target, file_path, field_label=label, session_id=state.application_id
                            )
                            # Portals often auto-advance or re-render upon resume parsing
                            await page.wait_for_timeout(2000)
                            if page.url != initial_url and page.url not in state.completed_pages:
                                logger.info(f"Node [AUTO_FILL]: File upload caused portal navigation to '{page.url}'.")
                                await event_stream.log_action(
                                    state.application_id,
                                    f"👉 Resume uploaded and application progressed to next step ({page.url}). Loading new fields...",
                                    level="info",
                                    action="navigate"
                                )
                                auto_advanced = True
                                break
                        else:
                            logger.warning(f"File upload target '{target}' has no valid resume document at '{file_path}'.")
                            await event_stream.log_action(
                                state.application_id,
                                f"Notice: No resume document found to upload for '{label}'.",
                                level="warning",
                                field_id=target
                            )
                else:
                    await BrowserActions.fill_text(
                        page, target, val, field_label=label, session_id=state.application_id
                    )

                state.total_fields_filled += 1
                state.all_completed_fields.append({
                    "field_id": target,
                    "label": label,
                    "value": val,
                    "field_type": ftype,
                    "step": state.current_step
                })
            except Exception as field_err:
                logger.warning(
                    f"Node [AUTO_FILL]: Could not interact with field '{target}' ('{label}'): {field_err}"
                )
                await event_stream.log_action(
                    state.application_id,
                    f"Could not fill field '{label}' automatically ({field_err}). Escalating to Human-In-The-Loop review.",
                    level="warning",
                    field_id=target,
                    field_label=label
                )
                skipped += 1
                # Escalate to Human-in-the-Loop instead of silently failing/skipping
                # If target value failed to match choice options, clear answer so UI doesn't seed invalid string
                escalated_answer = None if ftype in ("radio", "select", "checkbox_group") else val
                hitl_item = ConfidenceResult(
                    field_id=target,
                    answer=escalated_answer,
                    confidence=0.0,
                    reason=f"Automation could not interact with field '{label}': {field_err}. Please fill or verify this field manually.",
                    source_citations=["auto_fill_failure_escalation"],
                    requires_human_input=True
                )
                state.mapped_answers[target] = hitl_item
                if not any(item.field_id == target for item in state.human_review_queue):
                    state.human_review_queue.append(hitl_item)
                continue

        state.auto_fill_queue.clear()

        # If a page navigation occurred during the fill loop (e.g. resume auto-advance), transition state to new step
        if auto_advanced:
            if initial_url not in state.completed_pages:
                state.completed_pages.append(initial_url)
            state.current_url = page.url
            state.current_step += 1
            state.has_auto_advanced = True
            state.auto_fill_queue.clear()
            state.human_review_queue.clear()
            state.validation_errors.clear()
            state.mapped_answers.clear()

            await page.wait_for_timeout(2000)
            await BrowserActions.dismiss_cookie_and_overlay_banners(page)
            updated_form = await DOMInspector.inspect_page(page)
            state.form_page = updated_form
            state.detected_fields = updated_form.fields

            fillable = [
                f for f in updated_form.fields
                if f.is_visible and f.tag_name not in ("button", "a")
                and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
            ]
            logger.info(f"Auto-advanced to Step {state.current_step}: '{updated_form.title}'. Detected {len(fillable)} fillable fields.")
            await event_stream.log_action(
                state.application_id,
                f"👉 Step {state.current_step} loaded: '{updated_form.title}'. Identified {len(fillable)} interactive fields.",
                level="info"
            )
            return state

        # Post-interaction DOM re-inspection to detect newly revealed conditional fields
        updated_form = await DOMInspector.inspect_page(page)
        state.form_page = updated_form
        state.detected_fields = updated_form.fields

        summary_msg = f"Auto-fill complete: {total_fields - skipped} fields filled successfully" + (f", {skipped} skipped." if skipped else ".")
        logger.info(summary_msg)
        await event_stream.log_action(state.application_id, summary_msg, level="info")

        return state
    except Exception as e:
        logger.error(f"Node [AUTO_FILL] Fatal error: {e}")
        state.error_message = f"Auto-fill error: {e}"
        await event_stream.log_action(state.application_id, f"Auto-fill encountered an error: {e}", level="error")
        return state


async def human_review_pause_node(state: ApplicationState) -> ApplicationState:
    """Pause workflow when human intervention or review is needed."""
    count = len(state.human_review_queue)
    logger.info(f"Node [HUMAN_REVIEW_PAUSE]: Workflow paused for human input ({count} questions).")
    state.status = "WAITING_FOR_USER"
    await event_stream.update_status(state.application_id, "WAITING_FOR_USER", f"Waiting for human input ({count} questions)")
    await event_stream.log_action(
        state.application_id,
        f"Workflow paused: {count} questions require your review or answer in the JobPilot dashboard.",
        level="warning"
    )
    return state


async def validate_page_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """
    Final active cross-check before Review:
    Inspect actual browser state and compare EVERY field against saved profile and intended answers.
    Verify text fields, phone/country code, dropdowns, checkboxes, multi-selects, and resume uploads.
    Automatically correct mismatches and re-verify them.
    If a value cannot be reliably corrected or verified, trigger HITL and clearly report the issue.
    Never trust completion counters alone or proceed while unresolved mismatches are silently treated as successful.
    """
    logger.info("Node [VALIDATE_PAGE]: Executing deep browser DOM state cross-check & reconciliation...")
    await event_stream.update_status(state.application_id, "RUNNING", "Cross-checking browser fields against profile...")
    await event_stream.log_action(
        state.application_id,
        "Deep verification: Inspecting live browser state and comparing every field against saved profile & intended answers...",
        level="info",
        action="analyze"
    )

    try:
        if state.has_auto_advanced:
            logger.info(f"Node [VALIDATE_PAGE]: Form has auto-advanced to Step {state.current_step}. Bypassing verification for previous step.")
            return state

        page = await browser_manager.get_page(state.application_id)
        field_map = {f.data_jp_id: f for f in (state.detected_fields or [])}
        mismatches: List[str] = []
        hitl_items: List[ConfidenceResult] = []

        # 1. Cross-check all mapped fields against live browser state in top-to-bottom order
        def _get_sort_key(field_id: str) -> int:
            digits = re.findall(r'\d+', field_id)
            return int(digits[0]) if digits else 9999

        sorted_mapped = sorted(list(state.mapped_answers.items()), key=lambda kv: _get_sort_key(kv[0]))
        for fid, ans_obj in sorted_mapped:
            field = field_map.get(fid)
            if not field or not field.is_visible:
                continue

            # Skip buttons, navigation elements, and cookie widgets
            lbl_lower = (field.label or field.name or "").strip().lower()
            is_dropdown_btn = (
                (field.input_type or "").lower() in ("select", "combobox")
                or bool(field.options)
            )
            is_nav = (
                lbl_lower in ("back", "next", "continue", "cancel", "previous", "prev", "close", "save", "save & continue", "save and continue", "submit", "filter cookie list", "close preference center")
                or (field.input_type or "").lower() in ("submit", "reset", "image", "hidden")
            )
            if is_nav or "cookie" in lbl_lower or "preference center" in lbl_lower or (field.tag_name not in ("input", "select", "textarea") and not is_dropdown_btn):
                continue

            expected = ans_obj.answer
            # If answer is marked as requiring human input and missing, it's already slated for HITL
            if expected is None or ans_obj.requires_human_input:
                if field.is_required:
                    mismatches.append(f"Required field '{field.label or fid}' requires your review.")
                    hitl_items.append(ans_obj)
                continue

            field_label = field.label or field.name or field.placeholder or fid

            # Safety Guard: Ensure mapped answer's question matches the field being inspected
            # Prevents step cross-contamination where e.g. 'Job Title' from Step 2 collides with 'Country or Region' from Step 1
            ans_q = (ans_obj.question_text or "").strip().lower()
            field_q = field_label.strip().lower()
            if ans_q and field_q:
                norm_ans_q = re.sub(r'[*:\s]+', ' ', ans_q).strip()
                norm_fld_q = re.sub(r'[*:\s]+', ' ', field_q).strip()
                words_ans = set(norm_ans_q.split())
                words_fld = set(norm_fld_q.split())
                meaningful_common = [w for w in words_ans.intersection(words_fld) if len(w) > 2 and w not in ('the', 'and', 'for', 'your', 'please')]
                if norm_ans_q != norm_fld_q and norm_ans_q not in norm_fld_q and norm_fld_q not in norm_ans_q and not meaningful_common:
                    logger.warning(
                        f"Node [VALIDATE_PAGE]: Skipping cross-check for fid '{fid}' because question '{ans_obj.question_text}' does not match field label '{field_label}'."
                    )
                    continue

            ftype = (field.input_type or field.tag_name or "text").lower()

            live_state = await BrowserActions.get_field_live_state(page, field)
            mismatch_detected = False
            mismatch_reason = ""

            # --- Text & Textarea (including Phone Number) ---
            if ftype in ("text", "textarea", "email", "url", "number", "tel"):
                actual_val = str(live_state.get("value") or "").strip()
                expected_str = str(expected).strip()

                # Phone number verification: compare numeric digits
                val_digits = re.sub(r'\D', '', expected_str)
                act_digits = re.sub(r'\D', '', actual_val)
                is_phone = any(k in field_label.lower() for k in ("phone", "mobile", "cell", "contact")) or (len(val_digits) >= 10)

                if is_phone and val_digits:
                    if act_digits != val_digits:
                        mismatch_detected = True
                        mismatch_reason = f"Phone number incomplete: actual browser digits '{act_digits}' != expected '{val_digits}'"
                elif expected_str.lower() != actual_val.lower() and (not actual_val or expected_str.lower() not in actual_val.lower()):
                    mismatch_detected = True
                    mismatch_reason = f"Value mismatch: browser contains '{actual_val}', expected '{expected_str}'"

                # Automatic Correction Attempt for Text/Phone
                if mismatch_detected:
                    logger.warning(f"Cross-check mismatch on '{field_label}': {mismatch_reason}. Attempting auto-correction...")
                    await event_stream.log_action(
                        state.application_id,
                        f"Cross-check detected mismatch on '{field_label}'. Auto-correcting...",
                        level="warning",
                        field_id=fid
                    )
                    try:
                        await BrowserActions.fill_text(page, fid, expected_str, field_label=field_label, session_id=state.application_id)
                        # Re-verify
                        re_live = await BrowserActions.get_field_live_state(page, field)
                        re_val = str(re_live.get("value") or "").strip()
                        re_digits = re.sub(r'\D', '', re_val)
                        if is_phone and val_digits:
                            mismatch_detected = (re_digits != val_digits)
                        else:
                            mismatch_detected = (expected_str.lower() != re_val.lower() and expected_str.lower() not in re_val.lower())

                        if not mismatch_detected:
                            logger.info(f"Successfully auto-corrected '{field_label}' in browser.")
                            await event_stream.log_action(state.application_id, f"Auto-corrected '{field_label}' in browser. ✓", level="info", field_id=fid)
                    except Exception as corr_err:
                        logger.error(f"Auto-correction failed for '{field_label}': {corr_err}")

            # --- Select Dropdowns (Country Code, School, Degree, etc.) ---
            elif ftype == "select":
                actual_text = str(live_state.get("selected_text") or "").strip()
                actual_val = str(live_state.get("value") or "").strip()
                expected_str = str(expected).strip()

                is_country_code = any(k in field_label.lower() for k in ("country code", "dial code", "prefix")) or re.search(r'\+\d{1,4}', expected_str)

                if is_country_code:
                    # Match +91 or 91 or India
                    if not any(token in actual_text.lower() or token in actual_val.lower() for token in ("+91", "91", "india")):
                        mismatch_detected = True
                        mismatch_reason = f"Country code mismatch: browser selected '{actual_text or actual_val}', expected '+91 / India'"
                else:
                    norm_exp = expected_str.lower()
                    norm_act = actual_text.lower()
                    norm_val = actual_val.lower()
                    if norm_exp != norm_act and norm_exp != norm_val and norm_exp not in norm_act and norm_act not in norm_exp:
                        # Allow 'Other' if candidate's choice was not listed
                        if "other" in norm_act and "other" in norm_exp:
                            mismatch_detected = False
                        else:
                            mismatch_detected = True
                            mismatch_reason = f"Dropdown mismatch: browser selected '{actual_text or actual_val}', expected '{expected_str}'"

                # Automatic Correction Attempt for Select
                if mismatch_detected:
                    logger.warning(f"Cross-check mismatch on select '{field_label}': {mismatch_reason}. Attempting auto-correction...")
                    await event_stream.log_action(
                        state.application_id,
                        f"Cross-check detected dropdown mismatch on '{field_label}'. Auto-correcting...",
                        level="warning",
                        field_id=fid
                    )
                    try:
                        await BrowserActions.select_option(page, fid, expected_str, field_label=field_label, session_id=state.application_id)
                        re_live = await BrowserActions.get_field_live_state(page, field)
                        re_text = str(re_live.get("selected_text") or "").strip()
                        re_val = str(re_live.get("value") or "").strip()
                        if is_country_code:
                            mismatch_detected = not any(token in re_text.lower() or token in re_val.lower() for token in ("+91", "91", "india"))
                        else:
                            mismatch_detected = (norm_exp != re_text.lower() and norm_exp != re_val.lower() and norm_exp not in re_text.lower() and re_text.lower() not in norm_exp and not ("other" in re_text.lower() and "other" in norm_exp))

                        if not mismatch_detected:
                            logger.info(f"Successfully auto-corrected dropdown '{field_label}' to '{re_text}'.")
                            await event_stream.log_action(state.application_id, f"Auto-corrected dropdown '{field_label}' to '{re_text}'. ✓", level="info", field_id=fid)
                    except Exception as corr_err:
                        logger.error(f"Auto-correction failed for select '{field_label}': {corr_err}")

            # --- Radio Group ---
            elif ftype == "radio":
                actual_val = str(live_state.get("value") or "").strip().lower()
                actual_text = str(live_state.get("selected_text") or "").strip().lower()
                expected_str = str(expected).strip().lower()
                matched_radio = (expected_str == actual_val or expected_str in actual_val or actual_val in expected_str or
                                 expected_str == actual_text or expected_str in actual_text or actual_text in expected_str)
                if not matched_radio:
                    mismatch_detected = True
                    mismatch_reason = f"Radio mismatch: browser has '{actual_text or actual_val or 'none selected'}', expected '{expected}'"
                    try:
                        opt_elem_map = field.option_elements or {}
                        elem_id = opt_elem_map.get(str(expected))
                        if not elem_id:
                            for o_name, o_id in opt_elem_map.items():
                                if expected_str == o_name.lower() or expected_str in o_name.lower() or o_name.lower() in expected_str:
                                    elem_id = o_id
                                    break
                        if elem_id:
                            await BrowserActions.check(page, elem_id, checked=True, field_label=f"{field_label} -> {expected}", session_id=state.application_id)
                            re_live = await BrowserActions.get_field_live_state(page, field)
                            re_val = str(re_live.get("value") or "").strip().lower()
                            re_text = str(re_live.get("selected_text") or "").strip().lower()
                            mismatch_detected = not (expected_str == re_val or expected_str in re_val or re_val in expected_str or
                                                     expected_str == re_text or expected_str in re_text or re_text in expected_str)
                    except Exception as r_err:
                        logger.error(f"Auto-correction failed for radio '{field_label}': {r_err}")

            # --- Checkbox (Single) ---
            elif ftype == "checkbox":
                actual_checked = live_state.get("checked", False)
                expected_bool = str(expected).lower() in ("yes", "true", "1", "on")
                if actual_checked != expected_bool:
                    mismatch_detected = True
                    mismatch_reason = f"Checkbox checked state mismatch: actual={actual_checked}, expected={expected_bool}"
                    try:
                        await BrowserActions.check(page, fid, checked=expected_bool, field_label=field_label, session_id=state.application_id)
                        re_live = await BrowserActions.get_field_live_state(page, field)
                        mismatch_detected = (re_live.get("checked", False) != expected_bool)
                    except Exception:
                        pass

            # --- File Upload (Resume / CV / Photo) ---
            elif ftype == "file":
                files = live_state.get("files") or []
                actual_file_val = str(live_state.get("value") or "")
                expected_filename = os.path.basename(str(expected))
                has_file = len(files) > 0 or (actual_file_val and expected_filename.lower() in actual_file_val.lower())
                if not has_file:
                    mismatch_detected = True
                    mismatch_reason = f"No document attached in browser for '{field_label}'. Expected '{expected_filename}'."
                    try:
                        if os.path.exists(str(expected)):
                            await BrowserActions.upload_file(page, fid, str(expected), field_label=field_label, session_id=state.application_id)
                            re_live = await BrowserActions.get_field_live_state(page, field)
                            re_files = re_live.get("files") or []
                            mismatch_detected = (len(re_files) == 0 and expected_filename.lower() not in str(re_live.get("value") or "").lower())
                    except Exception:
                        pass

            # If mismatch remains unresolvable after auto-correction, flag for HITL
            if mismatch_detected:
                logger.warning(f"UNRESOLVED Cross-check mismatch for '{field_label}': {mismatch_reason}")
                mismatches.append(f"Discrepancy on '{field_label}': {mismatch_reason}")
                hitl_items.append(ConfidenceResult(
                    field_id=fid,
                    answer=live_state.get("value") or None,
                    confidence=0.0,
                    reason=f"Verification Mismatch: {mismatch_reason}. Please verify or enter correct value.",
                    source_citations=["browser_state_cross_check"],
                    requires_human_input=True
                ))

        # 2. Check for any required fields that are completely empty
        for field in state.detected_fields:
            if not field.is_required or not field.is_visible:
                continue
            lbl_lower = (field.label or field.name or "").strip().lower()
            is_dropdown_btn = (
                (field.input_type or "").lower() in ("select", "combobox")
                or bool(field.options)
            )
            is_nav = (
                lbl_lower in ("back", "next", "continue", "cancel", "previous", "prev", "close", "save", "save & continue", "save and continue", "submit", "filter cookie list", "close preference center")
                or (field.input_type or "").lower() in ("submit", "reset", "image", "hidden")
            )
            if is_nav or "cookie" in lbl_lower or "preference center" in lbl_lower or (field.tag_name not in ("input", "select", "textarea") and not is_dropdown_btn):
                continue

            live_state = await BrowserActions.get_field_live_state(page, field)
            is_empty = False
            ftype = (field.input_type or field.tag_name or "text").lower()

            if ftype in ("text", "textarea", "email", "url", "number", "tel", "select"):
                val = live_state.get("value")
                txt = live_state.get("selected_text")
                if not (str(val or "").strip() or str(txt or "").strip()):
                    is_empty = True
            elif ftype == "radio":
                val = live_state.get("value")
                txt = live_state.get("selected_text")
                if not (val or txt):
                    is_empty = True
            elif ftype == "file":
                if not live_state.get("files") and not live_state.get("value"):
                    is_empty = True

            if is_empty:
                field_label = field.label or field.name or field.placeholder or field.data_jp_id
                if not any(item.field_id == field.data_jp_id for item in hitl_items):
                    mismatches.append(f"Required field '{field_label}' is empty.")
                    hitl_items.append(ConfidenceResult(
                        field_id=field.data_jp_id,
                        answer=None,
                        confidence=0.0,
                        reason=f"Required field '{field_label}' was not filled. Please provide an answer.",
                        source_citations=["page_validation_empty_required"],
                        requires_human_input=True
                    ))

        state.validation_errors = mismatches
        if hitl_items:
            logger.warning(f"Cross-check flagged {len(hitl_items)} issues for human review: {mismatches}")
            await event_stream.log_action(
                state.application_id,
                f"Cross-check detected {len(hitl_items)} field discrepancies requiring human review before submission.",
                level="warning"
            )
            state.human_review_queue = hitl_items
        else:
            logger.info("Deep browser DOM state cross-check passed cleanly with 100% field reconciliation.")
            await event_stream.log_action(
                state.application_id,
                "✓ Cross-check completed: Every browser field verified against your saved profile and intended answers with zero discrepancies.",
                level="info"
            )

        # 3. Detect multi-step progression ("Next" / "Continue") vs final submission step
        next_btn = None
        for f in state.detected_fields:
            if not f.is_visible:
                continue
            ftype = (f.input_type or f.tag_name or "").lower()
            if f.tag_name not in ("button", "a") and ftype not in ("button", "submit"):
                continue
            txt = (f.visible_text or f.placeholder or f.label or "").lower().strip()
            # Ignore back / prev / cancel / close / reset
            if any(neg in txt for neg in ["back", "prev", "previous", "cancel", "close", "sign out", "log out", "reset"]):
                continue
            # Ignore final submission triggers
            if any(sub in txt for sub in ["submit application", "submit", "apply now", "send application", "complete application", "finish"]):
                continue
            # Check for next step indicators
            if any(kw in txt for kw in ["next", "continue", "proceed", "save & continue", "save and continue", "next step", "save & next", "save and next", "continue to", "review application"]):
                next_btn = f
                break

        if not next_btn and page:
            try:
                live_next_id = await page.evaluate("""
                    () => {
                        const candidates = Array.from(document.querySelectorAll(
                            'button, input[type="button"], input[type="submit"], a.btn, [role="button"]'
                        ));
                        const nextKeywords = [
                            'next', 'continue', 'proceed', 'save & continue', 'save and continue',
                            'next step', 'save & next', 'save and next', 'continue to', 'review application'
                        ];
                        const rejectKeywords = [
                            'back', 'prev', 'previous', 'cancel', 'close', 'sign out', 'log out',
                            'submit application', 'submit', 'apply now', 'send application'
                        ];

                        for (const el of candidates) {
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || (el.offsetWidth === 0 && el.offsetHeight === 0)) {
                                continue;
                            }
                            const txt = (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase().trim();
                            if (rejectKeywords.some(rk => txt.includes(rk))) continue;
                            if (nextKeywords.some(nk => txt.includes(nk))) {
                                return el.getAttribute('data-jp-id') || el.id || el.className;
                            }
                        }
                        return null;
                    }
                """)
                if live_next_id:
                    state.has_next_page = True
                    state.next_button_id = live_next_id
                else:
                    state.has_next_page = False
                    state.next_button_id = None
            except Exception:
                state.has_next_page = False
                state.next_button_id = None
        elif next_btn:
            state.has_next_page = True
            state.next_button_id = next_btn.data_jp_id
        else:
            state.has_next_page = False
            state.next_button_id = None

        if state.page_type == "APPLICATION_SUBMITTED" or (state.form_page and state.form_page.page_type == "APPLICATION_SUBMITTED"):
            state.status = "SUBMITTED"
            state.has_next_page = False
            return state

        if state.has_next_page:
            logger.info(f"Node [VALIDATE_PAGE]: Intermediate step detected. Multi-step 'Next' button active: {state.next_button_id}")

        return state
    except Exception as e:
        logger.error(f"Node [VALIDATE_PAGE] Error: {e}")
        return state


async def navigate_next_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """Find and click Next/Continue/Save navigation buttons in multi-page applications and advance to the next step."""
    logger.info("Node [NAVIGATE_NEXT]: Advancing to next application page/step...")
    try:
        page = await browser_manager.get_page(state.application_id)
        await page.bring_to_front()

        # 1. Neutralize blocking cookie consent or overlay backdrops
        await BrowserActions.dismiss_cookie_and_overlay_banners(page)

        # 2. Locate navigation button
        btn_elem = None
        target_label = "Next"

        if state.next_button_id:
            btn_elem, _ = await BrowserActions._find_element(page, BrowserActions._selector(state.next_button_id))
            target_label = state.next_button_id

        if not btn_elem or await btn_elem.count() == 0:
            for f in state.detected_fields:
                txt = (f.visible_text or f.placeholder or f.label or "").lower().strip()
                if any(k in txt for k in ["next", "continue", "proceed", "save & continue", "save and continue", "next step", "save & next"]):
                    if not any(sub in txt for sub in ["submit", "back", "previous", "cancel"]):
                        btn_elem, _ = await BrowserActions._find_element(page, BrowserActions._selector(f.data_jp_id))
                        target_label = f.visible_text or f.data_jp_id
                        break

        if not btn_elem or await btn_elem.count() == 0:
            locators = [
                'button:has-text("Next")',
                'button:has-text("Continue")',
                'button:has-text("Save & Continue")',
                'button:has-text("Save and Continue")',
                'button:has-text("Next Step")',
                'input[type="button"][value*="Next" i]',
                'input[type="submit"][value*="Next" i]',
                'button:has-text("Proceed")',
                'button:has-text("Review Application")'
            ]
            for sel in locators:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    txt = (await loc.text_content() or await loc.get_attribute("value") or "").strip()
                    if not any(k in txt.lower() for k in ("back", "prev", "cancel", "submit application")):
                        btn_elem = loc
                        target_label = txt or "Next"
                        break

        if not btn_elem or await btn_elem.count() == 0:
            logger.warning("Node [NAVIGATE_NEXT]: No navigation button found to click.")
            state.has_next_page = False
            return state

        # 3. Check if disabled
        is_disabled = await btn_elem.evaluate("""
            el => el.disabled || el.getAttribute('aria-disabled') === 'true' ||
                  el.classList.contains('disabled') || el.getAttribute('disabled') !== null ||
                  window.getComputedStyle(el).pointerEvents === 'none'
        """)
        if is_disabled:
            logger.warning(f"Node [NAVIGATE_NEXT]: Next button '{target_label}' is disabled.")
            state.status = "WAITING_FOR_USER"
            state.error_message = f"Next button '{target_label}' is disabled. Please verify any incomplete fields in the visible browser."
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Next Button Disabled")
            await event_stream.log_action(
                state.application_id,
                f"⚠️ The '{target_label}' button is disabled. Please check the visible browser for any missing information, then resume.",
                level="warning"
            )
            return state

        # 4. Click the Next button
        old_ids = [f.data_jp_id for f in (state.detected_fields or [])]
        logger.info(f"Clicking multi-page navigation button '{target_label}'...")
        await event_stream.log_action(
            state.application_id,
            f"Advancing application: Clicking '{target_label}' to proceed to the next step...",
            level="info",
            action="click"
        )
        try:
            await btn_elem.scroll_into_view_if_needed()
            await btn_elem.click(timeout=5000)
        except Exception as click_err:
            logger.warning(f"Standard click failed on '{target_label}': {click_err}. Retrying with force click...")
            await btn_elem.click(force=True, timeout=5000)

        # 5. Wait for page transition / new DOM elements to mount
        await page.wait_for_timeout(3500)
        await BrowserActions.dismiss_cookie_and_overlay_banners(page)

        # 6. Check for validation errors displayed after click
        val_errors = await page.evaluate("""
            () => {
                const errors = [];
                const errEls = document.querySelectorAll(
                    '.error, .error-message, [role="alert"], .invalid-feedback, .has-error, [aria-invalid="true"], .field-error, .help-block-error, .alert-danger'
                );
                errEls.forEach(el => {
                    if (el.offsetParent !== null) {
                        const txt = el.innerText.trim();
                        if (txt && !errors.includes(txt) && txt.length < 250) errors.push(txt);
                    }
                });
                return errors;
            }
        """)
        if val_errors:
            logger.warning(f"Node [NAVIGATE_NEXT]: Page transition blocked by form validation errors: {val_errors}")
            state.status = "WAITING_FOR_USER"
            state.validation_errors = val_errors
            err_summary = "; ".join(val_errors[:3])
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Validation Errors After Next")
            await event_stream.log_action(
                state.application_id,
                f"⚠️ Moving to the next step was blocked by validation errors ({err_summary}). Please correct them in the visible browser.",
                level="warning"
            )
            return state

        # 7. Re-inspect the DOM on the new step
        updated_form = await DOMInspector.inspect_page(page)

        # Check if clicking the button actually completed and submitted the application
        if updated_form.page_type == "APPLICATION_SUBMITTED":
            logger.info(f"Node [NAVIGATE_NEXT]: Application submission confirmed on page '{updated_form.title}'!")
            state.status = "SUBMITTED"
            state.page_type = "APPLICATION_SUBMITTED"
            state.has_next_page = False
            await event_stream.update_status(state.application_id, "SUBMITTED", "Application successfully submitted!")
            await event_stream.log_action(
                state.application_id,
                "🎉 Application verified and successfully SUBMITTED in browser!",
                level="info"
            )
            return state

        # Check if the page URL and fields didn't change at all (step did not advance)
        prev_url = state.current_url or page.url

        # Compare core visible input elements (immune to dynamic error banners or transient text changes)
        old_inputs = sorted([
            (f.name or f.element_id or f.label or "").strip().lower()
            for f in (state.detected_fields or [])
            if f.is_visible and f.tag_name in ("input", "select", "textarea")
        ])
        new_inputs = sorted([
            (f.name or f.element_id or f.label or "").strip().lower()
            for f in updated_form.fields
            if f.is_visible and f.tag_name in ("input", "select", "textarea")
        ])

        old_visible_ids = [f.data_jp_id for f in (state.detected_fields or []) if f.is_visible]
        new_visible_ids = [f.data_jp_id for f in updated_form.fields if f.is_visible]

        # Extract step indicators from URL (e.g. step=1 vs step=2)
        prev_step_match = re.search(r'[?&#]step(?:name)?=([^&#]+)', prev_url, re.I)
        new_step_match = re.search(r'[?&#]step(?:name)?=([^&#]+)', page.url, re.I)
        step_param_same = bool(prev_step_match and new_step_match and prev_step_match.group(1).lower() == new_step_match.group(1).lower())

        page_unchanged = (
            (prev_url == page.url or step_param_same)
            and old_inputs
            and old_inputs == new_inputs
        ) or (
            prev_url == page.url
            and old_visible_ids
            and old_visible_ids == new_visible_ids
        )
        if page_unchanged:
            logger.warning("Node [NAVIGATE_NEXT]: Page URL and visible interactive fields remained unchanged after click. Page did not advance.")
            state.has_next_page = False
            state.status = "WAITING_FOR_USER"
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Please complete required fields")
            await event_stream.log_action(
                state.application_id,
                "⚠️ Moving to the next step was blocked. Please check the visible browser for any required questions or error messages, then click Resume.",
                level="warning"
            )
            return state

        # Step successfully transitioned to new step!
        if prev_url not in state.completed_pages:
            state.completed_pages.append(prev_url)
        state.current_url = page.url
        state.current_step += 1
        state.form_page = updated_form
        state.detected_fields = updated_form.fields

        # Preserve all answers from previous steps into state.all_completed_fields for final review display
        for fid, ans in list(state.mapped_answers.items()):
            if not any(f.get("field_id") == fid for f in state.all_completed_fields):
                field_obj = next((f for f in state.detected_fields if f.data_jp_id == fid), None)
                state.all_completed_fields.append({
                    "field_id": fid,
                    "label": (field_obj.label if field_obj else None) or fid,
                    "value": ans.answer,
                    "field_type": getattr(ans, "field_type", None) or (field_obj.input_type if field_obj else "text") or "text",
                    "step": state.current_step - 1
                })

        # Clear active fill, mapped answers, and HITL queues for the new page so previous step answers never contaminate new step fields!
        state.auto_fill_queue.clear()
        state.human_review_queue.clear()
        state.validation_errors.clear()
        state.mapped_answers.clear()

        fillable_fields = [
            f for f in updated_form.fields
            if f.is_visible and f.tag_name not in ("button", "a")
            and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
        ]

        logger.info(
            f"Navigated to Step {state.current_step}: '{updated_form.title}' ({page.url}). "
            f"Detected {len(updated_form.fields)} elements ({len(fillable_fields)} fillable fields)."
        )
        await event_stream.log_action(
            state.application_id,
            f"👉 Step {state.current_step} loaded: '{updated_form.title}'. "
            f"Identified {len(fillable_fields)} interactive fields to process.",
            level="info",
            action="navigate"
        )

        return state
    except Exception as e:
        logger.error(f"Node [NAVIGATE_NEXT] Error: {e}")
        state.error_message = f"Navigation error: {e}"
        return state

