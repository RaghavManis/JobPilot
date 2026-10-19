import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.app.schemas.form import FormField, FormPage, ConfidenceResult, FieldValue
from backend.app.schemas.profile import UserProfile, PersonalInfo, EducationInfo, ProfessionalInfo
from backend.app.agent.nodes.reasoning_nodes import map_fields_and_retrieve_node
from backend.app.agent.confidence import ConfidenceEngine
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.browser.actions import BrowserActions
from backend.app.core.exceptions import BrowserException
from backend.app.agent.state import ApplicationState


@pytest.fixture
def sample_user_profile():
    return UserProfile(
        user_id="test_manish",
        personal=PersonalInfo(
            first_name="Manish",
            last_name="Yadav",
            full_name="Manish Yadav",
            email="mnsyd24@gmail.com",
            phone="8429766063",
            gender="male"
        ),
        professional=ProfessionalInfo(
            total_experience_years=1.0,
            notice_period_days=0,
            current_company="Infosys"
        ),
        education=[
            EducationInfo(
                degree="Master of Computer Applications (MCA)",
                institution="Motilal Nehru National Institute of Technology Allahabad (MNNIT Allahabad)",
                graduation_year=2026,
                start_year=2023,
                major="Computer Applications",
                gpa_or_percentage="CPI 8.15",
                status="Completed; provisional degree obtained"
            ),
            EducationInfo(
                degree="Bachelor of Science (B.Sc.)",
                institution="Smt. Indira Gandhi PG College, Mau",
                graduation_year=2023,
                start_year=2020,
                major="physics honors",
                status="Completed"
            )
        ]
    )


