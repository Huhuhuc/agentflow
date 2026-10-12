"""Versioned additive schema upgrades. Future column changes require a new migration."""
from sqlalchemy import Column, MetaData, String, Table, inspect, select
from .database import Base, engine
from . import models  # register metadata

VERSIONS = [
    ("001_core", ("tenants","users","workflows","workflow_versions","executions","execution_logs","templates","agent_feedbacks","workflow_run_snapshots","agent_runs","agent_tickets","business_leases")),
    ("002_service", ("service_catalogues","service_orders","service_policies","service_conversations","service_tasks","service_turns","service_audits","service_ticket_states","business_dispatches","service_datasets","service_experiments")),
]
version_table = Table("schema_versions", MetaData(), Column("version",String(40),primary_key=True))


def upgrade(target_engine):
    with target_engine.begin() as connection:
        version_table.create(connection,checkfirst=True)
        applied=set(connection.scalars(select(version_table.c.version)))
        known={version for version,_ in VERSIONS}
        if applied-known:raise RuntimeError("Database schema is newer than this application")
        for version,names in VERSIONS:
            if version in applied:continue
            existing=set(inspect(connection).get_table_names())
            for name in names:
                table=Base.metadata.tables[name]
                if name in existing:
                    columns={c["name"] for c in inspect(connection).get_columns(name)}
                    if set(table.columns.keys())-columns:
                        raise RuntimeError("Existing table "+name+" needs a column migration; automatic stamping refused")
                table.create(connection,checkfirst=True)
            connection.execute(version_table.insert().values(version=version))


if __name__=="__main__":
    upgrade(engine)
    print("Schema upgraded to 002_service; existing rows preserved.")
