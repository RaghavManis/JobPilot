import re
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field
from backend.app.schemas.form import FormField
from backend.app.core.logging import logger


class PageClassificationResult(BaseModel):
    """Structured result of page classification analysis."""
    page_type: str = "APPLICATION_FORM"  # AUTHENTICATION_REQUIRED, APPLICATION_FORM, JOB_DESCRIPTION, APPLICATION_SUBMITTED, GENERAL
    is_auth_barrier: bool = False
    auth_category: Optional[str] = None  # LOGIN, REGISTRATION, LOGIN_OR_REGISTER, OTP_VERIFICATION, CAPTCHA
    auth_details: Optional[str] = None
    has_password_field: bool = False
    has_apply_button: bool = False
    apply_button_selector: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    clean_application_fields: List[FormField] = Field(default_factory=list)


class PageClassifier:
    """Intelligent, portal-agnostic web page classifier for job application workflows."""

    # Words that indicate authentication in URLs
    AUTH_URL_PATTERNS = [
        r"/login\b", r"/signin\b", r"/sign-in\b", r"/sign_in\b",
        r"/auth\b", r"/authenticate\b", r"/authentication\b",
        r"/session/new\b", r"/users/sign_in\b", r"/account/login\b",
        r"/register\b", r"/signup\b", r"/sign-up\b", r"/sign_up\b",
        r"[?&]jobId=[^&]+&login", r"/careers[^/]+/login\b"
    ]

    # Words that indicate authentication in page titles
    AUTH_TITLE_KEYWORDS = [
        "login", "log in", "sign in", "signin", "sign-in",
        "candidate portal", "portal login", "authenticate", "authentication",
        "create account", "register", "registration", "sign up", "new user"
    ]

    # Keywords on buttons indicating auth actions
    AUTH_BUTTON_KEYWORDS = [
        "log in", "login", "sign in", "signin", "sign-in", "sign on",
        "continue with sso", "logon", "authenticate"
    ]

    REGISTRATION_KEYWORDS = [
        "create account", "create an account", "register", "registration",
        "sign up", "signup", "new user", "new candidate", "first time user"
    ]

    # Field attributes that identify sensitive authentication credentials
    AUTH_FIELD_IDENTIFIERS = {
        "password", "passwd", "pwd", "user_password", "current-password",
        "new-password", "confirm_password", "confirmpassword", "passphrase",
        "otp", "2fa", "passcode", "security_code", "verification_code",
        "captcha", "g-recaptcha-response"
    }

    # Job description "Apply" button keywords
    APPLY_BUTTON_KEYWORDS = [
        "apply now", "apply for this job", "apply", "submit application",
        "easy apply", "start application"
    ]

    # Submission success keywords
    SUCCESS_KEYWORDS = [
        "application submitted", "application received", "thank you for applying",
        "successfully submitted", "application complete"
    ]

    APPLICATION_PAGE_KEYWORDS = [
        "general information", "candidate profile", "personal information",
        "personal details", "job application", "application form",
        "contact information", "work experience", "education",
        "resume", "questionnaire", "my profile", "application summary"
    ]

    @classmethod
    def is_auth_field(cls, field: FormField) -> bool:
        """Determine if a FormField represents an authentication credential rather than a job answer."""
        if (field.input_type or "").lower() == "password":
            return True

        for attr in (field.name, field.element_id, field.label, field.placeholder):
            if not attr:
                continue
            cleaned = re.sub(r"[^a-zA-Z0-9_]", "", attr.lower())
            if any(k in cleaned for k in ("password", "passwd", "pwd", "confirmpassword")):
                return True
            if any(k in cleaned for k in ("otp", "2fa", "passcode", "securitycode", "verificationcode")):
                return True
            if "captcha" in cleaned:
                return True

        return False

    @classmethod
    def classify_page(
        cls,
        url: str,
        title: str,
        fields: List[FormField],
        page_text: str = "",
        has_captcha: bool = False
    ) -> PageClassificationResult:
        """Classify page DOM structure and context generically across any ATS/portal."""
        reasons: List[str] = []
        url_lower = (url or "").lower()
        title_lower = (title or "").lower()
        text_lower = (page_text or "").lower()

        # 1. Inspect Fields - STRICTLY separate VISIBLE fields from hidden template DOM elements
        visible_fields = [f for f in fields if f.is_visible]
        visible_password_fields = [
            f for f in visible_fields
            if (f.input_type or "").lower() == "password" or cls.is_auth_field(f)
        ]
        has_visible_password = len(visible_password_fields) > 0

        # Visible non-auth interactive candidate input fields (text, email, tel, select, textarea, file, checkbox, radio)
        visible_app_fields = [
            f for f in visible_fields
            if not cls.is_auth_field(f)
            and f.tag_name in ("input", "select", "textarea")
            and (f.input_type or "").lower() not in ("hidden", "submit", "button", "reset")
        ]

        # All clean fields for form extraction
        clean_fields = [f for f in fields if not cls.is_auth_field(f)]

        # 2. Check for Submission Success
        if any(sk in title_lower or sk in text_lower for sk in cls.SUCCESS_KEYWORDS):
            reasons.append("Application submission success message detected on page.")
            return PageClassificationResult(
                page_type="APPLICATION_SUBMITTED",
                is_auth_barrier=False,
                reasons=reasons,
                clean_application_fields=clean_fields
            )

        # 3. Check if page is explicitly an Application Form section (e.g. "General information", "/apply")
        is_app_title = any(ak in title_lower for ak in cls.APPLICATION_PAGE_KEYWORDS)
        is_app_url = any(ak in url_lower for ak in ("/apply", "/jobs/apply", "/careers/apply", "/application"))
        has_substantial_app_fields = len(visible_app_fields) >= 3

        # If the page title/URL is an application section OR has 3+ visible application fields with no visible password:
        if (is_app_title or is_app_url or has_substantial_app_fields) and not has_visible_password and len(visible_app_fields) > 0:
            logger.info(
                f"PageClassifier: Confirmed active APPLICATION_FORM ('{title}', "
                f"visible_app_fields={len(visible_app_fields)}, visible_passwords={len(visible_password_fields)})"
            )
            reasons.append(
                f"Detected legitimate job application form '{title}' with {len(visible_app_fields)} visible candidate fields."
            )
            return PageClassificationResult(
                page_type="APPLICATION_FORM",
                is_auth_barrier=False,
                has_password_field=has_visible_password,
                reasons=reasons,
                clean_application_fields=clean_fields
            )

        # 4. Check CAPTCHA / Bot Barrier (Only when there are no substantial candidate form fields to fill)
        if (has_captcha or "verify you are human" in text_lower or "security check" in text_lower) and len(visible_app_fields) < 3:
            reasons.append("CAPTCHA or bot verification barrier detected on page.")
            return PageClassificationResult(
                page_type="AUTHENTICATION_REQUIRED",
                is_auth_barrier=True,
                auth_category="CAPTCHA",
                auth_details="CAPTCHA or bot security verification required.",
                has_password_field=has_visible_password,
                reasons=reasons,
                clean_application_fields=[]
            )

        # 5. Check Authentication Signals for Dedicated Login/Registration Barriers
        auth_score = 0
        auth_reasons: List[str] = []

        # (a) Visible password field on a page with few or no candidate application fields
        if has_visible_password and len(visible_app_fields) <= 2:
            auth_score += 60
            auth_reasons.append(f"Detected {len(visible_password_fields)} visible password input field(s).")

        # (b) URL Signals
        for pattern in cls.AUTH_URL_PATTERNS:
            if re.search(pattern, url_lower):
                auth_score += 40
                auth_reasons.append(f"URL matches authentication pattern '{pattern}'.")
                break

        # (c) Title Signals
        for kw in cls.AUTH_TITLE_KEYWORDS:
            if kw in title_lower:
                auth_score += 30
                auth_reasons.append(f"Page title contains authentication keyword '{kw}'.")
                break

        # (d) Interactive Button Signals on visible elements
        button_texts = [
            (f.visible_text or f.label or f.current_value or "").lower()
            for f in visible_fields
            if f.tag_name in ("button", "a") or (f.input_type or "").lower() in ("submit", "button")
        ]
        has_login_button = any(any(kw == b.strip() or kw in b for kw in cls.AUTH_BUTTON_KEYWORDS) for b in button_texts)
        has_reg_button = any(any(kw in b for kw in cls.REGISTRATION_KEYWORDS) for b in button_texts)

        if has_login_button:
            auth_score += 25
            auth_reasons.append("Login/Sign-in button detected on page.")
        if has_reg_button:
            auth_score += 20
            auth_reasons.append("Account registration / Sign-up option detected on page.")

        # (e) Field Composition Check: Form has very few fields and includes a visible password
        if len(visible_fields) <= 4 and has_visible_password:
            auth_score += 30
            auth_reasons.append(f"Page contains only {len(visible_fields)} visible elements with password authentication structure.")

        # 6. Decide if Authentication Barrier Exists
        # A barrier requires significant score AND must not have substantial application fields
        if (auth_score >= 50 or (has_visible_password and len(visible_app_fields) <= 2)) and len(visible_app_fields) <= 2:
            category = "LOGIN"
            if has_reg_button and has_login_button:
                category = "LOGIN_OR_REGISTER"
            elif has_reg_button and not has_login_button:
                category = "REGISTRATION"
            elif any(k in text_lower for k in ("verification code", "two-step", "2-step", "one-time")):
                category = "OTP_VERIFICATION"

            details = f"Authentication barrier ({category}) detected. " + " ".join(auth_reasons)
            logger.info(f"PageClassifier: Classified as AUTHENTICATION_REQUIRED (score={auth_score}, category={category})")

            return PageClassificationResult(
                page_type="AUTHENTICATION_REQUIRED",
                is_auth_barrier=True,
                auth_category=category,
                auth_details=details,
                has_password_field=has_visible_password,
                reasons=auth_reasons,
                clean_application_fields=[]
            )

        # 6. Check if page is a Job Description page with "Apply" button
        apply_button_selector = None
        has_apply = False
        for f in fields:
            f_text = (f.visible_text or f.label or f.current_value or "").lower().strip()
            if any(ak == f_text or ak in f_text for ak in cls.APPLY_BUTTON_KEYWORDS):
                has_apply = True
                apply_button_selector = f'[data-jp-id="{f.data_jp_id}"]'
                reasons.append(f"Detected Apply action '{f_text}' ({f.data_jp_id}).")
                break

        # If there are NO application input fields but an Apply button exists
        input_fields = [f for f in clean_fields if f.tag_name in ("input", "select", "textarea") and (f.input_type or "") not in ("button", "submit", "hidden")]
        if has_apply and len(input_fields) == 0:
            return PageClassificationResult(
                page_type="JOB_DESCRIPTION",
                is_auth_barrier=False,
                has_apply_button=True,
                apply_button_selector=apply_button_selector,
                reasons=reasons,
                clean_application_fields=clean_fields
            )

        # 7. Otherwise, standard Job Application Form
        reasons.append(f"Detected legitimate job application form with {len(clean_fields)} candidate fields.")
        return PageClassificationResult(
            page_type="APPLICATION_FORM",
            is_auth_barrier=False,
            has_password_field=has_visible_password,
            reasons=reasons,
            clean_application_fields=clean_fields
        )
