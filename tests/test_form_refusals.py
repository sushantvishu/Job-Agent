import json
from pathlib import Path
from app.form_filler import is_refusal_or_invalid_answer, LLM_REFUSAL_PATTERNS


def test_refusal_detection():
    assert is_refusal_or_invalid_answer("I cannot provide this information")
    assert is_refusal_or_invalid_answer("I don't have access to candidate data")
    assert is_refusal_or_invalid_answer("I am unable to answer this question")
    assert is_refusal_or_invalid_answer("As an AI language model, I cannot")
    assert is_refusal_or_invalid_answer("Here's a tailored application text for you")
    assert is_refusal_or_invalid_answer("")
    assert is_refusal_or_invalid_answer("   ")


def test_legitimate_answers_not_flagged():
    assert not is_refusal_or_invalid_answer("1.0 years of experience in VAPT and OWASP")
    assert not is_refusal_or_invalid_answer("Immediate")
    assert not is_refusal_or_invalid_answer("Bengaluru, India")
    assert not is_refusal_or_invalid_answer("Yes")
    assert not is_refusal_or_invalid_answer("No")


def test_eeoc_answers_preserved():
    assert not is_refusal_or_invalid_answer(
        "No, I do not have a disability and have not had one in the past",
        label="disability status"
    )
    assert not is_refusal_or_invalid_answer(
        "I am not a protected veteran",
        label="veteran status"
    )


def test_answer_templates_json_clean():
    path = Path("templates/answer_templates.json")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    custom = data.get("custom_answers", {})
    
    for k, v in custom.items():
        assert not is_refusal_or_invalid_answer(v, label=k, allow_empty=True), f"Found refusal in saved template: {k} -> {v}"
        assert not (k.isdigit() and len(k) >= 5), f"Found numeric session key: {k}"
