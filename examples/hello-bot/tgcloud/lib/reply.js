// Shared helper: the reply text for a chat.
export function replyText(name, seen) {
  return `Hello${name ? ', ' + name : ''}! I have seen ${seen} message(s) from this chat.`;
}
