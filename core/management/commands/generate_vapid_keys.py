import base64

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a VAPID key pair for Web Push and print env-var-ready output."

    def handle(self, *args, **options):
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "The `cryptography` package isn't installed. It ships with "
                "pywebpush — run `pip install -r requirements.txt` first."
            ))
            return

        def b64url(raw_bytes):
            return base64.urlsafe_b64encode(raw_bytes).rstrip(b'=').decode('ascii')

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        public_raw = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        private_value = private_key.private_numbers().private_value
        private_raw = private_value.to_bytes(32, 'big')

        self.stdout.write(self.style.SUCCESS("VAPID key pair generated.\n"))
        self.stdout.write("Add these to your environment (e.g. a .env file):\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
        self.stdout.write("VAPID_ADMIN_EMAIL=you@example.com\n")
        self.stdout.write(self.style.WARNING(
            "Keep VAPID_PRIVATE_KEY secret — anyone with it can send push "
            "notifications to your subscribers."
        ))
