from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class AddressInfo(BaseModel):
    """Structured address — tolerates both full objects and missing fields."""
    model_config = {"extra": "allow"}

    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None

    def as_string(self) -> str:
        parts = [
            self.address_line_1,
            self.address_line_2,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        return ", ".join(p for p in parts if p)


class PersonalInfo(BaseModel):
    """Personal contact information. Tolerates extra fields in the JSON."""
    model_config = {"extra": "allow"}

    first_name: str
    last_name: str
    email: str
    # phone may arrive as int (8429766063) or str — always stored as str
    phone: Optional[str] = None
    # address may be a flat str OR a nested dict/AddressInfo object
    address: Optional[Union[AddressInfo, str]] = None
    # Flat address fields (old schema compat)
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    # Extra personal fields
    full_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    leetcode_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    photo_path: Optional[str] = None
    # Demographic / Diversity fields
    hispanic_latino: Optional[str] = "No / Not Hispanic or Latino"
    race: Optional[str] = "Asian"
    race_detailed: Optional[str] = "Asian Indian"
    race_ethnicity: Optional[str] = "Asian (Asian Indian)"
    veteran_status: Optional[str] = "I am not a protected veteran / Not a Veteran"
    disability_status: Optional[str] = None

    @field_validator("phone", mode="before")
    @classmethod
    def coerce_phone_to_str(cls, v):
        """Accept phone as int or str, always return str."""
        if v is None:
            return None
        return str(v)

    @field_validator("address", mode="before")
    @classmethod
    def coerce_address(cls, v):
        """Accept address as str or dict; if dict, parse into AddressInfo."""
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, dict):
            return AddressInfo(**v)
        return v

    def flat_address(self) -> Optional[str]:
        """Return a single-line address string usable for form filling."""
        if isinstance(self.address, AddressInfo):
            return self.address.as_string() or None
        if isinstance(self.address, str):
            return self.address
        # Fall back to flat fields
        parts = [self.city, self.state, self.postal_code, self.country]
        result = ", ".join(p for p in parts if p)
        return result or None

    def flat_city(self) -> Optional[str]:
        if isinstance(self.address, AddressInfo):
            return self.address.city or self.city
        return self.city

    def flat_state(self) -> Optional[str]:
        if isinstance(self.address, AddressInfo):
            return self.address.state or self.state
        return self.state

    def flat_country(self) -> Optional[str]:
        if isinstance(self.address, AddressInfo):
            return self.address.country or self.country
        return self.country

    def flat_postal_code(self) -> Optional[str]:
        if isinstance(self.address, AddressInfo):
            return self.address.postal_code or self.postal_code
        return self.postal_code


class ProfessionalInfo(BaseModel):
    """Professional / employment info. Tolerates extra fields."""
    model_config = {"extra": "allow"}

    current_company: Optional[str] = None
    current_role: Optional[str] = None
    total_experience_years: Optional[float] = None
    employment_status: Optional[str] = None
    # notice_period_days: int OR human-readable string like "immediate joiner"
    notice_period_days: Optional[Union[int, str]] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    # Extended fields
    last_employer: Optional[str] = None
    last_role: Optional[str] = None
    last_employment_start: Optional[str] = None
    last_employment_end: Optional[str] = None
    last_role_description: Optional[str] = None
    previous_internships: Optional[List[Dict[str, Any]]] = None
    linkedin_headline: Optional[str] = None
    work_authorization: Optional[Dict[str, Any]] = None

    @field_validator("total_experience_years", mode="before")
    @classmethod
    def coerce_experience(cls, v):
        """Convert None → None, str/int/float → float."""
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @field_validator("notice_period_days", mode="before")
    @classmethod
    def coerce_notice_period(cls, v):
        """
        Convert 'immediate joiner' / 'immediate' → 0.
        Keep plain ints as-is. Leave other strings as-is.
        """
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            lower = v.lower().strip()
            if "immediate" in lower:
                return 0
            try:
                return int(v)
            except ValueError:
                return v  # leave unknown strings as-is
        return v

    def notice_period_display(self) -> str:
        """Human-readable notice period for form filling."""
        if self.notice_period_days == 0:
            return "Immediate joiner"
        if isinstance(self.notice_period_days, int):
            return f"{self.notice_period_days} days"
        return str(self.notice_period_days) if self.notice_period_days else "Not specified"


