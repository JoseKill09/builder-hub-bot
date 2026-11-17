import { db } from 'sdk';
import { eq } from 'sdk/db';
import { counters } from '../schema.js';

// Called from the Mini App: Telegram.WebApp.Serverless.call('getStats', {}, cb)
export default async function (input, ctx) {
  const user = ctx.initData.user;
  const row = await db.select().from(counters).where(eq(counters.chatId, user.id)).get();
  return { name: user.first_name, seen: row?.seen ?? 0 };
}
