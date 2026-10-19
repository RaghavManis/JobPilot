from typing import Optional
from backend.app.agent.state import ApplicationState
from backend.app.browser.manager import BrowserManager
from backend.app.browser.actions import BrowserActions
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException
from backend.app.services.event_stream import event_stream


async def final_review_node(
    state: ApplicationState,
    browser_manager: Optional[BrowserManager] = None
) -> ApplicationState:
    """Summarize application completion state before final submission."""
    # Safety Check: Never claim application ready for review if 0 fields were processed across all steps
    total_processed = len(state.mapped_answers) + state.total_fields_filled + len(state.all_completed_fields)
    fillable_fields = [
        f for f in (state.detected_fields or [])
        if f.is_visible and f.tag_name not in ("button", "a")
        and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
    ]
    if total_processed == 0 and len(fillable_fields) > 0 and len(state.completed_pages) == 0:
        state.status = "FAILED"
        state.error_message = "Application cannot enter Final Review because zero fields were filled or processed."
        logger.error("Node [FINAL_REVIEW]: Blocked transition to READY_FOR_REVIEW — 0 fields processed.")
        await event_stream.update_status(state.application_id, "FAILED", "0 fields processed")
        await event_stream.log_action(
            state.application_id,
            "Error: Application entered review stage with 0 fields processed. Automation halted.",
            level="error"
        )
        return state

    logger.info(f"Node [FINAL_REVIEW]: Application forms completed ({total_processed} fields processed). Transitioning to READY_FOR_REVIEW...")

    # If the review page has no input fields (summary review page), synthesize review fields from all_completed_fields
    from backend.app.schemas.form import FormField, ConfidenceResult
    has_fillable = any(
        f.tag_name not in ("button", "a") and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
        for f in state.detected_fields
    )
    if not has_fillable and state.all_completed_fields:
        logger.info(f"Node [FINAL_REVIEW]: Synthesizing review display from {len(state.all_completed_fields)} completed fields across previous steps.")
        for item in state.all_completed_fields:
            fid = item.get("field_id", "")
            lbl = item.get("label", fid)
            val = item.get("value", "")
            if fid not in state.mapped_answers:
                state.mapped_answers[fid] = ConfidenceResult(
                    field_id=fid,
                    answer=val,
                    confidence=1.0,
                    reason="Completed on previous step",
                    source_citations=["multi_step_form_history"]
                )
            if not any(f.data_jp_id == fid for f in state.detected_fields):
                state.detected_fields.append(FormField(
                    data_jp_id=fid,
                    tag_name="input",
                    input_type=item.get("field_type") or "text",
                    label=lbl,
                    is_required=False,
                    is_visible=True,
                    current_value=str(val) if val is not None else ""
                ))

    if browser_manager:
        try:
            page = await browser_manager.get_page(state.application_id)
            for f in state.detected_fields:
                try:
                    val = await BrowserActions.get_input_value(page, f.data_jp_id)
                    if val is not None:
                        f.current_value = val
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Could not read live input values for review: {e}")

    state.status = "READY_FOR_REVIEW"
    await event_stream.update_status(state.application_id, "READY_FOR_REVIEW", "Application ready for review")
    await event_stream.log_action(
        state.application_id,
        "All application fields have been filled and verified. Safety lock active: explicit human approval is required to submit.",
        level="info"
    )
    return state