class EducationInfo(BaseModel):
    """Single education entry."""
    model_config = {"extra": "allow"}

    degree: str
    institution: str
    graduation_year: Optional[int] = None
    start_year: Optional[int] = None
    major: Optional[str] = None
    gpa_or_percentage: Optional[str] = None
    status: Optional[str] = None


class JobPreferences(BaseModel):
    """Job search preferences."""
    model_config = {"extra": "allow"}

    target_roles: List[str] = []
    preferred_locations: List[str] = []
    remote_preference: Optional[str] = None
    willing_to_relocate: Optional[Union[bool, str]] = None
    employment_types: List[str] = []
    salary_expectation: Optional[str] = None
    currency: Optional[str] = None
    notice_period_days: Optional[Union[int, str]] = None
    preferred_company_types: List[str] = []

    @field_validator("willing_to_relocate", mode="before")
    @classmethod
    def coerce_willing_to_relocate(cls, v):
        if isinstance(v, str):
            return v.lower() in ("yes", "true", "1", "y")
        return v

    @field_validator("notice_period_days", mode="before")
    @classmethod
    def coerce_notice(cls, v):
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and "immediate" in v.lower():
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return v


class DemographicsInfo(BaseModel):
    """Candidate demographic / diversity self-identification."""
    model_config = {"extra": "allow"}

    hispanic_latino: Optional[str] = "No / Not Hispanic or Latino"
    race: Optional[str] = "Asian"
    race_detailed: Optional[str] = "Asian Indian"
    race_ethnicity: Optional[str] = "Asian (Asian Indian)"
    veteran_status: Optional[str] = "I am not a protected veteran / Not a Veteran"
    disability_status: Optional[str] = None


# ---------------------------------------------------------------------------
# Root UserProfile
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """
    Canonical candidate profile.
    Tolerates both the old flat schema and the new rich structured schema.
    Extra top-level keys (profile_version, achievements, documents, etc.)
    are preserved via model_config extra='allow'.
    """
    model_config = {"extra": "allow"}

    user_id: str
    personal: PersonalInfo
    professional: Optional[ProfessionalInfo] = None
    education: List[EducationInfo] = []

    # skills: accept flat list[str] OR categorized dict — always expose flat list
    skills: Union[List[str], Dict[str, Any]] = []

    # Top-level convenience fields (old schema compat)
    preferred_locations: List[str] = []
    willing_to_relocate: Optional[Union[bool, str]] = None
    salary_expectation: Optional[str] = None

    # New rich schema fields
    demographics: Optional[DemographicsInfo] = None
    job_preferences: Optional[JobPreferences] = None
    projects: Optional[List[Dict[str, Any]]] = None
    achievements: Optional[List[Dict[str, Any]]] = None
    documents: Optional[Dict[str, Any]] = None
    application_profile: Optional[Dict[str, Any]] = None
    additional_information: Optional[Dict[str, Any]] = None

    @field_validator("willing_to_relocate", mode="before")
    @classmethod
    def coerce_relocate(cls, v):
        if isinstance(v, str):
            return v.lower() in ("yes", "true", "1", "y")
        return v

    def flat_skills(self) -> List[str]:
        """
        Return a flat list of all skill strings regardless of whether
        skills was stored as a list or a categorised dict.
        """
        if isinstance(self.skills, list):
            return self.skills
        if isinstance(self.skills, dict):
            flat: List[str] = []
            for items in self.skills.values():
                if isinstance(items, list):
                    flat.extend(str(s) for s in items)
                elif items:
                    flat.append(str(items))
            return flat
        return []

    def effective_notice_period_days(self) -> Optional[int]:
        """Returns notice period as int (0 = immediate), checking both locations."""
        # Check professional first
        if self.professional and self.professional.notice_period_days is not None:
            v = self.professional.notice_period_days
            if isinstance(v, int):
                return v
        # Then job_preferences
        if self.job_preferences and self.job_preferences.notice_period_days is not None:
            v = self.job_preferences.notice_period_days
            if isinstance(v, int):
                return v
        return None

    def effective_salary_expectation(self) -> Optional[str]:
        if self.salary_expectation:
            return self.salary_expectation
        if self.job_preferences and self.job_preferences.salary_expectation:
            return self.job_preferences.salary_expectation
        return None
