"""
Minimal offline stub of the `genlayer` SDK.

THIS IS A TEST-ONLY SHIM, NOT PART OF THE DEPLOYABLE CONTRACT.

Extends the stub pattern used by this portfolio's prior oracle
contracts with the primitives FlightShield newly relies on:
  - gl.message.sender_address / gl.message.value  (per-call context)
  - @gl.public.write.payable
  - Address(...) and gl.ContractAt(...).emit_transfer(value=...)

Tests set the "current caller" via the `tx_context(sender, value)`
context manager exported below - this is a TEST-ONLY convenience, not
part of the real SDK's surface.
"""

from contextlib import contextmanager

__all__ = ["gl", "TreeMap", "u256", "DynArray", "i256", "bigint", "Address", "tx_context"]


class _SubscriptableContainer:
    def __class_getitem__(cls, item):
        return cls


class TreeMap(_SubscriptableContainer, dict):
    """Stand-in for genlayer's persistent TreeMap - behaves like a dict."""


class DynArray(_SubscriptableContainer, list):
    """Stand-in for genlayer's persistent DynArray - behaves like a list."""


class u256(int):
    pass


class i256(int):
    pass


class bigint(int):
    pass


class Address(str):
    """Stand-in for genlayer's Address type - a normalized string wrapper."""

    def __new__(cls, value):
        return str.__new__(cls, str(value))


class UserError(Exception):
    pass


class _Vm:
    UserError = UserError


class _PublicWrite:
    def __call__(self, fn):
        return fn

    @staticmethod
    def payable(fn):
        fn._is_payable = True
        return fn


class _PublicNamespace:
    write = _PublicWrite()

    @staticmethod
    def view(fn):
        return fn


class _NondetWeb:
    @staticmethod
    def render(url, mode="text"):
        raise NotImplementedError("gl.nondet.web.render must be patched in tests")


class _Nondet:
    web = _NondetWeb()

    @staticmethod
    def exec_prompt(prompt, response_format="text"):
        raise NotImplementedError("gl.nondet.exec_prompt must be patched in tests")


class _EqPrinciple:
    @staticmethod
    def strict_eq(fn):
        return fn()

    @staticmethod
    def prompt_comparative(fn, principle=None):
        return fn()

    @staticmethod
    def prompt_non_comparative(fn, task="", criteria=""):
        return fn()


class _MessageContext:
    """
    Stand-in for `gl.message`. Real GenVM populates this per-transaction;
    this stub reads a thread-local-ish module-level stack set by the
    `tx_context(...)` test helper, defaulting to a fixed test address
    with zero value if no test has set one (keeps non-payable-focused
    tests from needing boilerplate).
    """

    _stack = [{"sender": "0xTEST_DEFAULT_SENDER", "value": 0}]

    @property
    def sender_address(self):
        return Address(self._stack[-1]["sender"])

    @property
    def value(self):
        return self._stack[-1]["value"]


class _TransferRecorder:
    """Records every emit_transfer call so tests can assert on payouts."""

    calls = []

    @classmethod
    def reset(cls):
        cls.calls = []


class _ContractHandle:
    def __init__(self, address):
        self.address = Address(address)

    def emit_transfer(self, value):
        _TransferRecorder.calls.append({"to": str(self.address), "value": int(value)})


def _get_contract_at(address):
    return _ContractHandle(address)


class _Contract:
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in vars(klass).get("__annotations__", {}).items():
                if isinstance(annotation, type) and issubclass(annotation, (TreeMap, DynArray)):
                    setattr(instance, name, annotation())
        return instance

    def __init__(self, *args, **kwargs):
        pass


class _GL:
    Contract = _Contract
    public = _PublicNamespace()
    nondet = _Nondet()
    eq_principle = _EqPrinciple()
    vm = _Vm()
    message = _MessageContext()
    get_contract_at = staticmethod(_get_contract_at)


gl = _GL()


@contextmanager
def tx_context(sender: str, value: int = 0):
    """
    TEST-ONLY helper: push a (sender, value) pair that gl.message will
    report for the duration of the `with` block, simulating a specific
    caller sending a specific amount of GEN in one transaction.
    """
    gl.message._stack.append({"sender": sender, "value": int(value)})
    try:
        yield
    finally:
        gl.message._stack.pop()
