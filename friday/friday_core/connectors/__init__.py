# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""The Friday Connector framework (Design 81) — the generic, governed spine for
every integration with an external ecosystem.

This package is CORE / `integration` track: the signed-event intake, the
dispatch, the outbound client, and the audit are generic. The *meaning* of a
connector's events (e.g. RandomPack's project.created -> engine) lives in that
connector's domain module, pointed to by Connector.handler_module. The seam is
generic; the meaning is domain data.
"""
