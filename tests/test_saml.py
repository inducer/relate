from __future__ import annotations

import pytest
from saml2.xml.schema import (  # pyright: ignore[reportMissingTypeStubs]
    XMLSchemaError,
    validate,
)


_LOGOUT_REQUEST = """\
<samlp:LogoutRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="_logout" Version="2.0" IssueInstant="2026-10-21T00:00:00Z">
  <saml:Issuer>https://example.com/sp</saml:Issuer>
  <saml:NameID>test-user</saml:NameID>
</samlp:LogoutRequest>
"""


def test_saml_schema_validation():
    # Exercise PySAML2's wrapper with the overridden xmlschema dependency.
    validate(_LOGOUT_REQUEST)


@pytest.mark.parametrize("document", [
    _LOGOUT_REQUEST.replace('ID="_logout"', ""),
    _LOGOUT_REQUEST.replace('IssueInstant="2026-10-21T00:00:00Z"',
                                'IssueInstant="invalid"'),
    "<unexpected/>",
])
def test_saml_schema_rejects_invalid_documents(document: str):
    with pytest.raises(XMLSchemaError):
        validate(document)
