from virtual_company.workflows.research.normalization import normalize_company_name


def test_normalize_company_name_applies_research_identity_rules() -> None:
    assert normalize_company_name(" Example Pty. Ltd. ") == "example"
    assert normalize_company_name("Example Proprietary Limited") == "example"
