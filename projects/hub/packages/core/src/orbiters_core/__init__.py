"""Orbiters: the freelance community, as a product of its own.

Moved out of PigroCRM on 2026-09-09. This package knows nothing about the CRM: its own
settings (`ORBITERS_*`), its own Postgres database, its own Alembic history. What it
holds today is what the community's site collects -- the signup list -- and the ad
conversion that measures it; the freelancer profiles, the company requests and the
admin area arrive in the steps the hub spec lays out
(`projects/hub/docs/superpowers/specs/2026-09-09-orbiters-hub-design.md`).
"""
