import importlib


def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    from bot import config, db, vault
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(vault)
    return db, vault


def test_vault_roundtrip_and_key_file(tmp_path, monkeypatch):
    db, vault = fresh(tmp_path, monkeypatch)
    fake = "app111:" + "x" * 30                      # token inventado
    blob = vault.seal(fake)
    assert fake not in blob and vault.unseal(blob) == fake
    key = tmp_path / "vault.key"
    assert key.exists() and (key.stat().st_mode & 0o077) == 0
    assert vault.unseal("basura") is None and vault.unseal(None) is None


def test_matching_access_and_delete(tmp_path, monkeypatch):
    db, vault = fresh(tmp_path, monkeypatch)
    p = db.project_upsert(5, "app222", "Linux ISO Notifier")
    db.project_set_slug(p["id"], "Linux ISO Notifier")
    db.project_upsert(5, "app333", "Other bot")
    assert [x["app"] for x in db.projects_matching(5, "linux-iso-notifier")] == ["app222"]
    assert db.projects_matching(6, "Linux ISO Notifier") == []        # solo los del usuario
    db.project_save_token(p["id"], vault.seal("app222:" + "y" * 30))
    assert db.project_get(p["id"])["access"] == "saved"
    db.project_access_lost(p["id"])
    got = db.project_get(p["id"])
    assert got["access"] == "lost" and got["token_enc"] is None
    v = db.version_add(p["id"], label="1.0", sha256="a" * 64, file_id="F", store="channel")
    db.version_store(v, "channel", "F2", -100123, 77)
    db.deploy_finish(db.deploy_start(5, "app222"), "published")
    assert db.project_delete(6, p["id"]) == {}                        # no es suyo
    info = db.project_delete(5, p["id"])
    assert info["versions"] == 1 and info["deploys"] == 1 and info["copies"] == [(-100123, 77)]
    assert db.project_get(p["id"]) is None and db.versions_of(p["id"]) == []
    assert db.project_history(5, "app222") == []
    assert len(db.projects_of(5)) == 1


def test_brand_texts_fit_telegram_limits():
    from bot import brand
    for lang in ("es", "en"):
        assert len(brand.SHORT[lang]) <= 120
        assert len(brand.DESCRIPTION[lang]) <= 512
        assert all(len(d) <= 256 and c.islower() for c, d in brand.COMMANDS[lang])
    assert (brand.BRAND_DIR / "profile.jpg").exists()
