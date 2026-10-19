import pytest
from backend.app.browser.page_classifier import PageClassifier
from backend.app.schemas.form import FormField
from backend.app.agent.state import ApplicationState
from backend.app.agent.graph import route_after_detect, route_after_confidence


def test_classify_deloitte_login_page():
    """Test classification of the Deloitte login URL pattern."""
    fields = [
        FormField(data_jp_id="f1", tag_name="input", input_type="email", name="username", label="Email address"),
        FormField(data_jp_id="f2", tag_name="input", input_type="password", name="password", label="Password"),
        FormField(data_jp_id="f3", tag_name="button", input_type="submit", visible_text="Login")
    ]
    result = PageClassifier.classify_page(
        url="https://usijobs.deloitte.com/en_US/careersUSI/Login?jobId=371199",
        title="Login | Deloitte | India Offices of the US",
        fields=fields,
        page_text="Please sign in with your email and password to apply."
    )

    assert result.page_type == "AUTHENTICATION_REQUIRED"
    assert result.is_auth_barrier is True
    assert result.auth_category == "LOGIN"
    assert result.has_password_field is True
    # Crucial: Password and login fields must NOT be exposed as application questions
    assert len(result.clean_application_fields) == 0


def test_classify_registration_page():
    """Test classification of a candidate registration page."""
    fields = [
        FormField(data_jp_id="f1", tag_name="input", input_type="email", name="email", label="Email"),
        FormField(data_jp_id="f2", tag_name="input", input_type="password", name="password", label="Password"),
        FormField(data_jp_id="f3", tag_name="input", input_type="password", name="confirm_password", label="Confirm Password"),
        FormField(data_jp_id="f4", tag_name="button", input_type="submit", visible_text="Register Account")
    ]
    result = PageClassifier.classify_page(
        url="https://careers.company.com/register",
        title="Create New Account - Careers Portal",
        fields=fields,
        page_text="Create an account to track your job application."
    )

    assert result.page_type == "AUTHENTICATION_REQUIRED"
    assert result.is_auth_barrier is True
    assert result.auth_category in ("REGISTRATION", "LOGIN_OR_REGISTER")
    assert len(result.clean_application_fields) == 0


def test_classify_job_application_form():
    """Test that legitimate job application forms without password walls are classified as APPLICATION_FORM."""
    fields = [
        FormField(data_jp_id="f1", tag_name="input", input_type="text", name="firstName", label="First Name"),
        FormField(data_jp_id="f2", tag_name="input", input_type="text", name="lastName", label="Last Name"),
        FormField(data_jp_id="f3", tag_name="input", input_type="email", name="email", label="Email Address"),
        FormField(data_jp_id="f4", tag_name="input", input_type="tel", name="phone", label="Phone Number"),
        FormField(data_jp_id="f5", tag_name="select", name="country", label="Country of Residence"),
        FormField(data_jp_id="f6", tag_name="input", input_type="file", name="resume", label="Upload Resume"),
        FormField(data_jp_id="f7", tag_name="input", input_type="checkbox", name="consent", label="I consent"),
        FormField(data_jp_id="f8", tag_name="button", input_type="submit", visible_text="Save & Continue")
    ]
    result = PageClassifier.classify_page(
        url="http://localhost:8001/mock_form.html",
        title="JobPilot Mock Job Application",
        fields=fields,
        page_text="Please fill out the application form below."
    )

    assert result.page_type == "APPLICATION_FORM"
    assert result.is_auth_barrier is False
    assert result.auth_category is None
    assert len(result.clean_application_fields) == 8


def test_classify_captcha_barrier():
    """Test classification when CAPTCHA is present."""
    fields = [
        FormField(data_jp_id="f1", tag_name="button", visible_text="Submit")
    ]
    result = PageClassifier.classify_page(
        url="https://portal.com/apply",
        title="Security Check",
        fields=fields,
        has_captcha=True,
        page_text="Please verify you are human."
    )

    assert result.page_type == "AUTHENTICATION_REQUIRED"
    assert result.is_auth_barrier is True
    assert result.auth_category == "CAPTCHA"


