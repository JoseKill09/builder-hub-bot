import { api, db } from 'sdk';
import { sql } from 'sdk/db';
import { counters } from '../schema.js';
import { replyText } from '../lib/reply.js';

export default async function (message) {
  const [row] = await db.insert(counters)
    .values({ chatId: message.chat.id, seen: 1 })
    .onConflictDoUpdate({ target: counters.chatId, set: { seen: sql`${counters.seen} + 1`, updated: sql`(unixepoch())` } })
    .returning()
    .run();
  await api.sendMessage({ chat_id: message.chat.id, text: replyText(message.from?.first_name, row.seen) });
}
