from virtual_company.utils.url_normalization import (
    normalize_domain,
    normalize_fetch_url,
    normalize_url,
)


def test_normalize_fetch_url_canonicalizes_scheme_host_ports_path_and_fragment() -> None:
    assert (
        normalize_fetch_url(" HTTP://EXAMPLE.COM:80/path///#section ")
        == "http://example.com/path"
    )
    assert normalize_fetch_url("HTTPS://EXAMPLE.COM:443/") == "https://example.com"
    assert normalize_fetch_url("https://example.com:8443/path/") == (
        "https://example.com:8443/path"
    )


def test_normalize_fetch_url_removes_tracking_and_preserves_other_query_parameters() -> None:
    assert normalize_fetch_url(
        "https://example.com/path?utm_source=newsletter&keep=one&gclid=abc&keep=two"
    ) == "https://example.com/path?keep=one&keep=two"


def test_normalize_domain_extracts_a_lowercase_hostname_without_www() -> None:
    assert normalize_domain(" HTTPS://WWW.Example.COM/about ") == "example.com"
    assert normalize_domain("www.example.com") == "example.com"
    assert normalize_domain(" ") is None


def test_normalize_url_canonicalizes_authority_path_and_fragment() -> None:
    assert normalize_url(" HTTP://WWW.EXAMPLE.COM:80/path///?q=1#part ") == (
        "http://www.example.com/path?q=1"
    )
    assert normalize_url("https://example.com:8443/") == "https://example.com:8443"
