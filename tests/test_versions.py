import io
import zipfile

from bot import versions as V

CL = """# Changelog

## 1.3 — 2026-11-19
- Added **search**.
  - nested detail

## 1.2 — 2026-11-10
- Fixed a bug.

## 1.1
- First public version.
"""


def make_zip(tmp_path, files: dict, name="bot.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return p


def test_vkey_and_cmp():
    assert V.vkey("1.10") == (1, 10)
    assert V.vkey("v2.0") == (2,)
    assert V.vkey("#3") is None
    assert V.cmp("1.10", "1.9") == 1
    assert V.cmp("2.0", "2") == 0
    assert V.cmp("1.0", "#2") is None


def test_peek_reads_manifest_and_changelog_inside_root(tmp_path):
    p = make_zip(tmp_path, {
        "my-bot/tgcloud/handlers/message.js": "export default async function () {}",
        "my-bot/CHANGELOG.md": CL,
        "my-bot/builderhub.json": '{"name": "Linux ISO Notifier", "no_rollback_before": "1.2"}',
    })
    m = V.peek(p, "my-bot-v1.3.zip")
    assert m.root == "my-bot"
    assert m.name == "Linux ISO Notifier"
    assert m.version == "1.3"          # del CHANGELOG
    assert m.no_rollback_before == "1.2"


def test_peek_name_from_filename_and_manifest_version_wins(tmp_path):
    p = make_zip(tmp_path, {"tgcloud/schema.js": "", "builderhub.json": '{"version": "2.0"}', "CHANGELOG.md": CL})
    m = V.peek(p, "phone-backup-bot-v2.0.zip")
    assert m.version == "2.0"
    assert m.name == "phone-backup-bot"


def test_peek_bad_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"not a zip")
    assert "zip" in V.peek(p).problems


def test_changelog_since_and_between():
    since = V.changelog_since(CL, "1.1")
    assert [v for v, _ in since] == ["1.3", "1.2"]
    assert [v for v, _ in V.changelog_since(CL, None)] == ["1.3"]
    assert V.changelog_since(CL, "1.3") == []
    lose = V.changelog_between(CL, "1.1", "1.3")
    assert [v for v, _ in lose] == ["1.3", "1.2"]
    head, lines = V.block_lines(since[0][1])
    assert head.startswith("1.3")
    assert lines[0] == "• Added **search**."
    assert lines[1].startswith("  ↳ ")


def vs(*rows):
    return [{"seq": i + 1, "label": lab, "no_rollback_before": nrb, "destructive": d} for i, (lab, nrb, d) in enumerate(rows)]


def test_rollback_free_when_nothing_declared():
    versions = vs(("1.0", "", 0), ("1.1", "", 0), ("1.2", "", 0))
    r = V.rollback_check(versions, 3, "1.0", 1)
    assert r.downgrade and r.ok and not r.data_loss


def test_rollback_blocked_by_declared_floor():
    versions = vs(("1.0", "", 0), ("1.1", "", 0), ("2.0", "2.0", 0), ("2.1", "", 0))
    r = V.rollback_check(versions, 4, "1.1", 2)
    assert not r.ok and r.blocked == ["2.0"] and r.floor == "2.0"
    assert V.rollback_check(versions, 4, "2.0", 3).ok
    assert V.floor_of(versions, 4) == ("2.0", 3)
    # Si ya estás en una versión anterior al piso, no cuenta.
    assert V.floor_of(versions, 2) == ("", None)


def test_rollback_warns_about_data_loss():
    versions = vs(("1.0", "", 0), ("1.1", "", 1), ("1.2", "", 0))
    r = V.rollback_check(versions, 3, "1.0", 1)
    assert r.ok and r.data_loss == ["1.1"]


def test_forward_is_never_rollback():
    versions = vs(("1.0", "", 0), ("2.0", "2.0", 1))
    assert not V.rollback_check(versions, 1, "2.0", 2).downgrade


def test_uploaded_older_zip_is_a_downgrade():
    versions = vs(("1.0", "", 0), ("2.0", "2.0", 0))
    r = V.rollback_check(versions, 2, "1.5")
    assert r.downgrade and not r.ok
    assert V.rollback_check(versions, 2, "2.1").downgrade is False
