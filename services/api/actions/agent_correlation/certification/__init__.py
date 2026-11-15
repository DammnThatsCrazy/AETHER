"""Sandbox certification for agent correlation mappers.

A mapper is certified for a provider record kind only by payloads the provider
itself returned from a sandbox account, recorded by ``recorders`` and replayed
by ``runner``. Fixtures keep only the fields mappers read (free text reduced to
correlation tokens and provider object IDs), so they hold no customer data.
A kind with no recorded fixture is reported ``uncertified``, never assumed.

Recording writes test objects to provider sandboxes (a PaymentIntent, a draft
product). It is an operator tool, refuses live accounts, and is never part of
the observation runtime, which only reads.
"""
