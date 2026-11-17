from bot.deploy.cli import looks_like_token, mask, parse_push, parse_schema_plan, parse_status, parse_webhook, unmanaged_static

# Salidas reales de `tgcloud` 0.2.0 (con IDs inventados).
STATUS = """Linked to app1234567890 (from env)
Local revision: 7
Webhook: in sync

Modified:
  tgcloud/handlers/message.js

New (not yet deployed):
  tgcloud/lib/reply.js

Deleted locally (still in snapshot):
  tgcloud/endpoints/act.js
  tgcloud/lib/ui.js

Static (webapp/ → https://app1234567890.tgcloud.ai/)
Modified:
  webapp/index.html
New (not yet deployed):
  webapp/nuevo.txt
"""

MIGRATE = """- Checking schema...
(diff computed against your local tgcloud/schema.js)

Schema out of sync — 4 changes:
  +  hits                new table
  ✗  admins              drop table
  ~  users.name          type change
  ?  chats               not in schema
"""

FAKE_TOKEN = "app1234567890:FakeSecretForTests_0123456789abcd"
FAKE_BOT_TOKEN = "1234567890:AAFakeBotTokenForTests_0123456789ab"


def test_status():
    st = parse_status(STATUS)
    assert st.revision == 7
    assert st.modified == ["tgcloud/handlers/message.js"]
    assert st.new == ["tgcloud/lib/reply.js"]
    assert st.deleted == ["tgcloud/endpoints/act.js", "tgcloud/lib/ui.js"]
    assert st.static_lines == ["modified: webapp/index.html", "new: webapp/nuevo.txt"]


def test_schema_plan():
    sp = parse_schema_plan(MIGRATE)
    assert sp.safe == ["hits — new table"] and sp.destructive == ["admins — drop table"]
    assert sp.manual == ["users.name — type change"] and sp.undocumented == ["chats"]
    assert parse_schema_plan("No schema changes. Database is in sync with the deployed tgcloud/schema.js.").none


def test_other_parsers():
    assert parse_push("Done in 0.4s\nStatic: https://app1.tgcloud.ai/\nSchema out of sync")["static_url"] == "https://app1.tgcloud.ai/"
    w = parse_webhook("  allowed updates:  message, callback_query\n  ✓ in sync with your deployed handlers")
    assert w["in_sync"] and w["allowed"] == ["message", "callback_query"]
    assert unmanaged_static("Warning: the bot has a deployed Mini App that this project does not manage.")


def test_tokens():
    assert looks_like_token(FAKE_TOKEN)
    assert not looks_like_token(FAKE_BOT_TOKEN)
    assert mask(f"token {FAKE_TOKEN} here") == "token app1234567890:*** here"
