import pytest
from app.utils import AddressData, CompensationData, EducationData, ProfileData, WorkEligibilityData


def test_profile_submodels_defaults():
    profile = ProfileData(
        name="Test Candidate",
        email="test@example.com",
        phone="+919876543210",
        location="Bengaluru, India",
    )
    assert profile.address.city == "Bengaluru"
    assert profile.address.country == "India"
    assert profile.education.graduation_year == "2024"
    assert profile.work_eligibility.work_authorization == "Yes"
    assert profile.work_eligibility.visa_sponsorship == "No"
    assert profile.compensation.currency == "INR"


def test_profile_submodels_custom_values():
    addr = AddressData(city="Hyderabad", state="Telangana", postal_code="500081", country="India")
    edu = EducationData(highest_degree="Master's", field_of_study="Cybersecurity", graduation_year="2023")
    elig = WorkEligibilityData(work_authorization="Yes", visa_sponsorship="Yes", gender="Prefer not to say")
    comp = CompensationData(current_salary="5 LPA", expected_salary="8 LPA", currency="INR")

    profile = ProfileData(
        name="Custom Candidate",
        email="custom@example.com",
        phone="+919123456789",
        location="Hyderabad, India",
        address=addr,
        education=edu,
        work_eligibility=elig,
        compensation=comp,
    )

    assert profile.address.city == "Hyderabad"
    assert profile.education.highest_degree == "Master's"
    assert profile.work_eligibility.visa_sponsorship == "Yes"
    assert profile.compensation.expected_salary == "8 LPA"
