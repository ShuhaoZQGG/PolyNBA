"""Shared helpers for API validation scripts."""


class ValidationResult:
    """Tracks pass/fail/skip for a single check."""

    def __init__(self, name: str):
        self.name = name
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)

    def fail(self, msg: str) -> None:
        self.failed.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def success(self) -> bool:
        return len(self.failed) == 0


def header(title: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {title}")
    print(f"{'=' * 64}")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def report(vr: ValidationResult) -> None:
    status = "PASS" if vr.success else "FAIL"
    icon = "[OK]" if vr.success else "[FAIL]"
    print(f"\n{icon} {vr.name}: {status}")
    for msg in vr.passed:
        print(f"    + {msg}")
    for msg in vr.warnings:
        print(f"    ? {msg}")
    for msg in vr.failed:
        print(f"    X {msg}")


def summary(results: list[ValidationResult]) -> int:
    """Print a summary of all results and return exit code (0=pass, 1=fail)."""
    header("SUMMARY")
    total_pass = sum(1 for r in results if r.success)
    total_fail = sum(1 for r in results if not r.success)
    total_checks = sum(len(r.passed) for r in results)
    total_failures = sum(len(r.failed) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)

    print(f"\nSections:  {total_pass} passed, {total_fail} failed (of {len(results)} total)")
    print(f"Checks:    {total_checks} passed, {total_failures} failed, {total_warnings} warnings")

    for r in results:
        icon = "[OK]  " if r.success else "[FAIL]"
        print(f"  {icon} {r.name}")

    if total_fail > 0:
        print(f"\n{total_fail} SECTION(S) FAILED")
        return 1
    else:
        print("\nALL SECTIONS PASSED")
        return 0
