{%- if message.role == 'function' %}
# Tool Name
You used the **{{ message.tool_name }}** tool.
{% if message.tool_arguments %}
# Tool Arguments
{% for k, v in message.tool_arguments.items() %}
{{ k }}:
```
{{ v }}
```
{% endfor %}
{% endif %}
{% if message.error %}
# Tool Error:
This tool did not run successfully and returned the following error:
```
{{ message.error }}
```
{%- else %}
# Tool Response:
```
{{ message.tool_output }}
```
{% endif %}
{%- elif message.role == 'system' %}
{{ message.message }}
{%- elif message.role == 'user' or message.role == 'agent' %}
{% if message.error %}
This message failed with the following error:
```
{{ message.error }}
```
Message content:
```
{{ message.sender_name.lower() }} to {{ message.recipient_name.lower() }}: {{ message.summary or message.message }}
```
{%- else %}
{{ message.sender_name.lower() }} to {{ message.recipient_name.lower() }}: {{ message.summary or message.message }}
{%- endif %}
{%- endif %}