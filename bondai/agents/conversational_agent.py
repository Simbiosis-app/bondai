import os
import traceback
import json
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable
from bondai.util import load_local_resource
from bondai.tools import Tool
from bondai.memory import MemoryManager
from bondai.tools.conversational import (
    SEND_MESSAGE_TOOL_NAME,
    EXIT_CONVERSATION_TOOL_NAME,
    SendMessageTool,
    ExitConversationTool,
)
from bondai.prompt import JinjaPromptBuilder
from bondai.models.llm import LLM
from bondai.models.openai import (
    OpenAILLM, 
    OpenAIModelNames,
    get_total_cost
)
from .agent import (
    Agent, 
    AgentStatus, 
    AgentException,
)
from .util import (
    AgentException,
    AgentEventNames,
    parse_response_content_message,
)
from .prompts import (
    DEFAULT_AGENT_NAME,
    DEFAULT_CONVERSATIONAL_INSTRUCTIONS
)
from .conversation_member import (
    ConversationMember, 
    ConversationMemberEventNames
)
from .messages import (
    AgentMessage, 
    ConversationMessage,
    ToolUsageMessage,
    SystemMessage,
    AgentMessageList, 
    USER_MEMBER_NAME
)

DEFAULT_MAX_SEND_ATTEMPTS = 3
DEFAULT_SYSTEM_PROMPT_TEMPLATE = load_local_resource(__file__, os.path.join('prompts', 'conversational_agent_system_prompt_template.md'))

