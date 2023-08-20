import json
from pydantic import BaseModel
from typing import List
from bondai.tools import Tool

TOOL_NAME = 'final_answer'
TOOL_DESCRIPTION = """Use this tool ONLY after you have captured ALL of the required information from the user. This tool will send the information to the next AI assistant that will complete the task.
- user_exit: This is a boolean value that indicates whether the user has asked to exit. If the user has asked to exit you should NOT ask for any other information from the user.
- task_description: This must be detailed enough for the next AI assistant to understand what the user wants to do. Ask the user any necessary follow up questions.
- task_budget: This is the maximum amount of money the user is willing to spend on this task. Ask the user any necessary follow up questions.
- tool_ids: This is a list of the IDs for the tools that the next AI assistant will need to complete the task. Ask the user any necessary follow up questions.
- user_confirmation: This is a boolean value that indicates whether the user has confirmed the task description, task budget, and tool ids.
"""

class Parameters(BaseModel):
    user_exit: bool = False
    task_description: str
    task_budget: float
    tool_ids: List[str]
    user_confirmation: bool = False

class OnboardingTool(Tool):
    def __init__(self, tool_options):
        super(OnboardingTool, self).__init__(TOOL_NAME, TOOL_DESCRIPTION, Parameters)
        self.tool_options = tool_options
    
    def run(self, arguments):
        user_exit = arguments.get('user_exit')
        if user_exit:
            return json.dumps({
                'user_exit': True
            })

        task_description = arguments.get('task_description')
        task_budget = arguments.get('task_budget')
        tool_ids = arguments.get('tool_ids')
        user_confirmation = arguments.get('user_confirmation')

        if not task_description:
            raise Exception('You must provide a task description.')
        if not task_budget:
            raise Exception('You must provide a task budget.')
        if not tool_ids:
            raise Exception('You must provide a list of tool ids.')
        if not user_confirmation:
            raise Exception('You must confirm the task description, task budget, and tool ids with the user before calling the final_answer tool.')

        for tool_id in tool_ids:
            if tool_id not in [tool.name for tool in self.tool_options]:
                raise Exception(f'Invalid tool id: {tool_id}')
        
        return json.dumps({
            'task_description': task_description,
            'task_budget': task_budget,
            'tool_ids': tool_ids
        })