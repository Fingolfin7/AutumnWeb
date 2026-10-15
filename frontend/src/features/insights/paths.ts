/* /insights/ is a new chat, /insights/<uuid>/ an existing one (the old Django
   URLs). app/links.tsx has no entry for the second form. */
export function chatPath(chatId?: string): string {
  return chatId ? `/insights/${chatId}/` : "/insights/";
}
