"""Shared pytest fixtures.

Every test in this suite runs offline. No test may reach the network, and no test may
write outside the ``tmp_path`` fixture. Synthetic API fixtures arrive in Task 1.
"""

from __future__ import annotations
