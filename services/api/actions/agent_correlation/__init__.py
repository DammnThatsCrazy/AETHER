"""Cross-role agent correlation runtime.

Connects what agent platforms know (who asked, which agent, which tool) to what
business systems record (the order, the charge, the inventory change), with an
evidence class on every link. Contracts live in
``shared.integration_contracts.{source_roles,correlation,correlation_token}``;
this package maps vendor records into observations, stores them, runs the join
rules on arrival, projects proven links into the graph, and serves the routes
and MCP tools agents use to register tasks.

INVARIANT: AETHER observes. It never executes, signs, or settles anything in a
provider system; a correlation token is a reference an agent chooses to carry.
"""
