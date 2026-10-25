"""Built-in ladder networks.

The node format is derived from real ISPSoft 3.19 projects.  A template is a
complete ``<NETWORK_START>`` block with ``{{PLACEHOLDER}}`` device names;
``add_ladder_pou`` then inserts it as a new POU.

Node types used here:

* ``TYPE=1``  normally-open contact
* ``TYPE=2``  normally-closed contact
* ``TYPE=6``  branch open  (``LNK_C``/``LNK_L`` grid coordinates)
* ``TYPE=29`` branch close
* ``TYPE=13`` coil (OUT)
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def selflock_network(
    start: str,
    stop: str,
    coil: str,
    indicator: str = "",
    comment: str = "",
) -> str:
    """Return a start/stop self-hold network for ``start``/``stop`` -> ``coil``.

    Ladder shape::

        start            stop
        --[ ]--+--------[/]--------( coil )
               |                    |
        coil   |                    +--( indicator )
        --[ ]--+

    ``indicator`` is optional; when empty the second coil node is omitted.
    """

    template = (TEMPLATE_DIR / "selflock.network").read_text(encoding="utf-8")
    template = template.replace("\r\n", "\n")

    if not indicator:
        template = re.sub(
            r"\[LD_NODE\]\nTYPE=13\nDEV_NAME=\{\{INDICATOR\}\}\n\[END_LD_NODE\]\n",
            "",
            template,
            count=1,
        )

    replacements = {
        "{{START}}": start,
        "{{STOP}}": stop,
        "{{COIL}}": coil,
        "{{INDICATOR}}": indicator,
        "{{COMMENT}}": comment or f"电机自锁：{start} 启动，{stop} 停止",
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    return template.replace("\n", "\r\n")
