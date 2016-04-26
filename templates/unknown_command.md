{% extends "message.md" %}

{% block title -%}
Unknown command
{% endblock %}

{% block message %}
I'm sorry **{{ author }}**. I'm afraid I can't do that.

I don't know what `{{ command }}` means.

Please **edit** or **delete** the corresponding comment(s) so I can move on.

As a reminder, you can type `@scality_wall-e help` to get the list of valid
commands.
{% endblock %}
