"""
MercadoPago integration for La Sede subscription sync.
This module has been removed as part of the MercadoPago cleanup.
Stub functions are provided to prevent import errors — reimplement as needed.
"""


def format_payment_method(payment_method):
    return payment_method or ''


def apply_subscription_to_profile(profile, details, match_method=None):
    raise NotImplementedError('MercadoPago integration has been removed. Reimplement to support a new payment provider.')


def refresh_sede_subscription_plans():
    raise NotImplementedError('MercadoPago integration has been removed.')


def run_full_sync(log=None):
    raise NotImplementedError('MercadoPago integration has been removed.')
