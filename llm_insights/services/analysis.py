from llm_insights.services.chats import save_llm_messages


async def perform_llm_analysis_stream(
    llm_handler,
    sessions,
    user_prompt="",
    username="",
    conversation_history=None,
    sessions_updated=False,
    chat_obj=None,
    attachments=None,
    session_filters=None,
):
    llm_handler.set_username(username)
    already_persisted = len(llm_handler.get_conversation_history())

    if sessions_updated and conversation_history and llm_handler.has_system_context():
        stream = llm_handler.stream_update_session_data(
            sessions, user_prompt=user_prompt, attachments=attachments
        )
    elif user_prompt:
        llm_handler.initialize_chat(username, sessions)
        stream = llm_handler.stream_message(user_prompt, attachments=attachments)
    else:
        return

    async for chunk in stream:
        yield chunk
    if chat_obj:
        await save_llm_messages(
            chat_obj,
            llm_handler.get_conversation_history()[already_persisted:],
            session_filters=session_filters,
        )
