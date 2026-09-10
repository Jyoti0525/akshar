"""Background workers. AKSHAR.md sections 8c and 12.

Two queues, one worker pool. `workers.broker` owns the topology and the
fair-share middleware; `workers.tasks` declares the actors. Nothing in here is
ever on the path of a verdict.
"""
