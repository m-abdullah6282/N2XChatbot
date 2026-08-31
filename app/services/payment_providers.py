"""Provider-independent payment abstraction.

This intentionally does NOT call any real payment API. It defines a minimal
interface so the rest of the subscription system never depends on provider-
specific logic. Future providers (Easypaisa, JazzCash) implement the interface;
today they raise NotImplementedError until the real APIs are integrated.

Security: nothing here stores secrets or API credentials. Real provider
credentials will live in environment configuration, never in the database.
"""

from abc import ABC, abstractmethod

SUPPORTED_PROVIDERS = ("easypaisa", "jazzcash")


class PaymentProvider(ABC):
    """Interface every payment provider must implement."""

    name: str

    @abstractmethod
    def create_payment(self, payment: dict) -> dict:
        """Initiate a pending payment. ``payment`` carries the DB payment row
        (id, admin_id, subscription_id, amount, currency). Returns a dict with
        provider instructions/redirect data for the frontend. NOTE: creating a
        payment must never activate a subscription."""

    @abstractmethod
    def verify_payment(self, payment: dict, provider_data: dict) -> bool:
        """Verify a payment server-side before any subscription activation.
        Returns True only when the backend confirms success with the provider."""


class EasypaisaProvider(PaymentProvider):
    """Easypaisa stub. No real API integration yet."""

    name = "easypaisa"

    def create_payment(self, payment: dict) -> dict:
        raise NotImplementedError("Easypaisa API integration is not implemented yet.")

    def verify_payment(self, payment: dict, provider_data: dict) -> bool:
        raise NotImplementedError("Easypaisa API integration is not implemented yet.")


class JazzCashProvider(PaymentProvider):
    """JazzCash stub. No real API integration yet."""

    name = "jazzcash"

    def create_payment(self, payment: dict) -> dict:
        raise NotImplementedError("JazzCash API integration is not implemented yet.")

    def verify_payment(self, payment: dict, provider_data: dict) -> bool:
        raise NotImplementedError("JazzCash API integration is not implemented yet.")


_PROVIDERS = {
    "easypaisa": EasypaisaProvider,
    "jazzcash": JazzCashProvider,
}


def get_provider(provider_name: str) -> PaymentProvider:
    """Return the provider instance for a given name, or None if unknown."""
    cls = _PROVIDERS.get((provider_name or "").lower())
    if cls is None:
        return None
    return cls()