class ConversationalAgent(Agent, ConversationMember):

    def __init__(self, 
                    llm: LLM = OpenAILLM(OpenAIModelNames.GPT4_0613),
                    tools: List[Tool] = [],
                    name: str = DEFAULT_AGENT_NAME,
                    persona: str | None = None,
                    persona_summary: str | None = None,
                    instructions: str | None = DEFAULT_CONVERSATIONAL_INSTRUCTIONS,
                    system_prompt_sections: List[Callable[[], str]] = [],
                    system_prompt_builder: Callable[..., str] = None,
                    message_prompt_builder: Callable[..., str] = None,
                    memory_manager : MemoryManager | None = None,
                    max_context_length: int = None,
                    max_context_pressure_ratio: float = 0.8,
                    enable_context_compression: bool = False,
                    enable_conversation: bool = True,
                    enable_exit_conversation: bool=True,
                    quiet: bool=True,
                ):
        ConversationMember.__init__(
            self,
            name=name,
            persona=persona,
            persona_summary=persona_summary,
        )
        Agent.__init__(
            self,
            llm=llm,
            quiet=quiet,
            tools=tools,
            system_prompt_sections=system_prompt_sections,
            system_prompt_builder=system_prompt_builder or JinjaPromptBuilder(DEFAULT_SYSTEM_PROMPT_TEMPLATE),
            message_prompt_builder=message_prompt_builder,
            memory_manager=memory_manager,
            max_context_length=max_context_length,
            max_context_pressure_ratio=max_context_pressure_ratio,
            enable_context_compression=enable_context_compression,
            allowed_events=[
                AgentEventNames.CONTEXT_COMPRESSION_REQUESTED,
                AgentEventNames.TOOL_SELECTED,
                AgentEventNames.TOOL_ERROR,
                AgentEventNames.TOOL_COMPLETED,
                ConversationMemberEventNames.MESSAGE_RECEIVED,
                ConversationMemberEventNames.MESSAGE_ERROR,
                ConversationMemberEventNames.MESSAGE_COMPLETED,
                ConversationMemberEventNames.CONVERSATION_EXITED
            ]
        )

        self._instructions: str = instructions
        self._enable_exit_conversation: bool = enable_exit_conversation
        self._enable_conversation = enable_conversation
        if self._enable_conversation:
            self.add_tool(SendMessageTool())
        if self._enable_exit_conversation:
            self.add_tool(ExitConversationTool())
    
    @property
    def instructions(self) -> str:
        return self._instructions

    def send_message(self, 
                    message: str | ConversationMessage, 
                    sender_name: str = USER_MEMBER_NAME, 
                    group_members: List[ConversationMember] = [], 
                    group_messages: List[AgentMessage] = [], 
                    max_attempts: int = DEFAULT_MAX_SEND_ATTEMPTS, 
                    content_stream_callback: Callable[[str], None] | None = None,
                    function_stream_callback: Callable[[str], None] | None = None
                ) -> (ConversationMessage | None):
        if self._status == AgentStatus.RUNNING:
            raise AgentException('Cannot send message while agent is in a running state.')        
        if not message:
            raise AgentException("'message' cannot be empty.")
        
        if isinstance(message, ConversationMessage):
            agent_message = message
        elif isinstance(message, str):
            if not sender_name:
                raise AgentException("sender_name cannot be empty.")
            agent_message = ConversationMessage(
                sender_name=sender_name,
                recipient_name=self.name,
                message=message
            )
        else:
            raise AgentException("'message' must be an instance of ConversationMessage or a string.")
        
        attempts = 0
        starting_cost = get_total_cost()
        self._status = AgentStatus.RUNNING
        self._messages.add(agent_message)
        if self._memory_manager and self._memory_manager.conversation_memory:
            self._memory_manager.conversation_memory.add(agent_message)
        self._trigger_event(ConversationMemberEventNames.MESSAGE_RECEIVED, self, agent_message)

        def complete_agent_message(success=False, conversation_exited=False, error=None):
            agent_message.success = success
            agent_message.conversation_exited = conversation_exited
            agent_message.error = error
            agent_message.cost = get_total_cost() - starting_cost
            agent_message.completed_at = datetime.now()
            if success:
                self._trigger_event(ConversationMemberEventNames.MESSAGE_COMPLETED, self, agent_message)
                if conversation_exited:
                    self._trigger_event(ConversationMemberEventNames.CONVERSATION_EXITED, self, agent_message)
            else:
                self._trigger_event(ConversationMemberEventNames.MESSAGE_ERROR, self, agent_message)

        def validate_recipient(recipient_name: str):
            if not recipient_name:
                return "recipient_name cannot be empty."
            if len(group_members) > 0 and not any([member.name.lower() == recipient_name.lower() for member in group_members]):
                return f"InvalidResponseError: The response does not conform to the required format. You do not have the ability to send messages to '{recipient_name}'. Try sending a message to someone else."
        
        while True:
            try:
                attempts += 1
                if attempts > max_attempts:
                    raise AgentException("The maximum number of attempts has been exceeded.")

                tool_result = self._run_tool_loop(
                    addition_context_messages=group_messages,
                    tools=self._tools,
                    conversation_members=group_members,
                    starting_cost=starting_cost,
                    return_conversational_responses=True,
                    content_stream_callback=content_stream_callback,
                    function_stream_callback=function_stream_callback
                )

                response_message: ConversationMessage | None = None
                if isinstance(tool_result, ToolUsageMessage):
                    if not tool_result.success:
                        complete_agent_message(success=False, error=tool_result.error)
                        raise tool_result.error
                    elif tool_result.tool_name == EXIT_CONVERSATION_TOOL_NAME:
                        complete_agent_message(success=True, conversation_exited=True)
                        return tool_result.tool_output
                    elif tool_result.tool_name == SEND_MESSAGE_TOOL_NAME:
                        response_message = tool_result.tool_output
            

                if isinstance(tool_result, str):
                    recipient_name, message = parse_response_content_message(tool_result)
                    if not recipient_name or not message:
                        recipient_name = agent_message.sender_name
                        message = tool_result
                    response_message = ConversationMessage(
                        role="assistant",
                        recipient_name=recipient_name,
                        message=message
                    )
                
                if response_message:
                    response_message.sender_name = self.name
                    error = validate_recipient(response_message.recipient_name)
                    if not error:
                        complete_agent_message(success=True)
                        self._messages.add(response_message)
                        if self._memory_manager and self._memory_manager.conversation_memory:
                            self._memory_manager.conversation_memory.add(response_message)
                        
                        return response_message
                    else:
                        self._messages.add(SystemMessage(message=error))
                else:
                    self._messages.add(
                        SystemMessage(
                            message="InvalidResponseError: The response does not conform to the required format. A function selection was expected, but none was provided.\nYour must correct this error."
                        )
                    )
            finally:
                self._status = AgentStatus.IDLE
    
    def save_state(self, file_path: str = None) -> Dict:
        state = super().save_state()
        state['name'] = self._name
        state['persona'] = self._persona
        state['persona_summary'] = self._persona_summary
        state['instructions'] = self.instructions
        state['allow_exit'] = self._enable_exit_conversation
        state['quiet'] = self._quiet
        state['enable_conversation'] = self._enable_conversation
        state['max_context_length'] = self._max_context_length
        state['max_context_pressure_ratio'] = self._max_context_pressure_ratio
        state['messages'] = self.messages.to_dict()

        if file_path:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as file:
                json.dump(state, file, indent=4)

        return state
    
    @classmethod
    def from_dict(cls, data: List[Dict], file_path: str = None) -> 'ConversationalAgent':
        if not data and file_path:
            with open(file_path, 'r') as file:
                data = json.load(file)

        agent = cls(
            name=data['name'],
            persona=data['persona'],
            persona_summary=data['persona_summary'],
            instructions=data['instructions'],
            allow_exit=data['allow_exit'],
            quiet=data['quiet'],
            enable_conversation=data['enable_conversation'],
            max_context_length=data['max_context_length'],
            max_context_pressure_ratio=data['max_context_pressure_ratio']
        )
        agent._messages = AgentMessageList.from_dict(data['messages'])
        agent.load_state(data)
        return agent
        
