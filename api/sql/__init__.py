"""SQL-backed implementations of the storage Protocols in `api/repository.py`.

`db/schema.sql` is the source of truth for the schema; `tables.py` mirrors it as
SQLAlchemy Core so every query is compiled and parameterised, and a test asserts
the two agree. `stores.py` implements the Protocols the routers already depend
on, so nothing above this package changes when a deployment gains a database.
"""
