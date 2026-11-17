import shutil
from pathlib import Path

from bot.deploy.validate import strip_jsonc, validate

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "hello-bot"


def proj(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def codes(rep, level="error"):
    return sorted(i.code for i in rep.issues if i.level == level)


def test_example_is_valid(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "p")
    rep = validate(tmp_path / "p")
    assert rep.errors == [], rep.for_ai()
    assert rep.static_dir == "webapp"
    assert len(rep.modules) == 4


def test_detects_common_mistakes(tmp_path):
    rep = validate(proj(tmp_path, {
        "tgcloud/handlers/mesage.js": "export default async function () {}",
        "tgcloud/handlers/message.js": "import x from 'lodash';\nimport { a } from '../lib/a';\nexport default async () => {}",
        "tgcloud/endpoints/2bad.js": "export default async () => 1",
        "tgcloud/util.js": "export const x = 1",
        "tgcloud/lib/sub/ok.js": "export const y = require('fs')",
        "tgcloud/schema.js": "import { table, integer } from 'sdk/db';\nexport const t = table('t', { u: integer('u').references(() => x) });",
        "tgcloud/endpoints/noDefault.js": "export const z = 1",
    }), check_syntax=False)
    assert codes(rep) == sorted(["handler_name", "import_npm", "import_ext", "endpoint_name", "stray_js", "require",
                                 "foreign_key", "no_default_export"])
    assert "lodash" in rep.for_ai()


def test_syntax_error_is_reported(tmp_path):
    rep = validate(proj(tmp_path, {"tgcloud/handlers/message.js": "export default async function ( {"}))
    assert "syntax" in codes(rep)


def test_old_layout_and_missing(tmp_path):
    rep = validate(proj(tmp_path / "a", {"handlers/message.js": "export default 1"}))
    assert codes(rep) == ["old_layout"]
    rep2 = validate(proj(tmp_path / "b", {"README.md": "hi"}))
    assert codes(rep2) == ["no_tgcloud"]


def test_imports_resolve(tmp_path):
    rep = validate(proj(tmp_path, {
        "tgcloud/lib/a.js": "export const a = 1",
        "tgcloud/handlers/message.js": "import { a } from '../lib/a.js';\nimport { b } from '../lib/b.js';\nimport { db } from 'sdk';\nimport { c } from 'sdk/nope';\nexport default async () => a",
    }), check_syntax=False)
    assert codes(rep) == ["import_missing", "import_sdk"]


def test_static_checks(tmp_path):
    rep = validate(proj(tmp_path, {
        "tgcloud/handlers/message.js": "export default async () => {}",
        "tgcloud.jsonc": '{ /* web */ "static": { "source": "dist", }, }',
        "dist/api/x.json": "{}",
    }), check_syntax=False)
    assert "static_api" in codes(rep)
    assert "static_no_index" in codes(rep, "warn")


def test_jsonc():
    import json
    assert json.loads(strip_jsonc('{"a": "http://x", // c\n "b": [1,2,], /* z */ }')) == {"a": "http://x", "b": [1, 2]}
