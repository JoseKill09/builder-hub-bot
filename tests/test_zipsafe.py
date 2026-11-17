import stat
import zipfile

import pytest

from bot.deploy.zipsafe import ZipError, extract


def make(tmp_path, entries, name="p.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in entries:
            if isinstance(data, zipfile.ZipInfo):
                z.writestr(data, "x")
            else:
                z.writestr(n, data)
    return p


def test_strips_single_root_and_skips_junk(tmp_path):
    z = make(tmp_path, [("proj/tgcloud/schema.js", "x"), ("proj/node_modules/a.js", "x"), ("proj/.envrc", "A=1"),
                        ("proj/.tgcloud/state.json", "{}"), ("proj/README.md", "hi")])
    out = extract(z, tmp_path / "d")
    assert out.stripped_root == "proj"
    assert sorted(out.files) == ["README.md", "tgcloud/schema.js"]
    assert not (tmp_path / "d" / ".envrc").exists()


@pytest.mark.parametrize("bad", ["../evil.js", "/abs.js", "a/../../x.js", "C:/win.js"])
def test_rejects_bad_paths(tmp_path, bad):
    with pytest.raises(ZipError) as e:
        extract(make(tmp_path, [(bad, "x")]), tmp_path / "d")
    assert e.value.code == "zip_path"


def test_rejects_symlink(tmp_path):
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ZipError) as e:
        extract(make(tmp_path, [("link", info)]), tmp_path / "d")
    assert e.value.code == "zip_symlink"


def test_limits(tmp_path):
    z = make(tmp_path, [("a.js", "x" * 3000), ("b.js", "x" * 3000)])
    with pytest.raises(ZipError) as e:
        extract(z, tmp_path / "d", max_total=4000)
    assert e.value.code == "zip_too_big"
    with pytest.raises(ZipError) as e:
        extract(z, tmp_path / "e", max_file=1000)
    assert e.value.code == "zip_file_big"
    with pytest.raises(ZipError) as e:
        extract(z, tmp_path / "f", max_files=1)
    assert e.value.code == "zip_too_many"


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_text("hola")
    with pytest.raises(ZipError) as e:
        extract(p, tmp_path / "d")
    assert e.value.code == "zip_bad"
