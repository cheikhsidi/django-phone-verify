# -*- coding: utf-8 -*-

import importlib

# Third Party Stuff
import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from nexmo.errors import ClientError
from twilio.base.exceptions import TwilioRestException

# phone_verify Stuff
import phone_verify.services
from phone_verify.services import (
    PhoneVerificationService,
    send_security_code_and_generate_session_token,
)

from .test_backends import _get_backend_cls

pytestmark = pytest.mark.django_db


def test_message_generation_and_sending_service(client, mocker, backend):
    with override_settings(PHONE_VERIFICATION=backend):
        service = PhoneVerificationService(phone_number="+13478379634")
        backend_service = backend.get("BACKEND")
        mock_api = mocker.patch(f"{backend_service}.send_sms")
        service.send_verification("+13478379634", "123456")

        assert mock_api.called


def test_exception_is_logged_when_raised(client, mocker, backend):
    with override_settings(PHONE_VERIFICATION=backend):
        mock_send_verification = mocker.patch(
            "phone_verify.services.PhoneVerificationService.send_verification"
        )
        mock_logger = mocker.patch("phone_verify.services.logger")
        backend_cls = _get_backend_cls(backend)
        if (
            backend_cls == "nexmo.NexmoBackend"
            or backend_cls == "nexmo.NexmoSandboxBackend"
        ):
            exc = ClientError()
            mock_send_verification.side_effect = exc
        elif (
            backend_cls == "twilio.TwilioBackend"
            or backend_cls == "twilio.TwilioSandboxBackend"
        ):
            exc = TwilioRestException(status=mocker.Mock(), uri=mocker.Mock())
            mock_send_verification.side_effect = exc
        send_security_code_and_generate_session_token(phone_number="+13478379634")
        mock_logger.error.assert_called_once_with(
            f"Error in sending verification code to +13478379634: {exc}"
        )


@override_settings(
    PHONE_VERIFICATION={
        "BACKEND": "phone_verify.backends.twilio.TwilioBackend",
        "MESSAGE": "Welcome to {app}! Please use security code {security_code} to proceed.",
        "APP_NAME": "Phone Verify",
        "SECURITY_CODE_EXPIRATION_TIME": 1,  # In seconds only
        "VERIFY_SECURITY_CODE_ONLY_ONCE": False,
    }
)
def test_exception_is_raised_when_improper_settings(client):
    with pytest.raises(ImproperlyConfigured) as exc:
        PhoneVerificationService(phone_number="+13478379634")
        assert (
            exc.info
            == "Please specify following settings in settings.py: OPTIONS, TOKEN_LENGTH"
        )


def test_exception_is_raised_when_no_settings(client, backend):
    with override_settings(PHONE_VERIFICATION=backend):
        del settings.PHONE_VERIFICATION
        with pytest.raises(ImproperlyConfigured) as exc:
            importlib.reload(phone_verify.services)
            PhoneVerificationService(phone_number="+13478379634")
            assert exc.info == "Please define PHONE_VERIFICATION in settings"


class DummyBackend:
    def __init__(self):
        self.sent_messages = []

    def send_sms(self, number, message):
        self.sent_messages.append((number, message))


class CustomBackendWithMessage(DummyBackend):
    def generate_message(self, security_code, context=None):
        return f"Custom: {security_code} / {context.get('extra', '')}"


@pytest.mark.django_db
def test_generate_message_default_fallback(settings):
    settings.PHONE_VERIFICATION = {
        'BACKEND': 'tests.test_services.DummyBackend',
        'OPTIONS': {},
        'TOKEN_LENGTH': 6,
        'MESSAGE': 'Code: {security_code} from {app}, note: {extra}',
        'APP_NAME': 'TestApp',
        'SECURITY_CODE_EXPIRATION_TIME': 300,
        'VERIFY_SECURITY_CODE_ONLY_ONCE': True,
    }

    svc = PhoneVerificationService(phone_number="+1234567890", backend=DummyBackend())
    msg = svc._generate_message("123456", context={"extra": "extra-info"})

    assert msg == "Code: 123456 from TestApp, note: extra-info"


@pytest.mark.django_db
def test_generate_message_from_custom_backend(settings):
    settings.PHONE_VERIFICATION = {
        'BACKEND': 'tests.test_services.CustomBackendWithMessage',
        'OPTIONS': {},
        'TOKEN_LENGTH': 6,
        'MESSAGE': 'SHOULD NOT BE USED',
        'APP_NAME': 'TestApp',
        'SECURITY_CODE_EXPIRATION_TIME': 300,
        'VERIFY_SECURITY_CODE_ONLY_ONCE': True,
    }

    svc = PhoneVerificationService(phone_number="+1234567890", backend=CustomBackendWithMessage())
    msg = svc._generate_message("999999", context={"extra": "runtime"})

    assert msg == "Custom: 999999 / runtime"
