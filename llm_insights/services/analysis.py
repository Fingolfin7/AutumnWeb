from llm_insights.services.chats import save_llm_messages


async def perform_llm_analysis(
    llm_handler,
    sessions,
    user_prompt="",
    username="",
    conversation_history=None,
    sessions_updated=False,
    chat_obj=None,
):
    llm_handler.set_username(username)
    already_persisted = len(llm_handler.get_conversation_history())

    if (
        conversation_history is None
        or not conversation_history
        or not llm_handler.has_system_context()
    ):
        llm_handler.initialize_chat(username, sessions)
    elif sessions_updated:
        assistant_response = await llm_handler.update_session_data(
            sessions, user_prompt=user_prompt
        )
        conversation_history = llm_handler.get_conversation_history()
        if chat_obj:
            await save_llm_messages(chat_obj, conversation_history[already_persisted:])
        return assistant_response, conversation_history

    if user_prompt:
        assistant_response = await llm_handler.send_message(user_prompt)
        conversation_history = llm_handler.get_conversation_history()
        if chat_obj:
            await save_llm_messages(chat_obj, conversation_history[already_persisted:])
        return assistant_response, conversation_history

    return None, conversation_history


async def perform_llm_analysis_stream(
    llm_handler,
    sessions,
    user_prompt="",
    username="",
    conversation_history=None,
    sessions_updated=False,
    chat_obj=None,
):
    llm_handler.set_username(username)
    already_persisted = len(llm_handler.get_conversation_history())

    if (
        conversation_history is None
        or not conversation_history
        or not llm_handler.has_system_context()
    ):
        llm_handler.initialize_chat(username, sessions)
    elif sessions_updated:
        async for chunk in llm_handler.stream_update_session_data(
            sessions, user_prompt=user_prompt
        ):
            yield chunk
        if chat_obj:
            await save_llm_messages(
                chat_obj, llm_handler.get_conversation_history()[already_persisted:]
            )
        return

    if user_prompt:
        async for chunk in llm_handler.stream_message(user_prompt):
            yield chunk
        if chat_obj:
            await save_llm_messages(
                chat_obj, llm_handler.get_conversation_history()[already_persisted:]
            )
