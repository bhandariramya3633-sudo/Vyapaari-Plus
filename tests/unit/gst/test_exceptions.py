from app.core.exceptions import VyapaariException
from app.modules.gst.exceptions import SchemaValidationError, SigningError


def test_schema_validation_error_carries_details():
    err = SchemaValidationError("bad payload", ["BuyerDtls.Gstin is required"])
    assert isinstance(err, VyapaariException)
    assert err.code == "SCHEMA_INVALID"
    assert err.message == "bad payload"
    assert err.errors == ["BuyerDtls.Gstin is required"]


def test_schema_validation_error_defaults_to_no_details():
    assert SchemaValidationError("bad payload").errors == []


def test_signing_error_code():
    err = SigningError("key missing")
    assert isinstance(err, VyapaariException)
    assert err.code == "SIGNING_FAILED"
    assert err.message == "key missing"
