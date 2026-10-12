from sqlalchemy import create_engine,inspect,select
from app.migrations import upgrade,version_table


def test_fresh_and_repeated_upgrade_preserves_rows(tmp_path):
    engine=create_engine("sqlite:///"+str(tmp_path/"upgrade.db"))
    upgrade(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO tenants(id,name,plan,created_at) VALUES ('kept','Existing tenant','pro',CURRENT_TIMESTAMP)")
    upgrade(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT name FROM tenants WHERE id='kept'").scalar()=="Existing tenant"
        assert set(connection.scalars(select(version_table.c.version)))=={"001_core","002_service"}
        assert "service_tasks" in inspect(connection).get_table_names()
    engine.dispose()


def test_legacy_database_additive_upgrade(tmp_path):
    engine=create_engine("sqlite:///"+str(tmp_path/"legacy.db"))
    from app.database import Base
    from app.migrations import VERSIONS
    with engine.begin() as connection:
        for name in VERSIONS[0][1]:Base.metadata.tables[name].create(connection)
        connection.exec_driver_sql("INSERT INTO tenants(id,name,plan,created_at) VALUES ('old','Legacy tenant','pro',CURRENT_TIMESTAMP)")
    upgrade(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM tenants").scalar()==1
        assert "service_policies" in inspect(connection).get_table_names()
    engine.dispose()
