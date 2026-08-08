"""One-time-passcode handling for phone-based signup/login.

Delivery is pluggable and free by default: `_dispatch_otp()` logs the code
to the console. Wire in a real (often free-tier) SMS/WhatsApp provider —
e.g. Fast2SMS, MSG91, Twilio's trial tier — by replacing the body of that
one function. Nothing else in the app needs to change.
"""
import logging
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import OTP, SiteSettings

logger = logging.getLogger(__name__)

OTP_LENGTH = 6
OTP_VALID_MINUTES = 5
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 30


def otp_required():
    return SiteSettings.load().otp_required


def _generate_code():
    return ''.join(random.choices('0123456789', k=OTP_LENGTH))


def _dispatch_otp(phone, code):
    """The one place that actually 'sends' the OTP. Free by default:
    prints it to the server console/log. Swap this out for a real
    SMS/WhatsApp API call when you're ready to go live.
    """
    logger.info("SquadTurf OTP for %s: %s (valid %s min)", phone, code, OTP_VALID_MINUTES)
    print(f"[SquadTurf OTP] {phone} -> {code}")  # visible in `runserver` console


def can_resend(phone, purpose):
    latest = OTP.objects.filter(phone=phone, purpose=purpose).order_by('-created_at').first()
    if not latest:
        return True
    age = (timezone.now() - latest.created_at).total_seconds()
    return age >= OTP_RESEND_COOLDOWN_SECONDS


def issue_otp(phone, purpose):
    """Create + dispatch a fresh OTP. Returns the OTP row. In DEBUG the
    plaintext code is also returned so the UI can surface it for local
    testing without needing a real SMS provider hooked up.
    """
    code = _generate_code()
    otp = OTP.objects.create(
        phone=phone,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=OTP_VALID_MINUTES),
    )
    _dispatch_otp(phone, code)
    debug_code = code if settings.DEBUG else None
    return otp, debug_code


def verify_otp(phone, purpose, submitted_code):
    """Returns (ok: bool, error_message: str | None)."""
    otp = OTP.objects.filter(
        phone=phone, purpose=purpose, is_used=False
    ).order_by('-created_at').first()

    if not otp:
        return False, "No pending code for this number. Request a new one."

    if otp.expires_at < timezone.now():
        return False, "That code has expired. Request a new one."

    if otp.attempts >= OTP_MAX_ATTEMPTS:
        return False, "Too many incorrect attempts. Request a new code."

    if not check_password(submitted_code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=['attempts'])
        return False, "Incorrect code. Please try again."

    otp.is_used = True
    otp.save(update_fields=['is_used'])
    return True, None
