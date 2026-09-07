"""
Shared test bootstrap - wires up the offline genlayer SDK stub and
loads contract.py once. Same pattern used in this portfolio's prior
Intelligent Contract test suites (OilPriceOracle, GoldPriceOracle).
"""
import importlib.util
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

_CONTRACT_PATH = os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("flightshield_contract", _CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

FlightShield = _contract_module.FlightShield
gl = _contract_module.gl

from genlayer import tx_context, Address, _TransferRecorder  # noqa: E402
import datetime as _real_datetime_module  # noqa: E402


def make_contract() -> "FlightShield":
    return FlightShield()


def transfers():
    """Returns the list of emit_transfer calls recorded since the last reset."""
    return _TransferRecorder.calls


def reset_transfers():
    _TransferRecorder.reset()


class _ControllableDatetime:
    """
    TEST-ONLY stand-in for the `datetime` class contract.py imports.
    Swapped into the loaded contract module's namespace so tests can
    pin "now" to an exact value (simulating the passage of time for
    timeout logic) without needing a real GenVM. `fromisoformat`
    delegates to the real implementation so stored ISO strings still
    round-trip correctly.
    """

    _current = None

    @classmethod
    def now(cls):
        if cls._current is not None:
            return cls._current
        return _real_datetime_module.datetime.now()

    @staticmethod
    def fromisoformat(s):
        return _real_datetime_module.datetime.fromisoformat(s)


_contract_module.datetime = _ControllableDatetime


def set_now(dt):
    """Pin the contract's notion of 'now' to an exact datetime for this test."""
    _ControllableDatetime._current = dt


def reset_now():
    """Return the contract's notion of 'now' to the real wall clock."""
    _ControllableDatetime._current = None