async def submit_application_node(
    state: ApplicationState,
    browser_manager: BrowserManager
) -> ApplicationState:
    """HARD SUBMISSION SAFETY GATE: Execute submit action ONLY if submission_approved is True and verify actual browser completion."""
    logger.info("Node [SUBMIT_APPLICATION]: Evaluated submission approval lock...")

    if not state.submission_approved:
        logger.error("HARD SUBMISSION SAFETY LOCK TRIGGERED: Attempted to submit without explicit submission_approved == True!")
        await event_stream.log_action(
            state.application_id,
            "HARD SAFETY LOCK: Submission blocked because explicit user approval was not granted.",
            level="error"
        )
        raise JobPilotException(
            "HARD SUBMISSION LOCK PREVENTED SUBMISSION: Explicit user approval (submission_approved=True) is required."
        )

    try:
        page = await browser_manager.get_page(state.application_id)
        await page.bring_to_front()

        # Helper to check for submission confirmation in browser
        async def check_browser_submission_confirmed() -> bool:
            curr_url = (page.url or "").lower()
            success_url_patterns = [
                "/thank", "/confirm", "/submitted", "/success",
                "/applied", "/status", "/application_complete", "/post-apply"
            ]
            if any(p in curr_url for p in success_url_patterns):
                return True

            try:
                body_text = (await page.evaluate("() => document.body ? document.body.innerText : ''") or "").lower()
                success_phrases = [
                    "application submitted", "application received", "thank you for applying",
                    "successfully submitted", "application complete", "we've received your application",
                    "your application has been submitted", "thanks for applying", "your application was sent"
                ]
                if any(sp in body_text for sp in success_phrases):
                    return True
            except Exception:
                pass

            try:
                from backend.app.browser.dom_inspector import DOMInspector
                form_page = await DOMInspector.inspect_page(page)
                if form_page.page_type == "APPLICATION_SUBMITTED":
                    return True
            except Exception:
                pass

            return False

        # Helper to check for OTP / 2FA / Verification challenge
        async def check_for_otp_challenge() -> bool:
            try:
                return await page.evaluate("""
                    () => {
                        const text = (document.body ? document.body.innerText : '').toLowerCase();
                        const otpKeywords = [
                            'verification code', 'enter code', 'we sent a code', 'one-time password',
                            'enter the 6-digit', 'enter 6-digit', 'sms code', 'verify your phone',
                            'verify your email', 'security code', 'enter the otp', 'authenticator code',
                            'two-step verification', '2-step verification', 'passcode'
                        ];
                        const hasOtpKeyword = otpKeywords.some(kw => text.includes(kw));
                        const otpInputs = document.querySelectorAll(
                            'input[autocomplete="one-time-code"], input[name*="otp" i], input[name*="code" i], ' +
                            'input[id*="otp" i], input[id*="code" i], input[placeholder*="code" i], input[placeholder*="otp" i]'
                        );
                        const visibleOtpInput = Array.from(otpInputs).some(el => el.offsetParent !== null);
                        return hasOtpKeyword && (visibleOtpInput || text.includes('code') || text.includes('sent'));
                    }
                """)
            except Exception:
                return False

        # Helper to check for visible form validation errors
        async def check_for_validation_errors() -> List[str]:
            try:
                return await page.evaluate("""
                    () => {
                        const errors = [];
                        const errEls = document.querySelectorAll(
                            '.error, .error-message, [role="alert"], .invalid-feedback, .has-error, [aria-invalid="true"], .field-error, .help-block-error, .alert-danger'
                        );
                        errEls.forEach(el => {
                            if (el.offsetParent !== null) {
                                const txt = el.innerText.trim();
                                if (txt && !errors.includes(txt) && txt.length < 250) {
                                    errors.push(txt);
                                }
                            }
                        });
                        return errors;
                    }
                """)
            except Exception:
                return []

        # 1. Pre-check: Is the browser ALREADY on a submission confirmation page?
        if await check_browser_submission_confirmed():
            state.status = "SUBMITTED"
            state.page_type = "APPLICATION_SUBMITTED"
            logger.info("Application already confirmed submitted in browser.")
            await event_stream.update_status(state.application_id, "SUBMITTED", "Application successfully submitted!")
            await event_stream.log_action(state.application_id, "🎉 Application verified and successfully SUBMITTED in browser!", level="info")
            return state

        # 2. Locate Submit Button (Strictly matching final submission triggers, NOT intermediate Next/Back buttons)
        submit_btn = None
        # Check detected_fields for submission button
        for f in state.detected_fields:
            txt = (f.visible_text or f.placeholder or f.label or "").lower().strip()
            ftype = (f.input_type or f.tag_name or "").lower()
            # Explicitly disallow pure navigation buttons
            if txt in ("next", "next step", "step 2", "step 3", "back", "prev", "previous", "cancel") or txt.startswith("back "):
                continue
            if any(k in txt for k in ("submit application", "submit", "apply now", "complete application", "send application", "confirm and submit", "finish")):
                submit_btn = f
                break
            if ftype in ("submit", "button") and any(k in txt for k in ("submit", "apply", "save & continue", "save and continue")):
                submit_btn = f
                break

        # Fallback to direct Playwright locator on the live page
        submit_locator = None
        if not submit_btn:
            candidates = [
                'button:has-text("Submit Application")',
                'button:has-text("Submit application")',
                'button:has-text("Submit")',
                'button:has-text("Apply Now")',
                'button:has-text("Apply now")',
                'button:has-text("Send Application")',
                'button:has-text("Complete Application")',
                'button:has-text("Finish")',
                'button.btn-submit',
                'button[id*="submit" i]',
                'input[type="submit"][value*="Submit" i]',
                'input[type="submit"][value*="Apply" i]',
                'button[type="submit"]',
                'input[type="submit"]'
            ]
            for sel in candidates:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    txt = (await loc.text_content() or await loc.get_attribute("value") or "").lower().strip()
                    # CRITICAL SAFEGUARD: Never treat a pure "Next" or "Back" button as final submission
                    if txt in ("next", "next step", "step 2", "step 3", "back", "prev", "previous", "cancel") or txt.startswith("back "):
                        continue
                    submit_locator = loc
                    break

        if not submit_btn and not submit_locator:
            logger.warning("Node [SUBMIT_APPLICATION]: No submit button found automatically on page.")
            state.status = "WAITING_FOR_USER"
            state.error_message = "No submission button could be found automatically on the application form. Please submit in the visible browser."
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Submission Button Not Found")
            await event_stream.log_action(
                state.application_id,
                "⚠️ Could not locate submission button automatically. Please switch to the visible browser window, complete final submission, and verify.",
                level="warning"
            )
            return state

        # 3. Check if Submit Button is Disabled & Diagnose Incomplete Fields
        btn_elem = None
        if submit_btn:
            btn_elem, _ = await BrowserActions._find_element(page, BrowserActions._selector(submit_btn.data_jp_id))
        elif submit_locator:
            btn_elem = submit_locator

        is_btn_disabled = False
        if btn_elem and await btn_elem.count() > 0:
            try:
                is_btn_disabled = await btn_elem.evaluate("""
                    el => el.disabled ||
                          el.getAttribute('aria-disabled') === 'true' ||
                          el.classList.contains('disabled') ||
                          el.getAttribute('disabled') !== null ||
                          window.getComputedStyle(el).pointerEvents === 'none'
                """)
            except Exception:
                pass

        if is_btn_disabled:
            logger.warning("Node [SUBMIT_APPLICATION]: Submit button is DISABLED. Inspecting form for incomplete required fields or errors...")
            # Run in-depth form diagnostic to find WHY submit is disabled
            form_diagnostic = await page.evaluate("""
                () => {
                    const missing = [];
                    const errors = [];

                    // Check required inputs, selects, textareas, checkboxes
                    const reqEls = document.querySelectorAll(
                        'input[required], select[required], textarea[required], [aria-required="true"]'
                    );
                    reqEls.forEach(el => {
                        if (el.offsetParent === null) return;
                        const type = (el.getAttribute('type') || '').toLowerCase();
                        const label = (el.labels && el.labels[0] ? el.labels[0].innerText : (el.placeholder || el.name || 'Required field')).trim();
                        if (type === 'checkbox' || type === 'radio') {
                            if (!el.checked) missing.push(`Checkbox '${label}' is required and not checked.`);
                        } else if (type === 'file') {
                            if (!el.files || el.files.length === 0) missing.push(`File/Resume '${label}' is not attached.`);
                        } else {
                            if (!(el.value || '').trim()) missing.push(`Field '${label}' is empty.`);
                        }
                    });

                    // Check validation errors
                    const errEls = document.querySelectorAll('.error, .error-message, [role="alert"], .invalid-feedback, .has-error, [aria-invalid="true"], .field-error');
                    errEls.forEach(el => {
                        if (el.offsetParent !== null) {
                            const txt = el.innerText.trim();
                            if (txt && !errors.includes(txt) && txt.length < 200) errors.push(txt);
                        }
                    });

                    return { missing, errors };
                }
            """)

            missing_fields = form_diagnostic.get("missing", [])
            form_errors = form_diagnostic.get("errors", [])
            all_issues = missing_fields + form_errors

            state.status = "WAITING_FOR_USER"
            state.validation_errors = all_issues

            issue_summary = "; ".join(all_issues[:3]) if all_issues else "Form incomplete or pending validation"
            state.error_message = f"Submit button is disabled: {issue_summary}."

            logger.warning(f"Submission halted: Submit button is disabled. Issues: {all_issues}")
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Submit Button Disabled (Form Incomplete)")
            await event_stream.log_action(
                state.application_id,
                f"⚠️ Submit button is disabled because the form is incomplete or has validation errors: {issue_summary}. "
                f"Please switch to the visible browser to complete the missing fields, then click Resume.",
                level="warning"
            )
            return state

        # 4. Click the Submit Button
        if submit_btn:
            label = submit_btn.visible_text or submit_btn.data_jp_id
            logger.info(f"Clicking final submission button '{label}' ({submit_btn.data_jp_id})...")
            await event_stream.log_action(
                state.application_id,
                f"Submitting application: Clicking submission button '{label}'...",
                level="info",
                action="click"
            )
            await BrowserActions.click(
                page, submit_btn.data_jp_id, field_label=label, session_id=state.application_id
            )
        elif submit_locator:
            btn_text = (await submit_locator.text_content() or "Submit").strip()
            logger.info(f"Clicking live submit button '{btn_text}'...")
            await event_stream.log_action(
                state.application_id,
                f"Submitting application: Clicking submission button '{btn_text}'...",
                level="info",
                action="click"
            )
            await submit_locator.scroll_into_view_if_needed()
            await submit_locator.click(timeout=5000)

        # 5. Wait for browser response and page transition
        await page.wait_for_timeout(3500)
        state.current_url = page.url

        # 5. Check for OTP / SMS / Email verification challenge
        if await check_for_otp_challenge():
            logger.warning("Node [SUBMIT_APPLICATION]: Additional verification barrier (OTP) detected.")
            state.status = "WAITING_FOR_USER"
            state.auth_category = "OTP_VERIFICATION"
            state.auth_details = "Additional verification required: The website is asking for an OTP / verification code."
            state.login_required = True
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "OTP Verification Required")
            await event_stream.log_action(
                state.application_id,
                "⚠️ Additional Verification Required: The portal is asking for an OTP / verification code. Please enter the code in the visible browser, then submit.",
                level="warning"
            )
            return state

        # 6. Check for visible form validation errors preventing submission
        val_errors = await check_for_validation_errors()
        if val_errors:
            logger.warning(f"Node [SUBMIT_APPLICATION]: Submission blocked by form validation errors: {val_errors}")
            state.status = "WAITING_FOR_USER"
            state.validation_errors = val_errors
            err_summary = "; ".join(val_errors[:3])
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Form Validation Errors Detected")
            await event_stream.log_action(
                state.application_id,
                f"⚠️ Submission not completed: The portal displayed form validation errors ({err_summary}). Please resolve them in the visible browser.",
                level="warning"
            )
            return state

        # 7. Check for confirmed submission in the browser
        if await check_browser_submission_confirmed():
            state.status = "SUBMITTED"
            state.page_type = "APPLICATION_SUBMITTED"
            logger.info(f"Application for session '{state.application_id}' successfully SUBMITTED and verified!")
            await event_stream.update_status(state.application_id, "SUBMITTED", "Application successfully submitted!")
            await event_stream.log_action(
                state.application_id,
                "🎉 Application verified and successfully SUBMITTED in browser!",
                level="info"
            )
            return state

        # 8. Second chance wait for slow networks / SPAs
        await page.wait_for_timeout(3000)
        if await check_browser_submission_confirmed():
            state.status = "SUBMITTED"
            state.page_type = "APPLICATION_SUBMITTED"
            logger.info(f"Application for session '{state.application_id}' successfully SUBMITTED (after delay)!")
            await event_stream.update_status(state.application_id, "SUBMITTED", "Application successfully submitted!")
            await event_stream.log_action(
                state.application_id,
                "🎉 Application verified and successfully SUBMITTED in browser!",
                level="info"
            )
            return state

        # Re-check OTP after second wait
        if await check_for_otp_challenge():
            state.status = "WAITING_FOR_USER"
            state.auth_category = "OTP_VERIFICATION"
            state.auth_details = "Additional verification required: The website is asking for an OTP / verification code."
            state.login_required = True
            await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "OTP Verification Required")
            await event_stream.log_action(
                state.application_id,
                "⚠️ Additional Verification Required: The portal is asking for an OTP / verification code. Please enter the code in the visible browser.",
                level="warning"
            )
            return state

        # 9. If browser is still on the same unconfirmed form, do NOT declare success!
        logger.warning(f"Node [SUBMIT_APPLICATION]: Browser state unconfirmed after click. URL: {page.url}")
        state.status = "WAITING_FOR_USER"
        state.error_message = "Form submission initiated, but browser has not displayed a confirmation page. Please verify in the visible browser."
        await event_stream.update_status(state.application_id, "WAITING_FOR_USER", "Submission Verification Pending")
        await event_stream.log_action(
            state.application_id,
            "⚠️ Form submission was initiated, but the browser has not yet confirmed completion. Please inspect the visible browser window to ensure the form was received.",
            level="warning"
        )
        return state

    except Exception as e:
        logger.error(f"Node [SUBMIT_APPLICATION] Error: {e}")
        state.status = "FAILED"
        state.error_message = f"Submission error: {e}"
        await event_stream.update_status(state.application_id, "FAILED", str(e))
        await event_stream.log_action(
            state.application_id,
            f"Submission error: {e}",
            level="error"
        )
        return state