@pytest.mark.asyncio
async def test_education_mapping_answers_yes_to_postgraduate(sample_user_profile):
    """Verify JobPilot correctly answers 'Yes' to postgraduate completion instead of 'No'."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    fields = [
        FormField(
            data_jp_id="field_pg",
            tag_name="select",
            label="Have you completed your postgraduate education?",
            options=["Yes", "No"]
        ),
        FormField(
            data_jp_id="field_highest_edu",
            tag_name="select",
            label="Highest level of education",
            options=["High School", "Bachelor's Degree", "Master's Degree / Post-Graduate", "Doctorate"]
        ),
        FormField(
            data_jp_id="field_completion_date",
            tag_name="input",
            input_type="text",
            label="Month & year of completion *"
        )
    ]

    state = ApplicationState(
        application_id="app_test_edu",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=fields
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    answers = result_state.mapped_answers

    # 1. Postgraduate completion must be 'Yes'
    assert "field_pg" in answers
    assert answers["field_pg"].answer == "Yes"
    assert answers["field_pg"].confidence >= 0.95
    assert not answers["field_pg"].requires_human_input

    # 2. Highest degree matches 'Master's Degree / Post-Graduate'
    assert "field_highest_edu" in answers
    assert answers["field_highest_edu"].answer == "Master's Degree / Post-Graduate"

    # 3. Month & year of completion maps 2026
    assert "field_completion_date" in answers
    assert "2026" in answers["field_completion_date"].answer


@pytest.mark.asyncio
async def test_never_interpret_missing_info_as_no(sample_user_profile):
    """Verify that unknown yes/no questions never default to 'No' and require human review."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    # RAG returns insufficient evidence
    eval_result = MagicMock()
    eval_result.decision = "INSUFFICIENT_EVIDENCE"
    eval_result.best_evidence = None
    ks_mock.evaluate_evidence = AsyncMock(return_value=eval_result)

    field = FormField(
        data_jp_id="field_clearance",
        tag_name="select",
        label="Do you currently hold active Top Secret security clearance?",
        options=["Yes", "No"]
    )

    state = ApplicationState(
        application_id="app_test_no_guess",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans = result_state.mapped_answers["field_clearance"]

    # Must NEVER guess "No"
    assert ans.answer is None or ans.confidence < 0.5
    assert ans.requires_human_input is True


@pytest.mark.asyncio
async def test_user_corrections_learned_and_reused(sample_user_profile, tmp_path):
    """Verify that saved user corrections are remembered and prioritized for equivalent questions."""
    ks = KnowledgeService(
        db=AsyncMock(),
        embedding_provider=MagicMock(),
        vector_store=MagicMock()
    )
    # Redirect corrections file to temporary path
    test_corrections_file = str(tmp_path / "user_corrections.json")
    ks.CORRECTIONS_FILE = test_corrections_file

    # Save a correction
    ks.save_user_correction(
        question="Preferred Working Timezone",
        answer="IST (Indian Standard Time)",
        context={"field_type": "text"}
    )

    saved = ks.get_user_correction("Preferred Working Timezone *")
    assert saved is not None
    assert saved["answer"] == "IST (Indian Standard Time)"


@pytest.mark.asyncio
async def test_browser_actions_skip_redundant_fill():
    """Verify that fill_text skips re-typing if input already has identical value."""
    page_mock = AsyncMock()
    element_mock = AsyncMock()
    element_mock.input_value = AsyncMock(return_value="Manish")
    element_mock.get_attribute = AsyncMock(return_value="text")

    locator_mock = MagicMock()
    locator_mock.first = element_mock
    page_mock.locator = MagicMock(return_value=locator_mock)

    await BrowserActions.fill_text(page_mock, "field_001", "Manish")

    # fill("") and press_sequentially must NOT be called when value already matches!
    element_mock.fill.assert_not_called()
    element_mock.press_sequentially.assert_not_called()


@pytest.mark.asyncio
async def test_multi_select_countries_grouped_and_mapped(sample_user_profile):
    """Verify that multi-select country checkboxes are treated as ONE question and match India."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    field = FormField(
        data_jp_id="field_country_group",
        tag_name="input",
        input_type="checkbox_group",
        name="question_68710824[]",
        label="Please select the country or countries you anticipate working in for the role in which you are applying. *",
        options=["Australia", "Belgium", "Brazil", "Canada", "France", "Germany", "India", "United States"],
        option_elements={
            "Australia": "field_032",
            "Belgium": "field_033",
            "India": "field_038",
            "United States": "field_045"
        },
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_country_group",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans = result_state.mapped_answers["field_country_group"]

    assert ans is not None
    assert ans.answer == "India"
    assert ans.confidence >= 0.95
    assert not ans.requires_human_input
    assert ans.option_elements.get("India") == "field_038"


@pytest.mark.asyncio
async def test_degree_question_matches_profile_mca(sample_user_profile):
    """Verify that Degree* field matches MCA / Master's Degree without triggering HITL."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    # Combobox with options
    field_options = FormField(
        data_jp_id="field_degree_opt",
        tag_name="input",
        input_type="text",
        label="Degree*",
        options=["High School", "Associate's Degree", "Bachelor's Degree", "Master's Degree", "Doctorate"],
        is_required=True
    )

    # Combobox without static options
    field_text = FormField(
        data_jp_id="field_degree_txt",
        tag_name="input",
        input_type="text",
        label="Degree*",
        options=[],
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_degree",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_options, field_text]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans_opt = result_state.mapped_answers["field_degree_opt"]
    ans_txt = result_state.mapped_answers["field_degree_txt"]

    assert ans_opt.answer == "Master's Degree"
    assert ans_opt.confidence >= 0.95
    assert not ans_opt.requires_human_input

    assert "Master" in ans_txt.answer or "MCA" in ans_txt.answer
    assert ans_txt.confidence >= 0.95
    assert not ans_txt.requires_human_input


@pytest.mark.asyncio
async def test_sponsorship_inferred_as_no_for_india(sample_user_profile):
    """Verify sponsorship questions answer 'No' for Indian candidate applying in India without forcing HITL."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    field_sponsor = FormField(
        data_jp_id="field_sponsor",
        tag_name="input",
        input_type="text",
        label="Will you require Stripe to sponsor you for a work permit now or in the future for the location(s) you selected in in your previous response? *",
        options=["Yes", "No"],
        is_required=True
    )

    field_auth = FormField(
        data_jp_id="field_auth",
        tag_name="input",
        input_type="text",
        label="Are you authorized to work in the location(s) you selected in your previous response?*",
        options=["Yes", "No"],
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_sponsor",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_sponsor, field_auth]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans_sponsor = result_state.mapped_answers["field_sponsor"]
    ans_auth = result_state.mapped_answers["field_auth"]

    assert ans_sponsor.answer == "No"
    assert ans_sponsor.confidence >= 0.95
    assert not ans_sponsor.requires_human_input

    assert ans_auth.answer == "Yes"
    assert ans_auth.confidence >= 0.95

    # Verify ConfidenceEngine routes them to AUTO_FILL rather than MANDATORY_HUMAN_INPUT
    engine = ConfidenceEngine()
    auto_q, human_q = engine.partition_answers(
        [field_sponsor, field_auth],
        [ans_sponsor, ans_auth]
    )

    assert len(auto_q) == 2
    assert len(human_q) == 0
    assert any(q.data_jp_id == "field_sponsor" and q.value == "No" for q in auto_q)


@pytest.mark.asyncio
async def test_remote_work_preference_answers_yes(sample_user_profile):
    """Verify remote work questions answer 'Yes' based on profile remote_preference without forcing HITL."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    field_remote = FormField(
        data_jp_id="field_remote",
        tag_name="input",
        input_type="text",
        label="If this role offers the option to work from a remote location, do you plan to work remotely?*",
        options=["Yes", "No"],
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_remote",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_remote]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans_remote = result_state.mapped_answers["field_remote"]

    assert ans_remote.answer == "Yes"
    assert ans_remote.confidence >= 0.95
    assert not ans_remote.requires_human_input

    engine = ConfidenceEngine()
    auto_q, human_q = engine.partition_answers([field_remote], [ans_remote])
    assert len(auto_q) == 1
    assert len(human_q) == 0
    assert auto_q[0].value == "Yes"


@pytest.mark.asyncio
async def test_country_code_dropdown_selects_plus_91(sample_user_profile):
    """Issue 1: Verify phone country-code dropdown correctly selects +91/91 (India)."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    fields = [
        FormField(
            data_jp_id="field_cc_1",
            tag_name="select",
            label="Phone Country Code",
            options=["+1 (US)", "+44 (UK)", "India (+91)", "+61 (AU)"]
        ),
        FormField(
            data_jp_id="field_cc_2",
            tag_name="select",
            name="country_code",
            label="Country*",
            section_heading="Phone",
            options=["+1", "+44", "+91", "+33"]
        )
    ]

    state = ApplicationState(
        application_id="app_test_cc",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=fields
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans1 = result_state.mapped_answers["field_cc_1"]
    ans2 = result_state.mapped_answers["field_cc_2"]

    assert ans1.answer == "India (+91)"
    assert ans1.confidence >= 0.95
    assert ans2.answer == "+91"
    assert ans2.confidence >= 0.95


@pytest.mark.asyncio
async def test_phone_number_complete_10_digits_entered(sample_user_profile):
    """Issue 2: Verify full 10-digit number '8429766063' is preserved and truncation is recovered."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    field_phone = FormField(
        data_jp_id="field_phone",
        tag_name="input",
        input_type="tel",
        label="Phone number*",
        placeholder="Enter your mobile number"
    )

    state = ApplicationState(
        application_id="app_test_phone",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_phone]
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans = result_state.mapped_answers["field_phone"]
    # Complete 10-digit string, never truncated to 8429766
    assert ans.answer == "8429766063"
    assert len(ans.answer) == 10


@pytest.mark.asyncio
async def test_school_and_degree_other_option_selection(sample_user_profile):
    """Issue 3: When exact school/degree is not listed, select the actual 'Other' option."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    fields = [
        # School dropdown with western universities + 'Other / Not Listed'
        FormField(
            data_jp_id="field_school",
            tag_name="select",
            label="School / University",
            options=["Harvard University", "Stanford University", "MIT", "Other / Not Listed"]
        ),
        # Degree dropdown without MCA + 'Other'
        FormField(
            data_jp_id="field_degree",
            tag_name="select",
            label="Degree",
            options=["High School", "Associate's Degree", "Other"]
        )
    ]

    state = ApplicationState(
        application_id="app_test_other",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=fields
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans_school = result_state.mapped_answers["field_school"]
    ans_degree = result_state.mapped_answers["field_degree"]

    assert ans_school.answer == "Other / Not Listed"
    assert ans_school.confidence >= 0.95
    assert ans_degree.answer == "Other"
    assert ans_degree.confidence >= 0.95


@pytest.mark.asyncio
async def test_resume_upload_and_demographic_answers(sample_user_profile):
    """Issue 4: Automatically locate resume and persistently map demographic answers."""
    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    fields = [
        FormField(
            data_jp_id="field_resume",
            tag_name="input",
            input_type="file",
            label="Attach Resume/CV*"
        ),
        FormField(
            data_jp_id="field_hispanic",
            tag_name="select",
            label="Are you Hispanic or Latino?",
            options=["Yes", "No", "Decline to specify"]
        ),
        FormField(
            data_jp_id="field_race",
            tag_name="select",
            label="Race / Ethnicity",
            options=["White", "Black or African American", "Asian Indian", "Asian", "Two or More Races"]
        ),
        FormField(
            data_jp_id="field_veteran",
            tag_name="select",
            label="Veteran Status",
            options=["I am a veteran", "I am not a protected veteran", "I do not wish to answer"]
        )
    ]

    state = ApplicationState(
        application_id="app_test_resume_demo",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=fields
    )

    result_state = await map_fields_and_retrieve_node(state, ks_mock)
    ans_resume = result_state.mapped_answers["field_resume"]
    ans_hisp = result_state.mapped_answers["field_hispanic"]
    ans_race = result_state.mapped_answers["field_race"]
    ans_vet = result_state.mapped_answers["field_veteran"]

    # 1. Resume automatically located and mapped
    assert ans_resume.answer is not None
    assert ans_resume.answer.endswith((".pdf", ".docx", ".doc"))
    assert ans_resume.confidence >= 0.95
    assert not ans_resume.requires_human_input

    # 2. Hispanic/Latino: No
    assert ans_hisp.answer == "No"

    # 3. Race: Asian Indian selected because available
    assert ans_race.answer == "Asian Indian"

    # 4. Veteran: Not a veteran
    assert ans_vet.answer == "I am not a protected veteran"

    # Confidence routing should auto-fill all of them
    engine = ConfidenceEngine()
    auto_q, human_q = engine.partition_answers(fields, list(result_state.mapped_answers.values()))
    assert len(human_q) == 0
    assert len(auto_q) == 4


@pytest.mark.asyncio
async def test_deep_browser_state_cross_check():
    """Issue 5: Deep DOM cross-check detects mismatches, auto-corrects, and routes unresolved to HITL."""
    from backend.app.agent.nodes.execution_nodes import validate_page_node
    from backend.app.browser.manager import BrowserManager

    field_phone = FormField(
        data_jp_id="field_phone",
        tag_name="input",
        input_type="tel",
        label="Phone number",
        is_required=True
    )
    field_cc = FormField(
        data_jp_id="field_cc",
        tag_name="select",
        label="Country Code",
        is_required=True
    )

    state = ApplicationState(
        application_id="app_cross_check",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_phone, field_cc],
        mapped_answers={
            "field_phone": ConfidenceResult(
                field_id="field_phone",
                answer="8429766063",
                confidence=0.99,
                reason="profile.personal.phone"
            ),
            "field_cc": ConfidenceResult(
                field_id="field_cc",
                answer="+91",
                confidence=0.99,
                reason="profile.personal.country_code"
            )
        }
    )

    # Mock page and browser manager
    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    # Simulate browser DOM state: phone is truncated to 8429766 initially, country code is correct (+91)
    call_counts = {"phone": 0}

    async def mock_get_field_live_state(page, field):
        if field.data_jp_id == "field_phone":
            call_counts["phone"] += 1
            # After auto-correction attempt, return full 8429766063
            if call_counts["phone"] > 1:
                return {"value": "8429766063", "selected_text": None, "checked": False, "files": [], "is_visible": True}
            return {"value": "8429766", "selected_text": None, "checked": False, "files": [], "is_visible": True}
        elif field.data_jp_id == "field_cc":
            return {"value": "+91", "selected_text": "India (+91)", "checked": False, "files": [], "is_visible": True}
        return {"value": None, "selected_text": None, "checked": False, "files": [], "is_visible": True}

    with patch.object(BrowserActions, "get_field_live_state", side_effect=mock_get_field_live_state), \
         patch.object(BrowserActions, "fill_text", new_callable=AsyncMock) as mock_fill:
        res_state = await validate_page_node(state, bm_mock)

        # Phone mismatch was detected and auto-corrected to 8429766063!
        assert mock_fill.called
        assert len(res_state.human_review_queue) == 0
        assert len(res_state.validation_errors) == 0


@pytest.mark.asyncio
async def test_auto_fill_escalates_failed_fields_to_hitl():
    """Verify that when an automated interaction fails during auto_fill, the field is escalated to human_review_queue."""
    from backend.app.agent.nodes.execution_nodes import auto_fill_node
    from backend.app.schemas.form import FieldValue

    field = FormField(
        data_jp_id="field_custom_dropdown",
        tag_name="button",
        input_type="button",
        label="Preferred Work Location",
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_hitl_escalation",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field],
        auto_fill_queue=[
            FieldValue(data_jp_id="field_custom_dropdown", value="Bangalore", field_type="select")
        ],
        mapped_answers={},
        human_review_queue=[]
    )

    from backend.app.browser.manager import BrowserManager
    from backend.app.browser.dom_inspector import DOMInspector
    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    page_mock.url = "https://example.com/apply"
    page_mock.title = AsyncMock(return_value="Job Application")
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    # Simulate failure during select_option (e.g. unclickable custom component)
    with patch.object(BrowserActions, "select_option", side_effect=Exception("Element is obscured or detached")), \
         patch.object(DOMInspector, "inspect_page", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = FormPage(
            url="https://example.com/apply",
            title="Job Application",
            fields=[field]
        )

        res_state = await auto_fill_node(state, bm_mock)

        # Verified: field was NOT silently skipped, but escalated to human_review_queue!
        assert len(res_state.human_review_queue) == 1
        failed_item = res_state.human_review_queue[0]
        assert failed_item.field_id == "field_custom_dropdown"
        assert failed_item.requires_human_input is True
        assert "Element is obscured or detached" in failed_item.reason


@pytest.mark.asyncio
async def test_submit_application_detects_otp_barrier():
    """Verify that when an OTP verification prompt is detected after clicking submit, SUBMITTED is NOT set."""
    from backend.app.agent.nodes.review_nodes import submit_application_node
    from backend.app.browser.manager import BrowserManager

    submit_btn = FormField(
        data_jp_id="btn_submit",
        tag_name="button",
        input_type="submit",
        label="Submit Application",
        visible_text="Submit Application"
    )

    state = ApplicationState(
        application_id="app_test_otp",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[submit_btn],
        submission_approved=True
    )

    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    page_mock.url = "https://example.com/apply/verify"
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    # Page evaluate for OTP check returns True
    async def mock_evaluate(script, *args):
        if "otpKeywords" in script:
            return True
        elif "role=\"alert\"" in script:
            return []
        return ""

    page_mock.evaluate = AsyncMock(side_effect=mock_evaluate)
    elem_mock = AsyncMock()
    elem_mock.count = AsyncMock(return_value=1)
    elem_mock.evaluate = AsyncMock(return_value=False)  # button enabled

    with patch.object(BrowserActions, "_find_element", return_value=(elem_mock, page_mock)), \
         patch.object(BrowserActions, "click", new_callable=AsyncMock):
        res_state = await submit_application_node(state, bm_mock)

        # Must NOT be marked as SUBMITTED! Must pause for user with OTP_VERIFICATION.
        assert res_state.status == "WAITING_FOR_USER"
        assert res_state.auth_category == "OTP_VERIFICATION"
        assert res_state.status != "SUBMITTED"


@pytest.mark.asyncio
async def test_submit_application_detects_validation_errors():
    """Verify that when form validation errors are visible after clicking submit, SUBMITTED is NOT set."""
    from backend.app.agent.nodes.review_nodes import submit_application_node
    from backend.app.browser.manager import BrowserManager

    submit_btn = FormField(
        data_jp_id="btn_submit",
        tag_name="button",
        input_type="submit",
        label="Submit Application",
        visible_text="Submit Application"
    )

    state = ApplicationState(
        application_id="app_test_errors",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[submit_btn],
        submission_approved=True
    )

    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    page_mock.url = "https://example.com/apply"
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    async def mock_evaluate(script, *args):
        if "otpKeywords" in script:
            return False
        elif "role=\"alert\"" in script:
            return ["Phone number format is invalid", "Please agree to terms"]
        return ""

    page_mock.evaluate = AsyncMock(side_effect=mock_evaluate)
    elem_mock = AsyncMock()
    elem_mock.count = AsyncMock(return_value=1)
    elem_mock.evaluate = AsyncMock(return_value=False)  # button enabled

    with patch.object(BrowserActions, "_find_element", return_value=(elem_mock, page_mock)), \
         patch.object(BrowserActions, "click", new_callable=AsyncMock):
        res_state = await submit_application_node(state, bm_mock)

        # Must NOT be marked as SUBMITTED! Must reflect validation errors in WAITING_FOR_USER.
        assert res_state.status == "WAITING_FOR_USER"
        assert res_state.status != "SUBMITTED"
        assert len(res_state.validation_errors) == 2
        assert "Phone number format is invalid" in res_state.validation_errors


@pytest.mark.asyncio
async def test_submit_application_detects_disabled_submit_button_without_clicking():
    """Verify that when the submit button is disabled, submit_application_node halts with WAITING_FOR_USER and does not attempt click."""
    from backend.app.agent.nodes.review_nodes import submit_application_node
    from backend.app.browser.manager import BrowserManager

    submit_btn = FormField(
        data_jp_id="btn_submit",
        tag_name="button",
        input_type="submit",
        label="Submit Application",
        visible_text="Submit Application"
    )

    state = ApplicationState(
        application_id="app_test_disabled_btn",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[submit_btn],
        submission_approved=True
    )

    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    page_mock.url = "https://example.com/apply"
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    # Mock element locator for the submit button returning disabled=True
    elem_mock = AsyncMock()
    elem_mock.count = AsyncMock(return_value=1)
    
    async def mock_elem_evaluate(script, *args):
        if "aria-disabled" in script or "el.disabled" in script:
            return True
        return False
    elem_mock.evaluate = AsyncMock(side_effect=mock_elem_evaluate)

    async def mock_page_evaluate(script, *args):
        if "missing" in script:
            return {
                "missing": ["Field 'First Name' is empty.", "Checkbox 'Terms' is required and not checked."],
                "errors": []
            }
        return ""
    page_mock.evaluate = AsyncMock(side_effect=mock_page_evaluate)

    with patch.object(BrowserActions, "_find_element", return_value=(elem_mock, page_mock)), \
         patch.object(BrowserActions, "click", new_callable=AsyncMock) as mock_click:
        res_state = await submit_application_node(state, bm_mock)

        # Must halt with WAITING_FOR_USER without clicking the disabled button
        assert res_state.status == "WAITING_FOR_USER"
        assert res_state.status != "SUBMITTED"
        assert not mock_click.called
        assert "Submit button is disabled" in res_state.error_message
        assert len(res_state.validation_errors) == 2


@pytest.mark.asyncio
async def test_browser_actions_click_refuses_disabled_button():
    """Verify that BrowserActions.click refuses to click an element with disabled or aria-disabled='true'."""
    from backend.app.core.exceptions import BrowserException

    page_mock = AsyncMock()
    elem_mock = AsyncMock()
    elem_mock.count = AsyncMock(return_value=1)
    elem_mock.evaluate = AsyncMock(return_value=True)  # is_disabled = True

    with patch.object(BrowserActions, "_find_element", return_value=(elem_mock, page_mock)):
        with pytest.raises(BrowserException) as exc_info:
            await BrowserActions.click(page_mock, "btn_submit", field_label="Submit Button")
        assert "because the element is disabled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_autocomplete_combobox_selection_and_hitl_fallback():
    """Verify that autocomplete interaction waits for suggestions and escalates to HITL when selection fails."""
    from backend.app.agent.nodes.execution_nodes import auto_fill_node
    from backend.app.browser.manager import BrowserManager
    from backend.app.browser.dom_inspector import DOMInspector

    field_school = FormField(
        data_jp_id="field_school_input",
        tag_name="input",
        input_type="text",
        label="University / School",
        is_required=True
    )

    state = ApplicationState(
        application_id="app_test_autocomplete",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=[field_school],
        auto_fill_queue=[
            FieldValue(data_jp_id="field_school_input", value="MNNIT Allahabad", field_type="text")
        ],
        mapped_answers={},
        human_review_queue=[]
    )

    bm_mock = MagicMock(spec=BrowserManager)
    page_mock = AsyncMock()
    page_mock.url = "https://example.com/apply"
    bm_mock.get_page = AsyncMock(return_value=page_mock)

    mock_elem = AsyncMock()
    mock_elem.count = AsyncMock(return_value=1)
    mock_elem.get_attribute = AsyncMock(side_effect=lambda attr: "combobox" if attr == "role" else "")
    mock_elem.input_value = AsyncMock(return_value="")

    # When fill_autocomplete_or_combobox fails to find a matching option and element remains empty:
    with patch.object(BrowserActions, "_find_element", new_callable=AsyncMock, return_value=(mock_elem, page_mock)), \
         patch.object(BrowserActions, "fill_autocomplete_or_combobox", side_effect=BrowserException("Could not select matching option. Field remains empty.")), \
         patch.object(DOMInspector, "inspect_page", new_callable=AsyncMock) as mock_inspect:
        mock_inspect.return_value = FormPage(
            url="https://example.com/apply",
            title="Application",
            fields=[field_school]
        )

        res_state = await auto_fill_node(state, bm_mock)

        # Verified: escalates to human_review_queue instead of continuing with empty value!
        assert len(res_state.human_review_queue) == 1
        item = res_state.human_review_queue[0]
        assert item.field_id == "field_school_input"
        assert item.requires_human_input is True
        assert "Could not select matching option" in item.reason


@pytest.mark.asyncio
async def test_legal_litigation_and_directorship_mapping(sample_user_profile):
    """Verify court litigation question with 'position of responsibility' maps to 'No', not current_role."""
    sample_user_profile.professional.last_role = "Digital Specialist Engineer (DSE)"
    sample_user_profile.professional.current_role = "Digital Specialist Engineer (DSE)"

    ks_mock = MagicMock(spec=KnowledgeService)
    ks_mock.get_user_profile = AsyncMock(return_value=sample_user_profile)
    ks_mock.get_user_correction = MagicMock(return_value=None)

    fields = [
        FormField(
            data_jp_id="field_litigation",
            tag_name="input",
            input_type="radio",
            label="Do you have any pending litigation/court case against you in any Court of Law? (both personal/owing to a position of responsibility)",
            options=["Yes", "No"],
            is_required=True
        ),
        FormField(
            data_jp_id="field_directorship",
            tag_name="input",
            input_type="radio",
            label="Do you hold any external directorship/ public trusteeship or a role which requires you to take action on behalf of a non-HSBC entity?",
            options=["Yes", "No"],
            is_required=True
        ),
        FormField(
            data_jp_id="field_actual_job_title",
            tag_name="input",
            input_type="text",
            label="Current Job Title",
            options=[],
            is_required=True
        )
    ]

    state = ApplicationState(
        application_id="app_test_litigation",
        user_id="test_manish",
        target_url="https://example.com/apply",
        detected_fields=fields,
        form_page=FormPage(url="https://example.com/apply", title="Apply", fields=fields)
    )

    res_state = await map_fields_and_retrieve_node(state, ks_mock)

    # Question 1: Must be 'No', NOT 'Digital Specialist Engineer (DSE)'!
    lit_ans = res_state.mapped_answers.get("field_litigation")
    assert lit_ans is not None
    assert lit_ans.answer == "No"
    assert "Digital Specialist Engineer" not in str(lit_ans.answer)

    # Question 2: Directorships must be 'No'
    dir_ans = res_state.mapped_answers.get("field_directorship")
    assert dir_ans is not None
    assert dir_ans.answer == "No"

    # Actual job title text field: Maps to current_role
    title_ans = res_state.mapped_answers.get("field_actual_job_title")
    assert title_ans is not None
    assert title_ans.answer == "Digital Specialist Engineer (DSE)"



