import importlib


def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from bot import config, db
    importlib.reload(config)
    importlib.reload(db)
    return db


def test_projects_and_versions(tmp_path, monkeypatch):
    db = fresh_db(tmp_path, monkeypatch)
    p = db.project_upsert(7, "app123", "Phone backup")
    v1 = db.version_add(p["id"], label="1.0", sha256="a" * 64, file_id="F1")
    v2 = db.version_add(p["id"], label="", sha256="b" * 64, file_id="F2")
    db.project_set_current(p["id"], v2)
    rows = db.versions_of(p["id"])
    assert [r["seq"] for r in rows] == [1, 2]
    assert rows[1]["label"] == "#2"                    # sin versión: número de orden
    assert db.version_by_sha(p["id"], "a" * 64)["id"] == v1
    assert db.project_upsert(7, "app123", "")["name"] == "Phone backup"   # el nombre no se pierde
    assert db.projects_of(7)[0]["cur_label"] == "#2"
    assert db.projects_of(8) == []                       # cada usuario ve solo lo suyo
    db.version_touch(v1, destructive=True)
    assert db.version_get(v1)["destructive"] == 1
    db.version_touch(v1, destructive=False)
    assert db.version_get(v1)["destructive"] == 1        # una vez borró datos, queda apuntado
    did = db.deploy_start(7, "app123", "restore")
    db.deploy_version(did, v1)
    assert db.my_deploys(7)[0]["kind"] == "restore"
