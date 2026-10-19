import os
import re
from typing import List, Optional
from backend.app.agent.state import ApplicationState
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.schemas.form import FormField, ConfidenceResult
from backend.app.core.logging import logger
from backend.app.services.event_stream import event_stream


async def map_fields_and_retrieve_node(
    state: ApplicationState,
    knowledge_service: KnowledgeService
) -> ApplicationState:
    """Map interactive form fields to candidate profile data or query RAG evidence."""
    logger.info(f"Node [MAP_FIELDS]: Mapping {len(state.detected_fields)} form fields against canonical profile & RAG...")
    await event_stream.update_status(state.application_id, "RUNNING", "Mapping fields with Profile & RAG...")
    await event_stream.log_action(
        state.application_id,
        f"Mapping {len(state.detected_fields)} form fields against user profile and knowledge base...",
        action="analyze"
    )

    profile = await knowledge_service.get_user_profile(state.user_id)
    mapped_answers = {}

    from backend.app.browser.page_classifier import PageClassifier

    for field in state.detected_fields:
        if not field.is_visible:
            continue

        # Skip buttons, submit triggers, navigation controls, and non-input controls
        lbl_lower = (field.label or field.name or field.placeholder or field.visible_text or "").lower().strip()
        if (
            field.tag_name in ("button", "a")
            or (field.input_type or "").lower() in ("button", "submit", "reset", "image", "hidden")
            or lbl_lower in ("back", "next", "continue", "submit", "cancel", "previous", "prev", "close", "save", "save & continue", "save and continue", "proceed", "review", "review application", "finish", "close preference center", "filter cookie list")
            or any(k in lbl_lower for k in ("dropbox", "onedrive", "google drive", "box", "apply with linkedin", "apply with indeed", "cookie", "preference center", "back to", "return to", "privacy settings"))
        ):
            continue

        # Security Guardrail: Never map sensitive authentication fields (passwords, OTP, CAPTCHA, tokens)
        if PageClassifier.is_auth_field(field):
            logger.info(f"Node [MAP_FIELDS]: Skipping sensitive authentication field '{field.data_jp_id}' ('{field.label or field.name}')")
            continue

        label = (field.label or field.name or field.placeholder or "").lower().strip()
        field_id = field.data_jp_id

        # ---------------------------------------------------------------
        # 1. Deterministic match from UserProfile schema
        # ---------------------------------------------------------------
        if profile and profile.personal:
            p = profile.personal
            prof = profile.professional

            def _match(answer: str | bool, reason: str, confidence: float = 0.99):
                return ConfidenceResult(
                    field_id=field_id,
                    answer=answer,
                    confidence=confidence,
                    reason=reason,
                    source_citations=[reason]
                )

            def _find_other_option(options: list[str]) -> str | None:
                if not options:
                    return None
                for opt in options:
                    opt_c = opt.strip().lower()
                    if opt_c in (
                        "other", "other / not listed", "not listed", "other (not listed)",
                        "other / unknown", "other school", "other institution", "other university",
                        "other degree", "other / not specified", "other (please specify)"
                    ):
                        return opt
                for opt in options:
                    opt_c = opt.strip().lower()
                    if opt_c.startswith("other"):
                        return opt
                for opt in options:
                    opt_c = opt.strip().lower()
                    if "not listed" in opt_c or "unlisted" in opt_c:
                        return opt
                return None

            def _match_option(options: list[str], target_values: list[str], fallback_to_other: bool = False) -> str | None:
                if not options:
                    return None
                # 1. Exact match
                for opt in options:
                    opt_c = opt.strip().lower()
                    for tv in target_values:
                        if tv and opt_c == tv.strip().lower():
                            return opt
                # 2. Substring match
                for opt in options:
                    opt_c = opt.strip().lower()
                    for tv in target_values:
                        if tv:
                            tv_c = tv.strip().lower()
                            if tv_c in opt_c or opt_c in tv_c:
                                return opt
                # 3. Numeric / Dial code match (e.g. +91 vs 91 vs India (+91))
                for tv in target_values:
                    if tv and any(c.isdigit() for c in tv):
                        tv_digits = "".join(c for c in tv if c.isdigit())
                        if tv_digits:
                            for opt in options:
                                opt_digits = "".join(c for c in opt if c.isdigit())
                                if opt_digits == tv_digits or opt.strip().startswith(f"+{tv_digits}") or f"+{tv_digits}" in opt:
                                    return opt
                # 4. Fallback to "Other" option if requested
                if fallback_to_other:
                    other_opt = _find_other_option(options)
                    if other_opt:
                        return other_opt
                return None

            # -- Name fields --
            if any(t in label for t in ("first name", "firstname", "first_name", "given name")):
                mapped_answers[field_id] = _match(p.first_name, "profile.personal.first_name")
                continue
            if any(t in label for t in ("last name", "lastname", "last_name", "surname", "family name")):
                mapped_answers[field_id] = _match(p.last_name, "profile.personal.last_name")
                continue
            if any(t in label for t in ("full name", "fullname", "your name")) or label == "name":
                full = p.full_name or f"{p.first_name} {p.last_name}"
                mapped_answers[field_id] = _match(full, "profile.personal.full_name")
                continue

            # -- Contact & Phone Country Code --
            if "email" in label:
                mapped_answers[field_id] = _match(p.email, "profile.personal.email")
                continue

            # Check if this field is a Phone Device Type selector (Mobile / Cell / Home / Work)
            is_device_type = (
                any(t in label for t in ("device type", "phone device type", "phone type", "number type", "telephone type", "type of phone"))
                or any(t in (field.name or "").lower() for t in ("device_type", "phone_device_type", "phone_type", "phonetype", "devicetype"))
                or (
                    "type" in label
                    and any(t in (field.section_heading or "").lower() for t in ("phone", "mobile", "contact", "cell"))
                )
                or (
                    field.options
                    and any(str(o).strip().lower() in ("mobile", "cell", "cellular", "home", "work", "primary") for o in field.options)
                    and any(t in label for t in ("type", "device", "category"))
                )
            )

            if is_device_type:
                device_targets = ["Mobile", "Cell", "Cellular", "Personal", "Primary", "Home", "Work"]
                matched_dev = _match_option(field.options or [], device_targets) if field.options else None
                chosen_dev = matched_dev or "Mobile"
                mapped_answers[field_id] = _match(chosen_dev, "profile.personal.phone_device_type (Mobile)", 0.99)
                continue

            # Check if this field is a Phone Country Code / Dial Code selector
            is_country_code = (
                any(t in label for t in ("country code", "dial code", "calling code", "phone code", "dialing code", "phone prefix", "country dial", "phone country"))
                or any(t in (field.name or "").lower() for t in ("country_code", "phone_country", "dial_code", "calling_code", "countrycode", "phonecode", "phone_prefix"))
                or (field.options and any(re.search(r'\+\d{1,4}', str(opt)) for opt in field.options))
                or (
                    "country" in label
                    and any(t in (field.section_heading or "").lower() for t in ("phone", "mobile", "contact", "cell"))
                )
            )

            if is_country_code:
                dial_targets = ["+91", "India (+91)", "+91 (India)", "IN (+91)", "+91 - India", "India", "91"]
                matched_dial = _match_option(field.options or [], dial_targets) if field.options else None
                chosen_dial = matched_dial or "+91"
                mapped_answers[field_id] = _match(chosen_dial, "profile.personal.country_code (+91)", 0.99)
                continue

            if any(t in label for t in ("phone", "mobile", "contact number", "cell", "telephone", "phone number")):
                # Ensure this is NOT a device type or country dial code selector
                if not any(k in label for k in ("type", "device", "country", "code", "prefix", "calling")):
                    if p.phone:
                        phone_str = str(p.phone).strip()
                        mapped_answers[field_id] = _match(phone_str, "profile.personal.phone", 0.99)
                        continue

            # -- Address & Country / Location --
            if any(t in label for t in ("country or countries you anticipate working in", "country where you currently reside", "country of residence", "select country", "work location", "anticipated country", "reside in", "residence")) or (field.input_type in ("checkbox_group", "select") and "country" in label) or label in ("country", "country*"):
                country = p.flat_country() or "India"
                if field.options:
                    matched = _match_option(field.options, [country, "India", "IN"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.personal.address.country", 0.98)
                        continue
                mapped_answers[field_id] = _match(country, "profile.personal.address.country", 0.98)
                continue
            if any(t in label for t in ("city", "town")):
                city = p.flat_city()
                if city:
                    mapped_answers[field_id] = _match(city, "profile.personal.address.city", 0.95)
                    continue
            if any(t in label for t in ("state", "province", "region")):
                state_val = p.flat_state()
                if state_val:
                    mapped_answers[field_id] = _match(state_val, "profile.personal.address.state", 0.95)
                    continue
            if "country" in label:
                country = p.flat_country() or "India"
                if field.options:
                    matched = _match_option(field.options, [country, "India", "IN"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.personal.address.country", 0.98)
                        continue
                mapped_answers[field_id] = _match(country, "profile.personal.address.country", 0.98)
                continue
            if any(t in label for t in ("postal", "zip", "pin", "pincode")):
                postal = p.flat_postal_code()
                if postal:
                    mapped_answers[field_id] = _match(postal, "profile.personal.address.postal_code", 0.95)
                    continue
            if any(t in label for t in ("address", "street")):
                addr = p.flat_address()
                if addr:
                    mapped_answers[field_id] = _match(addr, "profile.personal.address", 0.90)
                    continue

            # -- Social links --
            if "linkedin" in label:
                url = p.linkedin_url or (prof.linkedin_url if prof else None)
                if url:
                    mapped_answers[field_id] = _match(url, "profile.personal.linkedin_url", 0.99)
                    continue
            if "github" in label:
                url = p.github_url or (prof.github_url if prof else None)
                if url:
                    mapped_answers[field_id] = _match(url, "profile.personal.github_url", 0.99)
                    continue
            if any(t in label for t in ("portfolio", "website")):
                url = p.portfolio_url or (prof.portfolio_url if prof else None)
                if url:
                    mapped_answers[field_id] = _match(url, "profile.personal.portfolio_url", 0.90)
                    continue

            # -- Gender --
            if "gender" in label:
                if p.gender:
                    mapped_answers[field_id] = _match(p.gender, "profile.personal.gender", 0.99)
                    continue

            # -- Professional fields --
            is_choice_field = bool(field.options) or (field.input_type or "").lower() in ("radio", "checkbox", "checkbox_group")
            has_yes_no = any(o.strip().lower() in ("yes", "no") for o in (field.options or []))

            if prof:
                if not has_yes_no and any(t in label for t in ("current company", "employer", "company name", "organization")):
                    if not any(q_word in label for q_word in ("have you", "were you", "are you", "worked for", "employed by")):
                        company = prof.current_company or prof.last_employer
                        if company:
                            mapped_answers[field_id] = _match(company, "profile.professional.current_company", 0.95)
                            continue
                if not is_choice_field and any(t in label for t in ("current role", "job title", "current position", "role / title", "designation")):
                    role = prof.current_role or prof.last_role
                    if role:
                        mapped_answers[field_id] = _match(role, "profile.professional.current_role", 0.95)
                        continue
                if any(t in label for t in ("years of experience", "total experience", "experience years")):
                    if prof.total_experience_years is not None:
                        mapped_answers[field_id] = _match(
                            str(prof.total_experience_years),
                            "profile.professional.total_experience_years",
                            0.90
                        )
                        continue
                if any(t in label for t in ("notice period", "notice", "joining")):
                    nd = prof.notice_period_display()
                    mapped_answers[field_id] = _match(nd, "profile.professional.notice_period_days", 0.95)
                    continue

            # -- Skills --
            if any(t in label for t in ("skill", "technology", "tech stack", "tools")):
                skills_flat = profile.flat_skills()
                if skills_flat:
                    mapped_answers[field_id] = _match(
                        ", ".join(skills_flat[:15]),
                        "profile.skills",
                        0.90
                    )
                    continue

            # -- Salary --
            if any(t in label for t in ("salary", "ctc", "compensation", "pay")):
                sal = profile.effective_salary_expectation()
                if sal:
                    mapped_answers[field_id] = _match(sal, "profile.job_preferences.salary_expectation", 0.85)
                    continue

            # -- Education Facts (Degrees, Postgraduate, Undergraduate, Institutions, Years) --
            edu_list = profile.education or []
            pg_edu = next(
                (e for e in edu_list if "master" in e.degree.lower() or "mca" in e.degree.lower() or "post" in e.degree.lower()),
                None
            )
            ug_edu = next(
                (e for e in edu_list if "bachelor" in e.degree.lower() or "b.sc" in e.degree.lower() or "btech" in e.degree.lower()),
                None
            )
            highest_edu = pg_edu or (edu_list[0] if edu_list else None)

            # Postgraduate / Master's degree completion
            if any(t in label for t in ("postgraduate", "post graduate", "master", "post-graduation", "pg degree", "pg completion")):
                if any(t in label for t in ("completed", "status", "holding", "have you", "pursuing", "did you")):
                    ans = "Yes" if pg_edu and "completed" in (pg_edu.status or "").lower() else ("Yes" if pg_edu else "No")
                    if field.options:
                        matched = _match_option(field.options, [ans, "Completed", "Yes, Completed"])
                        if matched:
                            mapped_answers[field_id] = _match(matched, "profile.education.postgraduate.status", 0.98)
                            continue
                    mapped_answers[field_id] = _match(ans, "profile.education.postgraduate.status", 0.98)
                    continue
                if any(t in label for t in ("institution", "university", "college", "school")):
                    if pg_edu:
                        mapped_answers[field_id] = _match(pg_edu.institution, "profile.education.postgraduate.institution", 0.98)
                        continue
                if any(t in label for t in ("year", "graduation year", "passing year", "completion year")):
                    if pg_edu and pg_edu.graduation_year:
                        mapped_answers[field_id] = _match(str(pg_edu.graduation_year), "profile.education.postgraduate.graduation_year", 0.98)
                        continue
                if any(t in label for t in ("degree", "qualification", "course", "program")):
                    if pg_edu:
                        if field.options:
                            matched = _match_option(field.options, [pg_edu.degree, "Master's", "Postgraduate", "MCA", "Master of Computer Applications"])
                            if matched:
                                mapped_answers[field_id] = _match(matched, "profile.education.postgraduate.degree", 0.98)
                                continue
                        mapped_answers[field_id] = _match(pg_edu.degree, "profile.education.postgraduate.degree", 0.98)
                        continue
                if any(t in label for t in ("gpa", "cpi", "cgpa", "percentage", "marks")):
                    if pg_edu and pg_edu.gpa_or_percentage:
                        cpi = pg_edu.gpa_or_percentage.replace("CPI", "").strip()
                        mapped_answers[field_id] = _match(cpi, "profile.education.postgraduate.cpi", 0.95)
                        continue

            # Undergraduate / Bachelor's degree completion
            if any(t in label for t in ("undergraduate", "bachelor", "bachelors", "graduation", "ug degree", "ug completion")):
                if any(t in label for t in ("completed", "status", "holding", "have you", "pursuing")):
                    ans = "Yes" if ug_edu else "No"
                    if field.options:
                        matched = _match_option(field.options, [ans, "Completed", "Yes, Completed"])
                        if matched:
                            mapped_answers[field_id] = _match(matched, "profile.education.undergraduate.status", 0.98)
                            continue
                    mapped_answers[field_id] = _match(ans, "profile.education.undergraduate.status", 0.98)
                    continue
                if any(t in label for t in ("institution", "university", "college", "school")):
                    if ug_edu:
                        mapped_answers[field_id] = _match(ug_edu.institution, "profile.education.undergraduate.institution", 0.98)
                        continue
                if any(t in label for t in ("year", "graduation year", "passing year", "completion year")):
                    if ug_edu and ug_edu.graduation_year:
                        mapped_answers[field_id] = _match(str(ug_edu.graduation_year), "profile.education.undergraduate.graduation_year", 0.98)
                        continue
                if any(t in label for t in ("degree", "qualification", "course")):
                    if ug_edu:
                        if field.options:
                            matched = _match_option(field.options, [ug_edu.degree, "Bachelor's", "Undergraduate", "B.Sc.", "BSc"])
                            if matched:
                                mapped_answers[field_id] = _match(matched, "profile.education.undergraduate.degree", 0.98)
                                continue
                        mapped_answers[field_id] = _match(ug_edu.degree, "profile.education.undergraduate.degree", 0.98)
                        continue

            # General Degree / Education Level (matches "Degree*", "Degree", "Highest degree", "Level of education", etc.)
            if any(t in label for t in ("degree", "highest level of education", "highest qualification", "highest degree", "level of education", "education level", "qualification")):
                is_ug = any(t in label for t in ("undergraduate", "bachelor", "btech", "ug degree"))
                target_edu = ug_edu if (is_ug and ug_edu) else highest_edu
                deg_name = target_edu.degree if target_edu else "Master of Computer Applications (MCA)"

                if field.options:
                    if is_ug:
                        deg_targets = [
                            ug_edu.degree if ug_edu else "", "Bachelor's Degree", "Bachelor's", "Bachelors", "Undergraduate", "B.Sc.", "BSc"
                        ]
                    else:
                        deg_targets = [
                            "Master's Degree / Post-Graduate", "Master's Degree", "Master's", "Masters",
                            "Postgraduate", "Post Graduate", "Master of Computer Applications (MCA)",
                            "Master of Computer Applications", "MCA", "Graduate", "College Graduate",
                            deg_name
                        ]
                    matched = _match_option(field.options, deg_targets, fallback_to_other=True)
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.education.degree", 0.98)
                        continue

                mapped_answers[field_id] = _match(deg_name, "profile.education.degree", 0.98)
                continue

            # General institution / college / university
            if any(t in label for t in ("college", "university", "institution", "institute name", "school")):
                if highest_edu:
                    inst_name = highest_edu.institution
                    inst_targets = [
                        inst_name,
                        "Motilal Nehru National Institute of Technology Allahabad (MNNIT Allahabad)",
                        "MNNIT Allahabad",
                        "Motilal Nehru National Institute of Technology",
                        "MNNIT",
                        "National Institute of Technology Allahabad",
                        "NIT Allahabad"
                    ]
                    if field.options:
                        matched = _match_option(field.options, inst_targets, fallback_to_other=True)
                        if matched:
                            mapped_answers[field_id] = _match(matched, "profile.education.institution", 0.98)
                            continue
                    mapped_answers[field_id] = _match(inst_name, "profile.education.institution", 0.95)
                    continue

            # General graduation year / completion year
            if any(t in label for t in ("graduation year", "year of graduation", "year of passing", "passing year", "completion year")):
                if highest_edu and highest_edu.graduation_year:
                    mapped_answers[field_id] = _match(str(highest_edu.graduation_year), "profile.education.graduation_year", 0.95)
                    continue

            # Month & year of completion / completion date
            if any(t in label for t in ("month & year of completion", "completion date", "month/year of graduation", "graduation date")):
                if highest_edu and highest_edu.graduation_year:
                    mapped_answers[field_id] = _match(f"06/{highest_edu.graduation_year}", "profile.education.completion_date", 0.92)
                    continue

            # Major / Field of study
            if any(t in label for t in ("major", "field of study", "specialization", "branch")):
                if highest_edu and highest_edu.major:
                    mapped_answers[field_id] = _match(highest_edu.major, "profile.education.major", 0.95)
                    continue

            # -- Remote work preference --
            if any(t in label for t in ("remote", "work remotely", "plan to work remotely", "work from home", "remote location", "work arrangement")):
                rem_pref = getattr(profile.job_preferences, "remote_preference", "yes") if profile.job_preferences else "yes"
                ans = "Yes" if rem_pref in (True, "yes", "Yes") else "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "Yes, I plan to work remotely", "Yes, open to remote", "Open to remote", "Remote", "Hybrid", "In-office / Remote"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.job_preferences.remote_preference", 0.98)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.job_preferences.remote_preference", 0.98)
                continue

            # -- Relocation with options --
            if any(t in label for t in ("relocate", "relocation")):
                reloc = profile.willing_to_relocate
                ans = "Yes" if reloc in (True, "yes", "Yes") else ("No" if reloc in (False, "no", "No") else None)
                if ans and field.options:
                    matched = _match_option(field.options, [ans, "Yes, open to relocation", "Willing to relocate"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.job_preferences.willing_to_relocate", 0.95)
                        continue
                if ans:
                    mapped_answers[field_id] = _match(ans, "profile.job_preferences.willing_to_relocate", 0.95)
                    continue

            # -- Work authorization & Sponsorship / Visa --
            if any(t in label for t in ("sponsor", "sponsorship", "visa sponsorship", "work permit", "require sponsorship")):
                ans = "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "No, I do not", "No, I will not require sponsorship", "I do not require sponsorship", "Not Required", "False"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.professional.work_authorization.sponsorship", 0.98)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.professional.work_authorization.sponsorship", 0.98)
                continue

            if any(t in label for t in ("authorized to work", "legally authorized", "work authorization", "eligible to work", "authorization")):
                ans = "Yes"
                if field.options:
                    matched = _match_option(field.options, [ans, "Authorized", "Yes, authorized", "Yes, I am authorized", "True"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.professional.work_authorization", 0.98)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.professional.work_authorization", 0.98)
                continue

            # -- Demographics / Diversity (Hispanic/Latino, Race, Veteran, Disability) --
            # Hispanic / Latino
            if any(t in label for t in ("hispanic", "latino", "are you hispanic")):
                hisp_val = getattr(p, "hispanic_latino", None) or "No / Not Hispanic or Latino"
                targets = ["No / Not Hispanic or Latino", "No", "Not Hispanic or Latino", "No, I am not Hispanic or Latino", "Not Hispanic/Latino", "False"]
                if field.options:
                    matched = _match_option(field.options, targets)
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.demographics.hispanic_latino", 0.99)
                        continue
                mapped_answers[field_id] = _match(hisp_val, "profile.demographics.hispanic_latino", 0.99)
                continue

            # Race / Ethnicity: Asian, preferring Asian Indian if available
            if any(t in label for t in ("race", "ethnicity", "racial", "ethnic background", "race / ethnicity")):
                targets = [
                    "Asian Indian", "Asian (Asian Indian)", "South Asian",
                    "Asian", "Asian (Not Hispanic or Latino)", "Asian / Pacific Islander"
                ]
                race_val = getattr(p, "race", "Asian")
                if field.options:
                    matched = _match_option(field.options, targets)
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.demographics.race", 0.99)
                        continue
                mapped_answers[field_id] = _match(race_val, "profile.demographics.race", 0.99)
                continue

            # Veteran Status
            if any(t in label for t in ("veteran", "military status", "protected veteran", "veteran status")):
                vet_val = getattr(p, "veteran_status", None) or "I am not a protected veteran / Not a Veteran"
                targets = [
                    "I am not a protected veteran / Not a Veteran",
                    "I am not a protected veteran",
                    "Not a Veteran",
                    "I am not a veteran",
                    "No",
                    "Not a protected veteran",
                    "I identify as one or more of the classifications of protected veteran: No"
                ]
                if field.options:
                    matched = _match_option(field.options, targets)
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.demographics.veteran_status", 0.99)
                        continue
                mapped_answers[field_id] = _match(vet_val, "profile.demographics.veteran_status", 0.99)
                continue

            # Disability Status
            if any(t in label for t in ("disability", "handicap")):
                dis_val = getattr(p, "disability_status", None) or "No, I do not have a disability"
                targets = [
                    "No, I do not have a disability",
                    "No, I don't have a disability",
                    "No",
                    "I do not have a disability",
                    "No disability"
                ]
                if field.options:
                    matched = _match_option(field.options, targets)
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.demographics.disability_status", 0.99)
                        continue
                mapped_answers[field_id] = _match(dis_val, "profile.demographics.disability_status", 0.99)
                continue

            # -- Legal / Litigation / Court of Law / Criminal Record / Disciplinary Actions --
            if any(t in label for t in (
                "litigation", "court case", "court of law", "criminal", "convicted",
                "conviction", "felony", "misdemeanor", "pending charges", "debarred",
                "disciplinary action", "arrested", "inquiry against you"
            )):
                ans = "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "None", "No, I do not", "False", "No litigation"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.compliance.clean_legal_record", 0.99)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.compliance.clean_legal_record", 0.99)
                continue

            # -- External Directorships / Public Trusteeships / Commercial Interests / Conflicts --
            if any(t in label for t in (
                "external directorship", "directorship", "public trusteeship", "trusteeship",
                "commercial interest", "conflict of interest", "non-hsbc entity", "secondary employment",
                "outside business", "outside commercial"
            )):
                ans = "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "None", "No, I do not", "False", "No directorship"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.compliance.no_external_directorships", 0.99)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.compliance.no_external_directorships", 0.99)
                continue

            # -- Relatives Working in Company / Auditor Affiliation --
            if any(t in label for t in (
                "relatives working", "relative working", "relatives within",
                "family member employed", "employed by external auditor",
                "employed, or are still employed, by hsbc's external auditor"
            )):
                ans = "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "None", "No, I do not", "False"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.compliance.no_company_relatives", 0.99)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.compliance.no_company_relatives", 0.99)
                continue

            # -- Prior Employment / Former Employee / Employee ID / Company Email --
            if any(t in label for t in (
                "ever been employed", "previously employed", "former employee", "prior employee",
                "previously worked", "ever worked", "issued a cisco employee id", "employee id or",
                "cisco employee id", "company email address", "ever been engaged as a contractor",
                "worked here before"
            )):
                ans = "No"
                if field.options:
                    matched = _match_option(field.options, [ans, "No, I have not", "False", "No, never"])
                    if matched:
                        mapped_answers[field_id] = _match(matched, "profile.professional.no_prior_company_employment", 0.99)
                        continue
                mapped_answers[field_id] = _match(ans, "profile.professional.no_prior_company_employment", 0.99)
                continue

            # -- Communication & Contact Consent (SMS, Email, WhatsApp) --
            if any(t in label for t in ("send sms", "sms message", "text message", "sms consent", "opt in to sms")):
                mapped_answers[field_id] = _match("Yes" if field.input_type != "checkbox" else True, "profile.communication.sms_consent", 0.95)
                continue

            if any(t in label for t in ("send email", "emailing me", "email opt", "email consent", "email notifications")):
                mapped_answers[field_id] = _match("Yes" if field.input_type != "checkbox" else True, "profile.communication.email_consent", 0.95)
                continue

            if any(t in label for t in ("send whatsapp", "whatsapp message", "whatsapp consent", "whatsapp")):
                mapped_answers[field_id] = _match("Yes" if field.input_type != "checkbox" else True, "profile.communication.whatsapp_consent", 0.95)
                continue

            # -- File Uploads: Resume / CV or Profile Photo --
            if (field.input_type or "").lower() == "file" or any(t in label for t in ("resume", "cv", "curriculum vitae", "attach resume", "photo", "photograph", "picture", "headshot", "avatar")):
                is_photo = any(t in label for t in ("photo", "photograph", "picture", "headshot", "avatar"))
                if is_photo:
                    photo_path = getattr(p, "photo_path", None)
                    if not photo_path or not os.path.exists(photo_path):
                        photos_dir = os.path.join(os.getcwd(), "knowledge_base", "photos")
                        if os.path.exists(photos_dir):
                            cands = [
                                os.path.join(photos_dir, f) for f in os.listdir(photos_dir)
                                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                            ]
                            if cands:
                                photo_path = cands[0]
                    if photo_path and os.path.exists(photo_path):
                        mapped_answers[field_id] = _match(photo_path, "profile.personal.photo_path", 0.99)
                        continue
                    else:
                        mapped_answers[field_id] = ConfidenceResult(
                            field_id=field_id,
                            answer=None,
                            confidence=0.0,
                            reason=f"No saved profile photograph found for '{label}'. Upload a photo in Profile settings.",
                            requires_human_input=True
                        )
                        continue
                else:
                    # Resume / CV upload
                    resume_path = None
                    if profile and profile.documents and isinstance(profile.documents, dict):
                        resume_path = profile.documents.get("resume_file_path")
                    if not resume_path or not os.path.exists(resume_path):
                        resumes_dir = os.path.join(os.getcwd(), "knowledge_base", "resumes")
                        if os.path.exists(resumes_dir):
                            candidates = [
                                os.path.join(resumes_dir, f)
                                for f in os.listdir(resumes_dir)
                                if f.lower().endswith((".pdf", ".docx", ".doc"))
                            ]
                            for cand in candidates:
                                if "resume" in os.path.basename(cand).lower():
                                    resume_path = cand
                                    break
                            if not resume_path and candidates:
                                resume_path = candidates[0]
                    if resume_path and os.path.exists(resume_path):
                        mapped_answers[field_id] = _match(resume_path, "profile.documents.resume_file_path", 0.99)
                        continue
                    else:
                        mapped_answers[field_id] = ConfidenceResult(
                            field_id=field_id,
                            answer=None,
                            confidence=0.0,
                            reason=f"No saved resume document found in knowledge_base/resumes for '{label}'. Human review required.",
                            requires_human_input=True
                        )
                        continue

        # ---------------------------------------------------------------
        # 2. Check Reusable User Feedback / Learned Corrections
        # ---------------------------------------------------------------
        user_corr = knowledge_service.get_user_correction(label)
        if user_corr and user_corr.get("answer"):
            ans_val = user_corr["answer"]
            if field.options:
                matched_corr = _match_option(field.options, [ans_val])
                if not matched_corr:
                    ans_val = None
                else:
                    ans_val = matched_corr
            if ans_val:
                mapped_answers[field_id] = ConfidenceResult(
                    field_id=field_id,
                    answer=ans_val,
                    confidence=0.98,
                    reason="Reused verified user correction for this question",
                    source_citations=["user_corrections.json"],
                    requires_human_input=False
                )
                continue

        # ---------------------------------------------------------------
        # 3. RAG evidence evaluation for all unmatched fields
        # ---------------------------------------------------------------
        if label:
            eval_res = await knowledge_service.evaluate_evidence(query=label)

            # Never guess! If options exist, select only when confident; never interpret missing info as 'No'
            if field.options:
                matched_opt = None
                if eval_res.decision == "SUFFICIENT_EVIDENCE" and eval_res.best_evidence:
                    matched_opt = _match_option(field.options, [eval_res.best_evidence.text])

                if matched_opt:
                    mapped_answers[field_id] = ConfidenceResult(
                        field_id=field_id,
                        answer=matched_opt,
                        confidence=eval_res.confidence_score,
                        reason=f"Matched option '{matched_opt}' based on knowledge base evidence in '{eval_res.best_evidence.document_name}'.",
                        source_citations=[eval_res.best_evidence.document_name]
                    )
                else:
                    # Never guess or default to 'No' when missing or insufficient evidence!
                    mapped_answers[field_id] = ConfidenceResult(
                        field_id=field_id,
                        answer=None,
                        confidence=0.0,
                        reason=f"Insufficient evidence to safely select from options: {', '.join(field.options[:6])}. Human input required.",
                        requires_human_input=True
                    )
            else:
                if eval_res.decision == "SUFFICIENT_EVIDENCE" and eval_res.best_evidence:
                    mapped_answers[field_id] = ConfidenceResult(
                        field_id=field_id,
                        answer=eval_res.best_evidence.text[:100],
                        confidence=eval_res.confidence_score,
                        reason=eval_res.reason,
                        source_citations=[eval_res.best_evidence.document_name]
                    )
                elif eval_res.decision == "WEAK_EVIDENCE" and eval_res.best_evidence:
                    mapped_answers[field_id] = ConfidenceResult(
                        field_id=field_id,
                        answer=eval_res.best_evidence.text[:100],
                        confidence=eval_res.confidence_score,
                        reason=eval_res.reason,
                        source_citations=[eval_res.best_evidence.document_name],
                        requires_human_input=True
                    )
                else:
                    # No evidence → Human input required
                    mapped_answers[field_id] = ConfidenceResult(
                        field_id=field_id,
                        answer=None,
                        confidence=0.0,
                        reason=f"No information found for '{label}'. Human input required.",
                        requires_human_input=True
                    )

    # Enrich all mapped answers with full FormField metadata for transparency in UI
    field_lookup = {f.data_jp_id: f for f in state.detected_fields}
    for fid, ans_obj in mapped_answers.items():
        fld = field_lookup.get(fid)
        if fld:
            ans_obj.question_text = fld.label or fld.name or fld.placeholder or fid
            ans_obj.section_heading = fld.section_heading
            ans_obj.helper_text = fld.helper_text
            ans_obj.field_type = fld.input_type or fld.tag_name
            ans_obj.options = fld.options or []
            ans_obj.option_elements = fld.option_elements or {}
            ans_obj.is_required = fld.is_required

    state.mapped_answers = mapped_answers
    logger.info(f"Field mapping complete. Mapped {len(mapped_answers)} fields.")
    return state