def test_workflow_route_after_detect():
    """Verify that route_after_detect halts at human_login_pause when login is required."""
    # When login is required, it must route to human_login_pause
    state_auth = ApplicationState(
        application_id="app_1",
        user_id="user_1",
        target_url="https://usijobs.deloitte.com/en_US/careersUSI/Login?jobId=371199",
        login_required=True,
        status="LOGIN_REQUIRED"
    )
    assert route_after_detect(state_auth) == "human_login_pause"

    # When login is not required, it routes to map_fields
    state_form = ApplicationState(
        application_id="app_2",
        user_id="user_1",
        target_url="http://localhost:8001/mock_form.html",
        login_required=False,
        status="RUNNING"
    )
    assert route_after_detect(state_form) == "map_fields"


def test_is_auth_field_filters_passwords():
    """Ensure is_auth_field detects sensitive credential fields."""
    f_pass = FormField(data_jp_id="f1", tag_name="input", input_type="password", name="pwd")
    assert PageClassifier.is_auth_field(f_pass) is True

    f_otp = FormField(data_jp_id="f2", tag_name="input", input_type="text", name="verification_code", label="Enter OTP")
    assert PageClassifier.is_auth_field(f_otp) is True

    f_normal = FormField(data_jp_id="f3", tag_name="input", input_type="text", name="first_name", label="First Name")
    assert PageClassifier.is_auth_field(f_normal) is False


def test_classify_post_login_general_information_page():
    """Test that a post-login page titled 'General information' with hidden password fields is classified as APPLICATION_FORM."""
    fields = [
        # Two hidden password inputs (e.g. from header modal / profile dropdown in DOM)
        FormField(data_jp_id="f_pwd1", tag_name="input", input_type="password", name="old_pwd", is_visible=False),
        FormField(data_jp_id="f_pwd2", tag_name="input", input_type="password", name="new_pwd", is_visible=False),
        # Legitimate visible application fields
        FormField(data_jp_id="f1", tag_name="input", input_type="text", name="firstName", label="First Name", is_visible=True),
        FormField(data_jp_id="f2", tag_name="input", input_type="text", name="lastName", label="Last Name", is_visible=True),
        FormField(data_jp_id="f3", tag_name="input", input_type="email", name="email", label="Email", is_visible=True),
        FormField(data_jp_id="f4", tag_name="input", input_type="tel", name="phone", label="Phone Number", is_visible=True),
        FormField(data_jp_id="f5", tag_name="select", name="country", label="Country", is_visible=True),
        FormField(data_jp_id="f6", tag_name="button", input_type="submit", visible_text="Save & Next", is_visible=True)
    ]
    result = PageClassifier.classify_page(
        url="https://usijobs.deloitte.com/en_US/careersUSI/JobApplication?jobId=371199",
        title="General information | Deloitte | India Offices of the US",
        fields=fields,
        page_text="General Information. Please enter your contact details and background."
    )

    assert result.page_type == "APPLICATION_FORM"
    assert result.is_auth_barrier is False
    assert result.has_password_field is False
    # Only visible clean application fields should be present
    assert len(result.clean_application_fields) == 6


def test_classify_application_form_with_background_captcha():
    """Verify pages with candidate application fields and background reCAPTCHA tokens are not blocked as auth barriers."""
    fields = [
        FormField(data_jp_id="f1", tag_name="input", input_type="text", name="first_name", label="First Name*", is_visible=True),
        FormField(data_jp_id="f2", tag_name="input", input_type="text", name="last_name", label="Last Name*", is_visible=True),
        FormField(data_jp_id="f3", tag_name="input", input_type="email", name="email", label="Email*", is_visible=True),
        FormField(data_jp_id="f4", tag_name="input", input_type="file", name="resume", label="Resume", is_visible=True),
        FormField(data_jp_id="f5", tag_name="button", input_type="submit", visible_text="Submit Application", is_visible=True)
    ]
    result = PageClassifier.classify_page(
        url="https://stripe.com/careers/apply/ai-engineer/8144196",
        title="Stripe Careers | Apply for AI Engineer",
        fields=fields,
        has_captcha=True,  # Background invisible reCAPTCHA present on ATS portal
        page_text="Apply for AI Engineer. Please enter your contact details and resume."
    )

    assert result.page_type == "APPLICATION_FORM"
    assert result.is_auth_barrier is False
    assert result.auth_category is None
    assert len(result.clean_application_fields) == 5
