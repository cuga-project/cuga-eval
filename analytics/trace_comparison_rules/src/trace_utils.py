import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()

project_path = os.getenv("PROJECT_PATH")
if project_path and project_path not in sys.path:
    sys.path.append(project_path)


##############################################################################
_JINJA_ONLY_LINE = re.compile(r'^\s*(\{%-?.*?-?%\}|\{\{.*?\}\}|\s)*\s*$')


def _strip_jinja_prefix(text):
    """Skip leading lines that contain only Jinja tags ({% %} or {{ }}) or are empty."""
    for i, line in enumerate(text.split('\n')):
        if not _JINJA_ONLY_LINE.match(line):
            return '\n'.join(text.split('\n')[i:]).lstrip('\n')
    return ''


def get_agent_name_from_prompt(agent_prompts, system_prompt):

    length_parameter = 100

    agent_name = "Unknown Agent"
    system_prompt_cmp = _strip_jinja_prefix(system_prompt).lstrip('\n')

    for name in agent_prompts.keys():
        current_system_prompt = _strip_jinja_prefix(agent_prompts[name]).lstrip('\n')
        if len(current_system_prompt) >= length_parameter and len(system_prompt_cmp) >= length_parameter:
            if current_system_prompt[0:length_parameter] == system_prompt_cmp[0:length_parameter]:
                agent_name = name
                break
        else:
            if current_system_prompt == system_prompt_cmp:
                agent_name = name
                break

    return agent_name


################################################################################
def get_agent_name_from_task(task_name, task, tasks):
    level = task_name.count(".") - 1

    if level < 1:
        return "ERROR"

    current_task = task
    for i in range(0, level - 1):
        parent_id = current_task.parent_id
        current_task = tasks[parent_id]

    agent_name = current_task.name.split(":")[-1]

    if agent_name == "" or agent_name is None:
        agent_name = "Unknown"

    return agent_name


def get_span_by_span_id(spans, span_id):
    for span in spans:
        if span.context.span_id == span_id:
            return span
    return None


#######################################################################
def extract_intent(text: str) -> str | None:
    # Remove code fences like ``` or ```json (keep content)
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()

    # Match "intent": "<string>" or 'intent': '<string>' allowing escaped quotes
    pattern = r"""['"]intent['"]\s*:\s*(?P<q>['"])(?P<val>(?:\\.|(?!\1).)*)\1"""
    m = re.search(pattern, text, flags=re.DOTALL)
    if not m:
        return None

    val = m.group("val")

    # Unescape common sequences (so yesterday\'s -> yesterday's)
    val = val.replace("\\'", "'").replace('\\"', '"')

    return val.strip()


###############################################################################
def get_agent_prompts(agent_info):

    num_agents = len(agent_info)

    agent_prompts = {}

    for i in range(0, num_agents):
        current_agent_name = agent_info[i]["agent_name"]
        current_prompt_path = os.path.join(project_path, "agent_data", agent_info[i]["system_prompt"])

        with open(current_prompt_path, "r", encoding="utf-8") as f:
            agent_prompts[current_agent_name] = f.read()

    return agent_prompts
