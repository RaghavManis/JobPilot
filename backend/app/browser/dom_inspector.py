from typing import List
from playwright.async_api import Page
from backend.app.schemas.form import FormField, FormPage
from backend.app.core.logging import logger
from backend.app.core.exceptions import FormExtractionException


class DOMInspector:
    """Inspects web pages, injects synthetic data-jp-id attributes, and extracts clean FormField schemas."""

    # JavaScript snippet executed in browser to annotate and extract form elements
    INSPECT_SCRIPT = """
    (startIndex = 1) => {
        const interactiveElements = document.querySelectorAll(
            'input, select, textarea, button, [role="button"], [role="checkbox"], [role="radio"], [role="combobox"]'
        );

        // Clean up any previously stamped synthetic IDs to ensure fresh indexing across steps
        document.querySelectorAll('[data-jp-id]').forEach(el => el.removeAttribute('data-jp-id'));

        const extractedFields = [];
        let index = startIndex;

        // First pass: inject data-jp-id on every valid element so every DOM node has an addressable synthetic ID
        interactiveElements.forEach((el) => {
            const type = (el.getAttribute('type') || '').toLowerCase();
            if (type === 'hidden') return;
            // Never stamp synthetic IDs on cookie consent widgets, preference centers, marketing headers/footers, or wizard navigation sliders/steppers
            if (el.closest('#onetrust-consent-sdk, #onetrust-pc-sdk, .ot-pc-container, [id*="onetrust" i], [class*="onetrust" i], .cookie-banner, #cookie-banner, [id*="cookie" i], [class*="cookie" i], .ot-modal, #ot-pc-content, [aria-label*="cookie" i], [aria-label*="preference center" i], [aria-label*="privacy" i], footer, header, nav, [role="navigation"], [role="contentinfo"], .slick-slider, .slick-list, [role="tablist"], [role="tab"], .wizard-progress, .stepper, .steps-nav, .steps-wrapper, .navigation-wrapper')) {
                return;
            }
            // Skip wizard navigation step items (li, span, slide) and standalone icons
            if (el.tagName === 'LI' || el.tagName === 'I' || el.classList.contains('slick-slide') || el.classList.contains('slide')) {
                return;
            }
            const atmId = (el.getAttribute('atm-id') || '').toLowerCase();
            if (
                atmId.includes('skydrive') || atmId.includes('dropbox') || atmId.includes('onedrive') ||
                atmId.includes('googledrive') || atmId.includes('personalinformation') ||
                atmId.includes('workandeducation') || atmId.includes('jobspecificquestions') ||
                atmId.includes('applicationreview') || atmId.includes('step')
            ) {
                return;
            }
            const idOrClassOrText = ((el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).toLowerCase();
            if (
                idOrClassOrText.includes('cookie') || idOrClassOrText.includes('onetrust') || idOrClassOrText.includes('filter-handler') ||
                idOrClassOrText.includes('accept-recommended') || idOrClassOrText.includes('clear-filters') ||
                idOrClassOrText.includes('dropbox') || idOrClassOrText.includes('onedrive') || idOrClassOrText.includes('google drive') ||
                idOrClassOrText.includes('skydrive') || idOrClassOrText.includes('box-upload') || idOrClassOrText.includes('box-picker') || idOrClassOrText.includes('box.com')
            ) {
                return;
            }
            if (!el.getAttribute('data-jp-id')) {
                el.setAttribute('data-jp-id', `field_${String(index).padStart(3, '0')}`);
                index++;
            }
        });

        const processedRadioNames = new Set();
        const processedCheckboxGroups = new Set();

        const getElementLabel = (el) => {
            let labelText = '';
            if (el.id) {
                try {
                    const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (labelEl) labelText = labelEl.innerText.trim();
                } catch (e) {}
            }
            if (!labelText && el.closest('label')) {
                labelText = el.closest('label').innerText.trim();
            }
            if (!labelText && el.getAttribute('aria-labelledby')) {
                const ref = document.getElementById(el.getAttribute('aria-labelledby'));
                if (ref) labelText = ref.innerText.trim();
            }
            if (!labelText && el.getAttribute('aria-label')) {
                labelText = el.getAttribute('aria-label').trim();
            }
            if (!labelText && el.getAttribute('placeholder')) {
                labelText = el.getAttribute('placeholder').trim();
            }
            if (!labelText && el.previousElementSibling && (el.previousElementSibling.tagName === 'LABEL' || el.previousElementSibling.tagName === 'SPAN')) {
                labelText = el.previousElementSibling.innerText.trim();
            }
            return labelText;
        };

        const getSectionHeading = (el) => {
            let sectionHeading = '';
            const fieldset = el.closest('fieldset');
            if (fieldset) {
                const legend = fieldset.querySelector('legend');
                if (legend) sectionHeading = legend.innerText.trim();
            }
            if (!sectionHeading) {
                let parent = el.parentElement;
                while (parent && parent !== document.body) {
                    const heading = parent.querySelector('h1, h2, h3, h4, h5, .section-title, .card-title, .panel-heading, [role="heading"]');
                    if (heading && !heading.contains(el)) {
                        sectionHeading = heading.innerText.trim();
                        break;
                    }
                    parent = parent.parentElement;
                }
            }
            return sectionHeading;
        };

        const getHelperText = (el) => {
            let helperText = '';
            const ariaDescribedBy = el.getAttribute('aria-describedby');
            if (ariaDescribedBy) {
                const descEl = document.getElementById(ariaDescribedBy);
                if (descEl) helperText = descEl.innerText.trim();
            }
            if (!helperText) {
                const container = el.closest('.form-group, .mb-3, .form-field, .field-wrapper, td, div');
                if (container) {
                    const hintEl = container.querySelector('.form-text, .help-block, .hint, .form-hint, small, .text-muted');
                    if (hintEl && !hintEl.contains(el)) {
                        helperText = hintEl.innerText.trim();
                    }
                }
            }
            return helperText;
        };

        interactiveElements.forEach((el) => {
            const type = (el.getAttribute('type') || '').toLowerCase();
            if (type === 'hidden') return;

            // Ignore cookie consent banners, preference centers, OneTrust, Cookiebot, and privacy modals
            if (el.closest('#onetrust-consent-sdk, #onetrust-pc-sdk, .ot-pc-container, [id*="onetrust" i], [class*="onetrust" i], .cookie-banner, #cookie-banner, [id*="cookie" i], [class*="cookie" i], .ot-modal, #ot-pc-content, [aria-label*="cookie" i], [aria-label*="preference center" i], [aria-label*="privacy" i]')) {
                return;
            }

            // Ignore elements inside marketing footers, navigation headers, wizard sliders, steppers, and newsletter subscription widgets
            if (el.closest('footer, header, nav, [role="navigation"], [role="contentinfo"], .footer, .site-footer, #footer, .global-header, .global-nav, .slick-slider, .slick-list, [role="tablist"], [role="tab"], .wizard-progress, .stepper, .steps-nav, .steps-wrapper, .navigation-wrapper')) {
                return;
            }
            // Skip wizard navigation step items (li, span, slide) and standalone icons
            if (el.tagName === 'LI' || el.tagName === 'I' || el.classList.contains('slick-slide') || el.classList.contains('slide')) {
                return;
            }
            const rawText = (el.innerText || el.textContent || '').toLowerCase();
            const placeholderOrName = (el.placeholder || el.name || el.id || el.getAttribute('aria-label') || rawText).toLowerCase();
            if (
                placeholderOrName.includes('cookie') ||
                placeholderOrName.includes('preference center') ||
                placeholderOrName.includes('targeting cookies') ||
                placeholderOrName.includes('performance cookies') ||
                placeholderOrName.includes('functional cookies') ||
                placeholderOrName.includes('strictly necessary') ||
                placeholderOrName.includes('newsletter') ||
                placeholderOrName.includes('subscribe') ||
                placeholderOrName.includes('industry insights')
            ) {
                return;
            }

            // Ignore cloud storage picker buttons (Dropbox, OneDrive, Google Drive, Box) and social apply triggers
            const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
            const atmId = (el.getAttribute('atm-id') || '').toLowerCase();
            const className = (typeof el.className === 'string' ? el.className : '').toLowerCase();
            const title = (el.getAttribute('title') || '').toLowerCase();
            if (
                ariaLabel.includes('dropbox') || ariaLabel.includes('onedrive') || ariaLabel.includes('google drive') ||
                ariaLabel.includes('skydrive') || ariaLabel.includes('box-upload') || ariaLabel.includes('box-picker') || ariaLabel.includes('box.com') ||
                atmId.includes('dropbox') || atmId.includes('onedrive') || atmId.includes('skydrive') ||
                atmId.includes('personalinformation') || atmId.includes('workandeducation') ||
                atmId.includes('jobspecificquestions') || atmId.includes('applicationreview') || atmId.includes('step') ||
                className.includes('dropbox') || className.includes('onedrive') || className.includes('skydrive') || className.includes('cloud-icon') ||
                title.includes('dropbox') || title.includes('onedrive') || title.includes('skydrive') ||
                rawText.includes('dropbox') || rawText.includes('onedrive') || rawText.includes('google drive') || rawText.includes('skydrive')
            ) {
                return;
            }

            let syntheticId = el.getAttribute('data-jp-id');
            if (!syntheticId) {
                syntheticId = `field_${String(index).padStart(3, '0')}`;
                el.setAttribute('data-jp-id', syntheticId);
                index++;
            }
            const sectionHeading = getSectionHeading(el);
            const helperText = getHelperText(el);
            const style = window.getComputedStyle(el);
            let isVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && el.offsetParent !== null;

            // For file inputs, portals often hide native <input type="file" style="display: none"> behind styled buttons like "Upload from PC"
            if (type === 'file') {
                const uploadContainer = el.closest('.resume-upload-wrapper, .upload-wrapper, [class*="upload"], .form-group, fieldset, div');
                if (uploadContainer) {
                    const cStyle = window.getComputedStyle(uploadContainer);
                    if (cStyle.display !== 'none' && cStyle.visibility !== 'hidden' && (uploadContainer.offsetWidth > 0 || uploadContainer.offsetHeight > 0)) {
                        isVisible = true;
                    }
                }
            }

            // 1. Grouped Radio Buttons
            if (type === 'radio' && el.name) {
                if (processedRadioNames.has(el.name)) return;
                processedRadioNames.add(el.name);

                let radios = [];
                try {
                    radios = Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`));
                } catch (e) {
                    radios = [el];
                }
                const options = [];
                const optionElements = {};

                radios.forEach((r) => {
                    let rId = r.getAttribute('data-jp-id');
                    if (!rId) {
                        rId = `field_${String(index).padStart(3, '0')}`;
                        r.setAttribute('data-jp-id', rId);
                        index++;
                    }
                    const rLabel = getElementLabel(r) || r.value || '';
                    if (rLabel && !options.includes(rLabel)) {
                        options.push(rLabel);
                        optionElements[rLabel] = rId;
                    }
                });

                // Determine question label for the radio group
                let groupQuestion = '';
                const groupContainer = el.closest('fieldset, .form-group, .radio-group, [role="radiogroup"], [role="group"]');
                if (groupContainer) {
                    const groupLabel = groupContainer.querySelector('legend, .group-label, .control-label, label:not([for]), p.question, span.question, strong');
                    if (groupLabel && !groupLabel.contains(el)) {
                        groupQuestion = groupLabel.innerText.trim();
                    }
                }
                if (!groupQuestion) {
                    groupQuestion = getElementLabel(el) || sectionHeading || el.name;
                }

                extractedFields.push({
                    data_jp_id: syntheticId,
                    tag_name: el.tagName.toLowerCase(),
                    input_type: 'radio',
                    name: el.name,
                    element_id: el.id || null,
                    placeholder: null,
                    label: groupQuestion,
                    visible_text: null,
                    is_required: radios.some(r => r.hasAttribute('required') || r.getAttribute('aria-required') === 'true'),
                    is_visible: isVisible,
                    current_value: (() => {
                        const checkedRadio = radios.find(r => r.checked);
                        return checkedRadio ? (getElementLabel(checkedRadio) || checkedRadio.value || null) : null;
                    })(),
                    options: options,
                    option_elements: optionElements,
                    section_heading: sectionHeading || null,
                    helper_text: helperText || null
                });
                return;
            }

            // 2. Grouped Checkboxes (multi-select country lists, skills, etc.)
            if (type === 'checkbox') {
                let sameNameCheckboxes = [];
                try {
                    sameNameCheckboxes = el.name ? Array.from(document.querySelectorAll(`input[type="checkbox"][name="${CSS.escape(el.name)}"]`)) : [];
                } catch (e) {
                    sameNameCheckboxes = [el];
                }
                const fieldset = el.closest('fieldset, [role="group"], .checkbox-group, .form-group');
                const fieldsetCheckboxes = fieldset ? Array.from(fieldset.querySelectorAll('input[type="checkbox"]')) : [];

                const isGroup = sameNameCheckboxes.length > 1 || (fieldset && fieldsetCheckboxes.length > 1);

                if (isGroup) {
                    const groupKey = el.name ? `name:${el.name}` : `fieldset:${fieldset ? (fieldset.id || fieldset.className || syntheticId) : syntheticId}`;
                    if (processedCheckboxGroups.has(groupKey)) return;
                    processedCheckboxGroups.add(groupKey);

                    const groupMembers = sameNameCheckboxes.length > 1 ? sameNameCheckboxes : fieldsetCheckboxes;
                    const options = [];
                    const optionElements = {};

                    groupMembers.forEach((cb) => {
                        let cbId = cb.getAttribute('data-jp-id');
                        if (!cbId) {
                            cbId = `field_${String(index).padStart(3, '0')}`;
                            cb.setAttribute('data-jp-id', cbId);
                            index++;
                        }
                        const cbLabel = getElementLabel(cb) || cb.value || '';
                        if (cbLabel && !options.includes(cbLabel)) {
                            options.push(cbLabel);
                            optionElements[cbLabel] = cbId;
                        }
                    });

                    // Determine question label for the checkbox group
                    let groupQuestion = el.getAttribute('description') || '';
                    if (!groupQuestion && fieldset) {
                        const legend = fieldset.querySelector('legend, .group-label, .control-label, label:not([for]), p.question, span.question, strong');
                        if (legend && !legend.contains(el)) {
                            groupQuestion = legend.innerText.trim();
                        }
                    }
                    if (!groupQuestion) {
                        const container = el.closest('.form-group, .mb-3, .form-field, .field-wrapper');
                        if (container) {
                            const lbl = container.querySelector('.control-label, label:not([for]), p.question, strong, h3, h4, h5');
                            if (lbl && !lbl.contains(el)) groupQuestion = lbl.innerText.trim();
                        }
                    }
                    if (!groupQuestion) {
                        groupQuestion = sectionHeading || getElementLabel(el) || el.name;
                    }

                    extractedFields.push({
                        data_jp_id: syntheticId,
                        tag_name: el.tagName.toLowerCase(),
                        input_type: 'checkbox_group',
                        name: el.name || null,
                        element_id: el.id || null,
                        placeholder: null,
                        label: groupQuestion,
                        visible_text: null,
                        is_required: groupMembers.some(cb => cb.hasAttribute('required') || cb.getAttribute('aria-required') === 'true'),
                        is_visible: isVisible,
                        current_value: null,
                        options: options,
                        option_elements: optionElements,
                        section_heading: sectionHeading || null,
                        helper_text: helperText || null
                    });
                    return;
                }
            }

            // 3. Select Dropdowns, Text Inputs, Textarea, Single Checkbox, Buttons
            const tag = el.tagName.toLowerCase();
            const role = (el.getAttribute('role') || '').toLowerCase();
            const isButtonLike = tag === 'button' || tag === 'a' || role === 'button';

            let calculatedType = type;
            if (!calculatedType) {
                if (tag === 'select' || role === 'combobox') calculatedType = 'select';
                else if (tag === 'textarea') calculatedType = 'textarea';
                else if (isButtonLike) calculatedType = 'button';
                else if (role === 'checkbox') calculatedType = 'checkbox';
                else if (role === 'radio') calculatedType = 'radio';
                else calculatedType = 'text';
            }

            let labelText = getElementLabel(el);
            if (isButtonLike && !labelText) {
                labelText = el.innerText ? el.innerText.trim() : (el.getAttribute('value') || '');
            }
            if (type === 'file' && !labelText) {
                const wrapper = el.closest('.resume-upload-wrapper, .upload-wrapper, [class*="upload"], .form-group, fieldset, div');
                const btn = wrapper ? wrapper.querySelector('button, .btn, label') : null;
                labelText = (btn ? btn.innerText.trim() : '') || sectionHeading || 'Upload Resume';
            }
            const options = [];
            if (tag === 'select') {
                Array.from(el.options).forEach(opt => {
                    if (opt.text.trim()) options.push(opt.text.trim());
                });
            }

            extractedFields.push({
                data_jp_id: syntheticId,
                tag_name: tag,
                input_type: calculatedType,
                name: el.getAttribute('name') || null,
                element_id: el.id || null,
                placeholder: el.getAttribute('placeholder') || null,
                label: labelText || null,
                visible_text: el.innerText ? el.innerText.trim() : null,
                is_required: isButtonLike ? false : (el.hasAttribute('required') || el.getAttribute('aria-required') === 'true'),
                is_visible: isVisible,
                current_value: el.value || null,
                options: options,
                option_elements: {},
                section_heading: sectionHeading || null,
                helper_text: helperText || null
            });
        });

        // Extract visible validation error messages on page
        const errorNodes = document.querySelectorAll('.error, .error-message, .error-banner, [role="alert"], .invalid-feedback');
        const validationErrors = [];
        errorNodes.forEach(node => {
            const style = window.getComputedStyle(node);
            if (style.display !== 'none' && style.visibility !== 'hidden' && node.innerText.trim()) {
                validationErrors.push(node.innerText.trim());
            }
        });

        // Check for active bot verification / blocking CAPTCHA challenges
        // Note: Exclude passive background invisible reCAPTCHA/Turnstile token iframes
        const hasCaptcha = Boolean(
            document.querySelector(
                'iframe[title*="recaptcha challenge" i], ' +
                'iframe[title*="reCAPTCHA challenge" i], ' +
                'iframe[src*="recaptcha/enterprise/bframe" i], ' +
                'iframe[src*="recaptcha/api2/bframe" i], ' +
                '.g-recaptcha:not([style*="display: none"]):not([style*="visibility: hidden"]), ' +
                '.h-captcha:not([style*="display: none"]):not([style*="visibility: hidden"])'
            )
        );

        // Check for live webcam / selfie / camera verification challenge
        const bodyText = document.body ? document.body.innerText : '';
        const hasWebcamPrompt = /\b(?:take a selfie|allow camera|position your face|webcam capture|live photo verification|identity verification selfie)\b/i.test(bodyText);

        let hasActiveWebcamElement = false;
        const candidates = document.querySelectorAll(
            'video, canvas#webcam, [class*="webcam"], [id*="webcam"], [class*="selfie"], [id*="selfie"], [class*="liveness"], [class*="face-verification"]'
        );
        for (const el of candidates) {
            const tag = el.tagName.toLowerCase();
            // Ignore SVG icons, symbols, icon fonts, and buttons with icon names
            if (['symbol', 'svg', 'path', 'use', 'i'].includes(tag)) continue;
            if (el.closest('svg, symbol')) continue;
            const idAndClass = ((el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '')).toLowerCase();
            if (idAndClass.includes('icon') || idAndClass.includes('btn-icon')) continue;

            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || el.offsetParent === null) {
                continue;
            }

            if (tag === 'video') {
                if (el.srcObject) {
                    hasActiveWebcamElement = true;
                    break;
                }
                if (el.src || el.querySelector('source')) {
                    continue;
                }
            }

            hasActiveWebcamElement = true;
            break;
        }

        const hasWebcam = hasWebcamPrompt || hasActiveWebcamElement;

        return {
            fields: extractedFields,
            validation_errors: validationErrors,
            has_captcha: hasCaptcha,
            has_webcam: hasWebcam,
            next_index: index
        };
    }
    """

    @classmethod
    async def inspect_page(cls, page: Page) -> FormPage:
        """Inject synthetic data-jp-id across main page and embedded child iframes, classify page role, and return parsed FormPage schema."""
        try:
            url = page.url
            title = await page.title()
            logger.info(f"Extracting DOM interactive elements for page '{title}' ({url})...")

            all_raw_fields = []
            all_validation_errors = []
            has_any_captcha = False
            has_any_webcam = False
            # If the page currently has few or no input fields, but iframe elements exist or it's an application URL,
            # wait dynamically for embedded ATS iframes (Greenhouse, Lever, etc.) or client-side forms to mount.
            max_wait_ms = 4000
            poll_interval_ms = 250
            elapsed_ms = 0

            while elapsed_ms < max_wait_ms:
                total_inputs = 0
                for f in page.frames:
                    try:
                        total_inputs += await f.locator('input:not([type="hidden"]), select, textarea').count()
                    except Exception:
                        pass

                if total_inputs >= 3:
                    break

                try:
                    has_dom_iframes = (await page.locator("iframe").count()) > 0
                except Exception:
                    has_dom_iframes = False

                if not has_dom_iframes and total_inputs > 0:
                    break

                await page.wait_for_timeout(poll_interval_ms)
                elapsed_ms += poll_interval_ms

            current_index = 1

            # Inspect main frame and child iframes (such as embedded Greenhouse, Lever, Workday forms)
            frames_to_inspect = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
            for frame in frames_to_inspect:
                try:
                    result = await frame.evaluate(cls.INSPECT_SCRIPT, current_index)
                    if not result:
                        continue
                    frame_fields = result.get("fields", [])
                    current_index = result.get("next_index", current_index + len(frame_fields))
                    all_raw_fields.extend(frame_fields)
                    all_validation_errors.extend(result.get("validation_errors", []))
                    if result.get("has_captcha"):
                        has_any_captcha = True
                    if result.get("has_webcam"):
                        has_any_webcam = True
                except Exception as frame_err:
                    logger.debug(f"Frame inspection skipped for {frame.url}: {frame_err}")

            form_fields = [FormField(**f) for f in all_raw_fields]

            # Extract page body text for content classification
            try:
                page_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            except Exception:
                page_text = ""
            is_multi = any(k in page_text.lower() for k in ["step 1", "step 2", "page 1 of", "continue to step"])

            # Run intelligent page classification
            from backend.app.browser.page_classifier import PageClassifier
            classification = PageClassifier.classify_page(
                url=url,
                title=title,
                fields=form_fields,
                page_text=page_text,
                has_captcha=has_any_captcha
            )

            logger.info(
                f"Page classification result: type='{classification.page_type}', "
                f"is_auth_barrier={classification.is_auth_barrier}, "
                f"category={classification.auth_category}, "
                f"reasons={classification.reasons}"
            )

            # If this is an authentication barrier, clean application fields are empty (credentials excluded)
            exposed_fields = (
                classification.clean_application_fields
                if classification.is_auth_barrier
                else form_fields
            )

            return FormPage(
                url=url,
                title=title,
                fields=exposed_fields,
                has_login_wall=classification.is_auth_barrier,
                is_multi_page=is_multi,
                page_type=classification.page_type,
                auth_category=classification.auth_category,
                auth_details=classification.auth_details,
                has_webcam_challenge=has_any_webcam
            )
        except Exception as e:
            logger.error(f"DOM inspection failed for page {page.url}: {e}")
            raise FormExtractionException(f"Failed to inspect DOM: {e}") from e
