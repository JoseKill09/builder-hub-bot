import { table, integer, text, sql } from 'sdk/db';

// One row per chat: how many messages the bot has seen.
export const counters = table('counters', {
  chatId:  integer('chat_id').primaryKey(),
  seen:    integer('seen').notNull().default(0),
  updated: integer('updated_at').default(sql`(unixepoch())`),
});
