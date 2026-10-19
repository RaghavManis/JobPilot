from backend.app.schemas.profile import UserProfile, PersonalInfo, ProfessionalInfo
from backend.app.schemas.form import FormField, ConfidenceResult

def test_user_profile_schema():
    profile = UserProfile(
        user_id="user_123",
        personal=PersonalInfo(
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@example.com",
            phone="+15551234567"
        ),
        professional=ProfessionalInfo(
            current_company="TechCorp",
            current_role="Senior Software Engineer",
            total_experience_years=5.5
        ),
        skills=["Python", "FastAPI", "React", "Playwright"]
    )
    assert profile.personal.first_name == "Jane"
    assert profile.professional.total_experience_years == 5.5
    assert "Python" in profile.skills

def test_form_field_schema():
    field = FormField(
        data_jp_id="field_001",
        tag_name="input",
        input_type="email",
        name="email",
        label="Email Address",
        is_required=True
    )
    assert field.data_jp_id == "field_001"
    assert field.is_required is True

def test_confidence_result_schema():
    res = ConfidenceResult(
        field_id="field_001",
        answer="jane.doe@example.com",
        confidence=0.98,
        reason="Direct match from user profile personal.email",
        source_citations=["user_profile.personal.email"]
    )
    assert res.confidence == 0.98
    assert res.requires_human_input is False
