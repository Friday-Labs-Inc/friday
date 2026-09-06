"""bench command discovery for the Friday app.

`bench` imports `<app>.commands` and reads its `commands` list, so the whole
`friday` click group is registered by re-exporting it here — no framework
change needed (this replaced a patch to frappe/commands/__init__.py when Friday
stopped being a fork).

    bench --site <site> friday setup
    bench --site <site> friday chat --profile "Friday"
"""

from friday.friday_core.cli.commands import commands

__all__ = ["commands"]
